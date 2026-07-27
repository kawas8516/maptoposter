"""Shared visual components for the AI Poster Studio front end.

Everything cosmetic lives here so the three tabs stay visually identical
without copy-pasting markup: the injected CSS token block, the page header,
panel/result cards, the distance slider with preset pills, the scrollable
theme-card grid, the session-history grid and the footer.

Only static strings and hex values already validated by ``ThemeSpec`` are ever
interpolated into HTML — no user text (security.md §3/§4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import streamlit as st

from aiposter import themes

#: Distance pills mirror the reference site's presets (FR7.2).
DISTANCE_PILLS: tuple[tuple[int, str], ...] = (
    (3, "Default"),
    (5, "Small"),
    (10, "Medium"),
    (15, "Large"),
)

#: One shared result slot: whichever tab renders (or a history click) writes
#: here, and every tab's Result panel reads it.
RESULT_KEY = "active_result"

_CSS = """
<style>
:root {
    --bg: #0F1117;
    --panel: #171A23;
    --panel-2: #1E2230;
    --accent: #6C63FF;
    --accent-hover: #837BFF;
    --accent-soft: rgba(108, 99, 255, 0.14);
    --text: #E6E8EF;
    --muted: #9AA0B4;
    --border: #2A2F3E;
    --radius: 14px;
}

.stApp { background: var(--bg); }
.stApp, .stApp p, .stApp label { color: var(--text); }

/* Header */
.aps-header { text-align: center; padding: 0.6rem 0 1.4rem; }
.aps-header h1 {
    color: var(--accent);
    font-size: 2.3rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin: 0 0 0.35rem;
}
.aps-header p { color: var(--muted); font-size: 0.95rem; margin: 0; }

/* Tab bar */
.stTabs [data-baseweb="tab-list"] {
    gap: 0.25rem;
    border-bottom: 1px solid var(--border);
    justify-content: center;
}
.stTabs [data-baseweb="tab"] {
    color: var(--muted);
    border-radius: 8px 8px 0 0;
    padding: 0.4rem 1.1rem;
}
.stTabs [aria-selected="true"] { color: var(--accent) !important; }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--accent); }

/* Panel cards (left control panel, right result card) */
div[class*="st-key-panel_"], div[class*="st-key-result_"] {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem 1.25rem 1.4rem;
}

/* Section eyebrows inside panels */
.aps-eyebrow {
    color: var(--muted);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin: 0.4rem 0 0.2rem;
}

/* Inputs */
.stTextInput input, .stTextArea textarea {
    background: var(--panel-2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text) !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 1px var(--accent) !important;
}

/* Buttons */
.stButton button, .stDownloadButton button {
    border-radius: 10px;
    border: 1px solid var(--border);
    transition: border-color .15s, background .15s, transform .05s;
}
.stButton button[kind="primary"], .stDownloadButton button[kind="primary"] {
    background: var(--accent);
    border-color: var(--accent);
    color: #FFFFFF;
    font-weight: 600;
}
.stButton button[kind="primary"]:hover, .stDownloadButton button[kind="primary"]:hover {
    background: var(--accent-hover);
    border-color: var(--accent-hover);
}
.stButton button[kind="secondary"], .stDownloadButton button[kind="secondary"] {
    background: var(--panel-2);
    color: var(--text);
}
.stButton button[kind="secondary"]:hover {
    border-color: var(--accent);
    color: var(--accent);
}

/* Distance pills */
[class*="st-key-pill_"] button {
    border-radius: 999px !important;
    font-size: 0.8rem;
    padding: 0.15rem 0.4rem;
    white-space: nowrap;
}

/* Theme cards: the button under each swatch */
[class*="st-key-themecard_"] button {
    border-radius: 0 0 10px 10px !important;
    border-top: none !important;
    font-size: 0.8rem;
    margin-top: -0.55rem;
}
.aps-swatch {
    border: 1px solid var(--border);
    border-bottom: none;
    border-radius: 10px 10px 0 0;
    height: 52px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.25rem;
    font-weight: 700;
}

