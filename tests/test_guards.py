"""Colour-science and guard tests. Fully offline and deterministic."""

from __future__ import annotations

import glob
import json

import pytest

from aiposter import guards
from aiposter.guards import (
    GuardConfig,
    apply_guards,
    ciede2000,
    contrast_ratio,
    delta_e_hex,
    lab_to_srgb_hex,
    normalize_hex,
    srgb_to_lab,
)

# Reference pairs from Sharma, Wu & Dalal, "The CIEDE2000 Color-Difference
# Formula: Implementation Notes, Supplementary Test Data, and Mathematical
# Observations" (2005). These are the cases that break naive implementations:
# hue angles straddling 0/360, and the arctangent discontinuity.
SHARMA_CASES = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0010), 7.1792),
    ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]

STOCK_THEMES = sorted(glob.glob("themes/*.json"))


@pytest.mark.parametrize("lab1,lab2,expected", SHARMA_CASES)
def test_ciede2000_matches_sharma_reference(lab1, lab2, expected):
    """Reference values are published to 4 dp, so agreement must be tight."""
    assert ciede2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)


def test_ciede2000_is_symmetric():
    for lab1, lab2, _ in SHARMA_CASES:
        assert ciede2000(lab1, lab2) == pytest.approx(ciede2000(lab2, lab1), abs=1e-9)


def test_ciede2000_identical_colors_is_zero():
    assert delta_e_hex("#A0522D", "#A0522D") == pytest.approx(0.0, abs=1e-12)


def test_contrast_black_white_is_exactly_21():
    """Definitional: (1.0 + 0.05) / (0.0 + 0.05)."""
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=1e-9)


def test_contrast_is_order_independent():
    assert contrast_ratio("#1A3A5C", "#E8F4FF") == pytest.approx(
        contrast_ratio("#E8F4FF", "#1A3A5C"), abs=1e-12
    )


def test_contrast_same_color_is_one():
    assert contrast_ratio("#7BAED4", "#7BAED4") == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("path", STOCK_THEMES)
def test_lab_round_trip_over_stock_corpus(path):
    """Every colour the project ships must survive sRGB -> LAB -> sRGB."""
    theme = json.loads(open(path, encoding="utf-8").read())
    for key, value in theme.items():
        if key in ("name", "description"):
            continue
        assert lab_to_srgb_hex(srgb_to_lab(value)) == normalize_hex(value), f"{path}:{key}"


def test_normalize_hex_accepts_both_forms():
    assert normalize_hex("1a3a5c") == "#1A3A5C"
    assert normalize_hex("#1A3A5C") == "#1A3A5C"
    with pytest.raises(ValueError):
        normalize_hex("#ZZZZZZ")
    with pytest.raises(ValueError):
        normalize_hex("#FFF")


def _theme(**overrides) -> dict:
    base = {
        "name": "Test",
        "description": "fixture",
        "bg": "#FFFFFF",
        "text": "#000000",
        "gradient_color": "#FFFFFF",
        "water": "#E0E8EE",
        "parks": "#E8EEE0",
        "road_motorway": "#111111",
        "road_primary": "#3C3C3C",
        "road_secondary": "#6A6A6A",
        "road_tertiary": "#9A9A9A",
        "road_residential": "#CCCCCC",
        "road_default": "#9A9A9A",
    }
    base.update(overrides)
    return base


def test_compliant_theme_is_left_alone():
    result = apply_guards(_theme())
    assert result.passed
    assert result.corrections == []


def test_low_contrast_text_is_corrected():
    result = apply_guards(_theme(bg="#FFFFFF", text="#EEEEEE"))
    assert result.passed
    assert any(c.field == "text" for c in result.corrections)
    assert result.metrics["contrast_text_bg"] >= 4.5


def test_contrast_correction_darkens_against_light_background():
    original = _theme(bg="#FFFFFF", text="#F0F0F0")
    result = apply_guards(original)
    assert srgb_to_lab(result.theme["text"])[0] < srgb_to_lab(original["text"])[0]


def test_contrast_correction_lightens_against_dark_background():
    original = _theme(bg="#050505", text="#111111")
    result = apply_guards(original)
    assert srgb_to_lab(result.theme["text"])[0] > srgb_to_lab(original["text"])[0]


def test_background_is_never_modified():
    """The background carries the aesthetic intent, so only text moves."""
    original = _theme(bg="#0B0E1A", text="#0C0F1B")
    result = apply_guards(original)
    assert result.theme["bg"] == original["bg"]


def test_flat_road_ramp_is_separated():
    flat = _theme(**{tier: "#808080" for tier in guards.ROAD_TIERS})
    result = apply_guards(flat)
    assert result.passed
    assert result.metrics["min_adjacent_delta_e"] >= 10.0


def test_road_default_is_not_treated_as_a_violation():
    """It duplicates a tier by convention in every stock theme."""
    result = apply_guards(_theme())
    assert not any("road_default" in v for v in result.violations)


def test_road_default_follows_its_tier_after_correction():
    flat = _theme(**{tier: "#808080" for tier in guards.ROAD_TIERS}, road_default="#808080")
    result = apply_guards(flat)
    assert result.theme["road_default"] == result.theme["road_tertiary"]


def test_gradient_color_is_forced_to_bg():
    result = apply_guards(_theme(bg="#102030", gradient_color="#FF0000", text="#FFFFFF"))
    assert result.theme["gradient_color"] == "#102030"
    assert any(c.field == "gradient_color" for c in result.corrections)


@pytest.mark.parametrize(
    "theme",
    [
        _theme(),
        _theme(bg="#000000", text="#000000"),
        _theme(bg="#FFFFFF", text="#FFFFFF"),
        _theme(**{tier: "#808080" for tier in guards.ROAD_TIERS}),
        _theme(bg="#0B0E1A", text="#0B0E1B", **{tier: "#0B0E1A" for tier in guards.ROAD_TIERS}),
        _theme(bg="#7F7F7F", text="#808080"),
    ],
    ids=["compliant", "black-on-black", "white-on-white", "flat-ramp", "everything-flat", "mid-grey"],
)
def test_guards_are_idempotent(theme):
    """A second pass must find nothing left to change."""
    once = apply_guards(theme)
    twice = apply_guards(once.theme)
    assert twice.corrections == []
    assert twice.theme == once.theme


def test_guards_do_not_mutate_the_input():
    original = _theme(bg="#FFFFFF", text="#EEEEEE")
    snapshot = dict(original)
    apply_guards(original)
    assert original == snapshot


def test_thresholds_are_configurable():
    strict = apply_guards(_theme(), GuardConfig(min_contrast=4.5, min_delta_e=30.0))
    assert strict.corrections, "a ΔE floor of 30 should force changes"


@pytest.mark.parametrize("path", STOCK_THEMES)
def test_evaluate_only_never_mutates_stock_themes(path):
    theme = json.loads(open(path, encoding="utf-8").read())
    snapshot = dict(theme)
    metrics = guards.evaluate_only(theme)
    assert theme == snapshot
    assert "contrast_text_bg" in metrics
