"""Timed bars on the single Story Effekt lane.

Zoom, blur, pixelate, and slow motion each occupy one bar inside a video
clip. Outside that bar the effect is off. Ranges live in ``effect_settings``.
Photos have no bars. Times are seconds from the clip's source in-point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from orga_drone.studio_frame import frame_from_effect_settings
from orga_drone.studio_mask import Mask, masks_from_effect_settings
from orga_drone.studio_speed import coerce_playback_speed

ZOOM_BAR_KEY = "zoom_bar"
SLOW_BAR_KEY = "slow_bar"
_MIN_SPAN_S = 0.05


@dataclass(frozen=True)
class TimedBar:
    start_s: float
    end_s: float
    zoom: float = 1.0
    speed: float = 1.0
    kind: str = ""
    mask_id: str = ""

    def covers(self, source_offset_s: float) -> bool:
        offset = float(source_offset_s)
        return self.start_s - 1e-3 <= offset <= self.end_s + 1e-3


def _load(raw: str | None) -> dict:
    if raw is None or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _span(value: object) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        start = float(value.get("start_s", 0))
        end = float(value.get("end_s", 0))
    except (TypeError, ValueError):
        return None
    if end < start:
        start, end = end, start
    if end - start < _MIN_SPAN_S:
        return None
    return round(start, 4), round(end, 4)


def zoom_bar(raw: str | None, source_duration_s: float) -> TimedBar | None:
    """A zoom above 1× is a bar. A missing range covers the whole clip."""
    frame = frame_from_effect_settings(raw)
    zoom = max(frame.zoom_start, frame.zoom_end)
    if zoom <= 1.001:
        return None
    duration = max(0.0, float(source_duration_s))
    stored = _span(_load(raw).get(ZOOM_BAR_KEY))
    start, end = stored if stored is not None else (0.0, max(duration, _MIN_SPAN_S))
    end = min(end, duration) if duration > 0 else end
    start = min(start, end)
    if end - start < _MIN_SPAN_S and duration >= _MIN_SPAN_S:
        start, end = 0.0, duration
    return TimedBar(start_s=start, end_s=end, zoom=zoom, kind="zoom")


def zoom_factor_at(raw: str | None, source_offset_s: float, source_duration_s: float) -> float:
    """1 outside the zoom bar. Inside, the stored zoom (1×–3×)."""
    bar = zoom_bar(raw, source_duration_s)
    if bar is None or not bar.covers(source_offset_s):
        return 1.0
    return bar.zoom


def mask_covers(mask: Mask, source_offset_s: float, source_duration_s: float) -> bool:
    """A mask with no range covers the clip. A bar does not."""
    if mask.start_s is None or mask.end_s is None:
        return True
    duration = max(0.0, float(source_duration_s))
    start = max(0.0, mask.start_s)
    end = mask.end_s if duration <= 0 else min(duration, mask.end_s)
    return start - 1e-3 <= float(source_offset_s) <= end + 1e-3


def slow_bar(raw: str | None, source_duration_s: float, playback_speed: float) -> TimedBar | None:
    """0.5× or 0.25× only. A clip speed with no bar covers the whole clip."""
    duration = max(0.0, float(source_duration_s))
    stored = _load(raw).get(SLOW_BAR_KEY)
    span = _span(stored)
    if span is not None and isinstance(stored, dict):
        try:
            speed = coerce_playback_speed(stored.get("speed", 1))
        except (TypeError, ValueError):
            speed = 1.0
        if speed >= 0.999:
            return None
        return TimedBar(start_s=span[0], end_s=span[1], speed=speed, kind="slow")
    speed = coerce_playback_speed(playback_speed)
    if speed >= 0.999 or duration < _MIN_SPAN_S:
        return None
    return TimedBar(start_s=0.0, end_s=duration, speed=speed, kind="slow")


def speed_at(
    raw: str | None,
    source_offset_s: float,
    source_duration_s: float,
    playback_speed: float,
) -> float:
    """1× outside a slow bar. Inside, only 0.5× or 0.25×."""
    bar = slow_bar(raw, source_duration_s, playback_speed)
    if bar is None or not bar.covers(source_offset_s):
        return 1.0
    return bar.speed


def output_seconds(source_duration_s: float, playback_speed: float, raw: str | None) -> float:
    """Story length. A partial slow bar lengthens only that range."""
    duration = max(0.0, float(source_duration_s))
    bar = slow_bar(raw, duration, playback_speed)
    if bar is None:
        return duration / max(coerce_playback_speed(playback_speed), 0.25)
    before = max(0.0, min(duration, bar.start_s))
    end = max(before, min(duration, bar.end_s))
    slowed = (end - before) / bar.speed
    after = max(0.0, duration - end)
    return before + slowed + after


def clear_zoom(raw: str | None) -> str:
    """Removing the zoom bar returns that clip to 1×."""
    from orga_drone.studio_frame import FrameTransform, dump_frame

    data = _load(raw)
    data.pop(ZOOM_BAR_KEY, None)
    text = json.dumps(data, separators=(",", ":"), sort_keys=True)
    return dump_frame(text, FrameTransform())


def clear_slow(raw: str | None) -> str:
    """Removing the slow bar returns that range to 1×."""
    data = _load(raw)
    data.pop(SLOW_BAR_KEY, None)
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def write_zoom_bar(raw: str | None, start_s: float, end_s: float) -> str:
    data = _load(raw)
    data[ZOOM_BAR_KEY] = {"start_s": round(float(start_s), 4), "end_s": round(float(end_s), 4)}
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def write_slow_bar(raw: str | None, start_s: float, end_s: float, speed: float) -> str:
    factor = coerce_playback_speed(speed)
    if factor >= 0.999:
        raise ValueError("speed must be 0.5 or 0.25")
    data = _load(raw)
    data[SLOW_BAR_KEY] = {
        "start_s": round(float(start_s), 4),
        "end_s": round(float(end_s), 4),
        "speed": factor,
    }
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def effect_bars(raw: str | None, source_duration_s: float, playback_speed: float) -> list[TimedBar]:
    """Bars for one video clip. Photos pass a zero duration and get none."""
    bars: list[TimedBar] = []
    zoom = zoom_bar(raw, source_duration_s)
    if zoom is not None:
        bars.append(zoom)
    for mask in masks_from_effect_settings(raw):
        if mask.start_s is None or mask.end_s is None:
            start, end = 0.0, max(float(source_duration_s), _MIN_SPAN_S)
        else:
            start, end = mask.start_s, mask.end_s
        bars.append(
            TimedBar(
                start_s=start,
                end_s=end,
                kind=mask.effect,
                mask_id=mask.id,
            )
        )
    slow = slow_bar(raw, source_duration_s, playback_speed)
    if slow is not None:
        bars.append(slow)
    return bars


def stored_lane(raw: str | None) -> dict[str, object]:
    """The saved zoom and slow bars, or null when the clip has none."""
    data = _load(raw)
    zoom = data.get(ZOOM_BAR_KEY)
    slow = data.get(SLOW_BAR_KEY)
    return {
        "zoom_bar": zoom if isinstance(zoom, dict) else None,
        "slow_bar": slow if isinstance(slow, dict) else None,
    }


def preview_audio_source(
    *,
    has_proxy: bool,
    stream_url: str,
    playback_speed: float,
) -> str:
    """Original file at 1×. A proxy picture is silent, so preview must not use it.

    An empty string means the slowed section stays muted.
    """
    if coerce_playback_speed(playback_speed) < 0.999:
        return ""
    if has_proxy:
        return stream_url
    return stream_url
