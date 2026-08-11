# Gallery images (FR6.2)

This directory holds pre-generated ControlNet-restyled poster images, produced offline by
`colab/controlnet_restyle.ipynb` on a Colab GPU runtime — **nothing in this directory or the
app's Gallery tab requires a GPU or that notebook at runtime.**

## Expected file naming

`{city}_{style}_{hash}.png` — city and style lowercase with spaces replaced by underscores,
followed by a 16-character hex hash of the generated image (same convention as the Streamlit
app's own `poster_{hash}.png` files, see `aiposter/render.py`). The hash means re-running the
notebook doesn't overwrite a previous generation of the same city/style — both just coexist
under different filenames. Real examples currently shipped in this folder:

```
paris_watercolor_4bd38f35e38317b0.png
paris_ink_wash_8d8d64a5b64aee7a.png
paris_cyberpunk_ff14f83b8e447cf4.png
tokyo_watercolor_a4ae51a691e73b40.png
```

The app's Gallery tab groups files by the `{city}` prefix and displays the `{style}` segment as
a caption; the trailing hash is only used for uniqueness, not shown. Any PNG not matching this
pattern (including the earlier two-part `{city}_{style}.png` scheme) is skipped, not an error.

## How to populate this folder

1. Open `colab/controlnet_restyle.ipynb` in Google Colab.
2. Runtime → Change runtime type → T4 GPU.
3. Run all cells. It fetches each sample city's road network, restyles it in 3 styles, and
   saves a review grid plus individual PNGs.
4. Download the notebook's `gallery_output/gallery/` folder and copy its PNGs in here.
5. Commit — that's it, the Gallery tab will pick them up on the next app run, no code changes.

**Populated:** the notebook has been run on a real Colab T4 GPU, and this folder currently
ships all 3 sample cities (Paris, Tokyo, Venice) × 3 styles (watercolor, ink-wash, cyberpunk) —
9 images. Re-running the notebook for more cities/styles just adds more files alongside these.
