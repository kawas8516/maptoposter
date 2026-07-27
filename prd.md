# PRD — AI Poster Studio

**Version:** 1.0 · **Date:** 2026-07-27 · **Owner:** Kaustubha Mandhane (SY MCA, Div C)
**Status:** Approved for build · **Base:** fork of `originalankur/maptoposter` (MIT)

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
- FR1.1: Three tabs: Describe, Match a Photo, Classic.
- FR1.2: Poster preview + high-resolution PNG download on every tab.
- FR1.3: Disk caching of OSM graphs (keyed city+distance); repeat renders avoid network.

### FR2 — Text-to-Poster (Describe)
- FR2.1: LLM call via Hugging Face Inference API (free tier; Qwen2.5 / Llama-3.x instruct) with JSON-schema-constrained system prompt + 3 few-shot examples.
- FR2.2: Output validated by pydantic `PosterSpec`: `{city, country, lat/long override, distance, theme: {12 hex fields}}`.
- FR2.3: On validation failure: exactly one repair round-trip with the error message; then fallback to nearest stock theme. The user always receives a poster.
- FR2.4: Display generated theme swatches alongside the poster.

### FR3 — Photo-to-Poster (Match a Photo)
- FR3.1: k-means (k≈6) palette extraction in LAB space (scikit-learn).
- FR3.2: Role assignment by lightness ordering (background, text, road tiers, water, parks) with documented rules.
- FR3.3: CLIP zero-shot mood classification on CPU (`openai/clip-vit-base-patch32`; labels: warm/cool/dark/pastel/vivid) steering role assignment.

### FR4 — Palette guards (applies to FR2 and FR3)
- FR4.1: WCAG contrast ratio check (text vs background).
- FR4.2: Minimum CIEDE2000 distance across road-hierarchy colors.
- FR4.3: Auto-correction by lightness nudging in LAB; corrections logged.

### FR5 — Evaluation harness
- FR5.1: Scripted run of ~100 prompts logging validity, repair, guard-trigger rates and latency to CSV.
- FR5.2: Blind preference study assets (poster pairs, Google Form) for ~10 participants.

### FR6 — Stretch: ControlNet gallery
- FR6.1: Colab notebook (free T4): road network → lineart conditioning → SD 1.5 + ControlNet restyling.
- FR6.2: Read-only Gallery tab of pre-generated images; zero runtime GPU dependency.

## 6. Non-Functional Requirements

- NFR1: Core path CPU-only on a development laptop.
- NFR2: Total cost ₹0 — open-source libraries and free-tier services only.
- NFR3: Offline demo mode: 8–10 pre-cached showcase cities; only the LLM call needs internet.
- NFR4: Respect Nominatim/Overpass rate limits via aggressive disk caching.
- NFR5: Repo never left broken — every working session ends with a runnable commit.
- NFR6: License compliance: fork remains MIT; attribution preserved.

## 7. Success Metrics

| Metric | Target |
|---|---|
| Schema validity (first attempt) | ≥ 80% over 100 prompts |
| Validity after one repair retry | ≥ 95% |
| Posters delivered (incl. fallback) | 100% |
| Guarded themes passing WCAG + CIEDE2000 | 100% (by construction) |
| End-to-end latency (text → poster, cached city) | ≤ ~30 s typical |
| Blind study | AI themes preferred or competitive (~≥40% preference share) |

## 8. Milestones (12 weeks · ~5 hrs/week)

| Phase | Weeks | Demoable checkpoint |
|---|---|---|
| 0 Foundation | 1–3 | Web generator equal to existing site |
| 1 Text-to-Poster | 4–6 | "Neon rainy Tokyo" renders legibly |
| 2 Photo-to-Poster | 7–8 | Sunset photo → sunset poster |
| 3 Evaluation & report | 9–10 | Metrics CSV + study + demo video |
| 4 Stretch: ControlNet | 11–12 | Pre-generated gallery tab |

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| OSM rate limits / outage | Disk caching + pre-cached showcase cities (offline demo) |
| HF API quota / outage | Second hosted model; rule-based keyword→palette fallback |
| LLM invalid JSON | Validate → one repair retry → stock-theme fallback |
| Demo-day connectivity | Fully local except one LLM call; recorded 3-min video |

## 10. Open Questions

- Final choice of hosted instruct model (availability on free tier at build time).
- Exact 12 theme fields to mirror upstream theme JSON (confirm during Week 1 code reading).
- Whether upstream PR of the theming layer is in scope before course deadline.
