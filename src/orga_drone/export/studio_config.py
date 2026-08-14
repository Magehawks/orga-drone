"""Codec-agnostic Studio export configuration (Issue #17)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class StudioExportClip:
    """One timeline clip for export (references source path; never copies media)."""

    source_path: Path
    kind: str  # photo | video
    duration_s: float
    source_start_s: float = 0.0
    source_end_s: float | None = None


@dataclass(frozen=True)
class StudioExportConfig:
    """User-facing export intent without encoder/codec details."""

    output_path: Path
    width: int
    height: int
    clips: tuple[StudioExportClip, ...] = field(default_factory=tuple)
    project_title: str = "Your story"

    def as_dict(self) -> dict[str, object]:
        return {
            "output_path": str(self.output_path),
            "width": self.width,
            "height": self.height,
            "project_title": self.project_title,
            "clip_count": len(self.clips),
        }
