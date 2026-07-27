"""Photo-to-poster theme derivation (FR3).

Extracts a palette from an uploaded photo (K-Means in CIELAB space),
classifies its overall mood zero-shot with CLIP, and maps the result onto the
same 9 independent theme colors every other path produces — the derived
theme is then guarded (``pipeline.apply_palette_guards``) and rendered
exactly like a stock or AI-generated one. No Streamlit/Gradio import here:
this module mirrors the framework-agnostic layering of ``llm.py`` and
``fallback.py``, so it can be called from the app, a test, or a CLI script.

Untrusted input handling (security.md §3.2): uploads are validated by
decoding with Pillow — never by filename/extension — capped in size and
pixel count, stripped of metadata by reconstruction, and never written to
disk.
"""

from __future__ import annotations

import io
import math
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

from .guards import lab_to_srgb_hex, srgb_to_lab
from .timing import Timings

if TYPE_CHECKING:
    from transformers import CLIPModel, CLIPProcessor

#: security.md §3.2 — reject oversized uploads before decoding anything.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: Decompression-bomb guard (security.md §3.2). Set once, process-wide: a
#: photo has no legitimate reason to exceed ~40 megapixels for this app's
#: purposes (palette extraction downsamples anyway).
Image.MAX_IMAGE_PIXELS = 40_000_000

_ACCEPTED_FORMATS = {"PNG", "JPEG", "WEBP"}

#: Clustering runs on a downsampled copy — proportion and hue are what matter
#: for a palette, not full-resolution pixel counts, and this keeps K-Means fast.
_CLUSTER_MAX_SIDE = 300

#: The 5 zero-shot mood labels from the PRD, phrased as full captions since
#: CLIP's text tower was trained on natural image captions, not bare adjectives.
MOOD_PROMPTS: dict[str, str] = {
    "warm": "a warm-toned photograph",
    "cool": "a cool-toned photograph",
    "dark": "a dark, moody photograph",
    "pastel": "a soft pastel photograph",
    "vivid": "a vivid, highly saturated photograph",
}

_CLIP_MODEL_ID = "openai/clip-vit-base-patch32"

#: Two candidate clusters within this many L* units are "close in lightness" —
#: the threshold at which mood is allowed to break a tie instead of pure sort
#: order (requirement 3: "adjust role assignment ... if two clusters are
#: close in lightness").
_LIGHTNESS_TIE_TOLERANCE = 8.0

#: Hue-angle windows (degrees, atan2(b*, a*) in CIELAB) used to recognise
#: "water-like" and "park-like" clusters. Approximate by design — guards run
#: on the final theme regardless of which cluster gets picked here, so a
#: rough hue match is enough to get a sensible starting assignment.
_BLUE_HUE_RANGE = (220.0, 320.0)
_GREEN_HUE_RANGE = (100.0, 170.0)


class UploadError(ValueError):
    """Raised when an uploaded file fails validation."""


