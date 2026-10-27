"""Detach one video clip's embedded audio onto its own bar.

The picture and the source file stay. The detached range starts as the clip's
current in/out. Trimming that bar changes only the audio range. Removing the
bar leaves the video. Slow motion keeps using silence, as it does today.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

DETACHED_KEY = "detached_audio"
_MIN_SPAN_S = 0.05


@dataclass(frozen=True)
class DetachedAudio:
    """Source-time range of a clip's split audio. Inactive means no bar."""

    active: bool = False
    source_in_s: float = 0.0
    source_out_s: float = 0.0

    @property
    def is_heard(self) -> bool:
        return self.active and (self.source_out_s - self.source_in_s) >= _MIN_SPAN_S

    def as_dict(self) -> dict[str, object]:
        return {
            "active": self.active,
            "source_in_s": self.source_in_s,
            "source_out_s": self.source_out_s,
        }


def detached_audio_from_effect_settings(raw: str | None) -> DetachedAudio:
    """Missing JSON is no split. The embedded track stays as it was."""
    if raw is None or not str(raw).strip():
        return DetachedAudio()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return DetachedAudio()
    if not isinstance(data, dict):
        return DetachedAudio()
    body = data.get(DETACHED_KEY)
    if not isinstance(body, dict):
        return DetachedAudio()
    active = body.get("active") is True
    start = _read_time(body.get("source_in_s"))
    end = _read_time(body.get("source_out_s"))
    if end < start:
        start, end = end, start
    return DetachedAudio(active=active, source_in_s=start, source_out_s=end)


def dump_detached_audio(existing: str | None, audio: DetachedAudio | None) -> str:
    """Write or remove the split and keep unrelated effect_settings keys."""
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    if audio is None or not audio.active:
        data.pop(DETACHED_KEY, None)
    else:
        data[DETACHED_KEY] = audio.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def parse_detached_trim(payload: Mapping[str, object]) -> tuple[float, float]:
    """New audio in/out. Does not describe the picture range."""
    start = _parse_time(payload.get("source_in_s"), "source_in_s")
    end = _parse_time(payload.get("source_out_s"), "source_out_s")
    if end - start < _MIN_SPAN_S:
        raise ValueError("audio range is too short")
    return start, end


def detached_audio_af(
    *,
    video_start_s: float,
    video_duration_s: float,
    audio_in_s: float,
    audio_out_s: float,
) -> str:
    """One ``-af`` chain. The embedded track is not mapped a second time.

    Times are source seconds. After ``-ss`` the filter clock starts at the
    picture's in-point. The chain trims the split range, places it once, and
    pads the rest of the picture with silence.
    """
    video_start = max(0.0, float(video_start_s))
    duration = max(0.05, float(video_duration_s))
    rel_in = max(0.0, float(audio_in_s) - video_start)
    rel_out = min(duration, max(rel_in, float(audio_out_s) - video_start))
    if rel_out - rel_in < 0.01:
        rel_in = 0.0
        rel_out = 0.02
    delay_ms = max(0, int(round(rel_in * 1000)))
    return (
        f"atrim=start={rel_in:.3f}:end={rel_out:.3f},"
        "asetpts=PTS-STARTPTS,"
        f"adelay={delay_ms}|{delay_ms},"
        f"apad=whole_dur={duration:.3f},"
        f"atrim=0:{duration:.3f}"
    )


def export_audio_args(
    *,
    video_start_s: float,
    video_duration_s: float,
    detached: DetachedAudio | None,
    slow: bool,
) -> list[str]:
    """``-af`` for a 1× split. Slow motion stays on the caller's silence."""
    if slow or detached is None or not detached.is_heard:
        return []
    return [
        "-af",
        detached_audio_af(
            video_start_s=video_start_s,
            video_duration_s=video_duration_s,
            audio_in_s=detached.source_in_s,
            audio_out_s=detached.source_out_s,
        ),
    ]


def _read_time(value: object) -> float:
    try:
        return _parse_time(value, "time")
    except ValueError:
        return 0.0


def _parse_time(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a time in seconds")
    number = float(value)
    if number < 0 or number > 86_400:
        raise ValueError(f"{key} must be a time in seconds")
    return round(number, 4)
