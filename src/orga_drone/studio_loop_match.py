"""Experimental local seam search for a repeated Studio section.

The search compares small RGB frames near the user's in and out points.
It does not call a cloud service, and it does not invent frames. A weak
match keeps the user's range and a hard cut.
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

MATCH_WINDOW_S = 3.0
MATCH_FPS = 4
MATCH_WIDTH = 48
MATCH_HEIGHT = 27
MATCH_CROSSFADE_S = 0.5
_MIN_WINDOW_S = 0.2
_MIN_RETAINED_S = 0.5
_RETAINED_FRACTION = 0.5
# Mean channel error, 0..1. Above this, the pair is not a usable seam.
_REJECT_SCORE = 0.34
# A clean pair stays a hard cut so two similar frames are not ghosted.
_CLEAN_SCORE = 0.10
_SHIFT_GAIN = 0.85

LOOP_MATCH_KEY = "loop_match"


@dataclass(frozen=True)
class SeamChoice:
    """The seam the search is willing to use."""

    applied: bool
    source_in_s: float
    source_out_s: float
    confidence: str
    crossfade_s: float
    score: float


def loop_match_key(path: Path, source_in_s: float, source_out_s: float) -> str | None:
    """Identity of one analysis. A new trim or a changed file misses the cache."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (
        f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|"
        f"{float(source_in_s):.3f}|{float(source_out_s):.3f}"
    )


def match_record(raw: str | None) -> dict[str, object] | None:
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    record = parsed.get(LOOP_MATCH_KEY)
    return record if isinstance(record, dict) else None


def dump_loop_match(existing: str | None, choice: SeamChoice, key: str) -> str:
    """Store the last search. The user's in/out columns are not rewritten."""
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data[LOOP_MATCH_KEY] = {
        "key": key,
        "confidence": choice.confidence,
        "source_in_s": round(float(choice.source_in_s), 3),
        "source_out_s": round(float(choice.source_out_s), 3),
        "crossfade_s": round(float(choice.crossfade_s), 3),
        "score": round(float(choice.score), 4),
    }
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def match_is_applied(
    raw: str | None,
    *,
    source_in_s: float | None,
    source_out_s: float | None,
    path: Path | None,
) -> bool:
    """True when the stored seam still belongs to this file and trim."""
    record = match_record(raw)
    if record is None or record.get("confidence") != "ok":
        return False
    if path is None or source_in_s is None or source_out_s is None:
        return False
    key = loop_match_key(path, float(source_in_s), float(source_out_s))
    return bool(key) and record.get("key") == key


def effective_source_bounds(
    raw: str | None,
    *,
    source_in_s: float | None,
    source_out_s: float | None,
    path: Path | None,
) -> tuple[float | None, float | None]:
    """Playback range. The stored trim is used when the search does not apply."""
    if not match_is_applied(
        raw, source_in_s=source_in_s, source_out_s=source_out_s, path=path
    ):
        return source_in_s, source_out_s
    record = match_record(raw) or {}
    try:
        start = float(record["source_in_s"])  # type: ignore[arg-type]
        end = float(record["source_out_s"])  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError):
        return source_in_s, source_out_s
    if end - start < _MIN_RETAINED_S:
        return source_in_s, source_out_s
    return start, end


def choose_seam(
    *,
    user_in_s: float,
    user_out_s: float,
    start_frames: list[tuple[float, bytes]],
    end_frames: list[tuple[float, bytes]],
    width: int = MATCH_WIDTH,
    height: int = MATCH_HEIGHT,
) -> SeamChoice:
    """Pick a seam inside the sampled windows, or keep the user's range.

    Pairs are scored on RGB and on a simple edge picture. Opposing
    left/right motion adds a penalty. Brightness alone does not decide.
    """
    user_in = float(user_in_s)
    user_out = float(user_out_s)
    cycle = user_out - user_in
    kept = SeamChoice(
        applied=False,
        source_in_s=user_in,
        source_out_s=user_out,
        confidence="low",
        crossfade_s=0.0,
        score=1.0,
    )
    if cycle < _MIN_RETAINED_S * 2 or not start_frames or not end_frames:
        return kept
    minimum = max(_MIN_RETAINED_S, cycle * _RETAINED_FRACTION)
    frame_bytes = width * height * 3
    original: tuple[float, float, float] | None = None
    best: tuple[float, float, float, float] | None = None
    for start_t, start in start_frames:
        if len(start) != frame_bytes:
            continue
        start_motion = _motion_sign(start_frames, start_t, width, height)
        for end_t, end in end_frames:
            if len(end) != frame_bytes or end_t - start_t < minimum - 1e-6:
                continue
            score = _pair_score(start, end, width, height)
            end_motion = _motion_sign(end_frames, end_t, width, height)
            if start_motion and end_motion and start_motion != end_motion:
                score += 0.35
            shift = abs(start_t - user_in) + abs(user_out - end_t)
            if original is None or shift < original[0]:
                original = (shift, score, start_t)
            if best is None or score < best[0] - 1e-9 or (
                abs(score - best[0]) <= 1e-9 and shift < best[1]
            ):
                best = (score, shift, start_t, end_t)
    if best is None or original is None:
        return kept
    best_score, best_shift, best_in, best_out = best
    original_score = original[1]
    improved = best_shift > 0.05 and best_score <= original_score * _SHIFT_GAIN
    usable = best_score < _REJECT_SCORE and (
        improved or original_score < _REJECT_SCORE
    )
    if not usable:
        return SeamChoice(
            applied=False,
            source_in_s=user_in,
            source_out_s=user_out,
            confidence="low",
            crossfade_s=0.0,
            score=best_score,
        )
    if not improved:
        best_in, best_out = user_in, user_out
    fade = MATCH_CROSSFADE_S if best_score >= _CLEAN_SCORE else 0.0
    return SeamChoice(
        applied=True,
        source_in_s=best_in,
        source_out_s=best_out,
        confidence="ok",
        crossfade_s=fade,
        score=best_score,
    )


