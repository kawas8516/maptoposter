"""Run one photo through the Match-a-Photo pipeline and print the result.

By default it stops before rendering, so the extracted swatches, detected
mood and guard report can be inspected on their own. Pass --render to go on
and draw the poster.

    python scripts/try_photo.py sunset.jpg
    python scripts/try_photo.py sunset.jpg --render --city Pune --country India
    python scripts/try_photo.py sunset.jpg --render --city Pune --country India -d 10000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiposter.guards import apply_guards  # noqa: E402
from aiposter.photo import derive_theme, validate_upload  # noqa: E402
from aiposter.spec import ThemeSpec  # noqa: E402
from aiposter.timing import Timings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive a theme from a photo")
    parser.add_argument("image", help="Path to a png/jpg/jpeg/webp photo")
    parser.add_argument("--render", action="store_true", help="Also render the poster")
    parser.add_argument("--city", help="City to render (required with --render)")
    parser.add_argument("--country", help="Country to render (required with --render)")
    parser.add_argument("--distance", "-d", type=int, default=3000, help="Map radius in metres")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"No such file: {image_path}")
        return 2

    print("=" * 72)
    print(f"PHOTO: {image_path}")
    print("=" * 72)

    image = validate_upload(image_path.read_bytes())
    print(f"Decoded: {image.size[0]}x{image.size[1]} {image.mode}")

    timings = Timings()
    raw_theme, mood, swatches = derive_theme(image, timings=timings)

    print(f"\n--- DETECTED MOOD: {mood} ---")

    print("\n--- EXTRACTED PALETTE (lightest -> darkest) ---")
    for hex_color, weight in swatches:
        print(f"  {hex_color}  {weight:.1%}")

    theme = ThemeSpec(**raw_theme).to_theme_dict()

    print("\n--- DERIVED THEME (before guards) ---")
    print(json.dumps(theme, indent=2))

    guarded = apply_guards(theme)

    print("\n--- GUARD REPORT ---")
    print(f"passed: {guarded.passed}")
    print(f"contrast(text,bg): {guarded.metrics['contrast_text_bg']} "
          f"(minimum {guarded.metrics['min_contrast_required']})")
    print(f"min adjacent dE2000: {guarded.metrics['min_adjacent_delta_e']} "
          f"(minimum {guarded.metrics['min_delta_e_required']})")

    print(f"\nviolations ({len(guarded.violations)}):")
    for violation in guarded.violations:
        print(f"  - {violation}")

    print(f"\ncorrections ({len(guarded.corrections)}):")
    for correction in guarded.corrections:
        print(f"  - {correction.field}: {correction.before} -> {correction.after}")
        print(f"      {correction.reason}")
        print(f"      metric {correction.metric_before:.2f} -> {correction.metric_after:.2f}")

    print("\n--- FINAL THEME (after guards) ---")
    print(json.dumps(guarded.theme, indent=2))

    print("\n--- TIMINGS ---")
    for label, ms, note in timings.rows():
        print(f"  {label:24} {ms / 1000:.2f} s  {note}")

    if not args.render:
        return 0

    if not (args.city and args.country):
        print("\nCannot render: pass --city and --country.")
        return 1

    from aiposter import render  # noqa: PLC0415 - deferred; importing loads the engine

    print(f"\n--- RENDERING {args.city}, {args.country} at {args.distance} m ---")
    point = render.geocode(args.city, args.country)
    print(f"Coordinates: {point[0]:.4f}, {point[1]:.4f}")
    path = render.render(guarded.theme, args.city, args.country, point, args.distance)
    print(f"Saved: {path}  ({path.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
