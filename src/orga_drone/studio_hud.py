"""Optional Studio telemetry HUD for one video clip (Issue #107).

The preset is a single on/off switch stored in ``studio_clips.effect_settings``
under ``hud``. It reads the sibling DJI SRT with the existing parser. Only
fields that parser already records can appear. Speed, home distance, heading,
battery, signal, and flight mode are not in that parser, so they stay off.

Altitude is hidden when the nearest cue is more than ``HOLD_S`` away. The
preview and the MP4 use the same 0.5 s windows, so a gap is blank on both.
Elapsed time is the source clock (``HH:MM:SS``), including a Cut in-point.
Source files are never modified. This is not a goggles picture and not tracking.
"""

from __future__ import annotations

import bisect
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from orga_drone.parse import parse_srt

HOLD_S = 1.0
STEP_S = 0.5
FILTER_INLINE_LIMIT = 24000

_FADE_PREFIX = re.compile(r"\]((?:fade=t=(?:in|out):[^,\[]+,)+)$")


class HudGraphError(Exception):
    """The segment graph has no place to put the HUD without dropping fades."""


@dataclass(frozen=True)
class HudCue:
    """One timed SRT sample. ``rel_alt`` is missing when the cue has no altitude."""

    t: float
    rel_alt: float | None


@dataclass(frozen=True)
class HudInterval:
    """Source-time window that shows one altitude, in metres to 0.1 m."""

    start_s: float
    end_s: float
    altitude_m: float

    def as_dict(self) -> dict[str, float]:
        return {
            "start": self.start_s,
            "end": self.end_s,
            "alt": self.altitude_m,
        }


def empty_hud_state() -> dict[str, object]:
    """Inspector payload when this clip cannot show a HUD."""
    return {
        "enabled": False,
        "available": False,
        "elapsed": "unavailable",
        "altitude": "unavailable",
        "speed": "unavailable",
        "home_distance": "unavailable",
        "intervals": [],
    }


def sibling_srt(media_path: Path) -> Path | None:
    """DJI writes ``.SRT`` or ``.srt`` next to the video. Nothing else is read."""
    for suffix in (".SRT", ".srt"):
        candidate = media_path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def cues_from_srt(path: Path) -> tuple[HudCue, ...]:
    """Every timed GPS cue. The map track stays downsampled; the HUD does not."""
    _start, track, _duration = parse_srt(path, max_track_points=1_000_000)
    cues: list[HudCue] = []
    for point in track:
        if point.t is None:
            continue
        cues.append(HudCue(t=float(point.t), rel_alt=point.rel_alt))
    cues.sort(key=lambda cue: cue.t)
    return tuple(cues)


def format_elapsed(source_s: float) -> str:
    """Source clock as ``HH:MM:SS``. Matches the export ``drawtext`` expression."""
    total = max(0, int(math.floor(float(source_s) + 1e-6)))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def source_window(
    *,
    source_start_s: float | None,
    source_end_s: float | None,
    media_duration_s: float | None,
    fallback_duration_s: float | None,
) -> tuple[float, float]:
    """Clip range on the source clock, so a Cut does not restart elapsed time."""
    start = float(source_start_s) if source_start_s is not None else 0.0
    if start < 0:
        start = 0.0
    if source_end_s is not None:
        end = float(source_end_s)
    elif media_duration_s is not None and float(media_duration_s) > start:
        end = float(media_duration_s)
    else:
        end = start + max(0.0, float(fallback_duration_s or 0.0))
    if end < start:
        end = start
    return start, end


def _altitude_index(
    cues: Sequence[HudCue],
) -> tuple[list[float], list[float]]:
    times: list[float] = []
    alts: list[float] = []
    for cue in cues:
        if cue.rel_alt is None:
            continue
        times.append(float(cue.t))
        alts.append(float(cue.rel_alt))
    return times, alts


