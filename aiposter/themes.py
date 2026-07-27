"""Registry of the 17 stock themes (FR7.1).

Single source of truth for anything that needs a stock palette: the Classic
tab's dropdown, the colour-picker defaults, and the offline fallback. Loading
happens once and is cached, so the seventeen small JSON reads do not repeat on
every Streamlit rerun.

Every theme is validated through :class:`~aiposter.spec.ThemeSpec` on load. That
is not ceremony: it normalises hex casing, fills the two derived fields, and
means a malformed or hand-edited theme file fails here with a clear message
rather than deep inside matplotlib.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from .spec import ThemeSpec

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"

#: Distance presets, mirroring the reference site (FR7.2).
DISTANCE_PRESETS: tuple[tuple[str, int], ...] = (
    ("3 km", 3000),
    ("5 km", 5000),
    ("10 km", 10000),
    ("15 km", 15000),
)
DEFAULT_DISTANCE_M = 3000

#: Colours a user may edit directly (FR7.3). `gradient_color` and `road_default`
#: are derived — exposing them would let a user create a state the guards would
#: immediately overwrite, which reads as a bug.
EDITABLE_COLOR_FIELDS: tuple[str, ...] = (
    "bg",
    "text",
    "water",
    "parks",
    "road_motorway",
    "road_primary",
    "road_secondary",
    "road_tertiary",
    "road_residential",
)

#: Human-readable labels for the colour pickers.
FIELD_LABELS: dict[str, str] = {
    "bg": "Background",
    "text": "Text",
    "water": "Water",
    "parks": "Parks",
    "road_motorway": "Motorway",
    "road_primary": "Primary road",
    "road_secondary": "Secondary road",
    "road_tertiary": "Tertiary road",
    "road_residential": "Residential road",
    "gradient_color": "Gradient (= background)",
    "road_default": "Default road (= tertiary)",
}


class ThemeNotFoundError(KeyError):
    """Raised when a theme name is not in the registry."""


@lru_cache(maxsize=1)
def registry() -> dict[str, dict]:
    """All stock themes as ``{name: theme_dict}``, sorted by name.

    Cached: the files do not change while the app is running.
    """
    themes: dict[str, dict] = {}
    if not THEMES_DIR.is_dir():
        return themes

    for path in sorted(THEMES_DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read theme file {path.name}: {exc}") from exc
        try:
            themes[path.stem] = ThemeSpec.model_validate(raw).to_theme_dict()
        except ValidationError as exc:
            raise ValueError(f"theme file {path.name} is not a valid theme: {exc}") from exc

    return themes


def theme_names() -> list[str]:
    """Stock theme slugs, sorted."""
    return list(registry())


def get(name: str) -> dict:
    """A copy of one stock theme, safe for the caller to mutate."""
    themes = registry()
    if name not in themes:
        raise ThemeNotFoundError(f"unknown theme {name!r}; available: {', '.join(themes)}")
    return dict(themes[name])


def display_name(name: str) -> str:
    """The theme's own display name, falling back to its slug."""
    try:
        return registry()[name].get("name", name)
    except KeyError:
        return name


def describe(name: str) -> str:
    """The theme's one-line description."""
    try:
        return registry()[name].get("description", "")
    except KeyError:
        return ""


def apply_edits(base: dict, edits: dict[str, str]) -> dict:
    """Overlay user colour edits onto a theme, re-deriving dependent fields.

    Returns a new dict. ``gradient_color`` follows ``bg`` and ``road_default``
    follows ``road_tertiary``, matching the invariant every stock theme holds,
    so a user editing the background does not leave a mismatched gradient band
    behind.
    """
    merged = dict(base)
    for key, value in edits.items():
        if key in EDITABLE_COLOR_FIELDS and value:
            merged[key] = value.upper() if value.startswith("#") else f"#{value.upper()}"

    merged["gradient_color"] = merged["bg"]
    merged["road_default"] = merged["road_tertiary"]
    return merged


def is_modified(base: dict, candidate: dict) -> bool:
    """Whether ``candidate`` differs from ``base`` in any colour field."""
    keys = set(EDITABLE_COLOR_FIELDS) | {"gradient_color", "road_default"}
    return any(base.get(k) != candidate.get(k) for k in keys)


def preset_label(distance: int) -> Optional[str]:
    """The preset label for a distance, or ``None`` if it is a custom value."""
    for label, metres in DISTANCE_PRESETS:
        if metres == distance:
            return label
    return None


def nearest_preset(distance: int) -> int:
    """Snap an arbitrary distance to the closest preset.

    The model picks its own radius, but the UI offers fixed presets; this keeps
    the dropdown showing something truthful rather than silently disagreeing
    with the value actually used.
    """
    return min((m for _, m in DISTANCE_PRESETS), key=lambda m: abs(m - distance))
