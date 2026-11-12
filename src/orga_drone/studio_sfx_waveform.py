"""Peak waveforms for local SFX clips (#184).

One ffmpeg decode per file revision is stored under the app data cache.
Timeline drag, resize, and zoom read those peaks; they do not decode again.
Missing, corrupt, and undecodable files return an empty waveform.
"""

from __future__ import annotations

import array
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_below_normal_kwargs

WAVEFORM_VERSION = 1
WAVEFORM_CACHE_DIR = "sfx-waveforms"
_SAMPLE_RATE = 8000
_PEAKS_PER_SECOND = 50
_MIN_BUCKETS = 8
_MAX_BUCKETS = 4000
_MAX_DECODE_S = 180.0


@dataclass(frozen=True)
class SfxWaveform:
    status: str
    duration_s: float
    peaks: tuple[float, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "duration_s": self.duration_s,
            "peaks": list(self.peaks),
        }


def waveform_cache_dir(data_dir: Path) -> Path:
    path = data_dir / WAVEFORM_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_sfx_waveform(path: Path, cache_dir: Path) -> SfxWaveform:
    """Return cached peaks, or decode once. Never raises for a bad file."""
    if not path.is_file():
        return _unavailable()
    cache_path = _cache_path(cache_dir, path)
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached
    decoded = _decode_pcm(path)
    if decoded is None:
        # Keep a negative cache so scrubbing does not spawn ffmpeg again.
        # A missing ffmpeg binary is not cached: a later install can succeed.
        if find_ffmpeg():
            result = _unavailable()
            _write_cache(cache_path, result)
            return result
        return _unavailable()
    pcm, duration_s = decoded
    try:
        peaks = peaks_from_pcm(pcm)
    except ValueError:
        result = _unavailable()
        _write_cache(cache_path, result)
        return result
    result = SfxWaveform(status="ready", duration_s=duration_s, peaks=peaks)
    _write_cache(cache_path, result)
    return result


def peaks_from_pcm(pcm: bytes, *, sample_rate: int = _SAMPLE_RATE) -> tuple[float, ...]:
    """Max-abs peaks for little-endian float32 mono PCM, normalized to 0..1."""
    usable = len(pcm) - (len(pcm) % 4)
    if usable < 4:
        raise ValueError("empty audio")
    samples = array.array("f")
    samples.frombytes(pcm[:usable])
    if sys.byteorder != "little":
        samples.byteswap()
    count = len(samples)
    if count <= 0 or sample_rate <= 0:
        raise ValueError("empty audio")
    duration_s = count / float(sample_rate)
    buckets = int(round(duration_s * _PEAKS_PER_SECOND))
    buckets = max(_MIN_BUCKETS, min(_MAX_BUCKETS, buckets))
    peaks: list[float] = []
    for index in range(buckets):
        start = int(index * count / buckets)
        end = int((index + 1) * count / buckets)
        if end <= start:
            peaks.append(0.0)
            continue
        peak = 0.0
        for sample in samples[start:end]:
            magnitude = abs(float(sample))
            if magnitude > peak:
                peak = magnitude
        peaks.append(peak)
    scale = max(peaks) if peaks else 0.0
    if scale <= 1e-8:
        return tuple(0.0 for _ in peaks)
    return tuple(round(min(1.0, peak / scale), 4) for peak in peaks)


def _unavailable() -> SfxWaveform:
    return SfxWaveform(status="unavailable", duration_s=0.0, peaks=())


def _cache_path(cache_dir: Path, path: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    stat = path.stat()
    digest = hashlib.sha256(
        (
            f"v{WAVEFORM_VERSION}|{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
        ).encode()
    ).hexdigest()
    return cache_dir / f"{digest}.json"


def _read_cache(path: Path) -> SfxWaveform | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("v") != WAVEFORM_VERSION:
        return None
    status = payload.get("status")
    if status == "unavailable":
        return _unavailable()
    if status != "ready":
        return None
    raw_peaks = payload.get("peaks")
    duration = payload.get("duration_s")
    if not isinstance(raw_peaks, list) or not isinstance(duration, (int, float)):
        return None
    if not raw_peaks:
        return None
    peaks: list[float] = []
    for item in raw_peaks:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        peaks.append(float(item))
    return SfxWaveform(status="ready", duration_s=float(duration), peaks=tuple(peaks))


def _write_cache(path: Path, waveform: SfxWaveform) -> None:
    payload = {
        "v": WAVEFORM_VERSION,
        "status": waveform.status,
        "duration_s": waveform.duration_s,
        "peaks": list(waveform.peaks),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return


def _decode_pcm(path: Path) -> tuple[bytes, float] | None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(_SAMPLE_RATE),
                "-t",
                str(_MAX_DECODE_S),
                "-f",
                "f32le",
                "pipe:1",
            ],
            check=False,
            capture_output=True,
            timeout=30,
            **subprocess_below_normal_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    pcm = proc.stdout or b""
    usable = len(pcm) - (len(pcm) % 4)
    if usable < 4:
        return None
    duration_s = (usable / 4) / float(_SAMPLE_RATE)
    if duration_s <= 0:
        return None
    return pcm[:usable], duration_s
