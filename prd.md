# PRD — AI Poster Studio

**Version:** 1.1 · **Date:** 2026-07-27 · **Owner:** Kaustubha Mandhane (SY MCA, Div C)
**Status:** Approved for build · **Base:** fork of `originalankur/maptoposter` (MIT)

> **v1.1 changes:** FR3 (Photo-to-Poster) deferred to Phase 2b behind the §7 benchmarks;
> new FR7 (theme chooser & editor); latency NFRs added; the "12 hex fields" figure
> corrected to 11 after reading the upstream theme files.
>
> **Post-launch note (not a versioned revision):** the live app has since diverged from
> what's documented below in two ways this PRD hasn't been formally updated to reflect:
> the **Describe tab** (FR2's UI surface) was removed from the Streamlit app — FR2's
> pipeline is unchanged and still reachable via `scripts/try_describe.py` (see README) —
> and **Match a Photo (FR3)** has since been fully implemented, not shipped as the
> placeholder FR1.1/§5b describe. Left as-is below rather than rewritten, since this is
> a decision record of what was approved, not a live spec; see the inline notes at
> FR1.1, FR2, and FR7.3 for exactly where it diverges.

---

## 1. Overview

AI Poster Studio replaces maptoposter's fixed catalogue of 17 hand-written theme files with an AI theming layer. Users generate minimalist city map posters from (a) a natural-language description, (b) a reference photo, or (c) the classic stock themes — all through one Streamlit web app. AI models produce only a validated specification (`PosterSpec`); the unmodified maptoposter engine performs all rendering.

## 2. Problem

The expressive bottleneck of existing map-poster generators is specification, not rendering:

- Users cannot describe a desired aesthetic in words.
- Users cannot match a poster to an existing object (room, brand, photo).
- No mechanism guarantees machine-generated palettes remain legible.

## 3. Goals & Non-Goals

**Goals**

- G1: Free-text description → valid, novel, legible theme + map config (text-to-poster).
- G2: Uploaded photo → matching theme via palette extraction + CLIP mood (photo-to-poster).
- G3: Automatic legibility guards (WCAG contrast, CIEDE2000 road separation, lightness auto-fix).
- G4: Quantitative evaluation (validity/repair/guard rates, latency) + 10-person blind preference study.
- G5: Core path runs entirely on CPU; demo works offline except one LLM call.

**Non-Goals**

- No model training or fine-tuning (all models used off-the-shelf).
- No changes to upstream rendering behavior.
- No user accounts, payments, or print-service integration (future scope).
- Live GPU inference is out of scope; ControlNet ships only as a pre-generated gallery (stretch).

## 4. Users & Use Cases

| User | Use case | Input | Output |
|---|---|---|---|
| Home decorator | Poster matching a room | Photo of room | Poster in room's palette |
| Gift buyer | Mood-based poster | Text description | Novel themed poster |
| Small brand / event | Poster in brand colors | Logo/swatch photo | Brand-toned poster |
| Hobbyist / student | Aesthetic exploration | Text or photo | Many rapid variations |
| Existing maptoposter user | Familiar workflow | Dropdown (Classic tab) | Stock-theme poster |

## 5. Functional Requirements

### FR1 — Web application (Streamlit)
- FR1.1: Three tabs: Describe, Classic, and Match a Photo. Match a Photo ships as an honest "coming soon" placeholder describing its designed pipeline until FR3 is undeferred (see §5b). *(Post-launch: the live app now ships Classic, a fully-implemented Match a Photo, and a Gallery tab (FR6.2) — the Describe tab has been removed from the UI. See the note at the top of this document.)*
- FR1.2: Poster preview + high-resolution PNG download on every tab.
- FR1.3: Disk caching of OSM graphs (keyed city+distance); repeat renders avoid network.

### FR2 — Text-to-Poster (Describe)

*Post-launch: the Describe tab this section describes has been removed from the live UI; the pipeline below is unchanged and reachable via `scripts/try_describe.py` (see README).*

- FR2.1: LLM call via Hugging Face Inference API (free tier; Qwen2.5 instruct) with JSON-schema-constrained system prompt + 3 few-shot examples.
- FR2.2: Output validated by pydantic `PosterSpec`: `{city, country, lat/long override, distance, theme: {11 hex fields + name + description}}`.
- FR2.3: On validation failure: exactly one repair round-trip with the error message; then fallback to nearest stock theme. The user always receives a poster.
- FR2.4: Display generated theme swatches alongside the poster.

### FR4 — Palette guards (applies to FR2, FR7 edits, and FR3 when undeferred)
- FR4.1: WCAG contrast ratio check (text vs background).
- FR4.2: Minimum CIEDE2000 distance across road-hierarchy colors.
- FR4.3: Auto-correction by lightness nudging in LAB; corrections logged.

### FR5 — Evaluation harness
- FR5.1: Scripted run of ~100 prompts logging validity, repair, guard-trigger rates and latency to CSV.
- FR5.2: Blind preference study assets (poster pairs, Google Form) for ~10 participants.

### FR6 — Stretch: ControlNet gallery
- FR6.1: Colab notebook (free T4): road network → lineart conditioning → SD 1.5 + ControlNet restyling.
- FR6.2: Read-only Gallery tab of pre-generated images; zero runtime GPU dependency.

### FR7 — Theme chooser & editor
Brings the app to parity with the reference site (maptoposter.penk.in) and makes every palette — stock or AI-generated — directly editable.

- FR7.1: Theme dropdown listing all 17 stock themes, with a swatch-row preview of the selected theme's colors shown *before* generating.
- FR7.2: Distance presets matching the reference site: 3 km (default), 5 km, 10 km, 15 km.
- FR7.3: Color editing — an expandable "Customize colors" panel with a `st.color_picker` per editable theme field (11 colors; `gradient_color` is derived from `bg` and `road_default` from `road_tertiary`, so 9 are independently editable). Pre-filled from the selected stock theme **or** from an AI-generated theme (originally via the Describe tab; that tab has since been removed from the UI, though the pipeline is still reachable via CLI — see FR2's note). Edited palettes run through the same FR4 WCAG/CIEDE2000 guards before rendering; any auto-correction is shown to the user with before/after values.
- FR7.4: "Previous posters" history strip — the last ~6 posters generated in this session shown as thumbnails, click to re-download. Session state only, no disk persistence (security.md §6).

## 5b. Deferred to Phase 2b

### FR3 — Photo-to-Poster (Match a Photo) — DEFERRED
**Gate:** FR3 will be built only after the text pipeline meets the evaluation-harness benchmarks in §7 — specifically schema validity ≥ 80% first-attempt and ≥ 95% after one repair, 100% poster delivery, and the p50 latency target in NFR7, all measured by FR5.1 over its full prompt set.

Rationale: photo-to-poster reuses the same guard and render path as text-to-poster. Hardening and measuring that shared path once is cheaper than debugging it through two input modalities at the same time. Until the gate is met, the Match a Photo tab ships as a placeholder that honestly describes the pipeline below rather than a broken or stubbed feature.

Design retained for when the gate is met:
- FR3.1: k-means (k≈6) palette extraction in LAB space (scikit-learn).
- FR3.2: Role assignment by lightness ordering (background, text, road tiers, water, parks) with documented rules.
- FR3.3: CLIP zero-shot mood classification on CPU (`openai/clip-vit-base-patch32`; labels: warm/cool/dark/pastel/vivid) steering role assignment.

Note that G2 in §3 remains a project goal; only its scheduling moves. The security controls in security.md §3.2 (upload validation, EXIF stripping, decompression-bomb limits) must be implemented as part of undeferring, not retrofitted after.

## 6. Non-Functional Requirements

- NFR1: Core path CPU-only on a development laptop.
- NFR2: Total cost ₹0 — open-source libraries and free-tier services only.
- NFR3: Offline demo mode: 8–10 pre-cached showcase cities; only the LLM call needs internet.
- NFR4: Respect Nominatim/Overpass rate limits via aggressive disk caching.
- NFR5: Repo never left broken — every working session ends with a runnable commit.
- NFR6: License compliance: fork remains MIT; attribution preserved.
- NFR7: **p50 end-to-end latency ≤ 15 s** for a cached city (description → rendered poster), measured from Generate to poster displayed. p95 ≤ 30 s.
- NFR8: **Per-stage timings must be logged** for every generation: `llm_ms`, `validate_ms`, `guard_ms`, `geocode_ms`, `graph_ms`, `render_ms`. Surfaced in the UI and written to the FR5.1 evaluation CSV, so latency regressions are attributable to a stage rather than to the pipeline as a whole.
- NFR9: A colour edit that changes no geographic parameter (city, country, distance) must re-render from the cached OSM graph — no geocode, no network fetch.

## 7. Success Metrics

| Metric | Target |
|---|---|
| Schema validity (first attempt) | ≥ 80% over 100 prompts |
| Validity after one repair retry | ≥ 95% |
| Posters delivered (incl. fallback) | 100% |
| Guarded themes passing WCAG + CIEDE2000 | 100% (by construction) |
| End-to-end latency, p50 (text → poster, cached city) | ≤ 15 s (NFR7) |
| End-to-end latency, p95 (text → poster, cached city) | ≤ 30 s (NFR7) |
| Re-render after a colour edit (cached graph) | ≤ 5 s (NFR9) |
| Blind study | AI themes preferred or competitive (~≥40% preference share) |

Meeting the first five rows is the gate that undefers FR3 (see §5b).

## 8. Milestones (12 weeks · ~5 hrs/week)

| Phase | Weeks | Demoable checkpoint |
|---|---|---|
| 0 Foundation | 1–3 | Web generator equal to existing site |
| 1 Text-to-Poster | 4–6 | "Neon rainy Tokyo" renders legibly |
| 2a Theme chooser & editor (FR7) | 7 | Stock-theme parity + hand-editable palettes |
| 3 Evaluation & report | 8–10 | Metrics CSV + study + demo video |
| 2b Photo-to-Poster (FR3) | after gate | Sunset photo → sunset poster |
| 4 Stretch: ControlNet | 11–12 | Pre-generated gallery tab |

Phase 2b is deliberately unscheduled: it starts when the §7 gate is met, not on a fixed week. If the gate is not met before the deadline, the project ships with FR3 as a documented placeholder rather than a rushed implementation.

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| OSM rate limits / outage | Disk caching + pre-cached showcase cities (offline demo) |
| HF API quota / outage | Second hosted model; rule-based keyword→palette fallback |
| LLM invalid JSON | Validate → one repair retry → stock-theme fallback |
| Demo-day connectivity | Fully local except one LLM call; recorded 3-min video |

## 10. Open Questions

- ~~Final choice of hosted instruct model~~ — **resolved:** `Qwen/Qwen2.5-7B-Instruct` (ungated, live on Together and Featherless-ai), backed by `Qwen/Qwen2.5-72B-Instruct` on DeepInfra. `meta-llama/Llama-3.1-8B-Instruct` was rejected: it is gated behind manual licence approval.
- ~~Exact 12 theme fields~~ — **resolved:** there are **11** colour fields plus `name` and `description` (13 keys). `gradient_color` always equals `bg`, and `road_default` duplicates one of the road tiers, so only 9 colours are independently meaningful.
- Whether upstream PR of the theming layer is in scope before course deadline.
- Whether the CIEDE2000 threshold should stay at 10. Measured against the stock catalogue, only 3 of 17 themes pass at ΔE ≥ 10, so generated themes are held to a stricter bar than the shipped ones. Lowering to ~6 would match existing practice.
- Whether to add a **road-vs-background** separation guard. FR4 checks text-vs-background and road-vs-road, but nothing constrains roads against the background — an observed failure mode where a valid, guard-passing theme rendered its lower road tiers nearly invisible.