def altitude_at(cues: Sequence[HudCue], source_s: float) -> float | None:
    """Relative altitude at ``source_s``, or None across a telemetry gap.

    The nearest cue wins. A cue farther than ``HOLD_S`` is not reused, so a
    missing interval stays blank instead of inventing a value.
    """
    times, alts = _altitude_index(cues)
    if not times:
        return None
    idx = bisect.bisect_left(times, float(source_s))
    best_i: int | None = None
    best_d: float | None = None
    for candidate in (idx - 1, idx):
        if candidate < 0 or candidate >= len(times):
            continue
        dist = abs(times[candidate] - float(source_s))
        if best_d is None or dist < best_d:
            best_d = dist
            best_i = candidate
    if best_i is None or best_d is None or best_d > HOLD_S + 1e-9:
        return None
    return round(alts[best_i], 1)


def altitude_intervals(
    cues: Sequence[HudCue],
    start_s: float,
    end_s: float,
) -> tuple[HudInterval, ...]:
    """Step the source range and merge equal altitudes.

    Windows are ``STEP_S`` wide, including the clip end. Preview and export
    both draw these windows, so they agree within one step.
    """
    start = float(start_s)
    end = float(end_s)
    if end <= start:
        return ()
    if not any(cue.rel_alt is not None for cue in cues):
        return ()
    count = int(math.floor((end - start) / STEP_S + 1e-9))
    samples: list[float] = [round(start + i * STEP_S, 4) for i in range(count + 1)]
    if samples[-1] < end - 1e-4:
        samples.append(round(end, 4))
    else:
        samples[-1] = round(end, 4)
    values = [altitude_at(cues, sample) for sample in samples]
    found: list[HudInterval] = []
    index = 0
    last = len(samples) - 1
    while index < last:
        altitude = values[index]
        nxt = index + 1
        if altitude is None:
            index = nxt
            continue
        while nxt < last and values[nxt] == altitude:
            nxt += 1
        found.append(
            HudInterval(
                start_s=samples[index],
                end_s=samples[nxt],
                altitude_m=float(altitude),
            )
        )
        index = nxt
    return tuple(found)


def hud_reading(
    intervals: Sequence[HudInterval],
    source_s: float,
) -> tuple[str, str | None]:
    """Elapsed text plus altitude text. Altitude is None inside a gap."""
    elapsed = format_elapsed(source_s)
    altitude: str | None = None
    for index, interval in enumerate(intervals):
        is_last = index == len(intervals) - 1
        after_start = float(source_s) >= interval.start_s - 1e-9
        before_end = float(source_s) < interval.end_s - 1e-9 or (
            is_last and float(source_s) <= interval.end_s + 1e-3
        )
        if after_start and before_end:
            altitude = f"{interval.altitude_m:.1f} m"
            break
    return elapsed, altitude


def hud_enabled_from_effect_settings(raw: str | None) -> bool:
    """Only a JSON boolean turns the preset on. Anything else stays off."""
    if raw is None or not str(raw).strip():
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    hud = data.get("hud", {})
    if not isinstance(hud, dict):
        return False
    return hud.get("enabled") is True


def parse_hud_enabled(payload: Mapping[str, object]) -> bool:
    """Replace the preset. Non-booleans raise so filter text cannot be stored."""
    if "enabled" not in payload:
        raise ValueError("JSON body must include enabled")
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    return enabled


