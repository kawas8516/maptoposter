"""Evaluation harness (FR5.1) — validity, repair, guard and latency rates.

Runs a prompt set through the generation pipeline and writes one CSV row per
prompt, then prints the aggregates the PRD's §7 gate is measured against.

Rendering is off by default: it dominates wall time and says nothing about the
model, so the default run measures the text pipeline alone. Pass --render to
include it in the latency figures.

    python scripts/evaluate.py --limit 20
    python scripts/evaluate.py --limit 20 --no-cache      # force live calls
    python scripts/evaluate.py --limit 20 --out runs/before.csv
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiposter import pipeline, themes  # noqa: E402
from aiposter.llm import ThemeGenerator  # noqa: E402
from aiposter.timing import STAGES  # noqa: E402

#: A deliberately varied prompt set: moods, named and unnamed cities, colour
#: words, and a few deliberately vague ones to probe the failure paths.
PROMPTS: list[str] = [
    "a moody, rain-soaked Tokyo at night with gold roads",
    "a warm monsoon evening over Pune, terracotta rooftops and green hills",
    "a sun-bleached whitewashed town on the Portuguese coast",
    "a quiet foggy morning in a northern harbour city",
    "neon cyberpunk Seoul, electric pink and cyan",
    "an austere Scandinavian winter, almost monochrome",
    "the golden hour over Rome, warm stone and long shadows",
    "a cold blue technical blueprint of Berlin",
    "deep forest greens around Vancouver",
    "a dusty desert city at noon, bleached and hot",
    "Venice at dawn, pale water and soft pink light",
    "brutalist concrete grey, stark and industrial",
    "a tropical Singapore afternoon, humid and vivid",
    "muted vintage postcard tones of Havana",
    "midnight over Reykjavik under the aurora",
    "an autumn morning in Kyoto, maple reds",
    "coastal Sydney, ocean blues and sandstone",
    "a soft pastel dream, candy colours",
    "something calm",
    "bold and graphic, high contrast only",
    "the Mumbai coastline at sunset",
    "an old European city with narrow winding streets",
    "arctic ice, pale and cold",
    "a jazz club at 2am",
]


def run(limit: int, use_cache: bool, do_render: bool, out_path: Path, delay: float) -> int:
    prompts = PROMPTS[:limit]
    generator = ThemeGenerator(use_cache=use_cache)
    rows: list[dict] = []

    print(f"Running {len(prompts)} prompts (cache={'on' if use_cache else 'off'}, "
          f"render={'on' if do_render else 'off'}, delay={delay}s)\n")

    for index, prompt in enumerate(prompts, start=1):
        # Free-tier inference rate-limits a rapid burst, and a throttled 429 is
        # indistinguishable in the aggregate from a model that cannot produce
        # valid JSON. Pacing the run keeps the validity figures measuring the
        # model rather than the quota (security.md §5).
        if index > 1 and delay > 0:
            time.sleep(delay)

        started = time.perf_counter()
        row: dict = {
            "prompt": prompt,
            "error": "",
            "first_error": "",
            "delivered": False,
            "source": "",
            "cache_hit": False,
            "first_attempt_valid": False,
            "repair_attempted": False,
            "repair_succeeded": False,
            "backup_used": False,
            "fallback_used": False,
            "network_failure": False,
            "guard_passed": False,
            "guard_violations": 0,
            "guard_corrections": 0,
            "contrast": 0.0,
            "min_adjacent_delta_e": 0.0,
        }

        try:
            prepared = pipeline.prepare_from_description(prompt, generator=generator)
            trace = prepared.generation.trace if prepared.generation else None
            guard = prepared.guard_result

            # A transport failure is not a schema failure. Recording it keeps a
            # rate-limited run from being misread as poor model output.
            failed = [a for a in (trace.attempts if trace else []) if not a.ok]
            first_error = failed[0].error if failed else ""
            network_failure = any(
                a.error and ":" in a.error and a.error.split(":")[0].endswith("Error")
                and "Validation" not in a.error
                for a in failed
            )

            row.update({
                "delivered": True,
                "first_error": (first_error or "")[:160],
                "network_failure": network_failure,
                "source": trace.source if trace else "",
                "cache_hit": trace.cache_hit if trace else False,
                "first_attempt_valid": trace.first_attempt_valid if trace else False,
                "repair_attempted": trace.repair_attempted if trace else False,
                "repair_succeeded": trace.repair_succeeded if trace else False,
                "backup_used": trace.backup_used if trace else False,
                "fallback_used": trace.fallback_used if trace else False,
                "guard_passed": guard.passed,
                "guard_violations": len(guard.violations),
                "guard_corrections": len(guard.corrections),
                "contrast": guard.metrics.get("contrast_text_bg", 0.0),
                "min_adjacent_delta_e": guard.metrics.get("min_adjacent_delta_e", 0.0),
                "city": prepared.city or "",
                "country": prepared.country or "",
                "distance": prepared.distance,
            })

            if do_render and prepared.ready:
                _, timings = pipeline.render_poster(
                    prepared.theme,
                    str(prepared.city),
                    str(prepared.country),
                    themes.nearest_preset(prepared.distance),
                    prepared.timings,
                )
                prepared.timings = timings

            row.update(prepared.timings.as_dict())
            status = "ok " if guard.passed else "GUARD"
        except Exception as exc:  # noqa: BLE001 - a failed prompt is a data point
            row["error"] = f"{type(exc).__name__}: {exc}"[:200]
            status = "FAIL"

        row["wall_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        rows.append(row)
        print(f"  [{index:>3}/{len(prompts)}] {status}  {row['wall_ms'] / 1000:5.1f}s  {prompt[:52]}")

    write_csv(rows, out_path)
    summarize(rows)
    return 0


def write_csv(rows: list[dict], out_path: Path) -> None:
    """Prompts and metrics only — no user identifiers (security.md §6)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "prompt", "delivered", "source", "cache_hit", "first_attempt_valid",
        "repair_attempted", "repair_succeeded", "backup_used", "fallback_used",
        "network_failure", "guard_passed", "guard_violations", "guard_corrections",
        "contrast", "min_adjacent_delta_e", "city", "country", "distance",
        *STAGES, "total_ms", "wall_ms", "first_error", "error",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"\nWrote {len(rows)} rows to {out_path}")


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(round(fraction * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[index]


def summarize(rows: list[dict]) -> None:
    total = len(rows)
    if not total:
        return
    ok = [r for r in rows if r["delivered"]]
    walls = [r["wall_ms"] for r in rows]

    def pct(count: int) -> str:
        return f"{count}/{total} ({100.0 * count / total:.0f}%)"

    reachable = [r for r in ok if not r["network_failure"]]
    unreachable = len(ok) - len(reachable)

    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"  Posters delivered              {pct(len(ok))}          target 100%")
    print(f"  Cache hits                     {pct(sum(r['cache_hit'] for r in ok))}")

    if unreachable:
        print(f"\n  ⚠ {unreachable}/{total} prompts hit a transport failure (rate limit, timeout,")
        print("    quota). Those are NOT schema failures. Validity below is computed")
        print("    over the prompts that actually reached a model; re-run with a")
        print("    larger --delay for a clean measurement.")

    print(f"\n  Schema validity (over {len(reachable)} prompts that reached a model)")
    if reachable:
        base = len(reachable)

        def rpct(count: int) -> str:
            return f"{count}/{base} ({100.0 * count / base:.0f}%)"

        valid_after = sum(r["first_attempt_valid"] or r["repair_succeeded"] for r in reachable)
        print(f"    Valid on first attempt       {rpct(sum(r['first_attempt_valid'] for r in reachable))}"
              f"          target >=80%")
        print(f"    Valid after one repair       {rpct(valid_after)}          target >=95%")
        print(f"    Repair round-trips           {rpct(sum(r['repair_attempted'] for r in reachable))}")
        print(f"    Backup model used            {rpct(sum(r['backup_used'] for r in reachable))}")
        print(f"    Stock-theme fallback         {rpct(sum(r['fallback_used'] for r in reachable))}")
    else:
        print("    no prompts reached a model")

    print(f"\n  Guards passed                  {pct(sum(r['guard_passed'] for r in ok))}          target 100%")
    print(f"  Guards triggered a correction  {pct(sum(r['guard_corrections'] > 0 for r in ok))}")

    print("\n  Latency (wall clock, per prompt)")
    print(f"    p50  {percentile(walls, 0.50) / 1000:6.2f} s          target <=15 s (NFR7)")
    print(f"    p95  {percentile(walls, 0.95) / 1000:6.2f} s          target <=30 s (NFR7)")
    print(f"    mean {statistics.mean(walls) / 1000:6.2f} s")
    print(f"    max  {max(walls) / 1000:6.2f} s")

    print("\n  Mean per-stage (ms)")
    for stage in STAGES:
        values = [r.get(stage, 0.0) for r in ok if r.get(stage)]
        if values:
            print(f"    {stage:<14} {statistics.mean(values):8.1f}")

    failures = [r for r in rows if r["error"]]
    if failures:
        print(f"\n  {len(failures)} error(s):")
        for row in failures[:5]:
            print(f"    - {row['prompt'][:40]}: {row['error'][:80]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FR5.1 evaluation harness")
    parser.add_argument("--limit", type=int, default=len(PROMPTS), help="How many prompts to run")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the response cache")
    parser.add_argument("--render", action="store_true", help="Also render each poster")
    parser.add_argument("--out", type=Path, default=None, help="CSV output path")
    parser.add_argument(
        "--delay", type=float, default=3.0,
        help="Seconds to pause between prompts, to stay under free-tier rate limits",
    )
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = args.out or Path("runs") / f"eval_{stamp}.csv"
    return run(args.limit, not args.no_cache, args.render, out, args.delay)


if __name__ == "__main__":
    raise SystemExit(main())
