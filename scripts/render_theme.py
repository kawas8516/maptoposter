"""Render a poster from a theme JSON file.

Separated from generation so a theme can be rendered, tweaked and re-rendered
without spending another model call.

    python scripts/render_theme.py theme.json --city Tokyo --country Japan -d 10000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiposter import render  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a poster from a theme JSON file")
    parser.add_argument("theme", type=Path, help="Path to a theme JSON file")
    parser.add_argument("--city", "-c", required=True)
    parser.add_argument("--country", "-C", required=True)
    parser.add_argument("--distance", "-d", type=int, default=12000)
    parser.add_argument("--width", "-W", type=float, default=12)
    parser.add_argument("--height", "-H", type=float, default=16)
    parser.add_argument("--out", "-o", type=Path, default=None)
    args = parser.parse_args()

    theme = json.loads(args.theme.read_text(encoding="utf-8"))
    render.assert_renderable(theme)

    print(f"Theme: {theme.get('name', args.theme.stem)}")
    print(f"Locating {args.city}, {args.country}...")
    point = render.geocode(args.city, args.country)
    print(f"Coordinates: {point[0]:.4f}, {point[1]:.4f}")

    print(f"Rendering at {args.distance} m radius (this fetches OSM data)...")
    path = render.render(
        theme,
        args.city,
        args.country,
        point,
        args.distance,
        out_path=args.out,
        width=args.width,
        height=args.height,
    )
    print(f"Saved: {path}  ({path.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
