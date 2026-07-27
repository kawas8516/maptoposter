"""Tests for the theme registry, response cache, timings and pipeline (FR7, NFR8/9)."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from aiposter import llm_cache, pipeline, render, themes
from aiposter.llm import PRIMARY_MODEL, PROMPT_VERSION, ThemeGenerator
from aiposter.spec import ThemeSpec
from aiposter.timing import STAGES, Timings

VALID_JSON = json.dumps({
    "city": "Pune",
    "country": "India",
    "distance": 5000,
    "theme": {
        "name": "Test", "description": "fixture",
        "bg": "#0B0E1A", "text": "#FFD98A", "water": "#0A0C14", "parks": "#12182A",
        "road_motorway": "#FFB1EF", "road_primary": "#FF85C3", "road_secondary": "#DC5A99",
        "road_tertiary": "#AF2D71", "road_residential": "#82004C",
    },
})


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Point the response cache at a temp dir so tests never touch the real one."""
    monkeypatch.setattr(llm_cache, "CACHE_DIR", tmp_path / "llm")
    return tmp_path


# --------------------------------------------------------------------------
# Theme registry (FR7.1)
# --------------------------------------------------------------------------


def test_registry_loads_all_seventeen_stock_themes():
    assert len(themes.theme_names()) == 17


@pytest.mark.parametrize("name", themes.theme_names())
def test_every_stock_theme_validates_against_the_schema(name):
    """A malformed theme file must fail here, not inside matplotlib."""
    theme = themes.get(name)
    assert set(ThemeSpec.model_validate(theme).to_theme_dict()) == set(theme)


def test_get_returns_a_copy_callers_can_mutate():
    first = themes.get("noir")
    first["bg"] = "#FFFFFF"
    assert themes.get("noir")["bg"] != "#FFFFFF"


def test_unknown_theme_raises():
    with pytest.raises(themes.ThemeNotFoundError):
        themes.get("no_such_theme")


def test_distance_presets_match_the_reference_site():
    assert [m for _, m in themes.DISTANCE_PRESETS] == [3000, 5000, 10000, 15000]
    assert themes.DEFAULT_DISTANCE_M == 3000


def test_nearest_preset_snaps_model_chosen_distances():
    assert themes.nearest_preset(3000) == 3000
    assert themes.nearest_preset(12000) == 10000
    assert themes.nearest_preset(30000) == 15000


# --------------------------------------------------------------------------
# Colour editing (FR7.3)
# --------------------------------------------------------------------------


def test_editing_background_resyncs_the_gradient():
    """Otherwise the fade would band against the new background."""
    edited = themes.apply_edits(themes.get("noir"), {"bg": "#123456"})
    assert edited["gradient_color"] == "#123456"


def test_editing_tertiary_resyncs_the_default_road():
    edited = themes.apply_edits(themes.get("noir"), {"road_tertiary": "#ABCDEF"})
    assert edited["road_default"] == "#ABCDEF"


def test_apply_edits_ignores_non_editable_fields():
    """Derived fields cannot be set directly, only followed."""
    base = themes.get("noir")
    edited = themes.apply_edits(base, {"gradient_color": "#FF0000", "name": "hacked"})
    assert edited["gradient_color"] == base["bg"]
    assert edited["name"] == base["name"]


def test_apply_edits_does_not_mutate_the_base():
    base = themes.get("noir")
    snapshot = dict(base)
    themes.apply_edits(base, {"bg": "#123456"})
    assert base == snapshot


def test_is_modified_detects_edits():
    base = themes.get("noir")
    assert not themes.is_modified(base, themes.apply_edits(base, {}))
    assert themes.is_modified(base, themes.apply_edits(base, {"bg": "#123456"}))


def test_edited_palettes_are_guarded():
    """An edit that destroys contrast must be corrected (FR7.3)."""
    base = themes.get("noir")
    edited = themes.apply_edits(base, {"bg": "#000000", "text": "#010101"})
    guarded, result = pipeline.apply_palette_guards(edited)
    assert result.corrections
    assert guarded["text"] != "#010101"


# --------------------------------------------------------------------------
# Response cache
# --------------------------------------------------------------------------


def test_prompt_normalization_collapses_case_and_whitespace():
    assert llm_cache.normalize_prompt("  Moody   RAINY  Tokyo ") == "moody rainy tokyo"


