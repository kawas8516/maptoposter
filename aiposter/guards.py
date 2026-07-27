"""Palette legibility guards.

Two checks run over every AI-generated theme before it reaches the renderer:

1. WCAG 2.x contrast ratio between the ``text`` and ``bg`` colors. The poster
   reuses one text color for the ~60pt city name *and* the 14pt coordinate line
   and 8pt attribution, so the AA-normal bar (4.5:1) is the honest threshold.
2. CIEDE2000 perceptual distance between adjacent road-hierarchy tiers, so a
   motorway stays visually distinguishable from a primary road.

When a check fails the offending color's lightness is nudged in CIELAB until it
passes, and the change is recorded so the UI and the evaluation harness can both
report exactly what was altered.

The color math is implemented here directly rather than pulled from a library:
``colormath`` is unmaintained and broken on numpy 2.x, and the formulae below
are short enough to test against published reference vectors.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence, Union

import numpy as np

#: A colour vector: three floats, as a plain sequence or a numpy array.
Vector3 = Union[Sequence[float], np.ndarray]

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: Road tiers in hierarchy order, most prominent first. ``road_default`` is
#: deliberately absent: in all 17 stock themes it duplicates one of these tiers,
#: so including it would make every theme self-report a zero-distance violation.
ROAD_TIERS: tuple[str, ...] = (
    "road_motorway",
    "road_primary",
    "road_secondary",
    "road_tertiary",
    "road_residential",
)

_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")

# sRGB (linear) -> CIEXYZ, D65.
_RGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
_XYZ_TO_RGB = np.linalg.inv(_RGB_TO_XYZ)

#: D65 reference white.
_WHITE = np.array([0.95047, 1.00000, 1.08883])

_DELTA = 6.0 / 29.0

#: Lightness band used by the last-resort ramp rebalance. Kept just inside
#: [0, 100] so tiers retain a little chroma instead of clipping to pure
#: black/white.
_REBALANCE_MIN = 8.0
_REBALANCE_MAX = 92.0


@dataclass(frozen=True)
class GuardConfig:
    """Thresholds for the legibility checks."""

    min_contrast: float = 4.5
    min_delta_e: float = 10.0


@dataclass
class Correction:
    """A single automatic change, recorded for display and for metrics."""

    field: str
    before: str
    after: str
    reason: str
    metric_before: float
    metric_after: float

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "metric_before": round(self.metric_before, 3),
            "metric_after": round(self.metric_after, 3),
        }


@dataclass
class GuardResult:
    """Outcome of running the guards over a theme."""

    theme: dict
    passed: bool
    violations: list[str] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.corrections)

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": list(self.violations),
            "corrections": [c.as_dict() for c in self.corrections],
            "metrics": self.metrics,
        }


# --------------------------------------------------------------------------
# Color space conversions
# --------------------------------------------------------------------------


def normalize_hex(color: str) -> str:
    """Return ``color`` as an uppercase ``#RRGGBB`` string.

    Matches the format used by every stock theme file.
    """
    match = _HEX_RE.match(color.strip())
    if not match:
        raise ValueError(f"not a 6-digit hex color: {color!r}")
    return "#" + match.group(1).upper()


def hex_to_rgb(color: str) -> np.ndarray:
    """Hex string -> sRGB channels in [0, 1]."""
    digits = normalize_hex(color)[1:]
    return np.array([int(digits[i:i + 2], 16) for i in (0, 2, 4)], dtype=float) / 255.0


def rgb_to_hex(rgb: Vector3) -> str:
    """sRGB channels in [0, 1] -> ``#RRGGBB``, clipping out-of-gamut values."""
    clipped = np.clip(np.asarray(rgb, dtype=float), 0.0, 1.0)
    return "#" + "".join(f"{round(c * 255):02X}" for c in clipped)


