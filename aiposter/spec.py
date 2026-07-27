"""The validated specification an AI-generated poster must satisfy.

Model output is untrusted input. Everything the LLM produces passes through
these models before it reaches the geocoder or the renderer:

* ``extra="forbid"`` blocks spec-injection — a model cannot smuggle in an
  ``output_file`` or any other render parameter we did not ask for.
* Every color is pinned to a 6-digit hex and normalised to the ``#RRGGBB``
  uppercase form the stock theme files use.
* ``distance`` and the optional coordinate override are range-checked.

Two theme fields are *derived* rather than invented. In all 17 stock themes
``gradient_color`` equals ``bg`` (it is the fade-to-background color, so any
other value shows as a band) and ``road_default`` duplicates one of the road
tiers. The model is told to omit both; if it supplies them anyway they are
reconciled here.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

#: A 6-digit hex color, with or without the leading '#'.
HexColor = Annotated[str, StringConstraints(pattern=r"^#?[0-9A-Fa-f]{6}$")]

#: Distance bounds in metres (security.md §4). Below ~1 km the street network is
#: too sparse to read as a poster; above ~30 km the OSM fetch becomes punishing.
MIN_DISTANCE_M = 1000
MAX_DISTANCE_M = 30000

#: The color fields the renderer actually consumes.
THEME_COLOR_FIELDS: tuple[str, ...] = (
    "bg",
    "text",
    "gradient_color",
    "water",
    "parks",
    "road_motorway",
    "road_primary",
    "road_secondary",
    "road_tertiary",
    "road_residential",
    "road_default",
)


class ThemeSpec(BaseModel):
    """An invented poster theme: 11 colors plus a name and description."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=120)]

    bg: HexColor = Field(description="Poster background")
    text: HexColor = Field(description="City name, country, coordinates")
    water: HexColor = Field(description="Rivers, lakes, bays")
    parks: HexColor = Field(description="Parks and green space")
    road_motorway: HexColor = Field(description="Most prominent road tier")
    road_primary: HexColor
    road_secondary: HexColor
    road_tertiary: HexColor
    road_residential: HexColor = Field(description="Least prominent road tier")

    # Derived — the model is instructed to omit these.
    gradient_color: Optional[HexColor] = Field(default=None, description="Omit; always equals bg")
    road_default: Optional[HexColor] = Field(default=None, description="Omit; defaults to road_tertiary")

    @field_validator(*THEME_COLOR_FIELDS, mode="after")
    @classmethod
    def _normalise_hex(cls, value: Optional[str]) -> Optional[str]:
        """Store every color as uppercase ``#RRGGBB``, matching the stock files."""
        if value is None:
            return None
        return "#" + value.lstrip("#").upper()

    @model_validator(mode="after")
    def _derive_fields(self) -> "ThemeSpec":
        """Force the two derived colors to their required values."""
        object.__setattr__(self, "gradient_color", self.bg)
        if self.road_default is None:
            object.__setattr__(self, "road_default", self.road_tertiary)
        return self

    def to_theme_dict(self) -> dict[str, str]:
        """Emit the exact 13-key dict ``create_map_poster`` expects."""
        theme: dict[str, str] = {"name": self.name, "description": self.description}
        for key in THEME_COLOR_FIELDS:
            value = getattr(self, key)
            assert value is not None  # guaranteed by _derive_fields
            theme[key] = value
        return theme


class PosterSpec(BaseModel):
    """A complete poster request: where to render, and in what theme."""

    model_config = ConfigDict(extra="forbid")

    city: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    country: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    distance: int = Field(
        default=12000,
        ge=MIN_DISTANCE_M,
        le=MAX_DISTANCE_M,
        description=f"Map radius in metres ({MIN_DISTANCE_M}-{MAX_DISTANCE_M})",
    )
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    theme: ThemeSpec

    @model_validator(mode="after")
    def _coordinates_come_in_pairs(self) -> "PosterSpec":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together, or both omitted")
        return self


def poster_json_schema() -> dict[str, Any]:
    """The JSON Schema for :class:`PosterSpec`.

    Single source of truth: this feeds both the system prompt and the
    best-effort ``response_format`` sent to the provider, so the instructions
    the model sees can never drift from what the validator enforces.
    """
    return PosterSpec.model_json_schema()


def poster_schema_text(indent: int = 2) -> str:
    """The JSON Schema rendered for embedding in the system prompt."""
    return json.dumps(poster_json_schema(), indent=indent, sort_keys=True)


def response_format() -> dict[str, Any]:
    """OpenAI-style structured-output request for providers that support it."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "PosterSpec",
            "schema": poster_json_schema(),
            "strict": True,
        },
    }
