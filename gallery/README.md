# Gallery images (FR6.2)

This directory holds pre-generated ControlNet-restyled poster images, produced offline by
`colab/controlnet_restyle.ipynb` on a Colab GPU runtime — **nothing in this directory or the
app's Gallery tab requires a GPU or that notebook at runtime.**

## Expected file naming

`{city}_{style}.png`, all lowercase, spaces replaced with underscores. For example:

```
paris_watercolor.png
paris_ink_wash.png
paris_cyberpunk.png
tokyo_watercolor.png
```

The app's Gallery tab groups files by the `{city}` prefix and displays the `{style}` suffix as
a caption. Any PNG not matching this pattern is skipped, not an error.

## How to populate this folder

1. Open `colab/controlnet_restyle.ipynb` in Google Colab.
2. Runtime → Change runtime type → T4 GPU.
3. Run all cells. It fetches each sample city's road network, restyles it in 3 styles, and
   saves a review grid plus individual PNGs.
4. Download the notebook's `gallery_output/gallery/` folder and copy its PNGs in here.
5. Commit — that's it, the Gallery tab will pick them up on the next app run, no code changes.

Empty for now: the app's Gallery tab shows an honest "nothing here yet" placeholder until you
do this.