def _srgb_to_linear(channels: np.ndarray) -> np.ndarray:
    return np.where(channels <= 0.04045, channels / 12.92, ((channels + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(channels: np.ndarray) -> np.ndarray:
    return np.where(channels <= 0.0031308, channels * 12.92, 1.055 * np.abs(channels) ** (1 / 2.4) - 0.055)


def _f_forward(t: np.ndarray) -> np.ndarray:
    return np.where(t > _DELTA ** 3, np.cbrt(t), t / (3 * _DELTA ** 2) + 4.0 / 29.0)


def _f_inverse(t: np.ndarray) -> np.ndarray:
    return np.where(t > _DELTA, t ** 3, 3 * _DELTA ** 2 * (t - 4.0 / 29.0))


def srgb_to_lab(color: str) -> np.ndarray:
    """Hex sRGB -> CIELAB (D65) as ``[L*, a*, b*]``."""
    linear = _srgb_to_linear(hex_to_rgb(color))
    xyz = _RGB_TO_XYZ @ linear
    f = _f_forward(xyz / _WHITE)
    return np.array([
        116.0 * f[1] - 16.0,
        500.0 * (f[0] - f[1]),
        200.0 * (f[1] - f[2]),
    ])


def lab_to_srgb_hex(lab: Vector3) -> str:
    """CIELAB -> hex sRGB, clipped into gamut."""
    lightness, a_star, b_star = (float(v) for v in lab)
    fy = (lightness + 16.0) / 116.0
    fx = fy + a_star / 500.0
    fz = fy - b_star / 200.0
    xyz = _f_inverse(np.array([fx, fy, fz])) * _WHITE
    return rgb_to_hex(_linear_to_srgb(_XYZ_TO_RGB @ xyz))


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def relative_luminance(color: str) -> float:
    """WCAG 2.x relative luminance of a hex color."""
    linear = _srgb_to_linear(hex_to_rgb(color))
    return float(np.dot([0.2126, 0.7152, 0.0722], linear))


def contrast_ratio(color_a: str, color_b: str) -> float:
    """WCAG 2.x contrast ratio. Order-independent; 21.0 for black vs white."""
    lum_a, lum_b = relative_luminance(color_a), relative_luminance(color_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def ciede2000(lab1: Vector3, lab2: Vector3) -> float:
    """CIEDE2000 color difference between two CIELAB values (kL=kC=kH=1)."""
    l1, a1, b1 = (float(v) for v in lab1)
    l2, a2, b2 = (float(v) for v in lab2)

    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    c_bar7 = c_bar ** 7
    g = 0.5 * (1.0 - math.sqrt(c_bar7 / (c_bar7 + 25.0 ** 7))) if c_bar > 0 else 0.0

    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)

    h1p = 0.0 if (a1p == 0.0 and b1 == 0.0) else math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = 0.0 if (a2p == 0.0 and b2 == 0.0) else math.degrees(math.atan2(b2, a2p)) % 360.0

    delta_lp = l2 - l1
    delta_cp = c2p - c1p

    if c1p * c2p == 0.0:
        delta_hp = 0.0
    else:
        diff = h2p - h1p
        if diff > 180.0:
            diff -= 360.0
        elif diff < -180.0:
            diff += 360.0
        delta_hp = diff
    delta_big_hp = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(delta_hp) / 2.0)

    l_bar = (l1 + l2) / 2.0
    c_bar_p = (c1p + c2p) / 2.0

    if c1p * c2p == 0.0:
        h_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        h_bar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        h_bar = (h1p + h2p + 360.0) / 2.0
    else:
        h_bar = (h1p + h2p - 360.0) / 2.0

    t = (
        1.0
        - 0.17 * math.cos(math.radians(h_bar - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * h_bar))
        + 0.32 * math.cos(math.radians(3.0 * h_bar + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * h_bar - 63.0))
    )

    delta_theta = 30.0 * math.exp(-(((h_bar - 275.0) / 25.0) ** 2))
    c_bar_p7 = c_bar_p ** 7
    r_c = 2.0 * math.sqrt(c_bar_p7 / (c_bar_p7 + 25.0 ** 7)) if c_bar_p > 0 else 0.0

    s_l = 1.0 + (0.015 * (l_bar - 50.0) ** 2) / math.sqrt(20.0 + (l_bar - 50.0) ** 2)
    s_c = 1.0 + 0.045 * c_bar_p
    s_h = 1.0 + 0.015 * c_bar_p * t
    r_t = -math.sin(math.radians(2.0 * delta_theta)) * r_c

    term_l = delta_lp / s_l
    term_c = delta_cp / s_c
    term_h = delta_big_hp / s_h
    return math.sqrt(term_l ** 2 + term_c ** 2 + term_h ** 2 + r_t * term_c * term_h)


def delta_e_hex(color_a: str, color_b: str) -> float:
    """CIEDE2000 between two hex colors."""
    return ciede2000(srgb_to_lab(color_a), srgb_to_lab(color_b))


# --------------------------------------------------------------------------
# Corrections
# --------------------------------------------------------------------------


def _with_lightness(color: str, lightness: float) -> str:
    """Return ``color`` with its L* replaced, preserving a*/b* (hue and chroma)."""
    lab = srgb_to_lab(color)
    return lab_to_srgb_hex([lightness, lab[1], lab[2]])


def _search_lightness(color: str, bound: float, passes, iterations: int = 40) -> tuple[str, bool]:
    """Binary-search L* between the color's current value and ``bound``.

    Finds the *smallest* lightness change satisfying ``passes(candidate_hex)``,
    so the correction preserves as much of the original hue and chroma as it
    can. Returns the candidate and whether the predicate was ever satisfied.

    The predicate is evaluated on the rendered hex rather than on LAB values, so
    gamut clipping is accounted for automatically.
    """
    start = float(srgb_to_lab(color)[0])
    if not passes(_with_lightness(color, bound)):
        return _with_lightness(color, bound), False

    low, high = start, bound
    best = _with_lightness(color, bound)
    for _ in range(iterations):
        mid = (low + high) / 2.0
        candidate = _with_lightness(color, mid)
        if passes(candidate):
            best, high = candidate, mid
        else:
            low = mid
    return best, True


def _ramp_direction(theme: dict) -> float:
    """+1 if roads get lighter down the hierarchy, -1 if they get darker.

    Derived from the theme's own ramp. If the ramp is flat we fall back to the
    background: roads recede *away* from a light background by getting lighter,
    and away from a dark one by getting darker.
    """
    first = float(srgb_to_lab(theme[ROAD_TIERS[0]])[0])
    last = float(srgb_to_lab(theme[ROAD_TIERS[-1]])[0])
    if abs(last - first) > 1e-6:
        return 1.0 if last > first else -1.0
    return 1.0 if float(srgb_to_lab(theme["bg"])[0]) >= 50.0 else -1.0


def _fix_contrast(theme: dict, cfg: GuardConfig, result: GuardResult) -> None:
    """Raise text/background contrast to the configured minimum."""
    before = contrast_ratio(theme["text"], theme["bg"])
    if before >= cfg.min_contrast:
        return

    result.violations.append(
        f"text/bg contrast {before:.2f}:1 is below the {cfg.min_contrast}:1 minimum"
    )

    # The background carries the aesthetic intent ("moody" lives in the bg), so
    # the text color is what moves.
    bg_light = float(srgb_to_lab(theme["bg"])[0]) >= 50.0
    bound = 0.0 if bg_light else 100.0
    original = theme["text"]

    candidate, converged = _search_lightness(
        original, bound, lambda c: contrast_ratio(c, theme["bg"]) >= cfg.min_contrast
    )
    reason = "text lightness nudged to meet WCAG contrast"
    if not converged:
        # Even the extreme of the lightness axis was not enough; fall back to
        # whichever pure tone maximises contrast against this background.
        candidate = "#000000" if bg_light else "#FFFFFF"
        reason = "text clamped to pure black/white; hue could not reach WCAG contrast"

    theme["text"] = candidate
    result.corrections.append(
        Correction(
            field="text",
            before=original,
            after=candidate,
            reason=reason,
            metric_before=before,
            metric_after=contrast_ratio(candidate, theme["bg"]),
        )
    )


def _rebalance_ramp(theme: dict, result: GuardResult, direction: float) -> None:
    """Last resort: respread the five tiers evenly across the lightness axis."""
    if direction > 0:
        targets = np.linspace(_REBALANCE_MIN, _REBALANCE_MAX, len(ROAD_TIERS))
    else:
        targets = np.linspace(_REBALANCE_MAX, _REBALANCE_MIN, len(ROAD_TIERS))

    for tier, target in zip(ROAD_TIERS, targets):
        original = theme[tier]
        updated = _with_lightness(original, float(target))
        if updated == original:
            continue
        theme[tier] = updated
        result.corrections.append(
            Correction(
                field=tier,
                before=original,
                after=updated,
                reason="road ramp rebalanced: tiers could not be separated individually",
                metric_before=float(srgb_to_lab(original)[0]),
                metric_after=float(target),
            )
        )


def _fix_road_separation(theme: dict, cfg: GuardConfig, result: GuardResult) -> None:
    """Push adjacent road tiers apart until they are perceptually distinct."""
    direction = _ramp_direction(theme)
    bound = 100.0 if direction > 0 else 0.0

    for upper, lower in zip(ROAD_TIERS, ROAD_TIERS[1:]):
        before = delta_e_hex(theme[upper], theme[lower])
        if before >= cfg.min_delta_e:
            continue

        result.violations.append(
            f"{upper} and {lower} differ by only dE2000 {before:.2f} "
            f"(minimum {cfg.min_delta_e})"
        )

        original = theme[lower]
        anchor = theme[upper]
        candidate, converged = _search_lightness(
            original, bound, lambda c, a=anchor: delta_e_hex(a, c) >= cfg.min_delta_e
        )
        if not converged:
            # No room left on this end of the axis; respread the whole ramp.
            _rebalance_ramp(theme, result, direction)
            return

        theme[lower] = candidate
        result.corrections.append(
            Correction(
                field=lower,
                before=original,
                after=candidate,
                reason=f"lightness nudged away from {upper} to meet CIEDE2000 separation",
                metric_before=before,
                metric_after=delta_e_hex(anchor, candidate),
            )
        )


def _road_pair_metrics(theme: dict) -> dict:
    """All 10 pairwise tier distances, so non-monotonic ramps are visible too."""
    pairs = {}
    for i, upper in enumerate(ROAD_TIERS):
        for lower in ROAD_TIERS[i + 1:]:
            pairs[f"{upper}|{lower}"] = round(delta_e_hex(theme[upper], theme[lower]), 3)
    return pairs


def _sync_derived_fields(theme: dict, before: dict, result: GuardResult) -> None:
    """Keep the two derived colors consistent after corrections.

    ``gradient_color`` is the fade-to-background color and must equal ``bg``;
    anything else produces a visible band. ``road_default`` mirrors whichever
    tier it originally matched.
    """
    if theme.get("gradient_color") != theme["bg"]:
        original = theme.get("gradient_color", "")
        theme["gradient_color"] = theme["bg"]
        if original and original != theme["bg"]:
            result.corrections.append(
                Correction(
                    field="gradient_color",
                    before=original,
                    after=theme["bg"],
                    reason="gradient_color must equal bg or the fade shows a visible band",
                    metric_before=0.0,
                    metric_after=0.0,
                )
            )

    default = before.get("road_default")
    if not default:
        return
    for tier in ROAD_TIERS:
        if before.get(tier) == default and theme[tier] != default:
            theme["road_default"] = theme[tier]
            return


def apply_guards(theme: dict, cfg: GuardConfig | None = None) -> GuardResult:
    """Check and, where needed, correct a theme for legibility.

    Returns a :class:`GuardResult` holding the (possibly corrected) theme plus a
    structured record of every violation found and change made. The input dict
    is not mutated. Running the guards a second time over the returned theme is
    a no-op.
    """
    cfg = cfg or GuardConfig()
    working = dict(theme)
    original = dict(theme)
    result = GuardResult(theme=working, passed=True)

    _fix_contrast(working, cfg, result)
    _fix_road_separation(working, cfg, result)
    _sync_derived_fields(working, original, result)

    final_contrast = contrast_ratio(working["text"], working["bg"])
    pair_metrics = _road_pair_metrics(working)
    adjacent = [
        pair_metrics[f"{upper}|{lower}"]
        for upper, lower in zip(ROAD_TIERS, ROAD_TIERS[1:])
    ]

    result.metrics = {
        "contrast_text_bg": round(final_contrast, 3),
        "min_contrast_required": cfg.min_contrast,
        "road_pair_delta_e": pair_metrics,
        "min_adjacent_delta_e": round(min(adjacent), 3),
        "min_delta_e_required": cfg.min_delta_e,
    }

    # A ramp can be monotonic-adjacent yet still fold back on itself; that is
    # worth surfacing even though we do not auto-correct it.
    for name, value in pair_metrics.items():
        upper, lower = name.split("|")
        is_adjacent = ROAD_TIERS.index(lower) - ROAD_TIERS.index(upper) == 1
        if not is_adjacent and value < cfg.min_delta_e:
            result.violations.append(
                f"non-adjacent tiers {upper} and {lower} are close "
                f"(dE2000 {value:.2f}); ramp may not be monotonic"
            )

    result.passed = (
        final_contrast >= cfg.min_contrast - 1e-9
        and min(adjacent) >= cfg.min_delta_e - 1e-9
    )
    return result


def evaluate_only(theme: dict, cfg: GuardConfig | None = None) -> dict:
    """Measure a theme without correcting it.

    Used to characterise the stock themes, which ship as hand-tuned designs and
    are deliberately *not* auto-corrected.
    """
    cfg = cfg or GuardConfig()
    pair_metrics = _road_pair_metrics(theme)
    adjacent = [
        pair_metrics[f"{upper}|{lower}"]
        for upper, lower in zip(ROAD_TIERS, ROAD_TIERS[1:])
    ]
    contrast = contrast_ratio(theme["text"], theme["bg"])
    return {
        "contrast_text_bg": round(contrast, 3),
        "min_adjacent_delta_e": round(min(adjacent), 3),
        "road_pair_delta_e": pair_metrics,
        "passes_contrast": contrast >= cfg.min_contrast,
        "passes_separation": min(adjacent) >= cfg.min_delta_e,
    }


def swatch_order(theme: dict) -> Iterable[tuple[str, str]]:
    """Theme fields in a sensible order for a swatch strip in the UI."""
    keys = ("bg", "text", "water", "parks", *ROAD_TIERS, "road_default")
    for key in keys:
        if key in theme:
            yield key, theme[key]
