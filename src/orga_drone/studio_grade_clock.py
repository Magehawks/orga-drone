"""Assemble RenderContext from existing timeline timing owners (#358).

This module does not invent a second remapping engine. It only packages
caller-supplied trim / speed / repeat / transition results into the pure
``RenderContext`` contract consumed by ``evaluate_grade``.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from orga_drone.studio_grade_plan import RenderContext
from orga_drone.studio_speed_ramp import SpeedRamp


def as_fraction_seconds(seconds: float, *, limit: int = 1_000_000) -> Fraction:
    """Stable rational encoding of a timeline second."""
    value = float(seconds)
    if value < 0:
        value = 0.0
    return Fraction(value).limit_denominator(limit)


@dataclass(frozen=True)
class ClipTimingInputs:
    """Timing fields already resolved by export/preview owners."""

    source_id: str
    source_in_s: float
    source_out_s: float | None
    # Absolute Story time for the playhead.
    story_time_s: float
    # Story start of this clip instance (after previous transitions).
    clip_story_start_s: float
    # Story duration of one play of the trimmed/speed-mapped clip.
    cycle_story_s: float
    section_repeats: int = 1
    speed_ramp: SpeedRamp | None = None
    transition_side: str = "single"
    width: int = 1920
    height: int = 1080
    orientation: int = 1
    source_frame_rate: float = 30.0


def map_repeat_pass(story_local_s: float, cycle_story_s: float, repeats: int) -> tuple[float, int]:
    """Fold Story-local time into one cycle and a 0-based repeat pass."""
    cycle = max(0.0, float(cycle_story_s))
    count = max(1, int(repeats))
    local = max(0.0, float(story_local_s))
    if cycle <= 0:
        return 0.0, 0
    total = cycle * count
    if local >= total:
        return cycle, count - 1
    pass_index = min(count - 1, int(local // cycle))
    within = local - pass_index * cycle
    if within > cycle:
        within = cycle
    return within, pass_index


def source_pts_for_cycle(
    *,
    cycle_local_s: float,
    source_in_s: float,
    source_out_s: float | None,
    speed_ramp: SpeedRamp | None,
) -> tuple[float, float]:
    """Map one-cycle Story-local seconds to absolute source PTS and speed.

    Uses ``SpeedRamp.source_at`` when a ramp exists; otherwise constant-speed
    identity across the trimmed interval.
    """
    start = max(0.0, float(source_in_s))
    end = float(source_out_s) if source_out_s is not None else None
    local = max(0.0, float(cycle_local_s))
    if speed_ramp is not None and end is not None:
        # Ramp primitives are absolute source seconds; invert against the trim.
        source = speed_ramp.source_at(local + speed_ramp.time_at(start), start, end)
        speed = max(1e-6, float(speed_ramp.speed_at(source)))
        return source, speed
    if speed_ramp is not None and end is None:
        # Open-ended: treat local as offset from in-point under ramp from start.
        probe_end = start + max(local, 0.05)
        source = speed_ramp.source_at(local + speed_ramp.time_at(start), start, probe_end)
        speed = max(1e-6, float(speed_ramp.speed_at(source)))
        return max(start, source), speed
    # Constant speed 1.0 across the trimmed range.
    source = start + local
    if end is not None:
        source = min(source, end)
    return source, 1.0


def build_render_context(inputs: ClipTimingInputs) -> RenderContext:
    """Build a validated RenderContext without re-deriving transition math."""
    story_local = max(0.0, float(inputs.story_time_s) - float(inputs.clip_story_start_s))
    cycle_local, repeat_pass = map_repeat_pass(
        story_local, inputs.cycle_story_s, inputs.section_repeats
    )
    source_pts_s, speed = source_pts_for_cycle(
        cycle_local_s=cycle_local,
        source_in_s=inputs.source_in_s,
        source_out_s=inputs.source_out_s,
        speed_ramp=inputs.speed_ramp,
    )
    source_in = as_fraction_seconds(inputs.source_in_s)
    source_pts = as_fraction_seconds(source_pts_s)
    source_out = (
        as_fraction_seconds(inputs.source_out_s)
        if inputs.source_out_s is not None
        else None
    )
    source_local = source_pts - source_in
    if source_local < 0:
        source_local = Fraction(0)
        source_pts = source_in
    frame = int(round(float(source_pts) * float(inputs.source_frame_rate)))
    side = inputs.transition_side if inputs.transition_side in (
        "single",
        "incoming",
        "outgoing",
    ) else "single"
    return RenderContext(
        source_id=str(inputs.source_id),
        source_pts=source_pts,
        source_frame=max(0, frame),
        source_in=source_in,
        source_out=source_out,
        source_local=source_local,
        story_time=as_fraction_seconds(inputs.story_time_s),
        speed=as_fraction_seconds(speed) if speed > 0 else Fraction(1),
        repeat_pass=max(0, int(repeat_pass)),
        transition_side=side,
        width=max(1, int(inputs.width)),
        height=max(1, int(inputs.height)),
        orientation=max(1, min(8, int(inputs.orientation))),
    )


def transition_side_for_hit(hit: Any) -> str:
    """Map ``StoryTimeHit`` overlap fields onto RenderContext.transition_side."""
    overlap = getattr(hit, "overlap_index", None)
    progress = getattr(hit, "crossfade_progress", None)
    if overlap is None or progress is None:
        return "single"
    # During a crossfade the primary clip is outgoing while the partner is
    # incoming; callers that evaluate the primary use outgoing.
    return "outgoing"
