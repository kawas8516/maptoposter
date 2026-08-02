# Gallery images (FR6.2)

This directory holds pre-generated ControlNet-restyled poster images, produced offline by
`colab/controlnet_restyle.ipynb` on a Colab GPU runtime — **nothing in this directory or the
app's Gallery tab requires a GPU or that notebook at runtime.**

## Expected file naming

`{city}_{style}_{hash}.png` — city and style lowercase with spaces replaced by underscores,
followed by a 16-character hex hash of the generated image (same convention as the Streamlit
app's own `poster_{hash}.png` files, see `aiposter/render.py`). The hash means re-running the
notebook doesn't overwrite a previous generation of the same city/style — both just coexist
under different filenames. For example:

```
paris_watercolor_a1b2c3d4e5f6a7b8.png
paris_ink_wash_1122334455667788.png
paris_cyberpunk_99aabbccddeeff00.png
tokyo_watercolor_0123456789abcdef.png
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

Empty for now: the app's Gallery tab shows an honest "nothing here yet" placeholder until you
do this.