def test_cache_key_is_stable_across_trivial_variants():
    a = llm_cache.cache_key("Moody  Rainy TOKYO ", PRIMARY_MODEL)
    b = llm_cache.cache_key("moody rainy tokyo", PRIMARY_MODEL)
    assert a == b


def test_cache_key_changes_with_model_and_prompt_version():
    base = llm_cache.cache_key("x", PRIMARY_MODEL, "v1")
    assert base != llm_cache.cache_key("x", "other/model", "v1")
    assert base != llm_cache.cache_key("x", PRIMARY_MODEL, "v2")


def test_cache_key_contains_no_prompt_text():
    """No user text may reach a file path (security.md §3.3)."""
    key = llm_cache.cache_key("../../etc/passwd", PRIMARY_MODEL)
    assert key.isalnum() and "/" not in key and ".." not in key


def test_cache_round_trip(isolated_cache):
    assert llm_cache.get("a prompt", PRIMARY_MODEL) is None
    llm_cache.put("a prompt", PRIMARY_MODEL, VALID_JSON)
    assert llm_cache.get("a prompt", PRIMARY_MODEL) == VALID_JSON
    assert llm_cache.get("A   PROMPT", PRIMARY_MODEL) == VALID_JSON


def test_corrupt_cache_entry_is_a_miss_not_an_error(isolated_cache):
    llm_cache.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = llm_cache.cache_key("a prompt", PRIMARY_MODEL, PROMPT_VERSION)
    (llm_cache.CACHE_DIR / f"{key}.json").write_text("{not json", encoding="utf-8")
    assert llm_cache.get("a prompt", PRIMARY_MODEL, PROMPT_VERSION) is None


def test_expired_cache_entry_is_ignored(isolated_cache, monkeypatch):
    llm_cache.put("a prompt", PRIMARY_MODEL, VALID_JSON)
    monkeypatch.setattr(llm_cache, "MAX_AGE_SECONDS", -1)
    assert llm_cache.get("a prompt", PRIMARY_MODEL) is None


def test_cache_stores_no_pickle(isolated_cache):
    """security.md §7 restricts pickle to locally generated data."""
    llm_cache.put("a prompt", PRIMARY_MODEL, VALID_JSON)
    for path in llm_cache.CACHE_DIR.glob("*"):
        json.loads(path.read_text(encoding="utf-8"))  # must parse as JSON


def test_second_identical_prompt_skips_the_network(isolated_cache):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        message = mock.Mock()
        message.content = VALID_JSON
        choice = mock.Mock()
        choice.message = message
        completion = mock.Mock()
        completion.choices = [choice]
        return completion

    client = mock.Mock()
    client.chat_completion.side_effect = fake

    generator = ThemeGenerator(token="fake", use_response_format=False, use_cache=True)
    generator._client = client

    first = generator.generate("a warm monsoon evening")
    assert len(calls) == 1
    assert not first.trace.cache_hit

    second = generator.generate("A  WARM   Monsoon Evening")
    assert len(calls) == 1, "a repeated prompt must not hit the network"
    assert second.trace.cache_hit
    assert second.theme == first.theme


# --------------------------------------------------------------------------
# Timings (NFR8)
# --------------------------------------------------------------------------


def test_timings_accumulate_per_stage():
    timings = Timings()
    timings.record("render_ms", 100.0)
    timings.record("render_ms", 50.0)
    assert timings.stages["render_ms"] == 150.0


def test_timings_measure_context_manager():
    timings = Timings()
    with timings.measure("llm_ms"):
        pass
    assert "llm_ms" in timings.stages


def test_timings_records_stage_even_when_the_block_raises():
    timings = Timings()
    with pytest.raises(RuntimeError):
        with timings.measure("render_ms"):
            raise RuntimeError("boom")
    assert "render_ms" in timings.stages


def test_timings_as_dict_has_every_stage_column():
    """CSV columns must stay stable across runs (NFR8)."""
    row = Timings().as_dict()
    for stage in STAGES:
        assert stage in row
    assert "total_ms" in row


