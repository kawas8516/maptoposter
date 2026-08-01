"""Photo-to-poster tests. Fully offline: synthetic in-memory images only,
no real photos and no CLIP (which needs the real model downloaded -- see
scripts/try_photo.py for that manual check instead)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from aiposter import guards, photo


def _solid_patches(patches: list[tuple[tuple[int, int, int], float]], size: int = 60) -> Image.Image:
    """Build an image whose pixels are exactly the given RGB colours, in the
    given proportions, so cluster assignment is deterministic and checkable."""
    total = size * size
    pixels = []
    for color, fraction in patches:
        pixels.extend([color] * round(total * fraction))
    while len(pixels) < total:
        pixels.append(patches[-1][0])
    pixels = pixels[:total]
    array = np.array(pixels, dtype=np.uint8).reshape(size, size, 3)
    return Image.fromarray(array, mode="RGB")


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------
# validate_upload
# --------------------------------------------------------------------------


def test_validate_upload_accepts_a_real_png():
    data = _png_bytes(_solid_patches([((255, 0, 0), 1.0)]))
    image = photo.validate_upload(data)
    assert image.mode == "RGB"
    assert image.size == (60, 60)


def test_validate_upload_rejects_oversized_file():
    data = _png_bytes(_solid_patches([((0, 0, 0), 1.0)]))
    huge = data + b"\x00" * (photo.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(photo.UploadError, match="MB"):
        photo.validate_upload(huge)


def test_validate_upload_rejects_garbage_bytes():
    with pytest.raises(photo.UploadError):
        photo.validate_upload(b"not an image, just filename-spoofed as one")


def test_validate_upload_rejects_wrong_format():
    # BMP is decodable by Pillow but not in the accepted set.
    image = _solid_patches([((10, 20, 30), 1.0)])
    buffer = io.BytesIO()
    image.save(buffer, format="BMP")
    with pytest.raises(photo.UploadError, match="format"):
        photo.validate_upload(buffer.getvalue())


def test_validate_upload_strips_exif():
    image = _solid_patches([((200, 200, 200), 1.0)])
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x0110] = "test-camera"  # Model tag
    image.save(buffer, format="JPEG", exif=exif)
    validated = photo.validate_upload(buffer.getvalue())
    assert not validated.getexif()


# --------------------------------------------------------------------------
# extract_palette
# --------------------------------------------------------------------------


def test_extract_palette_returns_k_clusters_sorted_lightest_first():
    image = _solid_patches([
        ((250, 250, 250), 0.5),
        ((10, 10, 10), 0.5),
    ])
    swatches = photo.extract_palette(image, k=2)
    assert len(swatches) == 2
    lightnesses = [guards.srgb_to_lab(hex_color)[0] for hex_color, _ in swatches]
    assert lightnesses[0] > lightnesses[1]


def test_extract_palette_weights_sum_to_one():
    image = _solid_patches([
        ((255, 255, 255), 0.7),
        ((0, 0, 0), 0.3),
    ])
    swatches = photo.extract_palette(image, k=2)
    assert sum(weight for _, weight in swatches) == pytest.approx(1.0, abs=1e-6)


def test_extract_palette_caps_k_to_available_colors():
    # Only one distinct colour present -- k=6 must not error.
    image = _solid_patches([((100, 150, 200), 1.0)])
    swatches = photo.extract_palette(image, k=6)
    assert len(swatches) == 1


# --------------------------------------------------------------------------
# Role assignment (derive_theme, with classify_mood monkeypatched so no
# CLIP/torch is needed for these deterministic role-assignment checks)
# --------------------------------------------------------------------------


def _fixed_mood(mood: str):
    def _classify(_image):
        return mood, {mood: 1.0}
    return _classify


def test_water_role_picks_the_blue_cluster(monkeypatch):
    monkeypatch.setattr(photo, "classify_mood", _fixed_mood("cool"))
    # Six distinct clusters: light bg, dark text/road, a clearly blue patch,
    # a clearly green patch, and two mid-tones to fill out the road ramp.
    image = _solid_patches([
        ((245, 245, 245), 0.30),
        ((20, 20, 20), 0.20),
        ((30, 60, 200), 0.15),   # blue -> water
        ((40, 160, 60), 0.15),   # green -> parks
        ((150, 150, 150), 0.10),
        ((100, 100, 100), 0.10),
    ])
    theme, mood, swatches = photo.derive_theme(image)
    assert mood == "cool"
    assert len(swatches) <= 6
    water_lab = guards.srgb_to_lab(theme["water"])
    # Water should be the hue-wise bluest of the assigned roles.
    hue = np.degrees(np.arctan2(water_lab[2], water_lab[1])) % 360
    assert 200 <= hue <= 300


def test_dark_mood_flips_background_to_the_darkest_cluster(monkeypatch):
    monkeypatch.setattr(photo, "classify_mood", _fixed_mood("dark"))
    image = _solid_patches([
        ((245, 245, 245), 0.30),
        ((15, 15, 15), 0.30),
        ((80, 80, 160), 0.10),
        ((60, 140, 80), 0.10),
        ((120, 120, 120), 0.10),
        ((180, 180, 180), 0.10),
    ])
    theme, mood, _swatches = photo.derive_theme(image)
    assert mood == "dark"
    bg_lightness = guards.srgb_to_lab(theme["bg"])[0]
    text_lightness = guards.srgb_to_lab(theme["text"])[0]
    # Background should be the darker of the two, not the lighter -- the
    # rule under test.
    assert bg_lightness < text_lightness


def test_derive_theme_produces_all_editable_fields(monkeypatch):
    monkeypatch.setattr(photo, "classify_mood", _fixed_mood("warm"))
    image = _solid_patches([
        ((245, 245, 245), 0.30),
        ((20, 20, 20), 0.20),
        ((30, 60, 200), 0.15),
        ((40, 160, 60), 0.15),
        ((150, 150, 150), 0.10),
        ((100, 100, 100), 0.10),
    ])
    theme, _mood, _swatches = photo.derive_theme(image)
    from aiposter.themes import EDITABLE_COLOR_FIELDS

    for field in EDITABLE_COLOR_FIELDS:
        assert field in theme
        guards.normalize_hex(theme[field])  # raises if not a valid hex


def test_derive_theme_passes_through_thememspec_and_guards(monkeypatch):
    monkeypatch.setattr(photo, "classify_mood", _fixed_mood("vivid"))
    image = _solid_patches([
        ((245, 245, 245), 0.30),
        ((20, 20, 20), 0.20),
        ((30, 60, 200), 0.15),
        ((40, 160, 60), 0.15),
        ((150, 150, 150), 0.10),
        ((100, 100, 100), 0.10),
    ])
    raw_theme, _mood, _swatches = photo.derive_theme(image)

    from aiposter.spec import ThemeSpec

    theme = ThemeSpec(**raw_theme).to_theme_dict()
    assert theme["gradient_color"] == theme["bg"]
    assert theme["road_default"] == theme["road_tertiary"]

    result = guards.apply_guards(theme)
    assert result.metrics["contrast_text_bg"] >= 1.0  # sane, guards may still adjust it
