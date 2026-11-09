"""Pure Timelapse helpers that reuse ADR 0034 flat speed ramps."""

from __future__ import annotations

import math
from dataclasses import dataclass

from orga_drone.studio_speed_ramp import MAX_SPEED, MIN_SPEED

EXPORT_FPS = 30
MIN_TIMELAPSE_SPEED = 1.0
MAX_TIMELAPSE_SPEED = MAX_SPEED
MIN_OUTPUT_FRAMES = 1
MIN_SOURCE_SPAN_S = 0.05


@dataclass(frozen=True)
class TimelapseDraft:
    source_span_s: float
    speed: float
    target_duration_s: float
    output_frames: int

    @property
    def output_duration_s(self) -> float:
        return self.output_frames / EXPORT_FPS


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def allowed_target_range(source_span_s: float) -> tuple[float, float]:
    span = _finite(source_span_s, label="source span")
    if span < MIN_SOURCE_SPAN_S:
        raise ValueError("source span is too short for timelapse")
    slowest = span / MAX_TIMELAPSE_SPEED
    fastest = span / MIN_TIMELAPSE_SPEED
    min_target = max(slowest, MIN_OUTPUT_FRAMES / EXPORT_FPS)
    if min_target > fastest + 1e-12:
        raise ValueError("source span is too short for timelapse")
    return min_target, fastest


def draft_from_target(source_span_s: float, target_duration_s: object) -> TimelapseDraft:
    span = _finite(source_span_s, label="source span")
    target = _finite(target_duration_s, label="target duration")
    if target <= 0:
        raise ValueError("target duration must be greater than zero")
    lo, hi = allowed_target_range(span)
    if target + 1e-9 < lo or target - 1e-9 > hi:
        raise ValueError(
            f"target duration requires speed outside {MIN_TIMELAPSE_SPEED:g}×–{MAX_TIMELAPSE_SPEED:g}×"
        )
    speed = span / target
    frames = max(MIN_OUTPUT_FRAMES, int(target * EXPORT_FPS + 0.5 + 1e-8))
    return TimelapseDraft(span, speed, target, frames)


def draft_from_speed(source_span_s: float, speed: object) -> TimelapseDraft:
    span = _finite(source_span_s, label="source span")
    rate = _finite(speed, label="speed")
    if not MIN_TIMELAPSE_SPEED <= rate <= MAX_TIMELAPSE_SPEED:
        raise ValueError(
            f"speed must stay between {MIN_TIMELAPSE_SPEED:g} and {MAX_TIMELAPSE_SPEED:g}"
        )
    if span < MIN_SOURCE_SPAN_S:
        raise ValueError("source span is too short for timelapse")
    target = span / rate
    if target * EXPORT_FPS + 1e-9 < MIN_OUTPUT_FRAMES:
        raise ValueError("result is shorter than one export frame")
    frames = max(MIN_OUTPUT_FRAMES, int(target * EXPORT_FPS + 0.5 + 1e-8))
    return TimelapseDraft(span, rate, target, frames)


def flat_timelapse_payload(source_in_s: float, source_out_s: float, speed: float) -> dict[str, object]:
    start = _finite(source_in_s, label="source in")
    end = _finite(source_out_s, label="source out")
    rate = _finite(speed, label="speed")
    if end - start < MIN_SOURCE_SPAN_S:
        raise ValueError("source span is too short for timelapse")
    if not MIN_SPEED <= rate <= MAX_SPEED:
        raise ValueError(f"speed ramp must stay between {MIN_SPEED:g} and {MAX_SPEED:g}")
    if abs(rate - 1.0) <= 1e-9:
        raise ValueError("use ramp removal for 1× instead of a muted flat ramp")
    return {
        "v": 1,
        "interp": "reciprocal_smoothstep",
        "points": [
            {"source_s": start, "speed": rate},
            {"source_s": end, "speed": rate},
        ],
    }


def timelapse_conflict(
    *,
    has_ramp: bool,
    section_repeats: int,
    forward_loop: bool,
) -> str | None:
    if has_ramp:
        return "Remove the speed ramp before applying Timelapse."
    if int(section_repeats) > 1:
        return "Turn off section repeat before applying Timelapse."
    if forward_loop:
        return "Turn off Repeat to soundtrack before applying Timelapse."
    return None