def analyze_loop_seam(
    path: Path,
    source_in_s: float,
    source_out_s: float,
    *,
    cancel_event: threading.Event | None = None,
) -> SeamChoice:
    """Sample the ends of ``path`` and choose a seam. A cancel keeps the range."""
    user_in = max(0.0, float(source_in_s))
    user_out = float(source_out_s)
    cycle = user_out - user_in
    window = min(MATCH_WINDOW_S, cycle * 0.5 - 0.05)
    if window < _MIN_WINDOW_S or cancel_event is not None and cancel_event.is_set():
        return choose_seam(
            user_in_s=user_in,
            user_out_s=user_out,
            start_frames=[],
            end_frames=[],
        )
    start_frames = _read_window(path, user_in, window, cancel_event=cancel_event)
    end_frames = _read_window(
        path, max(user_in, user_out - window), window, cancel_event=cancel_event
    )
    return choose_seam(
        user_in_s=user_in,
        user_out_s=user_out,
        start_frames=start_frames,
        end_frames=end_frames,
    )


def _pair_score(start: bytes, end: bytes, width: int, height: int) -> float:
    count = width * height
    rgb = 0
    edges = 0
    edge_count = 0
    for index in range(count):
        offset = index * 3
        rgb += (
            abs(start[offset] - end[offset])
            + abs(start[offset + 1] - end[offset + 1])
            + abs(start[offset + 2] - end[offset + 2])
        )
        column = index % width
        if column + 1 >= width:
            continue
        right = offset + 3
        edges += abs(_grad(start, offset, right) - _grad(end, offset, right))
        edge_count += 1
    rgb_mean = rgb / (count * 3 * 255.0)
    edge_mean = edges / (max(1, edge_count) * 255.0)
    blended = 0.55 * rgb_mean + 0.45 * edge_mean
    # Two flat pictures have no edges to compare, so color has to reject them.
    if edge_mean < 0.04:
        return max(rgb_mean, blended)
    return blended


def _grad(frame: bytes, left: int, right: int) -> int:
    return (
        abs(frame[right] - frame[left])
        + abs(frame[right + 1] - frame[left + 1])
        + abs(frame[right + 2] - frame[left + 2])
    ) // 3


def _motion_sign(
    frames: list[tuple[float, bytes]],
    time_s: float,
    width: int,
    height: int,
) -> int:
    """-1, 0, or 1 from the left/right change since the previous sample."""
    ordered = sorted(frames, key=lambda item: item[0])
    previous: bytes | None = None
    current: bytes | None = None
    for stamp, frame in ordered:
        if stamp < time_s - 1e-6:
            previous = frame
            continue
        current = frame
        break
    if previous is None or current is None or len(previous) != len(current):
        return 0
    left = 0.0
    right = 0.0
    left_n = 0
    right_n = 0
    split = width // 3
    for index in range(width * height):
        offset = index * 3
        delta = (
            current[offset] - previous[offset]
            + current[offset + 1] - previous[offset + 1]
            + current[offset + 2] - previous[offset + 2]
        ) / 3.0
        column = index % width
        if column < split:
            left += delta
            left_n += 1
        elif column >= width - split:
            right += delta
            right_n += 1
    if left_n == 0 or right_n == 0:
        return 0
    direction = (right / right_n) - (left / left_n)
    if abs(direction) < 12.0:
        return 0
    return 1 if direction > 0 else -1


def _read_window(
    path: Path,
    start_s: float,
    duration_s: float,
    *,
    cancel_event: threading.Event | None,
) -> list[tuple[float, bytes]]:
    if cancel_event is not None and cancel_event.is_set():
        return []
    from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs

    ffmpeg = find_ffmpeg()
    if ffmpeg is None or not path.is_file():
        return []
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_s:.3f}",
        "-t",
        f"{duration_s:.3f}",
        "-i",
        str(path),
        "-an",
        "-vf",
        f"fps={MATCH_FPS},scale={MATCH_WIDTH}:{MATCH_HEIGHT}:flags=area,format=rgb24",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            timeout=20,
            **subprocess_no_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if cancel_event is not None and cancel_event.is_set():
        return []
    frame_bytes = MATCH_WIDTH * MATCH_HEIGHT * 3
    if proc.returncode != 0 or len(proc.stdout) < frame_bytes:
        return []
    frames: list[tuple[float, bytes]] = []
    step = 1.0 / MATCH_FPS
    for index in range(0, len(proc.stdout) - frame_bytes + 1, frame_bytes):
        frames.append((start_s + len(frames) * step, proc.stdout[index : index + frame_bytes]))
    return frames
