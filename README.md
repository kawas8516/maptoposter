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

**Match a Photo tab** — deferred to Phase 2b, shipping as a placeholder that
describes the designed pipeline. It will be built once the text pipeline meets
the PRD's evaluation benchmarks, because it reuses the same guard and render
path and hardening that once is cheaper than debugging it through two input
modalities at the same time.

### Without the UI

```bash
# generate a theme and inspect it, no rendering
python scripts/try_describe.py "a foggy northern harbour at dawn"

# generate and render in one pass
python scripts/try_describe.py "warm monsoon evening" --render --city Pune --country India

# render any theme JSON
python scripts/render_theme.py scripts/rainy_night_tokyo.json \
    --city Tokyo --country Japan -d 10000

# evaluation harness: validity, repair, guard and latency rates -> CSV
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
`guard_ms`, `geocode_ms`, `graph_ms`, `render_ms` — surfaced in a "Performance"
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

## Tests

```bash
pytest tests/ -q
```

148 tests, none of which touch the network. They cover the CIEDE2000 reference
vectors, LAB round-tripping across every colour the project ships, guard
idempotence against adversarial palettes, schema rejection cases, prompt
injection isolation, and the theme-injection regression described below.

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

## Roadmap

Implemented: Describe tab, Classic tab, guards, evaluation telemetry.
Planned: Match a Photo (k-means palette extraction + CLIP mood), the evaluation
harness over ~100 prompts, and a pre-generated ControlNet gallery.

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
