"""Codec-agnostic Studio export configuration (Issue #17)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from orga_drone.studio_frame import FrameTransform
from orga_drone.studio_hud import HudInterval
from orga_drone.studio_image import ImageAdjust, SaturationRamp
from orga_drone.studio_map import GpsSample, MapPlacement
from orga_drone.studio_mask import Mask
from orga_drone.studio_overlay import Overlay


@dataclass(frozen=True)
class StudioExportClip:
    """One timeline clip for export (references source path; never copies media)."""

    source_path: Path | None
    kind: str  # photo | video | title_card
    duration_s: float
    source_start_s: float = 0.0
    source_end_s: float | None = None
    playback_speed: float = 1.0
    # Video only. 1 plays the in/out range once. The encoder repeats that range.
    section_repeats: int = 1
    # Internal: a repeat slice uses its real in/out length, including spans under 0.1s.
    exact_span: bool = False
    title_text: str = ""
    subtitle_text: str = ""
    background: str = "dark"
    locale: str = "en"
    label: str = ""
    transition_type: str = "cut"
    transition_s: float = 0.0
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0
    image: ImageAdjust = field(default_factory=ImageAdjust)
    saturation_ramp: SaturationRamp = field(default_factory=SaturationRamp)
    frame: FrameTransform = field(default_factory=FrameTransform)
    masks: tuple[Mask, ...] = ()
    overlays: tuple[Overlay, ...] = ()
    map_placement: MapPlacement = field(default_factory=MapPlacement)
    gps_track: tuple[GpsSample, ...] = ()
    media_duration_s: float | None = None
    hud_enabled: bool = False
    hud_intervals: tuple[HudInterval, ...] = ()


@dataclass(frozen=True)
class StudioExportMusic:
    """One optional soundtrack mixed onto the concat audio (reference only)."""

    source_path: Path
    volume: float = 0.8
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0
    loop: bool = False
    duration_s: float = 0.0


@dataclass
class HeldExportFile:
    """Handle of the one ordinary file a confirmed overwrite may replace.

    The handle stays open until publish. On Windows it is opened without
    sharing delete, so another program cannot rename or delete that name while
    the export runs. Bytes are written only through this handle. The handle
    does not prove this file was never a library original. A write that
    stops midway can leave this ordinary export file incomplete. No other file
    is written.
    """

    fd: int
    identity: tuple[int, int]
    _closed: bool = field(default=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.close(self.fd)

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass


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
    # Identity approved when the destination was checked. None means the name
    # was free: publish may create it and must not replace a file that appears later.
    approved_identity: tuple[int, int] | None = None
    # Identities of protected originals, captured before the destination is read.
    protected_identities: tuple[tuple[int, int], ...] = ()
    # Open handle for a confirmed overwrite. None when the name was free.
    approved_file: HeldExportFile | None = None

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
