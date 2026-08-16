"""Codec-agnostic Studio export configuration (Issue #17)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class StudioExportClip:
    """One timeline clip for export (references source path; never copies media)."""

    source_path: Path | None
    kind: str  # photo | video | title_card
    duration_s: float
    source_start_s: float = 0.0
    source_end_s: float | None = None
    title_text: str = ""
    subtitle_text: str = ""
    background: str = "dark"
    locale: str = "en"
    label: str = ""
    transition_type: str = "cut"
    transition_s: float = 0.0
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0


@dataclass(frozen=True)
class StudioExportMusic:
    """One optional soundtrack mixed onto the concat audio (reference only)."""

    source_path: Path
    volume: float = 0.8
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0
    loop: bool = False
    duration_s: float = 0.0


@dataclass(frozen=True)
class StudioExportConfig:
    """User-facing export intent without encoder/codec details."""

    output_path: Path
    width: int
    height: int
    clips: tuple[StudioExportClip, ...] = field(default_factory=tuple)
    project_title: str = "Your story"
    music_tracks: tuple[StudioExportMusic, ...] = field(default_factory=tuple)
    music: StudioExportMusic | None = None

    def __post_init__(self) -> None:
        if self.music is not None and not self.music_tracks:
            object.__setattr__(self, "music_tracks", (self.music,))
        elif self.music_tracks and self.music is None:
            object.__setattr__(self, "music", self.music_tracks[0])

    def as_dict(self) -> dict[str, object]:
        return {
            "output_path": str(self.output_path),
            "width": self.width,
            "height": self.height,
            "project_title": self.project_title,
            "clip_count": len(self.clips),
            "has_music": bool(self.music_tracks),
        }
