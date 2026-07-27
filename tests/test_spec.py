"""Schema validation tests — model output is untrusted input."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aiposter.spec import MAX_DISTANCE_M, MIN_DISTANCE_M, PosterSpec, ThemeSpec, poster_json_schema

THEME = {
    "name": "Test",
    "description": "fixture",
    "bg": "#1A3A5C",
    "text": "#E8F4FF",
    "water": "#0F2840",
    "parks": "#1E4570",
    "road_motorway": "#E8F4FF",
    "road_primary": "#C5DCF0",
    "road_secondary": "#9FC5E8",
    "road_tertiary": "#7BAED4",
    "road_residential": "#5A96C0",
}


def test_theme_normalizes_hex_case_and_hash():
    theme = ThemeSpec(**{**THEME, "bg": "1a3a5c", "text": "e8f4ff"})
    assert theme.bg == "#1A3A5C"
    assert theme.text == "#E8F4FF"


def test_gradient_color_is_always_bg():
    assert ThemeSpec(**THEME).gradient_color == THEME["bg"]
    overridden = ThemeSpec(**THEME, gradient_color="#FF0000")
    assert overridden.gradient_color == THEME["bg"]


def test_road_default_falls_back_to_tertiary():
    assert ThemeSpec(**THEME).road_default == THEME["road_tertiary"]
    explicit = ThemeSpec(**THEME, road_default="#123456")
    assert explicit.road_default == "#123456"


def test_theme_dict_matches_stock_shape():
    theme = ThemeSpec(**THEME).to_theme_dict()
    assert set(theme) == {
        "name", "description", "bg", "text", "gradient_color", "water", "parks",
        "road_motorway", "road_primary", "road_secondary", "road_tertiary",
        "road_residential", "road_default",
    }
    assert all(isinstance(v, str) for v in theme.values())


def test_extra_theme_fields_are_rejected():
    with pytest.raises(ValidationError, match="shadow"):
        ThemeSpec(**THEME, shadow="#000000")


@pytest.mark.parametrize("bad", ["#ZZZZZZ", "#FFF", "red", "", "#1234567", "0x123456"])
def test_bad_hex_is_rejected(bad):
    with pytest.raises(ValidationError):
        ThemeSpec(**{**THEME, "bg": bad})


def test_extra_spec_fields_are_rejected():
    """Blocks spec-injection of render parameters we never asked for."""
    with pytest.raises(ValidationError, match="output_file"):
        PosterSpec(city="Tokyo", country="Japan", theme=THEME, output_file="/etc/passwd")


@pytest.mark.parametrize("distance", [0, 999, MAX_DISTANCE_M + 1, 10**9, -5000])
def test_distance_out_of_range_is_rejected(distance):
    with pytest.raises(ValidationError):
        PosterSpec(city="Tokyo", country="Japan", distance=distance, theme=THEME)


@pytest.mark.parametrize("distance", [MIN_DISTANCE_M, 12000, MAX_DISTANCE_M])
def test_distance_in_range_is_accepted(distance):
    assert PosterSpec(city="Tokyo", country="Japan", distance=distance, theme=THEME).distance == distance


@pytest.mark.parametrize(
    "lat,lon", [(91, 0), (-91, 0), (0, 181), (0, -181), (999, 999)]
)
def test_coordinates_out_of_range_are_rejected(lat, lon):
    with pytest.raises(ValidationError):
        PosterSpec(city="Tokyo", country="Japan", latitude=lat, longitude=lon, theme=THEME)


@pytest.mark.parametrize("lat,lon", [(35.68, None), (None, 139.69)])
def test_half_a_coordinate_pair_is_rejected(lat, lon):
    with pytest.raises(ValidationError, match="together"):
        PosterSpec(city="Tokyo", country="Japan", latitude=lat, longitude=lon, theme=THEME)


def test_empty_city_is_rejected():
    with pytest.raises(ValidationError):
        PosterSpec(city="", country="Japan", theme=THEME)


def test_overlong_city_is_rejected():
    with pytest.raises(ValidationError):
        PosterSpec(city="x" * 81, country="Japan", theme=THEME)


def test_schema_is_serializable_and_names_every_color():
    schema = poster_json_schema()
    theme_props = schema["$defs"]["ThemeSpec"]["properties"]
    for key in ("bg", "text", "water", "parks", "road_motorway", "road_residential"):
        assert key in theme_props
