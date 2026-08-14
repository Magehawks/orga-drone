"""Studio music mix helpers (volume/fades/loop). Encoder-only; no DAW UI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

MUSIC_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"})
MUSIC_FADE_MAX_S = 10.0
DEFAULT_MUSIC_VOLUME = 0.8


def validate_music_file_path(raw: str | Path) -> Path:
    """Absolute existing audio file. May live outside library roots."""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("music path must be absolute")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    if resolved.suffix.lower() not in MUSIC_SUFFIXES:
        raise ValueError("unsupported music format")
    return resolved


def clamp_music_volume(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def clamp_fade_s(value: float) -> float:
    return max(0.0, min(MUSIC_FADE_MAX_S, float(value)))


def music_bed_duration_s(*, story_s: float, music_s: float, loop: bool) -> float:
    story = max(0.0, float(story_s))
    music = max(0.0, float(music_s))
    if loop:
        return story
    return min(music, story) if music > 0 else 0.0


def scaled_fades(fade_in_s: float, fade_out_s: float, bed_s: float) -> tuple[float, float]:
    fade_in = max(0.0, float(fade_in_s))
    fade_out = max(0.0, float(fade_out_s))
    bed = max(0.0, float(bed_s))
    total = fade_in + fade_out
    if bed <= 0 or total <= 0:
        return 0.0, 0.0
    if total > bed:
        scale = bed / total
        return fade_in * scale, fade_out * scale
    return fade_in, fade_out


def fade_out_start_s(bed_s: float, fade_out_s: float) -> float:
    return max(0.0, float(bed_s) - float(fade_out_s))


def fade_gain(
    t: float,
    *,
    bed_s: float,
    fade_in_s: float,
    fade_out_s: float,
) -> float:
    """Linear envelope 0..1 at story time ``t`` over the music bed."""
    if t < 0 or t >= bed_s:
        return 0.0
    fade_in, fade_out = scaled_fades(fade_in_s, fade_out_s, bed_s)
    gain = 1.0
    if fade_in > 0 and t < fade_in:
        gain = t / fade_in
    start = fade_out_start_s(bed_s, fade_out)
    if fade_out > 0 and t > start:
        gain = min(gain, max(0.0, (bed_s - t) / fade_out))
    return max(0.0, min(1.0, gain))


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def build_music_amix_filter(
    *,
    volume: float,
    fade_in_s: float,
    fade_out_s: float,
    story_s: float,
    music_s: float,
    loop: bool,
) -> str:
    """ffmpeg ``-filter_complex`` mixing concat audio [0:a] with music [1:a]."""
    bed = music_bed_duration_s(story_s=story_s, music_s=music_s, loop=loop)
    fade_in, fade_out = scaled_fades(fade_in_s, fade_out_s, bed)
    fo_start = fade_out_start_s(bed, fade_out)
    parts = [
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={_fmt(volume)}",
        f"atrim=0:{_fmt(story_s)}",
        "asetpts=PTS-STARTPTS",
    ]
    if fade_in > 0:
        parts.append(f"afade=t=in:st=0:d={_fmt(fade_in)}")
    if fade_out > 0:
        parts.append(f"afade=t=out:st={_fmt(fo_start)}:d={_fmt(fade_out)}")
    music_chain = ",".join(parts) + "[mus]"
    return (
        f"{music_chain};"
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[src];"
        "[src][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    )


def probe_audio_duration_s(path: Path) -> float | None:
    """Return audio duration in seconds, or None if no decodable audio stream."""
    from orga_drone.ffmpeg_bin import find_ffmpeg, find_ffprobe
    ffprobe = find_ffprobe()
    if ffprobe:
        cmd = [
            ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-select_streams",
            "a",
            str(path),
        ]
        try:
            proc = subprocess.run(
                cmd, check=False, capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            proc = None
        if proc is not None and proc.returncode == 0 and proc.stdout:
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                data = None
            if data is not None:
                streams = data.get("streams") or []
                if streams:
                    fmt = data.get("format") or {}
                    raw = fmt.get("duration")
                    try:
                        if raw is not None:
                            return max(0.0, float(raw))
                    except (TypeError, ValueError):
                        pass
                    try:
                        return max(0.0, float(streams[0].get("duration") or 0))
                    except (TypeError, ValueError):
                        return None

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    err = (proc.stderr or "") + (proc.stdout or "")
    if "Audio:" not in err:
        return None
    # Duration: 00:00:03.50
    for line in err.splitlines():
        if "Duration:" in line:
            stamp = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
            parts = stamp.split(":")
            if len(parts) == 3:
                try:
                    hours = float(parts[0])
                    mins = float(parts[1])
                    secs = float(parts[2])
                    return hours * 3600 + mins * 60 + secs
                except ValueError:
                    return None
    return None


def require_readable_music(path: Path) -> float:
    """Validate music file for export. Returns duration seconds.

    Raises:
        StudioExportError: missing / unreadable / unsupported.
    """
    from orga_drone.export.studio_encoder import StudioExportError
    if not path.is_file():
        raise StudioExportError(
            "The selected music file is no longer available.",
            code="music_missing",
        )
    try:
        path.open("rb").close()
    except OSError as exc:
        raise StudioExportError(
            "The selected music file could not be read.",
            code="music_unreadable",
        ) from exc
    duration = probe_audio_duration_s(path)
    if duration is None or duration <= 0:
        raise StudioExportError(
            "The selected music file cannot be decoded.",
            code="music_unsupported",
        )
    return duration
