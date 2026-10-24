"""Slow motion for a source range inside one Studio video clip.

Allowed speeds are 1× (reset), 0.5×, and 0.25×. A partial range splits the
clip so the sections outside that range keep their current speed. Story time
for a section is its source duration divided by the speed.

Slowed sections mute the source audio. There is no time-stretch and no
optical-flow interpolation: a 10 fps source stays 10 fps and is held to the
export frame rate. Fast-forward, reverse, and loop are out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass

from orga_drone.studio_cut import MIN_SEGMENT_S, SourceRange

ALLOWED_SPEEDS = (1.0, 0.5, 0.25)
# Snap a range that is this close to a clip edge onto that edge.
_EDGE_EPS_S = 0.002


@dataclass(frozen=True)
class SpeedSegment:
    """One constant-speed slice of a source range."""

    source_in_s: float
    source_out_s: float
    speed: float

    @property
    def source_duration_s(self) -> float:
        return max(0.0, float(self.source_out_s) - float(self.source_in_s))

    @property
    def output_duration_s(self) -> float:
        return output_duration_s(self.source_duration_s, self.speed)


def normalize_playback_speed(value: object) -> float:
    """Return 1, 0.5, or 0.25. Anything else, including speeds above 1, raises."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("speed must be 1, 0.5, or 0.25")
    number = float(value)
    for allowed in ALLOWED_SPEEDS:
        if abs(number - allowed) <= 0.001:
            return allowed
    raise ValueError("speed must be 1, 0.5, or 0.25")


def coerce_playback_speed(value: object) -> float:
    """Stored speeds outside the allowed set behave as 1×."""
    if value is None:
        return 1.0
    try:
        return normalize_playback_speed(value)
    except ValueError:
        return 1.0


def output_duration_s(source_duration_s: float, speed: float) -> float:
    """Story seconds for a source span. Independent of the source frame rate."""
    factor = coerce_playback_speed(speed)
    return max(0.0, float(source_duration_s)) / factor


def timeline_offset_s(source_offset_s: float, speed: float) -> float:
    """Map a source offset inside a clip to Story time. Preview uses this."""
    return output_duration_s(source_offset_s, speed)


def source_offset_s(timeline_offset_s: float, speed: float) -> float:
    """Map Story time inside a clip back to the source. Cut and seek use this."""
    factor = coerce_playback_speed(speed)
    return max(0.0, float(timeline_offset_s)) * factor


def source_span_s(
    *,
    source_start_s: float,
    source_end_s: float | None,
    output_duration_s: float,
    speed: float,
) -> tuple[float, float, float]:
    """Return source start, source end, and output duration for one clip."""
    factor = coerce_playback_speed(speed)
    start = max(0.0, float(source_start_s))
    if source_end_s is not None:
        end = max(start, float(source_end_s))
        source_dur = end - start
    else:
        source_dur = max(0.0, float(output_duration_s) * factor)
        end = start + source_dur
    return start, end, source_dur / factor


def ffmpeg_slow_prefix(source_start_s: float, source_end_s: float) -> str:
    """Trim to the source range and restart timestamps at zero.

    Runs before grade, framing, and scale so those filters see the section.
    """
    return (
        f"trim=start={float(source_start_s):.6f}:end={float(source_end_s):.6f},"
        "setpts=PTS-STARTPTS"
    )


def ffmpeg_slow_stretch(speed: float) -> str:
    """Hold frames so the section lasts ``1/speed`` times as long.

    Applied after ``fps`` so a 10 fps source is duplicated to the export
    frame rate first, then stretched. No new frames are invented.
    """
    factor = 1.0 / normalize_playback_speed(speed)
    return f"setpts={factor:.1f}*PTS"


def plan_speed_segments(
    rang: SourceRange,
    *,
    current_speed: float,
    range_in_s: float | None,
    range_out_s: float | None,
    speed: float,
) -> tuple[list[SpeedSegment], int]:
    """Split ``rang`` into constant-speed pieces.

    ``range_in_s`` / ``range_out_s`` are seconds from the start of ``rang``
    (the clip's own source range, including an existing cut). ``None`` means
    the whole clip. The returned index is the piece that receives ``speed``.
    """
    current = coerce_playback_speed(current_speed)
    target = normalize_playback_speed(speed)
    dur = rang.duration_s
    if range_in_s is None and range_out_s is None:
        start_local = 0.0
        end_local = dur
    else:
        if range_in_s is None or range_out_s is None:
            raise ValueError("speed range needs both start and end")
        start_local = float(range_in_s)
        end_local = float(range_out_s)
    if start_local < -_EDGE_EPS_S or end_local > dur + _EDGE_EPS_S:
        raise ValueError("speed range must stay inside the clip")
    start_local = min(max(0.0, start_local), dur)
    end_local = min(max(0.0, end_local), dur)
    if start_local <= _EDGE_EPS_S:
        start_local = 0.0
    if dur - end_local <= _EDGE_EPS_S:
        end_local = dur
    if end_local <= start_local:
        raise ValueError("speed range must stay inside the clip")
    if start_local == 0.0 and end_local == dur:
        return [SpeedSegment(rang.source_in_s, rang.source_out_s, target)], 0
    if end_local - start_local < MIN_SEGMENT_S:
        raise ValueError("speed range is too short")
    if 0.0 < start_local < MIN_SEGMENT_S or 0.0 < (dur - end_local) < MIN_SEGMENT_S:
        raise ValueError("speed range must leave a usable section on each side")

    abs_start = rang.source_in_s + start_local
    abs_end = rang.source_in_s + end_local
    segments: list[SpeedSegment] = []
    if start_local >= MIN_SEGMENT_S:
        segments.append(SpeedSegment(rang.source_in_s, abs_start, current))
    segments.append(SpeedSegment(abs_start, abs_end, target))
    if rang.source_out_s - abs_end >= MIN_SEGMENT_S:
        segments.append(SpeedSegment(abs_end, rang.source_out_s, current))
    if len(segments) > 1 and all(
        abs(seg.speed - segments[0].speed) <= 0.001 for seg in segments
    ):
        return [SpeedSegment(rang.source_in_s, rang.source_out_s, segments[0].speed)], 0
    selected = 0
    for index, seg in enumerate(segments):
        if abs(seg.source_in_s - abs_start) <= 1e-6 and abs(seg.speed - target) <= 0.001:
            selected = index
            break
    return segments, selected
