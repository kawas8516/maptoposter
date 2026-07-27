# Blind preference study — Google Form structure (FR5.2)

No Google Forms API access is available from this environment, so this is a scaffold to paste
into a form you create yourself at [forms.google.com](https://forms.google.com), not a form
created automatically. Fill in `pairs_manifest.csv` with the actual poster image paths once
both an AI-generated and a stock-theme poster exist for each showcase city, then upload those
images into the corresponding question in the form.

## Privacy (security.md §6)

Collect **no names or emails**. Do not enable "Collect email addresses" in Google Forms
settings. Responses must be anonymous; report only aggregates (e.g. "6/10 preferred B").

## Form structure

**Title:** Map Poster Style — Quick Preference Survey

**Description (paste verbatim):**
> You'll see 10 pairs of city map posters, labeled A and B. For each pair, pick the one you
> like better, or "No preference" if you genuinely can't decide. There's an optional field to
> say why. This should take about 5 minutes. Your response is anonymous — we don't collect
> your name or email.

**Per-city question block** (repeat once per row in `pairs_manifest.csv`, i.e. 8-10 times):

1. Image: Poster A for `{city}` (upload `ai_poster_path` **or** `stock_poster_path` —
   **randomize which one is A vs B per city**, don't always put the same source first; note
   which you used in your own tracking sheet, never in the form itself, so the pairing stays
   blind to participants)
2. Image: Poster B for `{city}` (the other one)
3. **Question (single choice, required):** "Which do you prefer for {city}?"
   - Poster A
   - Poster B
   - No preference
4. **Question (short answer, optional):** "Why? (optional)"

**Closing section:** "Thank you! Nothing else is collected."

## What's still manual

- Generating the actual AI + stock poster pairs (`scripts/try_describe.py` for AI themes,
  Classic tab for stock themes) for each showcase city and filling in
  `pairs_manifest.csv`'s path columns.
- Creating the real form at forms.google.com and uploading the images per the structure above.
- Randomizing A/B order per city so the same source isn't always "A" (avoids a positional bias
  in the results).
- Distributing the form link to ~10 participants and collecting the ~10 responses.
