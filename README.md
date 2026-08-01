# AI Poster Studio

Describe an aesthetic in plain English and get a minimalist city map poster in a
theme designed to match — automatically checked so it stays readable.

A fork of [maptoposter](https://github.com/originalankur/maptoposter) by Ankur
Gupta. The rendering engine is upstream's and is **unmodified**; this fork adds
an AI theming layer on top of it.

```
"a moody, rain-soaked Tokyo at night with gold roads"
        │
        ▼
   hosted LLM  ──►  validate  ──►  legibility guards  ──►  maptoposter  ──►  poster
                   (pydantic)      (WCAG + CIEDE2000)      (unchanged)
```

---

## Why

maptoposter ships 17 hand-written theme files. They are good, but they are a
fixed catalogue: you cannot ask for a mood, and there is no mechanism to stop a
new palette from being illegible. This fork replaces the catalogue with a
generator, and adds the missing safety net.

Two things make that more than a wrapper around a chat model:

**Model output is treated as untrusted input.** It is parsed with `json.loads`,
validated by a pydantic schema that forbids unknown fields, and range-checked
before it reaches a geocoder or a file path. A model cannot inject render
parameters, escape the output directory, or make the app request a 500 km map.

**Legibility is enforced, not hoped for.** Every generated palette is measured
for WCAG text contrast and CIEDE2000 separation between road tiers. Failures are
corrected by nudging lightness in CIELAB, and every change is reported back to
you rather than applied silently.

## Install

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Set a Hugging Face token so the Describe tab can reach a model:

```bash
export HF_TOKEN=hf_...             # or `huggingface-cli login`
```

The token is read from `HF_TOKEN`, then `.streamlit/secrets.toml`, then your
cached CLI login. It is never written to disk by this project and never logged.
Without one, the Describe tab still works — it falls back to the closest stock
theme.

The Match a Photo tab additionally pulls in `scikit-learn`, `transformers` and
`torch` (already pinned in `requirements.txt`). First use downloads CLIP's
weights (~600MB) to the Hugging Face cache. Everything here runs on CPU — no
GPU is needed for this tab. (The Gallery tab's notebook is the one part of
this project that wants a GPU, and it runs on Colab, not locally — see
[ControlNet stretch phase](#controlnet-stretch-phase) below.)

## Run

```bash
streamlit run app.py
```

**Describe tab** — type a mood, get a theme. The spec, the swatches and the
guard report all appear *before* rendering, so you can reject a bad palette or
fix a misidentified city without waiting on the map download. City, country and
radius are extracted from your description and pre-filled as editable fields.
Naming the city up front is faster: the map download then runs concurrently with
the model call instead of after it.

**Classic tab** — the 17 stock themes with swatch previews and 3/5/10/15 km
distance presets. Unedited stock themes render as their author designed them;
the guards run only if you change a colour.

**Customize colors** — on either tab, expand the panel and adjust any of the
nine independent colours. Edited palettes go through the same guards, and a
re-render reuses the cached map data, so it costs only drawing time. `gradient_color`
and `road_default` are derived and follow `bg` and `road_tertiary` automatically.

**Match a Photo tab** — upload a photo instead of describing one. A K-Means
(k=6) cluster in CIELAB space extracts its palette, CLIP classifies the
overall mood zero-shot (warm/cool/dark/pastel/vivid), and the clusters are
assigned to poster roles by a documented, mood-aware rule set: lightest/
darkest become background/text (flipped if the mood is "dark", so a genuinely
dark photo produces a dark-background poster instead of being forced light);
water and parks are picked by CIELAB hue match to blue/green; motorway and
residential come from what's darkest/lightest of what's left (tie-broken
toward redder for "warm" or highest-chroma for "vivid"); the three remaining
road tiers are generated as an even lightness ramp between them. The result
goes through the identical guards as every other theme source before
rendering. See `aiposter/photo.py` for the full rule set with rationale.

**Gallery tab** — read-only. Groups any `{city}_{style}.png` files it finds in
`gallery/` by city and displays them; shows an honest "nothing here yet" empty
state otherwise. Nothing on this tab runs a model or needs a GPU — the images
are pre-generated offline by a Colab notebook and copied in. See
[ControlNet stretch phase](#controlnet-stretch-phase) below.

### Without the UI

```bash
# generate a theme and inspect it, no rendering
python scripts/try_describe.py "a foggy northern harbour at dawn"

# generate and render in one pass
python scripts/try_describe.py "warm monsoon evening" --render --city Pune --country India

# render any theme JSON
python scripts/render_theme.py scripts/rainy_night_tokyo.json \
    --city Tokyo --country Japan -d 10000

# derive a theme from a photo and inspect it (exercises the real CLIP model)
python scripts/try_photo.py path/to/photo.jpg --city Tokyo --country Japan

# warm the OSM cache for the 10 showcase cities (offline demo mode)
python scripts/precache_showcase.py

# evaluation harness: validity, repair, guard and latency rates -> CSV
# (30 prompts today; see "Evaluation harness" below for the PRD's ~100 target)
python scripts/evaluate.py --limit 20
```

> The evaluation harness paces itself (`--delay`, default 3 s). Free-tier
> inference rate-limits a rapid burst, and a throttled request is
> indistinguishable in the aggregate from a model that cannot produce valid
> JSON — so an unpaced run reports a validity figure that is really a quota
> figure. The summary separates transport failures from schema failures for the
> same reason.

The original CLI is untouched and still works — see
[docs/UPSTREAM_README.md](docs/UPSTREAM_README.md):

```bash
python create_map_poster.py --city Paris --country France --theme noir
```

## How the theming layer works

| Module | Role |
|---|---|
| `aiposter/spec.py` | `PosterSpec` / `ThemeSpec` — the pydantic contract model output must satisfy |
| `aiposter/prompts.py` | System prompt, embedded JSON Schema, three few-shot examples |
| `aiposter/llm.py` | Hugging Face client, repair round-trip, model and heuristic fallbacks |
| `aiposter/guards.py` | sRGB↔CIELAB, WCAG contrast, CIEDE2000, auto-correction |
| `aiposter/fallback.py` | Offline keyword → nearest stock theme |
| `aiposter/photo.py` | K-Means (LAB) palette extraction, CLIP zero-shot mood, lightness-ordered role assignment (Match a Photo) |
| `aiposter/render.py` | Theme injection into the upstream engine; safe output paths |
| `aiposter/themes.py` | Registry of the 17 stock themes; colour-edit merging |
| `aiposter/pipeline.py` | Orchestration: concurrency, guards, staged rendering |
| `aiposter/llm_cache.py` | Disk cache of model responses, keyed by normalised prompt |
| `aiposter/timing.py` | Per-stage timing instrumentation |

### Generation always returns something

1. Ask `Qwen/Qwen2.5-7B-Instruct`.
2. If the JSON fails validation, **one** repair round-trip carrying the
   validation error back to the model.
3. If that fails, the same two steps against `Qwen/Qwen2.5-72B-Instruct`.
4. If that fails, an offline keyword match to the nearest stock theme.

The repair message contains the validator's complaint and nothing else — no
stack traces, no file paths, no environment details.

`meta-llama/Llama-3.1-8B-Instruct` is deliberately not used: it is gated behind
manual licence approval, so calls fail until a human is approved.

### Photo-to-theme pipeline

1. K-Means (k=6) over the photo's pixels in CIELAB space — perceptual
   clusters, not raw RGB — via `aiposter/guards.py`'s existing `srgb_to_lab`/
   `lab_to_srgb_hex`, so there's one color-math implementation, not two.
2. CLIP (`openai/clip-vit-base-patch32`) zero-shot mood classification over
   five caption-phrased prompts: warm, cool, dark, pastel, vivid.
3. Clusters are assigned to the nine independent theme fields by lightness
   order and CIELAB hue match, with the mood breaking ties between clusters
   that are close in lightness (see the Match a Photo tab description above
   for the exact rules).
4. The result is guarded and rendered through the identical path every other
   theme source uses — Describe, Classic edits, and Match a Photo all
   converge on the same `apply_palette_guards` call before a poster is drawn.

### The guards

| Check | Threshold | Rationale |
|---|---|---|
| WCAG contrast, `text` vs `bg` | ≥ 4.5:1 | One text colour serves the ~60pt city name *and* the 14pt coordinates and 8pt attribution, so the AA-normal bar is the honest one |
| CIEDE2000, adjacent road tiers | ≥ 10 | Keeps a motorway distinguishable from a primary road at poster scale |

When contrast fails, the **text** colour moves, never the background — the
background is where the aesthetic intent lives. The correction binary-searches
L\* for the smallest change that passes, so hue and chroma survive.

When two road tiers are too close, the lower-priority tier is pushed along the
ramp's lightness direction. `road_default` is excluded from the check because it
duplicates another tier by convention in all 17 stock themes.

Both thresholds live in `GuardConfig` and can be changed in one place.

> **Worth knowing:** at ΔE ≥ 10, only 3 of the 17 stock themes would pass road
> separation, and `sunset` fails contrast at 3.94:1. Generated themes are held
> to a stricter bar than the shipped catalogue. That is a defensible choice —
> hand-tuned designs earn latitude an automated palette has not — but if you
> want parity with existing practice, lower `min_delta_e` to about 6.

The colour maths is implemented directly rather than pulled from a library:
`colormath` is unmaintained and broken on numpy 2.x. The CIEDE2000
implementation is verified against 29 published reference pairs from Sharma,
Wu & Dalal (2005), including the arctangent-discontinuity cases that break naive
implementations.

## Performance

Every generation records per-stage timings — `llm_ms`, `validate_ms`,
`palette_ms`, `mood_ms`, `guard_ms`, `geocode_ms`, `graph_ms`, `render_ms` —
surfaced in a "Performance"
expander in the UI and written to the evaluation CSV. A single end-to-end number
cannot tell you whether a slow run was the model, the geocoder, the OSM download
or matplotlib; these can.

Three things keep the common path quick:

- **Overlapping** — when the city is known up front, the OSM download runs on a
  second thread while the model is still thinking. When it is not known, there
  is genuinely nothing to prefetch, and the pipeline says so rather than
  pretending otherwise.
- **Response caching** — repeated descriptions are served from disk, keyed by a
  hash of the normalised prompt plus the model id and prompt version, so editing
  the prompt or switching models does not serve stale answers.
- **Fetch/draw separation** — map data is fetched explicitly before drawing, so
  a colour edit re-renders from cache with no network at all. Measured on a
  cached city, a re-render after a colour tweak costs ~4 s, essentially all of
  it matplotlib.

## Offline demo mode

`scripts/precache_showcase.py` warms the OSM cache (geocode + road graph +
water/parks features) for 10 recognizable, geographically diverse cities —
Tokyo, Paris, New York, London, Pune, Venice, Barcelona, Dubai, Singapore,
Cairo — at the Classic tab's default 3km radius, using the same
`aiposter.render.prefetch` the app itself calls, so there's no separate fetch
logic to keep in sync. This is NFR3: once warm, only the Describe tab's LLM
call needs internet — Classic, Match a Photo (aside from CLIP's one-time
weight download) and Gallery all work fully offline.

It's idempotent (`render.is_cached` skips anything already warm), so
re-running before a demo costs nothing if the cache is already populated.

```bash
python scripts/precache_showcase.py
```

## Evaluation harness

`scripts/evaluate.py` (FR5.1) runs a fixed prompt set through the Describe
pipeline and writes one CSV row per prompt — `first_attempt_valid`,
`repair_attempted`/`repair_succeeded`, `backup_used`, `fallback_used`,
`guard_passed`/`guard_violations`/`guard_corrections`, and the full per-stage
latency breakdown plus wall-clock time — then prints validity, repair, guard
and latency rates against the PRD's §7 targets.

`PROMPTS` currently has 30 entries — moods, named and unnamed cities, explicit
named-color requests ("crimson rooftops and gold domes"), and a few
deliberately vague ones to probe the failure paths. The PRD's target is
~100; getting there is the main remaining item on the roadmap below.

It paces itself (`--delay`, default 3 s) because free-tier inference
rate-limits a rapid burst, and a throttled request is indistinguishable in
the aggregate from a model that cannot produce valid JSON — an unpaced run
reports a validity figure that is really a quota figure. The summary
separates transport failures from schema failures for the same reason.

```bash
python scripts/evaluate.py --limit 30
python scripts/evaluate.py --limit 30 --delay 8   # slower, cleaner latency numbers
```

**Latest run** (`runs/eval_20260801_194720.csv`, 30 prompts, default 3s delay):

| Metric | Result | Target |
|---|---|---|
| Posters delivered | 30/30 (100%) | 100% |
| Schema validity, first attempt* | 14/14 (100%) | ≥80% |
| Schema validity, after repair* | 14/14 (100%) | ≥95% |
| Guards passed | 30/30 (100%) | 100% |
| Guards triggered a correction | 23/30 (77%) | — |
| Latency p50 | 5.69 s | ≤15 s |
| Latency p95 | 31.23 s** | ≤30 s |

\* Computed over the 14/30 prompts that reached the model cleanly — 16/30 hit
a free-tier rate limit (a transport failure, not a schema failure, and
excluded from validity math for that reason).

\*\* Confounded by that same rate limiting — one prompt took 2194 s stuck in a
retry/backoff loop, and several others cluster at almost exactly 31 s,
consistent with a fixed internal retry-wait before eventual success rather
than organic pipeline latency. Pipeline correctness held (100% delivery, 100%
validity on reachable prompts, guards working as designed); the latency
figures need a re-run with a larger `--delay` to be trustworthy. This is a
point-in-time result, not a permanent claim — re-running produces a new CSV
under `runs/`.

## Blind preference study

`docs/blind_study/` (FR5.2, G4) scaffolds a 10-person blind preference study
comparing an AI-generated poster against a stock-theme poster of the same
city:

- `pairs_manifest.csv` — pre-seeded with the same 10 showcase cities above,
  columns for each city's AI/stock theme name and poster path (currently
  empty — needs real generated poster pairs).
- `README.md` — a Google Form structure to paste into a form you create
  yourself at forms.google.com (no Forms API access exists in this
  environment): title, description, a per-city A/B image-pair question block,
  and privacy notes (no names or emails collected; report aggregates only,
  per `security.md` §6).

Still manual: generating the actual poster pairs, filling in the manifest,
creating the real form, randomizing A/B order per city, and distributing it
to participants.

## ControlNet stretch phase

`colab/controlnet_restyle.ipynb` (FR6) is deliberately self-contained — it
never imports from `aiposter`, and nothing in the main app imports from it —
so a Colab disconnect, an OOM, or a bad generation has zero effect on the
live demo. Run on Colab with a free T4 GPU runtime, it:

1. Fetches a city's road network via `osmnx` (the same call
   `create_map_poster.py` makes) and exports it as clean black-on-white
   lineart — a ControlNet conditioning image.
2. Loads Stable Diffusion 1.5 + `lllyasviel/sd-controlnet-scribble` via
   `diffusers` and restyles that layout in 3 styles (watercolor, ink wash,
   cyberpunk) across 3 sample cities (Paris, Tokyo, Venice).
3. Saves a review grid plus individual `{city}_{style}.png` files.

Copying that output into the repo's `gallery/` directory (see
[gallery/README.md](gallery/README.md) for the exact naming convention) is
the only thing that connects it to the app — the Gallery tab picks the files
up with no code changes. The notebook has not been run in this environment
(no GPU here); every cell is unexecuted, and its own first cell says so.

## Tests

```bash
pytest tests/ -q
```

210 tests, none of which touch the network. They cover the CIEDE2000 reference
vectors, LAB round-tripping across every colour the project ships, guard
idempotence against adversarial palettes, schema rejection cases, prompt
injection isolation, the theme-injection regression described below, and (new
this round) photo-upload validation and EXIF-stripping, palette clustering,
and the mood-aware role-assignment rules.

**Latest run**: `210 passed in 6.77s`, 0 failed.

## A note on the upstream integration

`create_map_poster.py` reads its colours from a module-level `THEME` global that
is only assigned inside its `if __name__ == "__main__":` block. Run as a script
that is fine. Imported — as this app does — `THEME` stays empty and the first
colour lookup raises a bare `KeyError`, *after* the slow OSM download has already
completed.

Since upstream is not modified, `aiposter/render.py` assigns the module
attribute directly, under a lock that also serialises matplotlib's global figure
state. It validates that every required colour is present *before* the network
fetch, so a malformed theme fails in milliseconds instead of minutes. A
regression test asserts all 11 colours are live at call time.

## Project docs

- [prd.md](prd.md) — requirements and success metrics
- [security.md](security.md) — threat model, secrets handling, input validation
- [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md) — the original CLI documentation
- [docs/blind_study/README.md](docs/blind_study/README.md) — blind preference study scaffold
- [gallery/README.md](gallery/README.md) — ControlNet gallery naming convention and populate workflow

## Roadmap

**Implemented**: Describe tab, Classic tab, Match a Photo tab (K-Means
palette extraction + CLIP mood), Gallery tab (scaffold, awaiting
Colab-generated images), guards, evaluation harness (30 of the PRD's ~100
target prompts), OSM pre-cache for offline demo mode, blind-study scaffold.

**Remaining**: extend the evaluation harness toward ~100 prompts with a clean
(larger-`--delay`) latency run; actually execute
`colab/controlnet_restyle.ipynb` on real Colab hardware and populate
`gallery/`; fill in and run the blind preference study with real
participants.

## Credits and licensing

Built on [maptoposter](https://github.com/originalankur/maptoposter) by Ankur
Gupta, MIT licensed. This fork remains MIT; the original copyright notice is
retained in [LICENSE](LICENSE).

Map data © OpenStreetMap contributors, licensed under the
[ODbL](https://www.openstreetmap.org/copyright) — a different licence from the
code, and it applies to every poster you generate.

Bundled Roboto fonts are Apache 2.0. Note that `fonts/` currently ships the
`.ttf` files without their licence text; adding `fonts/LICENSE.txt` would close
that gap.
