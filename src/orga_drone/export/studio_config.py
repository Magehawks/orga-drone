"""Codec-agnostic Studio export configuration (Issue #17)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orga_drone.studio_audio import DetachedAudio
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
    # Derived at export time from a known soundtrack. Not a stored repeat count.
    # The soundtrack is mixed once afterwards. Joins are hard cuts unless
    # ``forward_transition_s`` is the applied crossfade overlap.
    forward_loop: bool = False
    forward_cycle_s: float = 0.0
    forward_transition_s: float = 0.0
    # ``linear`` uses xfade fade. ``smooth`` is the cinematic ease curve.
    # Story transitions ignore this and stay on ``transition_type``.
    forward_transition_curve: str = "linear"
    # Internal: a repeat slice uses its real in/out length, including spans under 0.1s.
    exact_span: bool = False
    title_text: str = ""
    subtitle_text: str = ""
    background: str = "dark"
    locale: str = "en"
    label: str = ""
    transition_type: str = "cut"
    transition_s: float = 0.0
    # Loop joins only. ``smooth`` selects the cinematic ease curve. Story
    # crossfades leave this at ``linear``.
    transition_curve: str = "linear"
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
    detached_audio: DetachedAudio | None = None
    # Clip-local source seconds. None keeps the existing whole-clip zoom or speed.
    zoom_span: tuple[float, float] | None = None
    slow_span: tuple[float, float, float] | None = None


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
    # standard | high | best. Missing callers use High.
    quality: str = "high"
    clips: tuple[StudioExportClip, ...] = field(default_factory=tuple)
    project_title: str = "Your story"
    music_tracks: tuple[StudioExportMusic, ...] = field(default_factory=tuple)
    music: StudioExportMusic | None = None
    music_start_s: float = 0.0
    # Identities of protected originals, captured before encoding starts.
    protected_identities: tuple[tuple[int, int], ...] = ()
    # Catalog paths an export must not create or replace, even when the file is absent.
    protected_paths: tuple[str, ...] = ()

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
            "quality": self.quality,
            "project_title": self.project_title,
            "clip_count": len(self.clips),
            "has_music": bool(self.music_tracks),
            "music_start_s": self.music_start_s,
        }
