"""AI Poster Studio — Streamlit front end.

Two tabs:

* **Classic** (FR7) — the 17 stock themes as a scrollable card grid with
  contrast-previewing swatches, plus the reference site's distance presets.
* **Match a Photo** (FR3) — upload a photo, extract a palette via K-Means in
  CIELAB space, classify its mood zero-shot with CLIP, and guard/render the
  derived theme exactly like every other path.

Every tab shares the same two-column shell — control panel left, Result card
right — built from the components in :mod:`ui`. All pipeline, guard and caching
behaviour is unchanged from before the visual overhaul; this file only decides
where things appear.

The Describe tab (FR2, AI theme generation from free text) has been removed
from the UI. The underlying modules (``aiposter/llm.py``, ``prompts.py``,
``fallback.py``, ``llm_cache.py``) are left in place, unreferenced here, in
case the feature is re-enabled later.
"""

from __future__ import annotations

import streamlit as st

import ui
from aiposter import guards, photo, pipeline, render, themes
from aiposter.spec import ThemeSpec
from aiposter.timing import Timings

st.set_page_config(page_title="AI Poster Studio", page_icon="🗺️", layout="wide")
ui.inject_css()

MAX_HISTORY = 6


# --------------------------------------------------------------------------
# Shared components
# --------------------------------------------------------------------------


def swatch_row(theme: dict, caption: str = "") -> None:
    """A labelled colour strip for a theme (FR7.1)."""
    if caption:
        st.caption(caption)
    items = list(guards.swatch_order(theme))
    for start in range(0, len(items), 6):
        row = items[start:start + 6]
        for column, (key, value) in zip(st.columns(len(row)), row):
            with column:
                st.markdown(
                    f"<div style='background:{value};height:48px;border-radius:6px;"
                    f"border:1px solid rgba(128,128,128,.35)'></div>"
                    f"<div style='font-size:11px;margin-top:4px'>"
                    f"<b>{themes.FIELD_LABELS.get(key, key)}</b><br><code>{value}</code></div>",
                    unsafe_allow_html=True,
                )


def color_editor(base_theme: dict, key_prefix: str) -> dict:
    """The "Customize colors" panel (FR7.3).

    Only the nine independent colours get pickers. ``gradient_color`` and
    ``road_default`` are derived and are shown read-only — offering pickers for
    them would let a user set a value the guards immediately overwrite, which
    reads as a bug rather than a rule.
    """
    edits: dict[str, str] = {}
    with st.expander("🎨 Customize colors"):
        st.caption(
            "Edited palettes are re-checked against the same WCAG and CIEDE2000 guards "
            "before rendering."
        )
        fields = list(themes.EDITABLE_COLOR_FIELDS)
        for start in range(0, len(fields), 3):
            for column, field_name in zip(st.columns(3), fields[start:start + 3]):
                with column:
                    edits[field_name] = st.color_picker(
                        themes.FIELD_LABELS[field_name],
                        value=base_theme.get(field_name, "#000000"),
                        key=f"{key_prefix}_color_{field_name}",
                    )
        st.caption(
            f"Derived automatically — gradient follows the background "
            f"(`{edits.get('bg', base_theme['bg'])}`), default road follows tertiary "
            f"(`{edits.get('road_tertiary', base_theme['road_tertiary'])}`)."
        )
    return themes.apply_edits(base_theme, edits)