def dump_hud(existing: str | None, enabled: bool) -> str:
    """Write ``hud.enabled`` and keep unrelated effect_settings keys."""
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data["hud"] = {"enabled": bool(enabled)}
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def hud_client_state(
    media_path: Path | None,
    *,
    effect_settings: str | None,
    source_start_s: float | None,
    source_end_s: float | None,
    media_duration_s: float | None,
    fallback_duration_s: float | None,
) -> dict[str, object]:
    """Availability plus the altitude windows the preview draws."""
    enabled = hud_enabled_from_effect_settings(effect_settings)
    start, end = source_window(
        source_start_s=source_start_s,
        source_end_s=source_end_s,
        media_duration_s=media_duration_s,
        fallback_duration_s=fallback_duration_s,
    )
    cues: tuple[HudCue, ...] = ()
    if media_path is not None:
        srt = sibling_srt(media_path)
        if srt is not None:
            cues = cues_from_srt(srt)
    available = bool(cues)
    has_altitude = any(cue.rel_alt is not None for cue in cues)
    intervals: list[dict[str, float]] = []
    if available and end > start and has_altitude:
        intervals = [
            item.as_dict() for item in altitude_intervals(cues, start, end)
        ]
    return {
        "enabled": enabled,
        "available": available,
        "elapsed": "available" if available else "unavailable",
        "altitude": "available" if has_altitude else "unavailable",
        "speed": "unavailable",
        "home_distance": "unavailable",
        "intervals": intervals,
    }


def _escape_filter_path(path: Path) -> str:
    text = str(path).replace("\\", "/")
    return text.replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def ffmpeg_hud_chain(
    *,
    fontfile: Path,
    height: int,
    intervals: Sequence[HudInterval],
) -> str:
    """Draw elapsed time for the whole segment and altitude on each window.

    Video segments keep ``-ss`` as an output option, so filter ``t`` is the
    source timestamp. The elapsed expression is that clock. Altitude ``enable``
    windows are the same source times as the preview intervals.
    """
    size = max(16, int(round(int(height) * 0.032)))
    margin = max(12, int(round(int(height) * 0.04)))
    pad = max(4, size // 6)
    font = _escape_filter_path(fontfile)
    common = (
        f"fontfile='{font}':fontsize={size}:fontcolor=white:"
        f"box=1:boxcolor=black@0.55:boxborderw={pad}"
    )
    elapsed_text = (
        "%{eif\\:floor(t/3600)\\:d\\:2}\\:"
        "%{eif\\:mod(floor(t/60)\\,60)\\:d\\:2}\\:"
        "%{eif\\:mod(floor(t)\\,60)\\:d\\:2}"
    )
    parts = [
        f"drawtext={common}:text='{elapsed_text}':x={margin}:y={margin}",
    ]
    line_y = margin + size + max(6, size // 4)
    for interval in intervals:
        parts.append(
            "drawtext="
            f"{common}:text='{interval.altitude_m:.1f} m':x={margin}:y={line_y}:"
            f"enable='between(t\\,{interval.start_s:.4f}\\,{interval.end_s:.4f})'"
        )
    return ",".join(parts)


def insert_hud_chain(graph: str, hud: str) -> str:
    """Put HUD drawtext on the framed picture, before fades.

    Overlay graphs format the frame and then fade. Mask graphs fade and then
    format. Both keep the HUD under the fade so it leaves with the picture.
    """
    if not hud:
        return graph
    marker = "format=yuv420p["
    index = graph.rfind(marker)
    if index < 0:
        raise HudGraphError("segment graph has no framed output")
    head = graph[:index]
    match = _FADE_PREFIX.search(head)
    if match:
        label_end = match.start() + 1
        fades = match.group(1)
        return graph[:label_end] + hud + "," + fades + graph[index:]
    return head + hud + "," + graph[index:]


def video_filter_args(
    body: str,
    *,
    script_path: Path,
    complex_graph: bool,
) -> list[str]:
    """Keep short graphs on the command line. Long HUD chains go to a file."""
    inline = len(body) <= FILTER_INLINE_LIMIT
    if not inline:
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(body, encoding="utf-8")
    if complex_graph:
        if inline:
            return ["-filter_complex", body, "-map", "[vout]"]
        return ["-filter_complex_script", str(script_path), "-map", "[vout]"]
    if inline:
        return ["-vf", body]
    return ["-filter_script:v", str(script_path)]
