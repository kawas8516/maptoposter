"""End-to-end orchestration: description → theme → guarded palette → poster.

Two things live here rather than in the UI, so both the Streamlit app and the
evaluation harness exercise identical code.

**Overlapping the model call with the network fetch (NFR7).** There is a genuine
dependency problem: the city normally comes *from* the model, so there is
nothing to prefetch until it answers. When the caller already knows the city —
the Classic tab always does, and the Describe tab offers an optional field — the
OSM download runs on a second thread while the model is still thinking, and the
two costs overlap instead of adding up. Without a city hint the pipeline falls
back to running them in sequence; this is stated plainly rather than pretending
concurrency always applies.

**Splitting fetch from draw.** ``create_poster`` fetches map data internally,
which would make the network and matplotlib time indistinguishable. Fetching
explicitly first — into the same disk cache the engine reads — separates
``geocode_ms``/``graph_ms`` from ``render_ms`` (NFR8), and leaves the render
itself purely CPU-bound so a colour edit re-renders without touching the network
(NFR9).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import guards, render, themes
from .guards import GuardResult
from .llm import GenerationResult, ThemeGenerator
from .timing import Timings


@dataclass
class PreparedPoster:
    """A guarded theme plus the location it should be rendered at."""

    theme: dict
    guard_result: GuardResult
    city: Optional[str]
    country: Optional[str]
    distance: int
    generation: Optional[GenerationResult] = None
    timings: Timings = field(default_factory=Timings)
    prefetched: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.city and self.country)


def apply_palette_guards(theme: dict, timings: Optional[Timings] = None) -> tuple[dict, GuardResult]:
    """Run the FR4 guards over any palette — AI-generated or hand-edited."""
    timings = timings or Timings()
    with timings.measure("guard_ms"):
        result = guards.apply_guards(theme)
    return result.theme, result


def prepare_from_description(
    description: str,
    city_hint: Optional[str] = None,
    country_hint: Optional[str] = None,
    distance_hint: Optional[int] = None,
    generator: Optional[ThemeGenerator] = None,
) -> PreparedPoster:
    """Generate a theme, guard it, and warm the map cache where possible.

    When ``city_hint`` and ``country_hint`` are supplied the prefetch overlaps
    the model call. The hints also win over whatever the model infers, so a user
    who names a city gets that city.
    """
    generator = generator or ThemeGenerator()
    timings = Timings()
    can_overlap = bool(city_hint and country_hint)
    prefetch_distance = distance_hint or themes.DEFAULT_DISTANCE_M

    if can_overlap:
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            generation_future = pool.submit(generator.generate, description)
            prefetch_future = pool.submit(
                render.prefetch, str(city_hint), str(country_hint), prefetch_distance
            )
            generation = generation_future.result()
            prefetched = prefetch_future.result() is not None
        wall_ms = (time.perf_counter() - started) * 1000.0

        # Both stages ran concurrently, so their individual durations sum to
        # more than the wall clock. Report the true wall time against the
        # dominant stage and note the overlap rather than double-counting.
        timings.record("llm_ms", generation.timings.stages.get("llm_ms", 0.0))
        timings.record("validate_ms", generation.timings.stages.get("validate_ms", 0.0))
        overlap_ms = max(wall_ms - timings.total_ms, 0.0)
        timings.record("graph_ms", overlap_ms, "overlapped with model call")
    else:
        generation = generator.generate(description)
        for stage, value in generation.timings.stages.items():
            timings.record(stage, value)
        prefetched = False

    theme, guard_result = apply_palette_guards(generation.theme, timings)

    return PreparedPoster(
        theme=theme,
        guard_result=guard_result,
        city=city_hint or generation.city,
        country=country_hint or generation.country,
        distance=distance_hint or generation.distance or themes.DEFAULT_DISTANCE_M,
        generation=generation,
        timings=timings,
        prefetched=prefetched,
    )


def prepare_from_theme(
    theme: dict,
    city: str,
    country: str,
    distance: int,
    run_guards: bool = True,
) -> PreparedPoster:
    """Prepare a stock or hand-edited palette, with no model involved.

    ``run_guards`` is off for unmodified stock themes: those are hand-tuned and
    ship as their author designed them. It is on for anything a user edited.
    """
    timings = Timings()
    if run_guards:
        guarded, result = apply_palette_guards(theme, timings)
    else:
        guarded, result = dict(theme), guards.apply_guards(theme)
        result.theme = dict(theme)
        result.corrections = []

    return PreparedPoster(
        theme=guarded,
        guard_result=result,
        city=city,
        country=country,
        distance=distance,
        timings=timings,
    )


def render_poster(
    theme: dict,
    city: str,
    country: str,
    distance: int,
    timings: Optional[Timings] = None,
) -> tuple[Path, Timings]:
    """Geocode, fetch and draw, timing each stage separately.

    The fetch is done explicitly before drawing so that ``render_ms`` measures
    only matplotlib. On a repeat render — a colour tweak, say — the geocode and
    fetch both hit their disk caches and cost almost nothing, which is what
    makes NFR9 hold.
    """
    timings = timings or Timings()

    with timings.measure("geocode_ms"):
        point = render.geocode(city, country)

    cached = render.is_cached(city, country, distance)
    with timings.measure("graph_ms", "cached" if cached else "downloaded"):
        if not cached:
            render.prefetch(city, country, distance)

    with timings.measure("render_ms"):
        path = render.render(theme, city, country, point, distance)

    return path, timings