def guard_report(result: guards.GuardResult) -> None:
    """What the guards measured and changed."""
    metrics = result.metrics
    left, right = st.columns(2)
    left.metric(
        "Text / background contrast",
        f"{metrics['contrast_text_bg']:.2f}:1",
        delta=f"min {metrics['min_contrast_required']}:1",
        delta_color="off",
    )
    right.metric(
        "Closest road tiers (ΔE2000)",
        f"{metrics['min_adjacent_delta_e']:.2f}",
        delta=f"min {metrics['min_delta_e_required']}",
        delta_color="off",
    )

    if result.passed and not result.corrections:
        st.success("Passed both guards unchanged.")
    elif result.passed:
        st.warning(f"Passed after {len(result.corrections)} automatic correction(s).")
    else:
        st.error("Could not be brought fully within the thresholds.")

    if result.corrections:
        with st.expander(f"Corrections applied ({len(result.corrections)})", expanded=True):
            for correction in result.corrections:
                cols = st.columns([2, 1, 1, 4])
                cols[0].markdown(f"**{themes.FIELD_LABELS.get(correction.field, correction.field)}**")
                for col, value in ((cols[1], correction.before), (cols[2], correction.after)):
                    col.markdown(
                        f"<div style='background:{value};height:26px;border-radius:4px;"
                        f"border:1px solid rgba(128,128,128,.35)'></div>"
                        f"<code style='font-size:10px'>{value}</code>",
                        unsafe_allow_html=True,
                    )
                cols[3].caption(
                    f"{correction.reason} "
                    f"({correction.metric_before:.2f} → {correction.metric_after:.2f})"
                )

    if result.violations:
        with st.expander(f"Violations found ({len(result.violations)})"):
            for violation in result.violations:
                st.write("•", violation)


def performance_panel(timings: Timings, extra: str = "") -> None:
    """Per-stage timings (NFR8)."""
    with st.expander(f"⚡ Performance — {timings.total_ms / 1000:.1f} s total"):
        if extra:
            st.caption(extra)
        for label, milliseconds, note in timings.rows():
            columns = st.columns([3, 2, 3])
            columns[0].write(label)
            columns[1].write(f"{milliseconds / 1000:.2f} s")
            columns[2].caption(note)
        st.caption("Target: p50 ≤ 15 s for a cached city (NFR7).")


def remember_poster(path, city: str, theme: dict) -> None:
    """Push a poster onto the session history grid (FR7.4).

    Session state only — nothing is persisted (security.md §6).
    """
    history = st.session_state.setdefault("history", [])
    entry = {"path": str(path), "city": city, "theme_name": theme.get("name", ""), "bg": theme["bg"]}
    history = [h for h in history if h["path"] != entry["path"]]
    history.insert(0, entry)
    st.session_state["history"] = history[:MAX_HISTORY]


def do_render(theme: dict, city: str, country: str, distance: int, timings: Timings) -> None:
    """Render, remember, and publish to the shared Result panel."""
    cached = render.is_cached(city, country, distance)
    spinner = "Re-rendering from cached map data…" if cached else f"Fetching map data for {city}…"
    try:
        with st.spinner(spinner):
            path, timings = pipeline.render_poster(theme, city, country, distance, timings)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        st.error(f"Rendering failed: {exc}")
        return

    remember_poster(path, city, theme)
    ui.set_result(path, city, theme.get("name", ""), timings)


def _result_timings(timings: Timings) -> None:
    performance_panel(timings)


def cache_hint(city: str, country: str, distance: int) -> None:
    if city.strip() and country.strip() and render.is_cached(city.strip(), country.strip(), distance):
        st.caption("✓ Map data cached — this render will skip the download.")


# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------


def classic_tab() -> None:
    names = themes.theme_names()
    if not names:
        st.error("No stock themes found in themes/.")
        return

    left, right = st.columns([6, 7], gap="large")

    with left, ui.panel("classic"):
        ui.eyebrow("Location")
        location_columns = st.columns(2)
        city = location_columns[0].text_input(
            "City", value="Pune", placeholder="e.g., Tokyo, Paris, New York", key="classic_city"
        )
        country = location_columns[1].text_input(
            "Country", value="India", placeholder="e.g., Japan, France, USA", key="classic_country"
        )

        distance = ui.distance_control("classic")

        ui.eyebrow("Theme")
        theme_name = ui.theme_grid("classic")
        base = themes.get(theme_name)

        with st.expander("Theme colours in detail"):
            swatch_row(base, f"{themes.display_name(theme_name)} — {themes.describe(theme_name)}")

        edited = color_editor(base, f"classic_{theme_name}")
        is_edited = themes.is_modified(base, edited)

        if is_edited:
            st.caption("Palette edited — the guards will run on your version.")
            guarded, guard_result = pipeline.apply_palette_guards(edited)
            swatch_row(guarded, "Your edited palette")
            guard_report(guard_result)
        else:
            guarded = base
            with st.expander("How this stock theme measures against the guard thresholds"):
                st.json(guards.evaluate_only(base))

        cache_hint(city, country, distance)
        go = st.button(
            "Generate Poster",
            type="primary",
            use_container_width=True,
            key="classic_render",
            disabled=not (city.strip() and country.strip()),
        )
        if go:
            do_render(guarded, city.strip(), country.strip(), distance, Timings())

    with right, ui.result_container("classic"):
        ui.result_panel("classic", _result_timings)


