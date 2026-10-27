"""Place one video clip's embedded audio on its own bar.

The picture and the source file stay. Until the bar is edited, the sound
follows the picture in/out. A drag stores a separate range: ``place_s`` is
how far into the clip the sound starts, and the source in/out is only the
audio. Slow motion keeps using silence, as it does today.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

DETACHED_KEY = "detached_audio"
_MIN_SPAN_S = 0.05


@dataclass(frozen=True)
class DetachedAudio:
    """Source-time range of a clip's own audio bar. Inactive follows the picture.

    ``place_s`` is story seconds from the clip start to the first audible sample.
    """

    active: bool = False
    source_in_s: float = 0.0
    source_out_s: float = 0.0
    place_s: float = 0.0

    @property
    def is_heard(self) -> bool:
        return self.active and (self.source_out_s - self.source_in_s) >= _MIN_SPAN_S

    def as_dict(self) -> dict[str, object]:
        return {
            "active": self.active,
            "source_in_s": self.source_in_s,
            "source_out_s": self.source_out_s,
            "place_s": self.place_s,
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
    return DetachedAudio(
        active=active,
        source_in_s=start,
        source_out_s=end,
        place_s=_read_place(body.get("place_s", 0.0)),
    )


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


def parse_detached_edit(payload: Mapping[str, object]) -> tuple[float, float, float | None]:
    """Audio in/out plus an optional story offset. Picture keys are ignored."""
    start, end = parse_detached_trim(payload)
    if "place_s" not in payload:
        return start, end, None
    return start, end, _parse_place(payload.get("place_s"))


def detached_audio_af(
    *,
    video_start_s: float,
    video_duration_s: float,
    audio_in_s: float,
    audio_out_s: float,
    place_s: float = 0.0,
) -> str:
    """One ``-af`` chain. The embedded track is not mapped a second time.

    Times are source seconds, except ``place_s`` which is story seconds from
    the clip start. After ``-ss`` the filter clock starts at the picture's
    in-point. The chain keeps the audio range, shifts it by ``place_s``, and
    pads the rest of the picture with silence.
    """
    video_start = max(0.0, float(video_start_s))
    duration = max(0.05, float(video_duration_s))
    play_in = float(audio_in_s)
    play_out = float(audio_out_s)
    story_in = float(place_s)
    if story_in < 0:
        play_in += -story_in
        story_in = 0.0
    if play_in < video_start:
        story_in += video_start - play_in
        play_in = video_start
    play_out = min(play_out, video_start + duration)
    if play_out - play_in < 0.01 or story_in >= duration - 0.01:
        return (
            "atrim=0:0.020,asetpts=PTS-STARTPTS,"
            f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f},volume=0"
        )
    rel_in = play_in - video_start
    rel_out = play_out - video_start
    delay_ms = max(0, int(round(story_in * 1000)))
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
            place_s=detached.place_s,
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


def _read_place(value: object) -> float:
    try:
        return _parse_place(value)
    except ValueError:
        return 0.0


def _parse_place(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("place_s must be a time in seconds")
    number = float(value)
    if number < -86_400 or number > 86_400:
        raise ValueError("place_s must be a time in seconds")
    return round(number, 4)