def validate_upload(data: bytes) -> Image.Image:
    """Decode and validate an uploaded photo. Never trust the filename.

    Returns a fresh in-memory RGB image. Nothing here touches disk, and the
    reconstruction via ``convert("RGB")`` drops EXIF/ICC metadata (which can
    carry GPS coordinates) rather than attempting to strip it after the fact.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(
            f"file is {len(data) / 1_048_576:.1f} MB, over the {MAX_UPLOAD_BYTES / 1_048_576:.0f} MB limit"
        )

    try:
        # Decoding IS the format check (security.md: "verify by decoding with
        # Pillow, not by extension"). Image.MAX_IMAGE_PIXELS (set at import
        # time above) makes Pillow itself raise on a decompression bomb.
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            image_format = opened.format
            if image_format not in _ACCEPTED_FORMATS:
                raise UploadError(f"unsupported image format: {image_format!r}")
            # .convert("RGB") alone is not enough: Pillow carries the raw EXIF
            # bytes forward in the new image's .info dict, so getexif() would
            # still return the original metadata. Rebuilding from a bare pixel
            # array drops .info (and therefore EXIF/ICC/GPS) entirely.
            rgb = Image.fromarray(np.asarray(opened.convert("RGB")))
    except UploadError:
        raise
    except Exception as exc:  # noqa: BLE001 - any decode failure is an invalid upload
        raise UploadError(f"could not decode image: {exc}") from exc

    return rgb


def _downsample(image: Image.Image, max_side: int = _CLUSTER_MAX_SIDE) -> Image.Image:
    width, height = image.size
    scale = min(1.0, max_side / max(width, height))
    if scale >= 1.0:
        return image
    return image.resize((max(1, round(width * scale)), max(1, round(height * scale))))


def extract_palette(image: Image.Image, k: int = 6) -> list[tuple[str, float]]:
    """K-Means (k=6) over the photo's pixels in CIELAB space.

    Returns ``[(hex, weight), ...]`` sorted lightest to darkest, where
    ``weight`` is the cluster's share of pixels (sums to 1.0). LAB, not RGB,
    so clusters follow perceived colour rather than raw channel values —
    the same reasoning ``guards.py`` gives for doing all its color math in
    LAB rather than sRGB.
    """
    small = _downsample(image)
    pixels = np.asarray(small, dtype=np.uint8).reshape(-1, 3)

    # srgb_to_lab takes one hex color at a time; vectorise it here rather
    # than adding a batch variant to guards.py, which is deliberately kept
    # to single-color conversions used by the guard corrections.
    unique_rgb, inverse, counts = np.unique(pixels, axis=0, return_inverse=True, return_counts=True)
    unique_lab = np.array([
        srgb_to_lab("#" + "".join(f"{c:02X}" for c in rgb)) for rgb in unique_rgb
    ])
    lab_pixels = unique_lab[inverse]
    sample_weights = counts[inverse]

    k = min(k, len(unique_rgb))
    kmeans = KMeans(n_clusters=k, n_init=4, random_state=0)
    labels = kmeans.fit_predict(lab_pixels, sample_weight=sample_weights)

    total = float(sample_weights.sum())
    clusters: list[tuple[np.ndarray, float]] = []
    for cluster_id in range(k):
        mask = labels == cluster_id
        if not mask.any():
            continue
        weight = float(sample_weights[mask].sum()) / total
        clusters.append((kmeans.cluster_centers_[cluster_id], weight))

    # Lightest first (L* descending) - the ordering every role-assignment
    # rule below assumes.
    clusters.sort(key=lambda item: item[0][0], reverse=True)
    return [(lab_to_srgb_hex(center), weight) for center, weight in clusters]


@lru_cache(maxsize=1)
def _load_clip() -> tuple["CLIPModel", "CLIPProcessor"]:
    """Load CLIP once per process. Deferred import + lru_cache: the heavy
    torch/transformers cost is paid on first Photo-tab use in a session, not
    at app import, so Classic/Match-a-Photo startup is unaffected."""
    from transformers import CLIPModel, CLIPProcessor

    model = CLIPModel.from_pretrained(_CLIP_MODEL_ID)
    processor = CLIPProcessor.from_pretrained(_CLIP_MODEL_ID)
    model.eval()
    return model, processor


def classify_mood(image: Image.Image) -> tuple[str, dict[str, float]]:
    """Zero-shot mood classification via CLIP, CPU only.

    Returns ``(best_label, {label: score, ...})`` where scores are the
    softmax over the 5 prompts below - the standard CLIP zero-shot recipe
    (image-text similarity logits, softmax over the label set).
    """
    import torch

    model, processor = _load_clip()
    labels = list(MOOD_PROMPTS)
    prompts = [MOOD_PROMPTS[label] for label in labels]

    inputs = processor(text=prompts, images=image, return_tensors="pt", padding=True)
    with torch.no_grad():
        outputs = model(**inputs)
    probs = outputs.logits_per_image.softmax(dim=1)[0].tolist()

    scores = dict(zip(labels, probs))
    best = max(scores, key=scores.get)
    return best, scores


# --------------------------------------------------------------------------
# Role assignment
# --------------------------------------------------------------------------


def _hue_angle(lab: np.ndarray) -> float:
    """LAB hue angle in degrees [0, 360), atan2(b*, a*)."""
    return math.degrees(math.atan2(lab[2], lab[1])) % 360.0


def _chroma(lab: np.ndarray) -> float:
    """LAB chroma sqrt(a*^2 + b*^2) - how saturated a color reads."""
    return math.hypot(lab[1], lab[2])


def _in_hue_range(angle: float, low: float, high: float) -> bool:
    return low <= angle <= high


def _pick_by_hue(candidates: list[tuple[str, np.ndarray, float]], hue_range: tuple[float, float]) -> int | None:
    """Index of the candidate whose hue falls in ``hue_range`` and is
    closest to its centre, or None if none qualify."""
    centre = sum(hue_range) / 2.0
    in_range = [
        (i, abs(_hue_angle(lab) - centre))
        for i, (_, lab, _) in enumerate(candidates)
        if _in_hue_range(_hue_angle(lab), *hue_range)
    ]
    if not in_range:
        return None
    return min(in_range, key=lambda pair: pair[1])[0]


def derive_theme(
    image: Image.Image, name: str = "From your photo", timings: Optional[Timings] = None
) -> tuple[dict, str, list[tuple[str, float]]]:
    """Extract a palette, classify mood, and assign it to theme roles.

    Returns ``(raw_theme, mood_label, cluster_swatches)``. ``raw_theme`` has
    exactly the 9 independent color fields (``themes.EDITABLE_COLOR_FIELDS``)
    plus ``name``/``description`` - the caller runs it through
    ``ThemeSpec`` (to get ``gradient_color``/``road_default`` derived and hex
    validated) and then the FR4 guards, exactly like every other theme path.

    Role-assignment rules (documented here, not just in code, since this is
    the part meant to be explainable in a report):

    With 6 LAB clusters sorted lightest -> darkest (c0..c5):

    1. bg/text: c0 -> bg, c5 -> text. If mood == "dark", this flips (c5 ->
       bg, c1 -> text) so a genuinely dark/moody photo produces a
       dark-background poster instead of being forced light - the rule that
       directly targets "visibly warm/dark toned, not generic".
    2. water: among the remaining middle clusters, whichever has a LAB hue
       angle closest to blue (~230-290 deg); falls back to the next-lightest
       remaining cluster if none qualifies. If mood == "cool" and the top two
       candidates are within the lightness tie tolerance, prefer the more
       negative-b* (bluer) one.
    3. parks: same hue-angle approach targeting green (~100-170 deg);
       fallback by lightness.
    4. road_motorway/road_residential: of what's left, darkest -> motorway
       (heaviest, most prominent - matches every stock theme's own
       darkest-motorway to lightest-residential convention), lightest of the
       remainder -> residential. If mood == "warm" and the top two darkest
       candidates are within tolerance, prefer higher a* (redder) for
       motorway. If mood == "vivid", prefer the highest-chroma remaining
       cluster for motorway over pure lightness, so a saturated photo
       produces visible "pop" on its most prominent road tier.
    5. road_primary/secondary/tertiary: only 6 clusters exist for 9 roles, so
       these three are *generated*, not extracted - an evenly spaced LAB
       lightness interpolation between the chosen motorway and residential
       colors, mirroring the smooth ramp every hand-authored stock theme
       already has across its road tiers.
    6. "pastel" mood gets no special-case rule: a photo CLIP calls pastel
       already has naturally low-chroma clusters, so the label is
       informational only - a deliberate simplification, not an oversight.
    """
    timings = timings if timings is not None else Timings()
    with timings.measure("palette_ms"):
        swatches = extract_palette(image, k=6)
    with timings.measure("mood_ms"):
        mood, _scores = classify_mood(image)

    labs = [(hex_color, srgb_to_lab(hex_color), weight) for hex_color, weight in swatches]
    # labs is already lightest -> darkest (extract_palette's contract).
    remaining = list(range(len(labs)))

    def take(index: int) -> str:
        remaining.remove(index)
        return labs[index][0]

    # 1. bg / text
    if mood == "dark":
        bg = take(remaining[-1])   # darkest
        text = take(remaining[0])  # now-lightest of what's left
    else:
        bg = take(remaining[0])    # lightest
        text = take(remaining[-1])  # darkest

    # 2. water: hue match to blue, mood-aware tie-break
    candidates = [(labs[i][0], labs[i][1], labs[i][2]) for i in remaining]
    water_idx = _pick_by_hue(candidates, _BLUE_HUE_RANGE)
    if water_idx is None:
        water_idx = 0  # next-lightest remaining
    elif mood == "cool" and len(candidates) > 1:
        # If another in-range-ish candidate is within the lightness
        # tolerance, prefer whichever is bluer (more negative b*).
        chosen_l = candidates[water_idx][1][0]
        close = [
            i for i, (_, lab, _) in enumerate(candidates)
            if i != water_idx and abs(lab[0] - chosen_l) <= _LIGHTNESS_TIE_TOLERANCE
        ]
        if close:
            pool = close + [water_idx]
            water_idx = min(pool, key=lambda i: candidates[i][1][2])  # most negative b*
    water = take(remaining[water_idx])

    # 3. parks: hue match to green
    candidates = [(labs[i][0], labs[i][1], labs[i][2]) for i in remaining]
    parks_idx = _pick_by_hue(candidates, _GREEN_HUE_RANGE)
    if parks_idx is None:
        parks_idx = 0
    parks = take(remaining[parks_idx])

    # 4. road_motorway / road_residential from what's left (already sorted
    # lightest->darkest by construction, so remaining[-1] is darkest).
    candidates = [(labs[i][0], labs[i][1], labs[i][2]) for i in remaining]
    darkest_idx = len(remaining) - 1
    if mood == "warm" and len(remaining) > 1:
        second_darkest_idx = len(remaining) - 2
        if abs(candidates[darkest_idx][1][0] - candidates[second_darkest_idx][1][0]) <= _LIGHTNESS_TIE_TOLERANCE:
            darkest_idx = max(
                (darkest_idx, second_darkest_idx), key=lambda i: candidates[i][1][1]  # higher a* (redder)
            )
    elif mood == "vivid":
        darkest_idx = max(range(len(candidates)), key=lambda i: _chroma(candidates[i][1]))
    road_motorway = take(remaining[darkest_idx])
    road_residential = take(remaining[0]) if remaining else road_motorway

    # 5. road_primary/secondary/tertiary: generated, evenly spaced LAB ramp
    # between motorway and residential (guards.lab_to_srgb_hex handles the
    # conversion back - no new color math).
    lab_motorway = srgb_to_lab(road_motorway)
    lab_residential = srgb_to_lab(road_residential)
    ramp = [
        lab_to_srgb_hex(lab_motorway + (lab_residential - lab_motorway) * t)
        for t in (0.25, 0.5, 0.75)
    ]
    road_primary, road_secondary, road_tertiary = ramp

    raw_theme = {
        "name": name,
        "description": f"Derived from an uploaded photo ({mood} mood)",
        "bg": bg,
        "text": text,
        "water": water,
        "parks": parks,
        "road_motorway": road_motorway,
        "road_primary": road_primary,
        "road_secondary": road_secondary,
        "road_tertiary": road_tertiary,
        "road_residential": road_residential,
    }
    return raw_theme, mood, swatches
