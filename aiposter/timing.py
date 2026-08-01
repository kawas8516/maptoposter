"""Per-stage timing instrumentation (NFR8).

A single end-to-end number cannot tell you whether a slow generation was the
model, the geocoder, the OSM download or matplotlib. Every stage is timed
separately so a latency regression is attributable to one of them.

The same record feeds the "Performance" expander in the UI and the FR5.1
evaluation CSV, so what the user sees and what gets measured cannot drift.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional

#: Stage names, in pipeline order. Fixed so CSV columns stay stable.
STAGES: tuple[str, ...] = (
    "llm_ms",
    "validate_ms",
    "palette_ms",
    "mood_ms",
    "guard_ms",
    "geocode_ms",
    "graph_ms",
    "render_ms",
)

STAGE_LABELS: dict[str, str] = {
    "llm_ms": "Model call",
    "validate_ms": "Schema validation",
    "palette_ms": "Palette extraction",
    "mood_ms": "Mood classification",
    "guard_ms": "Palette guards",
    "geocode_ms": "Geocoding",
    "graph_ms": "OSM graph",
    "render_ms": "Rendering",
}


@dataclass
class Timings:
    """Accumulated per-stage durations in milliseconds."""

    stages: dict[str, float] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)

    def record(self, stage: str, milliseconds: float, note: str = "") -> None:
        """Add to a stage, so repeated work in one stage accumulates."""
        self.stages[stage] = self.stages.get(stage, 0.0) + milliseconds
        if note:
            self.notes[stage] = note

    @contextmanager
    def measure(self, stage: str, note: str = "") -> Iterator[None]:
        """Time a block and attribute it to ``stage``."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record(stage, (time.perf_counter() - started) * 1000.0, note)

    @property
    def total_ms(self) -> float:
        return sum(self.stages.values())

    def as_dict(self) -> dict:
        """Flat dict with every stage present, for CSV rows."""
        row = {stage: round(self.stages.get(stage, 0.0), 1) for stage in STAGES}
        row["total_ms"] = round(self.total_ms, 1)
        return row

    def rows(self) -> list[tuple[str, float, str]]:
        """Non-zero stages as ``(label, ms, note)``, in pipeline order."""
        out = []
        for stage in STAGES:
            value = self.stages.get(stage)
            if value:
                out.append((STAGE_LABELS[stage], value, self.notes.get(stage, "")))
        return out

    def merge(self, other: Optional["Timings"]) -> "Timings":
        """Combine two timing records, e.g. generation plus a later render."""
        if other is None:
            return self
        combined = Timings(stages=dict(self.stages), notes=dict(self.notes))
        for stage, value in other.stages.items():
            combined.record(stage, value, other.notes.get(stage, ""))
        return combined