_MOOD_CAPTIONS = {
    "warm": "Warm-toned — reds/oranges lead the palette.",
    "cool": "Cool-toned — blues/greens lead the palette.",
    "dark": "Dark, moody — the poster's background follows the photo's darkest tone.",
    "pastel": "Soft pastel — low-saturation clusters throughout.",
    "vivid": "Vivid, saturated — the most prominent road tier follows the boldest colour.",
}


def photo_tab() -> None:
    left, right = st.columns([6, 7], gap="large")

    with left, ui.panel("photo"):
        ui.eyebrow("Match a Photo")
        st.caption(
            "Upload a photo to derive a theme from its colours and mood. Processed in memory "
            "only — nothing is written to disk or sent anywhere (security.md §3.2)."
        )
        uploaded = st.file_uploader("Photo", type=["png", "jpg", "jpeg", "webp"], key="photo_upload")

        location_columns = st.columns(2)
        city = location_columns[0].text_input(
            "City", placeholder="e.g., Tokyo, Paris, New York", key="photo_city"
        )
        country = location_columns[1].text_input(
            "Country", placeholder="e.g., Japan, France, USA", key="photo_country"
        )
        distance = ui.distance_control("photo")

        guarded = None
        timings = Timings()
        if uploaded is not None:
            try:
                image = photo.validate_upload(uploaded.getvalue())
            except photo.UploadError as exc:
                st.error(f"Couldn't use that file: {exc}")
            else:
                st.image(image, caption="Uploaded photo", use_container_width=True)

                with st.spinner("Extracting palette and classifying mood…"):
                    raw_theme, mood, swatches = photo.derive_theme(image, timings=timings)
                    theme = ThemeSpec(**raw_theme).to_theme_dict()

                st.info(f"**Detected mood: {mood}** — {_MOOD_CAPTIONS.get(mood, '')}")

                ui.eyebrow("Extracted palette")
                extracted_html = "".join(
                    f"<div style='background:{hex_color};height:40px;flex:1;border-radius:4px;"
                    f"border:1px solid rgba(128,128,128,.35)' title='{hex_color} ({weight:.0%})'></div>"
                    for hex_color, weight in swatches
                )
                st.markdown(f"<div style='display:flex;gap:4px'>{extracted_html}</div>", unsafe_allow_html=True)

                ui.eyebrow("Theme")
                swatch_row(theme, f"{theme['name']} — {theme['description']}")

                edited = color_editor(theme, "photo")
                is_edited = themes.is_modified(theme, edited)
                if is_edited:
                    st.caption("Palette edited — the guards will re-run on your version.")
                    guarded, guard_result = pipeline.apply_palette_guards(edited, timings)
                    swatch_row(guarded, "Your edited palette")
                else:
                    guarded, guard_result = pipeline.apply_palette_guards(theme, timings)
                    if guard_result.changed:
                        swatch_row(guarded, "After guard corrections")

                ui.eyebrow("Guard checks")
                guard_report(guard_result)

        cache_hint(city, country, distance)
        go = st.button(
            "Generate Poster",
            type="primary",
            use_container_width=True,
            key="photo_render",
            disabled=not (guarded is not None and city.strip() and country.strip()),
        )
        if go:
            do_render(guarded, city.strip(), country.strip(), distance, timings)

    with right, ui.result_container("photo"):
        ui.result_panel("photo", _result_timings)


ui.page_header()

classic_tab_widget, photo_tab_widget = st.tabs(["Classic", "Match a Photo"])
with classic_tab_widget:
    classic_tab()
with photo_tab_widget:
    photo_tab()

ui.history_grid()
ui.footer()
