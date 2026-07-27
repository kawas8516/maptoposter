"""Bridge from a validated theme to the unmodified maptoposter renderer.

``create_map_poster`` takes its colors from a module-level ``THEME`` global that
is only ever assigned inside its ``if __name__ == "__main__":`` block. Running
it as a script works fine; importing it does not — ``THEME`` stays the empty
dict declared at module scope, and the first color lookup raises a bare
``KeyError`` deep inside rendering, *after* the slow OSM fetch has completed.

We are not modifying upstream, so the theme is injected by assigning the module
attribute. Note that ``from create_map_poster import THEME`` followed by
rebinding does **not** work: that binds a name in this module and leaves the
renderer's own global untouched.

Both the ``THEME`` global and matplotlib's pyplot state are process-wide, so a
single lock serialises rendering across concurrent Streamlit sessions.
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Optional, Sequence

# The renderer prints check marks; on a Windows console (cp1252) that raises
# UnicodeEncodeError. Set this before importing, and harden stdout too.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

import matplotlib  # noqa: E402

matplotlib.use("Agg")  # headless; must precede the pyplot import inside the renderer

import create_map_poster as engine  # noqa: E402

#: Serialises the THEME global *and* matplotlib's global figure state.
_RENDER_LOCK = threading.Lock()

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "posters" / "generated"

#: Every key the renderer reads off THEME.
REQUIRED_THEME_KEYS: tuple[str, ...] = (
    "bg",
    "text",
    "gradient_color",
    "water",
    "parks",
    "road_motorway",
    "road_primary",
    "road_secondary",
    "road_tertiary",
    "road_residential",
    "road_default",
)


class ThemeIncompleteError(KeyError):
    """Raised when a theme is missing colors the renderer needs."""


def assert_renderable(theme: dict) -> None:
    """Fail fast, before the expensive OSM fetch, if a color is missing.

    Upstream would surface this as a ``KeyError`` only after the download.
    """
    missing = [key for key in REQUIRED_THEME_KEYS if not theme.get(key)]
    if missing:
        raise ThemeIncompleteError(f"theme is missing required colors: {', '.join(missing)}")


def output_path(city: str, distance: int, theme: dict, fmt: str = "png") -> Path:
    """Build an output path that never interpolates untrusted text.

    The city can come from a language model here, and upstream's own
    ``generate_output_filename`` drops raw city text straight into a path. We
    hash instead (security.md §3.3).
    """
    digest = hashlib.sha256(
        "|".join([city, str(distance), *(theme.get(k, "") for k in REQUIRED_THEME_KEYS)]).encode("utf-8")
    ).hexdigest()[:16]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / f"poster_{digest}.{fmt.lower()}"


def geocode(city: str, country: str) -> tuple[float, float]:
    """Look up a city via the renderer's own cached Nominatim helper.

    Reusing it keeps the 1 s throttle and the on-disk cache that the upstream
    tool already honours (NFR4 / security.md §5).
    """
    return engine.get_coordinates(city, country)


def compensated_distance(distance: int, width: float = 12, height: float = 16) -> float:
    """The radius the engine actually fetches for a requested poster radius.

    Mirrors the calculation inside ``create_poster``: the fetch is widened to
    survive the aspect-ratio crop. Duplicated here only so a prefetch warms
    exactly the cache entry the render will later look for — if these disagree,
    the prefetch is wasted work.
    """
    return distance * (max(height, width) / min(height, width)) / 4


def prefetch(city: str, country: str, distance: int) -> Optional[tuple[float, float]]:
    """Warm the geocode and OSM caches for a city ahead of rendering.

    Used to overlap the network work with the model call (NFR7). Everything the
    engine fetches is disk-cached by upstream, so a later ``render`` for the
    same city and distance finds it already present and does no network I/O.

    Returns the coordinates, or ``None`` if anything failed — a prefetch is an
    optimisation and must never break the request it was meant to speed up.
    """
    try:
        point = geocode(city, country)
        widened = compensated_distance(distance)
        engine.fetch_graph(point, widened)
        engine.fetch_features(
            point,
            widened,
            tags={"natural": ["water", "bay", "strait"], "waterway": "riverbank"},
            name="water",
        )
        engine.fetch_features(
            point, widened, tags={"leisure": "park", "landuse": "grass"}, name="parks"
        )
        return point
    except Exception:  # noqa: BLE001 - a failed prefetch is not an error
        return None


def is_cached(city: str, country: str, distance: int) -> bool:
    """Whether a render for this city and distance would avoid the network.

    Lets the UI promise a fast re-render honestly instead of guessing.
    """
    try:
        coords_key = f"coords_{city.lower()}_{country.lower()}"
        point = engine.cache_get(coords_key)
        if not point:
            return False
        lat, lon = point
        widened = compensated_distance(distance)
        return engine.cache_get(f"graph_{lat}_{lon}_{widened}") is not None
    except Exception:  # noqa: BLE001 - cache probing must never raise
        return False


def render(
    theme: dict,
    city: str,
    country: str,
    point: Sequence[float],
    distance: int,
    out_path: Optional[Path] = None,
    fmt: str = "png",
    width: float = 12,
    height: float = 16,
    display_city: Optional[str] = None,
    display_country: Optional[str] = None,
) -> Path:
    """Render a poster with ``theme`` and return the file written."""
    assert_renderable(theme)
    target = Path(out_path) if out_path else output_path(city, distance, theme, fmt)
    target.parent.mkdir(parents=True, exist_ok=True)

    with _RENDER_LOCK:
        engine.THEME = theme  # module attribute assignment - see module docstring
        try:
            engine.create_poster(
                city,
                country,
                tuple(point),
                distance,
                str(target),
                fmt,
                width,
                height,
                display_city=display_city,
                display_country=display_country,
            )
        finally:
            engine.THEME = {}

    return target


def stock_themes() -> list[str]:
    """Stock theme names, via the renderer's own discovery."""
    return engine.get_available_themes()


def load_stock_theme(name: str) -> dict:
    """Load a stock theme through the renderer's loader."""
    return engine.load_theme(name)
