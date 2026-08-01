"""Pre-cache OSM graph data for a curated set of showcase cities (NFR3).

Warms the geocode + OSM graph + water/parks feature caches for a handful of
recognizable, geographically diverse cities at the Classic tab's default
3 km radius, so a live demo on this machine can run the Classic tab offline
(only the Describe tab's LLM call needs internet — this script does not
touch that path at all).

    python scripts/precache_showcase.py

Uses aiposter.render.prefetch(), the same throttled/cached engine helper the
app itself calls (security.md §5, NFR4) — no new fetch logic here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiposter import render, themes  # noqa: E402

#: Recognizable, geographically diverse showcase cities.
SHOWCASE_CITIES: list[tuple[str, str]] = [
    ("Tokyo", "Japan"),
    ("Paris", "France"),
    ("New York", "USA"),
    ("London", "UK"),
    ("Pune", "India"),
    ("Venice", "Italy"),
    ("Barcelona", "Spain"),
    ("Dubai", "UAE"),
    ("Singapore", "Singapore"),
    ("Cairo", "Egypt"),
]


def main() -> int:
    distance = themes.DEFAULT_DISTANCE_M
    print(f"Pre-caching {len(SHOWCASE_CITIES)} cities at {distance} m radius\n")

    warmed = 0
    for index, (city, country) in enumerate(SHOWCASE_CITIES, start=1):
        already = render.is_cached(city, country, distance)
        status = "already cached" if already else "fetching…"
        print(f"  [{index:>2}/{len(SHOWCASE_CITIES)}] {city}, {country} — {status}")

        point = render.prefetch(city, country, distance)
        if point is None:
            print(f"      FAILED to warm {city}, {country} — check connectivity/city name")
            continue
        warmed += 1
        if not already:
            print(f"      cached at {point[0]:.4f}, {point[1]:.4f}")

    print(f"\n{warmed}/{len(SHOWCASE_CITIES)} cities cached and ready for an offline demo.")
    return 0 if warmed == len(SHOWCASE_CITIES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
