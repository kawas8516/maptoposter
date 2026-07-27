# Security & Privacy — AI Poster Studio

**Version:** 1.0 · **Date:** 2026-07-27 · **Scope:** Streamlit app, AI theming layer, poster library, evaluation harness, Colab stretch notebook.

---

## 1. Threat Model Summary

A locally run (or small-scale deployed) Streamlit app that accepts two untrusted inputs — free text and uploaded images — and calls three external services: Hugging Face Inference API, Nominatim, and Overpass. Primary risks: secret leakage, unsafe handling of user uploads, prompt-driven misuse of the LLM output, dependency vulnerabilities, and abuse of third-party APIs.

| Asset | Threat | Severity |
|---|---|---|
| HF API token | Leakage via repo/logs | High |
| User-uploaded photos | Malicious/oversized files; retention | Medium |
| LLM output | Injection into spec / unsafe values | Medium |
| External APIs | Rate-limit abuse, ToS violation | Medium |
| Dependencies / model weights | Supply-chain compromise | Medium |
| Study participants' data | Privacy of preferences/responses | Low–Medium |

## 2. Secrets Management

- The Hugging Face token is the only secret. Load exclusively from environment variable `HF_TOKEN` or `.streamlit/secrets.toml`.
- `.gitignore` must include: `.env`, `secrets.toml`, `*.token`, cache directories.
- Never hardcode tokens; never print/log tokens; never commit example files containing real values.
- Use a fine-grained HF token (read/inference-only). Rotate immediately if exposed; treat any token seen in git history as compromised (revoke, don't just delete the commit).
- Colab notebook reads the token from Colab Secrets, never from a notebook cell.

## 3. Input Handling

### 3.1 Free-text prompts (Describe tab)
- Enforce max prompt length (e.g. 500 chars) before the LLM call.
- Treat prompt content as untrusted data inside the system prompt; the LLM's only allowed effect is producing JSON — no tools, no code execution.
- Never interpolate user text into shell commands, file paths, or eval'd code.

### 3.2 Image uploads (Match a Photo tab)
- Accept only `png/jpg/jpeg/webp`; verify by decoding with Pillow, not by extension.
- Enforce max file size (e.g. 10 MB) and max pixel count (Pillow `MAX_IMAGE_PIXELS` guard against decompression bombs).
- Re-encode / downsample the image before processing; never execute or serve the raw upload.
- Process in memory or a temp directory; delete after theme extraction (see §6 Privacy).
- Strip EXIF (may contain GPS location) — never log or persist EXIF metadata.

### 3.3 City / geocoding inputs
- Pass city strings only as query parameters to Nominatim via OSMnx — never into file paths. Derive cache filenames from a hash of (city, distance), not raw user text (prevents path traversal).

## 4. LLM Output Handling (treat as untrusted)

- Parse with `json.loads` + pydantic strict validation only. Never `eval()` model output.
- Validate value ranges: hex colors match `^#?[0-9A-Fa-f]{6}$`; `distance` clamped to sane bounds (e.g. 1000–30000 m); lat/long bounds checked.
- Reject unexpected/extra fields (`model_config extra="forbid"`), preventing spec-injection of unintended parameters.
- Poster text rendered by matplotlib is data, not markup — but sanitize/limit length of any LLM-suggested label text.
- The repair round-trip sends only the validation error, never stack traces or environment details.

## 5. External Services & Rate Limiting

- **Nominatim/Overpass:** honor usage policies — set a descriptive User-Agent, cache aggressively on disk, add request throttling (≥1 s between geocode calls), pre-cache showcase cities. Never hammer on retry loops (bounded retries with backoff).
- **HF Inference API:** bounded retries (max 2), timeout on every call, graceful degradation to backup model → rule-based fallback. No user PII in prompts.
- If deployed publicly (Streamlit Cloud): add simple per-session rate limiting on Generate to prevent someone using the app to proxy-abuse free-tier APIs.

## 6. Privacy & Data Retention

- Uploaded photos: processed transiently; not stored beyond the session; never transmitted to any third party (palette + CLIP run locally on CPU).
- Text prompts: sent to the HF Inference API only — disclose this in the app UI ("your description is sent to a hosted model"). No other user data leaves the machine.
- Evaluation CSVs contain prompts + metrics only — no user identifiers.
- Blind study: collect no names/emails in the Google Form; responses anonymous; report aggregates only.
- Generated posters cached locally may embed city names only — no personal data.

## 7. Dependency & Supply-Chain Security

- Pin all dependencies in `requirements.txt` (exact versions); commit a lockfile if using pip-tools.
- Install only from PyPI / Hugging Face Hub official sources; model IDs pinned (e.g. `openai/clip-vit-base-patch32` at a specific revision).
- Load model weights with `safetensors` where available; avoid pickle-based weight files from untrusted repos.
- OSM graph cache uses pickle **locally generated only** — never load pickle files from untrusted sources; cache directory is app-private.
- Run `pip-audit` (or GitHub Dependabot on the fork) before the final release/demo.

## 8. Code & Repository Hygiene

- No `os.system` / `subprocess` with user-influenced strings anywhere in the codebase.
- Streamlit runs with default sandboxing; do not enable arbitrary file serving.
- Branch protection not required (solo project), but: every commit runnable, secrets scan before push (`git diff --staged | grep -i token` habit or pre-commit hook with `detect-secrets`).
- License/attribution: keep upstream MIT license and credit in README (legal, not just ethical, requirement).

## 9. Content Safety

- Generated themes are colors only — low content risk. The LLM cannot inject text into posters beyond city/country labels, which are validated against geocoding results.
- Stretch (ControlNet/SD 1.5): generate gallery images offline in Colab with default safety checker enabled; manually review all images before shipping in the read-only Gallery tab. No live user-driven diffusion generation, eliminating misuse of the image model through this app.

## 10. Incident Response (proportionate to project scale)

1. **Token leak:** revoke on HF immediately → generate new fine-grained token → purge from git history (`git filter-repo`) → force-push.
2. **API abuse observed:** disable public deployment; run local-only.
3. **Dependency CVE:** bump pinned version; re-run evaluation script as regression test.

## 11. Security Checklist (pre-demo)

- [ ] No secrets in repo (`git log -p | grep -iE "hf_|token"` clean; detect-secrets scan clean)
- [ ] `.gitignore` covers env files, secrets, caches
- [ ] Upload validation (type, size, pixel bomb) tested with hostile files
- [ ] pydantic schema rejects extra fields, bad hex, out-of-range distance
- [ ] Nominatim User-Agent + throttling in place
- [ ] EXIF stripped from uploads; uploads deleted post-processing
- [ ] `pip-audit` clean or exceptions documented
- [ ] Privacy note visible in app UI (prompt sent to hosted model)
- [ ] Gallery images manually reviewed (stretch)