def test_timings_merge_combines_stages():
    a, b = Timings(), Timings()
    a.record("llm_ms", 10.0)
    b.record("render_ms", 20.0)
    merged = a.merge(b)
    assert merged.stages == {"llm_ms": 10.0, "render_ms": 20.0}
    assert merged.total_ms == 30.0


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def test_compensated_distance_matches_the_engine():
    """If this drifts, prefetch warms a cache entry the render never reads."""
    assert render.compensated_distance(3000) == pytest.approx(1000.0)
    assert render.compensated_distance(12000) == pytest.approx(4000.0)


def test_prepare_from_theme_skips_guards_for_stock_themes():
    """Stock themes ship as their author designed them."""
    prepared = pipeline.prepare_from_theme(themes.get("sunset"), "Pune", "India", 3000, run_guards=False)
    assert prepared.theme == themes.get("sunset")
    assert prepared.guard_result.corrections == []


def test_prepare_from_theme_guards_edited_themes():
    edited = themes.apply_edits(themes.get("noir"), {"text": "#010101", "bg": "#000000"})
    prepared = pipeline.prepare_from_theme(edited, "Pune", "India", 3000, run_guards=True)
    assert prepared.guard_result.corrections
    assert "guard_ms" in prepared.timings.stages


def test_render_poster_times_each_stage_separately():
    theme = themes.get("noir")
    with mock.patch.object(render, "geocode", return_value=(18.5, 73.8)), \
         mock.patch.object(render, "is_cached", return_value=True), \
         mock.patch.object(render, "render", return_value=render.OUTPUT_DIR / "x.png") as drawn:
        _, timings = pipeline.render_poster(theme, "Pune", "India", 3000)
    drawn.assert_called_once()
    for stage in ("geocode_ms", "graph_ms", "render_ms"):
        assert stage in timings.stages


def test_cached_render_does_not_refetch(isolated_cache):
    """NFR9: a colour edit must not touch the network."""
    theme = themes.get("noir")
    with mock.patch.object(render, "geocode", return_value=(18.5, 73.8)), \
         mock.patch.object(render, "is_cached", return_value=True), \
         mock.patch.object(render, "prefetch") as prefetch, \
         mock.patch.object(render, "render", return_value=render.OUTPUT_DIR / "x.png"):
        _, timings = pipeline.render_poster(theme, "Pune", "India", 3000)
    prefetch.assert_not_called()
    assert timings.notes.get("graph_ms") == "cached"


def test_uncached_render_fetches_once():
    theme = themes.get("noir")
    with mock.patch.object(render, "geocode", return_value=(18.5, 73.8)), \
         mock.patch.object(render, "is_cached", return_value=False), \
         mock.patch.object(render, "prefetch") as prefetch, \
         mock.patch.object(render, "render", return_value=render.OUTPUT_DIR / "x.png"):
        _, timings = pipeline.render_poster(theme, "Pune", "India", 3000)
    prefetch.assert_called_once()
    assert timings.notes.get("graph_ms") == "downloaded"


def test_city_hint_overrides_what_the_model_inferred():
    generator = mock.Mock()
    generator.generate.return_value = ThemeGenerator(
        token="fake", use_cache=False
    ) and _fake_generation()
    with mock.patch.object(render, "prefetch", return_value=(18.5, 73.8)):
        prepared = pipeline.prepare_from_description(
            "anything", city_hint="Pune", country_hint="India",
            distance_hint=5000, generator=generator,
        )
    assert prepared.city == "Pune"
    assert prepared.country == "India"
    assert prepared.distance == 5000
    assert prepared.prefetched


def test_without_a_city_hint_no_prefetch_is_attempted():
    """There is nothing to prefetch until the model names a city."""
    generator = mock.Mock()
    generator.generate.return_value = _fake_generation()
    with mock.patch.object(render, "prefetch") as prefetch:
        prepared = pipeline.prepare_from_description("anything", generator=generator)
    prefetch.assert_not_called()
    assert not prepared.prefetched
    assert prepared.city == "Tokyo"


def _fake_generation():
    from aiposter.llm import GenerationResult, GenerationTrace
    from aiposter.spec import PosterSpec

    spec = PosterSpec.model_validate(json.loads(VALID_JSON.replace("Pune", "Tokyo").replace("India", "Japan")))
    timings = Timings()
    timings.record("llm_ms", 1000.0)
    return GenerationResult(
        theme=spec.theme.to_theme_dict(),
        spec=spec,
        trace=GenerationTrace(description="anything", source="first"),
        timings=timings,
    )
