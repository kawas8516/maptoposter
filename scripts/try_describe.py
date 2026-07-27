"""Run one description through the Describe pipeline and print the result.

By default it stops before rendering, so the generated spec and the guard report
can be inspected on their own. Pass --render to go on and draw the poster.

    python scripts/try_describe.py "a moody, rain-soaked Tokyo at night"
    python scripts/try_describe.py "warm monsoon evening in Pune" --render
    python scripts/try_describe.py "..." --render --city Pune --country India
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiposter.guards import apply_guards  # noqa: E402
from aiposter.llm import ThemeGenerator  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a theme from a description")
    parser.add_argument("description", nargs="*", help="The aesthetic description")
    parser.add_argument("--render", action="store_true", help="Also render the poster")
    parser.add_argument("--city", help="Override the city the model inferred")
    parser.add_argument("--country", help="Override the country the model inferred")
    parser.add_argument("--distance", "-d", type=int, help="Override the map radius in metres")
    args = parser.parse_args()

    description = " ".join(args.description).strip()
    if not description:
        parser.print_help()
        return 2

    print("=" * 72)
    print(f"PROMPT: {description}")
    print("=" * 72)

    result = ThemeGenerator().generate(description)

    print("\n--- GENERATION TRACE ---")
    print(json.dumps(result.trace.as_dict(), indent=2))

    print("\n--- MODEL OUTPUT (before guards) ---")
    print(json.dumps(result.theme, indent=2))
    if result.spec:
        print(f"\ncity={result.spec.city!r} country={result.spec.country!r} distance={result.spec.distance}")
    else:
        print("\nNo spec (fallback path) - city/country must be supplied by the user.")

    guarded = apply_guards(result.theme)

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

    print("\n--- ADJACENT ROAD-TIER DISTANCES ---")
    pairs = guarded.metrics["road_pair_delta_e"]
    tiers = ["road_motorway", "road_primary", "road_secondary", "road_tertiary", "road_residential"]
    for upper, lower in zip(tiers, tiers[1:]):
        print(f"  {upper:18} -> {lower:18} dE2000 = {pairs[f'{upper}|{lower}']:.2f}")

    print("\n--- FINAL THEME (after guards) ---")
    print(json.dumps(guarded.theme, indent=2))

    if not args.render:
        return 0

    city = args.city or (result.spec.city if result.spec else None)
    country = args.country or (result.spec.country if result.spec else None)
    distance = args.distance or (result.spec.distance if result.spec else 12000)
    if not city or not country:
        print("\nCannot render: no city/country available. Pass --city and --country.")
        return 1

    from aiposter import render  # noqa: PLC0415 - deferred; importing loads the engine

    print(f"\n--- RENDERING {city}, {country} at {distance} m ---")
    point = render.geocode(city, country)
    print(f"Coordinates: {point[0]:.4f}, {point[1]:.4f}")
    path = render.render(guarded.theme, city, country, point, distance)
    print(f"Saved: {path}  ({path.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