/* Expanders */
[data-testid="stExpander"] details {
    background: var(--panel-2);
    border: 1px solid var(--border) !important;
    border-radius: 10px;
}

/* Result empty state */
.aps-empty {
    border: 2px dashed var(--border);
    border-radius: var(--radius);
    padding: 4.5rem 1.5rem;
    text-align: center;
    color: var(--muted);
}
.aps-empty .aps-empty-icon { font-size: 2.4rem; margin-bottom: 0.6rem; }

/* History cards */
div[class*="st-key-hist_"] {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 0.6rem;
}
.aps-hist-caption {
    color: var(--muted);
    font-size: 0.72rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin: 0.25rem 0 0.35rem;
}

/* Footer */
.aps-footer {
    text-align: center;
    color: var(--muted);
    font-size: 0.8rem;
    padding: 2.2rem 0 0.8rem;
}
.aps-footer a { color: var(--accent); text-decoration: none; }

/* Scrollable theme grid: subtle scrollbar */
[class*="st-key-themegrid_"] ::-webkit-scrollbar { width: 8px; }
[class*="st-key-themegrid_"] ::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 4px;
}
</style>
"""


def inject_css() -> None:
    """Inject the design tokens and component styles, once per rerun."""
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header() -> None:
    st.markdown(
        "<div class='aps-header'><h1>AI Poster Studio</h1>"
        "<p>Minimalist city map posters, themed by AI · descriptions are sent to a "
        "hosted model on Hugging Face — nothing else leaves this machine</p></div>",
        unsafe_allow_html=True,
    )


def eyebrow(text: str) -> None:
    """A small uppercase section label inside a panel."""
    st.markdown(f"<div class='aps-eyebrow'>{text}</div>", unsafe_allow_html=True)


def panel(name: str):
    """A rounded control-panel card. Use as ``with ui.panel('classic'):``."""
    return st.container(key=f"panel_{name}")


def result_container(name: str):
    """The rounded Result card container for a tab."""
    return st.container(key=f"result_{name}")


# --------------------------------------------------------------------------
# Distance slider + preset pills (FR7.2)
# --------------------------------------------------------------------------


def _snap(slider_key: str, km: int) -> None:
    st.session_state[slider_key] = km


def distance_control(key_prefix: str, default_m: int = themes.DEFAULT_DISTANCE_M) -> int:
    """A km slider with a live value plus preset pills that snap it.

    Returns the chosen distance in metres, which is what the pipeline takes.
    """
    slider_key = f"{key_prefix}_dist_km"
    if slider_key not in st.session_state:
        st.session_state[slider_key] = max(1, round(default_m / 1000))

    km = st.slider("Distance", min_value=1, max_value=15, step=1, format="%d km", key=slider_key)

    pill_columns = st.columns(len(DISTANCE_PILLS))
    for column, (preset_km, label) in zip(pill_columns, DISTANCE_PILLS):
        with column:
            st.button(
                f"{preset_km} km · {label}",
                key=f"pill_{key_prefix}_{preset_km}",
                use_container_width=True,
                type="primary" if km == preset_km else "secondary",
                on_click=_snap,
                args=(slider_key, preset_km),
            )
    return km * 1000


# --------------------------------------------------------------------------
# Theme-card grid (replaces the Classic dropdown, FR7.1)
# --------------------------------------------------------------------------


def _select_theme(state_key: str, slug: str) -> None:
    st.session_state[state_key] = slug


def theme_grid(key_prefix: str, height: int = 340) -> str:
    """A scrollable 2-column grid of theme cards; returns the selected slug.

    Each card previews its own contrast: an "Aa" sample rendered in the theme's
    text colour on its background — the poster's legibility promise, applied to
    the picker itself.
    """
    names = themes.theme_names()
    state_key = f"{key_prefix}_selected_theme"
    if st.session_state.get(state_key) not in names:
        st.session_state[state_key] = names[0]
    selected = st.session_state[state_key]

    # Highlight the selected card (swatch ring + accent button).
    st.markdown(
        f"""<style>
        .st-key-themecard_{key_prefix}_{selected} .aps-swatch {{
            border: 2px solid var(--accent); border-bottom: none;
        }}
        .st-key-themecard_{key_prefix}_{selected} button {{
            border-color: var(--accent) !important;
            background: var(--accent-soft) !important;
            color: var(--accent) !important;
            font-weight: 600;
        }}
        </style>""",
        unsafe_allow_html=True,
    )

    with st.container(height=height, key=f"themegrid_{key_prefix}"):
        for start in range(0, len(names), 2):
            for column, slug in zip(st.columns(2), names[start:start + 2]):
                theme = themes.get(slug)
                with column, st.container(key=f"themecard_{key_prefix}_{slug}"):
                    st.markdown(
                        f"<div class='aps-swatch' style='background:{theme['bg']};"
                        f"color:{theme['text']}'>Aa</div>",
                        unsafe_allow_html=True,
                    )
                    st.button(
                        themes.display_name(slug),
                        key=f"themebtn_{key_prefix}_{slug}",
                        use_container_width=True,
                        on_click=_select_theme,
                        args=(state_key, slug),
                    )
    return st.session_state[state_key]


# --------------------------------------------------------------------------
# Result panel + history (FR7.4)
# --------------------------------------------------------------------------


def set_result(path: Path | str, city: str, theme_name: str, timings=None) -> None:
    """Publish a rendered poster to the shared Result panel."""
    st.session_state[RESULT_KEY] = {
        "path": str(path),
        "city": city,
        "theme_name": theme_name,
        "timings": timings,
    }


def current_result() -> Optional[dict]:
    return st.session_state.get(RESULT_KEY)


def result_panel(name: str, performance_renderer=None) -> None:
    """The Result card body: dashed empty state, or the poster + download.

    ``performance_renderer`` is called with the stored timings when present, so
    the NFR8 panel stays next to the poster it describes without this module
    importing app-level code.
    """
    eyebrow("Result")
    entry = current_result()
    if not entry or not Path(entry["path"]).is_file():
        st.markdown(
            "<div class='aps-empty'><div class='aps-empty-icon'>🖼️</div>"
            "Your generated poster will appear here</div>",
            unsafe_allow_html=True,
        )
        return

    path = Path(entry["path"])
    st.image(str(path), use_container_width=True)
    st.download_button(
        "Download PNG",
        data=path.read_bytes(),
        file_name=f"{entry['city'].lower().replace(' ', '_')}_poster.png",
        mime="image/png",
        type="primary",
        use_container_width=True,
        key=f"dl_{name}_{path.name}",
    )
    if entry.get("timings") is not None and performance_renderer is not None:
        performance_renderer(entry["timings"])


def history_grid(columns_per_row: int = 3) -> None:
    """The full-width Previous Posters grid; clicking a card re-opens it."""
    history = [h for h in st.session_state.get("history", []) if Path(h["path"]).is_file()]
    if not history:
        return

    st.markdown("---")
    eyebrow("Previous posters")
    for start in range(0, len(history), columns_per_row):
        row = history[start:start + columns_per_row]
        for column, entry in zip(st.columns(columns_per_row), row):
            path = Path(entry["path"])
            with column, st.container(key=f"hist_{path.stem}"):
                st.image(str(path), use_container_width=True)
                st.markdown(
                    f"<div class='aps-hist-caption' title='{path.name}'>{path.name}</div>",
                    unsafe_allow_html=True,
                )
                st.button(
                    f"Open — {entry['city']}",
                    key=f"histopen_{path.stem}",
                    use_container_width=True,
                    on_click=set_result,
                    args=(entry["path"], entry["city"], entry["theme_name"]),
                )


def footer() -> None:
    st.markdown(
        "<div class='aps-footer'>AI Poster Studio · built on the "
        "<a href='https://github.com/originalankur/maptoposter'>maptoposter</a> "
        "engine (MIT) · map data © OpenStreetMap contributors</div>",
        unsafe_allow_html=True,
    )
