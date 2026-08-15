"""Studio video encoder boundary (Issue #17).

Encoder-specific details stay behind this interface so Studio UI / config remain
codec-agnostic. The default adapter uses the existing ffmpeg binary discovery.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.ffmpeg_bin import find_ffmpeg

ProgressCallback = Callable[[dict[str, Any]], None]

# Internal encode speed/quality tradeoff (not a user setting). Prefer share-friendly
# turnaround; higher-quality / social profiles can come later if needed.
X264_PRESET = "veryfast"
# All segments use CFR + limited-range yuv420p; final concat re-encodes for a
# clean timeline (photo JPEG full-range vs DJI video previously broke playback).
EXPORT_FPS = 30


def _x264_color_args() -> list[str]:
    """Force limited-range BT.709 so photo (JPEG) and video segments match."""
    return [
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
    ]


def _x264_video_args() -> list[str]:
    return ["-c:v", "libx264", "-preset", X264_PRESET, *_x264_color_args()]


def _segment_vf(width: int, height: int) -> str:
    """Scale/pad + CFR + limited-range BT.709 yuv420p (photo and video match)."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"fps={EXPORT_FPS},format=yuv420p,"
        "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
    )


def _segment_vf_for_clip(width: int, height: int, clip: StudioExportClip) -> str:
    vf = _segment_vf(width, height)
    fades: list[str] = []
    fade_in = max(0.0, float(clip.fade_in_s))
    fade_out = max(0.0, float(clip.fade_out_s))
    if fade_in > 0:
        fades.append(f"fade=t=in:st=0:d={fade_in:.4f}")
    if fade_out > 0:
        start = max(0.0, float(clip.duration_s) - fade_out)
        fades.append(f"fade=t=out:st={start:.4f}:d={fade_out:.4f}")
    if fades:
        return f"{vf},{','.join(fades)}"
    return vf


def _has_crossfade(clips: tuple[StudioExportClip, ...]) -> bool:
    for clip in clips[:-1]:
        if clip.transition_type == "crossfade" and float(clip.transition_s) > 0:
            return True
    return False


def _export_story_length_s(clips: tuple[StudioExportClip, ...]) -> float:
    from orga_drone.studio_transition import AppliedTransition, story_length_s

    durations = [max(0.0, float(c.duration_s)) for c in clips]
    applied = [
        AppliedTransition(
            type=clip.transition_type,
            duration_s=float(clip.transition_s),
            stored_type=clip.transition_type,
            stored_duration_s=float(clip.transition_s),
            fallback_cut=False,
            clamped=False,
        )
        for clip in clips[:-1]
    ]
    return story_length_s(durations, applied)


def build_stitch_filters(clips: tuple[StudioExportClip, ...]) -> list[str]:
    """Build concat/xfade filter_complex steps. Audio is hard-cut, never acrossfade."""
    if len(clips) < 2:
        return []
    filters: list[str] = []
    current_v = "0:v"
    current_a = "0:a"
    current_dur = float(clips[0].duration_s)
    for index in range(len(clips) - 1):
        nxt = index + 1
        next_v = f"{nxt}:v"
        next_a = f"{nxt}:a"
        next_dur = float(clips[nxt].duration_s)
        v_out = f"xv{index}"
        a_out = f"xa{index}"
        outgoing = clips[index]
        if outgoing.transition_type == "crossfade" and outgoing.transition_s > 0:
            overlap = float(outgoing.transition_s)
            offset = max(0.0, current_dur - overlap)
            filters.append(
                f"[{current_v}][{next_v}]xfade=transition=fade:"
                f"duration={overlap:.4f}:offset={offset:.4f}[{v_out}]"
            )
            a_keep = max(0.0, current_dur - overlap / 2.0)
            b_start = overlap / 2.0
            filters.append(
                f"[{current_a}]atrim=0:{a_keep:.4f},asetpts=PTS-STARTPTS[al{index}]"
            )
            filters.append(
                f"[{next_a}]atrim={b_start:.4f},asetpts=PTS-STARTPTS[ar{index}]"
            )
            filters.append(
                f"[al{index}][ar{index}]concat=n=2:v=0:a=1[{a_out}]"
            )
            current_dur = current_dur + next_dur - overlap
        else:
            filters.append(
                f"[{current_v}][{next_v}]concat=n=2:v=1:a=0[{v_out}]"
            )
            filters.append(
                f"[{current_a}][{next_a}]concat=n=2:v=0:a=1[{a_out}]"
            )
            current_dur += next_dur
        current_v = v_out
        current_a = a_out
    return filters


class StudioExportError(Exception):
    """User-facing export failure (message is safe to show)."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def _clip_progress_label(clip: StudioExportClip) -> str:
    if clip.label:
        return clip.label
    if clip.source_path is not None:
        return clip.source_path.name
    return "Title card"


class StudioVideoEncoder(Protocol):
    def render(
        self,
        config: StudioExportConfig,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Render ``config`` to a finished file at ``config.output_path``.

        Implementations should write via a temporary file and only place the
        final destination after success. Must not modify source media.
        """


def export_progress_percent(
    *,
    clip_index: int,
    clip_total: int,
    phase: str,
    clip_fraction: float = 0.0,
) -> int:
    """Determinate percent: clips share steps with one extra concat step.

    ``clip_fraction`` is 0..1 progress within the current rendering clip.
    """
    total_steps = max(1, int(clip_total) + 1)
    if phase == "done":
        return 100
    if phase == "concat" or phase == "mixing":
        concat_pct = max(0, min(99, int(round(100 * clip_total / total_steps))))
        if phase == "mixing":
            return min(99, concat_pct + 1)
        return concat_pct
    if phase == "rendering":
        idx = max(1, min(int(clip_index), max(1, int(clip_total))))
        frac = max(0.0, min(1.0, float(clip_fraction)))
        value = 100.0 * ((idx - 1) + frac) / total_steps
        return max(0, min(99, int(round(value))))
    return 0


def parse_ffmpeg_out_time_seconds(line: str) -> float | None:
    """Parse one ffmpeg ``-progress`` line into output media seconds, if present."""
    text = line.strip()
    if text.startswith("out_time_ms="):
        raw = text.split("=", 1)[1].strip()
        try:
            # ffmpeg documents out_time_ms as microseconds despite the name.
            return int(raw) / 1_000_000.0
        except ValueError:
            return None
    if text.startswith("out_time_us="):
        raw = text.split("=", 1)[1].strip()
        try:
            return int(raw) / 1_000_000.0
        except ValueError:
            return None
    if text.startswith("out_time="):
        raw = text.split("=", 1)[1].strip()
        if raw in {"N/A", ""}:
            return None
        parts = raw.split(":")
        if len(parts) != 3:
            return None
        try:
            hours = float(parts[0])
            minutes = float(parts[1])
            seconds = float(parts[2])
        except ValueError:
            return None
        return hours * 3600.0 + minutes * 60.0 + seconds
    return None


def _emit(
    on_progress: ProgressCallback | None,
    *,
    phase: str,
    clip_index: int,
    clip_total: int,
    clip_fraction: float = 0.0,
    current_label: str | None = None,
) -> None:
    if on_progress is None:
        return
    payload: dict[str, Any] = {
        "phase": phase,
        "clip_index": clip_index,
        "clip_total": clip_total,
        "percent": export_progress_percent(
            clip_index=clip_index,
            clip_total=clip_total,
            phase=phase,
            clip_fraction=clip_fraction,
        ),
        "current_label": current_label,
    }
    on_progress(payload)


class FfmpegStudioEncoder:
    """Default encoder: H.264/AAC MP4 via system/bundled ffmpeg (not UI-selectable)."""

    def render(
        self,
        config: StudioExportConfig,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        if not config.clips:
            raise StudioExportError("Studio project has no exportable clips.")
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise StudioExportError(
                "ffmpeg is not available. Install ffmpeg or use a build that includes it."
            )
        dest = config.output_path.expanduser().resolve()
        parent = dest.parent
        if not parent.is_dir():
            raise StudioExportError("Export folder does not exist.")
        if not os_access_writable(parent):
            raise StudioExportError("Export folder is not writable.")

        clip_total = len(config.clips)
        tmp_dir = Path(tempfile.mkdtemp(prefix="orga-drone-export-"))
        tmp_out = tmp_dir / "export_tmp.mp4"
        try:
            segments: list[Path] = []
            for index, clip in enumerate(config.clips):
                clip_index = index + 1
                label = _clip_progress_label(clip)
                _emit(
                    on_progress,
                    phase="rendering",
                    clip_index=clip_index,
                    clip_total=clip_total,
                    clip_fraction=0.0,
                    current_label=label,
                )
                seg = tmp_dir / f"seg_{index:04d}.mp4"
                self._render_clip(
                    ffmpeg,
                    clip,
                    seg,
                    config.width,
                    config.height,
                    on_progress=on_progress,
                    clip_index=clip_index,
                    clip_total=clip_total,
                )
                _emit(
                    on_progress,
                    phase="rendering",
                    clip_index=clip_index,
                    clip_total=clip_total,
                    clip_fraction=1.0,
                    current_label=label,
                )
                segments.append(seg)
            _emit(
                on_progress,
                phase="concat",
                clip_index=clip_total,
                clip_total=clip_total,
                current_label=None,
            )
            self._concat_or_stitch(ffmpeg, segments, tmp_out, config)
            if config.music is not None:
                _emit(
                    on_progress,
                    phase="mixing",
                    clip_index=clip_total,
                    clip_total=clip_total,
                    current_label=config.music.source_path.name,
                )
                mixed = tmp_dir / "export_mixed.mp4"
                self._mix_music(ffmpeg, tmp_out, mixed, config)
                tmp_out = mixed
            if not tmp_out.is_file() or tmp_out.stat().st_size <= 0:
                raise StudioExportError("Export failed: empty output.")
            if dest.exists():
                dest.unlink()
            shutil.move(str(tmp_out), str(dest))
            _emit(
                on_progress,
                phase="done",
                clip_index=clip_total,
                clip_total=clip_total,
                current_label=None,
            )
            return dest
        except StudioExportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StudioExportError(f"Export failed: {exc}") from exc
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _render_clip(
        self,
        ffmpeg: str,
        clip: StudioExportClip,
        out: Path,
        width: int,
        height: int,
        *,
        on_progress: ProgressCallback | None,
        clip_index: int,
        clip_total: int,
    ) -> None:
        if clip.kind == "title_card":
            self._render_title_card(
                ffmpeg,
                clip,
                out,
                width,
                height,
                on_progress=on_progress,
                clip_index=clip_index,
                clip_total=clip_total,
            )
            return
        if clip.source_path is None or not clip.source_path.is_file():
            name = clip.source_path.name if clip.source_path is not None else "clip"
            raise StudioExportError(f"Missing source file: {name}")
        vf = _segment_vf_for_clip(width, height, clip)
        if clip.kind == "photo":
            self._render_photo(
                ffmpeg,
                clip,
                out,
                vf,
                on_progress=on_progress,
                clip_index=clip_index,
                clip_total=clip_total,
            )
        else:
            self._render_video(
                ffmpeg,
                clip,
                out,
                vf,
                on_progress=on_progress,
                clip_index=clip_index,
                clip_total=clip_total,
            )


    def _render_title_card(
        self,
        ffmpeg: str,
        clip: StudioExportClip,
        out: Path,
        width: int,
        height: int,
        *,
        on_progress: ProgressCallback | None,
        clip_index: int,
        clip_total: int,
    ) -> None:
        from orga_drone.studio_title_card import TitleCardFontError, render_title_card_image

        still = out.with_name(f"{out.stem}_card.jpg")
        try:
            img = render_title_card_image(
                width=width,
                height=height,
                title=clip.title_text,
                subtitle=clip.subtitle_text,
                background=clip.background or "dark",
                locale=clip.locale,
            )
            img.save(still, "JPEG", quality=92, optimize=True)
        except TitleCardFontError as exc:
            raise StudioExportError(
                "Title Card export needs a system sans font.",
                code="title_card_font_missing",
            ) from exc
        except OSError as exc:
            raise StudioExportError("Could not render Title Card.") from exc
        photo_clip = StudioExportClip(
            source_path=still,
            kind="photo",
            duration_s=clip.duration_s,
            label=_clip_progress_label(clip),
            fade_in_s=clip.fade_in_s,
            fade_out_s=clip.fade_out_s,
        )
        vf = _segment_vf_for_clip(width, height, photo_clip)
        self._render_photo(
            ffmpeg,
            photo_clip,
            out,
            vf,
            on_progress=on_progress,
            clip_index=clip_index,
            clip_total=clip_total,
        )

    def _progress_cb(
        self,
        on_progress: ProgressCallback | None,
        *,
        clip: StudioExportClip,
        clip_index: int,
        clip_total: int,
        duration_s: float,
    ) -> Callable[[float], None] | None:
        if on_progress is None:
            return None
        label = _clip_progress_label(clip)

        def _on_time(media_s: float) -> None:
            frac = 0.0 if duration_s <= 0 else max(0.0, min(1.0, media_s / duration_s))
            _emit(
                on_progress,
                phase="rendering",
                clip_index=clip_index,
                clip_total=clip_total,
                clip_fraction=frac,
                current_label=label,
            )

        return _on_time

    def _render_photo(
        self,
        ffmpeg: str,
        clip: StudioExportClip,
        out: Path,
        vf: str,
        *,
        on_progress: ProgressCallback | None,
        clip_index: int,
        clip_total: int,
    ) -> None:
        # Bundled ffmpeg often cannot -loop HEIC/HEIF (and some other stills).
        # Decode via Pillow (same HEIF path as the library), then loop a JPEG.
        still = out.with_name(f"{out.stem}_still.jpg")
        if clip.source_path is None:
            raise StudioExportError("Missing source file: clip")
        _materialize_photo_still(clip.source_path, still)
        dur = max(0.1, float(clip.duration_s))
        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(EXPORT_FPS),
            "-i",
            str(still),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            f"{dur:.3f}",
            "-vf",
            vf,
            *_x264_video_args(),
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-shortest",
            str(out),
        ]
        _run_ffmpeg(
            cmd,
            on_time=self._progress_cb(
                on_progress,
                clip=clip,
                clip_index=clip_index,
                clip_total=clip_total,
                duration_s=dur,
            ),
            duration_s=dur,
        )

    def _render_video(
        self,
        ffmpeg: str,
        clip: StudioExportClip,
        out: Path,
        vf: str,
        *,
        on_progress: ProgressCallback | None,
        clip_index: int,
        clip_total: int,
    ) -> None:
        start = max(0.0, float(clip.source_start_s))
        if clip.source_end_s is not None:
            end = float(clip.source_end_s)
            dur = max(0.1, end - start)
        else:
            dur = max(0.1, float(clip.duration_s))
        on_time = self._progress_cb(
            on_progress,
            clip=clip,
            clip_index=clip_index,
            clip_total=clip_total,
            duration_s=dur,
        )
        # Prefer accurate cuts on HEVC/DJI: decode then seek (slower, correct).
        # Explicit maps: DJI files often carry an attached JPEG that must not win.
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(clip.source_path),
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{dur:.3f}",
            "-vf",
            vf,
            *_x264_video_args(),
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            str(out),
        ]
        try:
            _run_ffmpeg(cmd, on_time=on_time, duration_s=dur)
        except StudioExportError:
            # Some clips have no audio track; add silence so concat stays uniform.
            cmd_silent = [
                ffmpeg,
                "-y",
                "-i",
                str(clip.source_path),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                # Keep decode-then-seek semantics: after both inputs, -ss is an
                # output option and trims the video source rather than anullsrc.
                "-ss",
                f"{start:.3f}",
                "-t",
                f"{dur:.3f}",
                "-vf",
                vf,
                *_x264_video_args(),
                "-c:a",
                "aac",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-shortest",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                str(out),
            ]
            _run_ffmpeg(cmd_silent, on_time=on_time, duration_s=dur)

    def _concat(self, ffmpeg: str, segments: list[Path], out: Path) -> None:
        """Join segments into one MP4.

        Always re-encodes (does not ``-c copy``): photo JPEG full-range and DJI
        video limited-range previously produced broken timelines (freeze / jump)
        even after per-segment fps normalization.
        """
        list_file = out.parent / "concat.txt"
        lines = []
        for seg in segments:
            # ffmpeg concat demuxer: escape single quotes in paths
            p = seg.resolve().as_posix().replace("'", r"'\''")
            lines.append(f"file '{p}'")
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [
            ffmpeg,
            "-y",
            "-fflags",
            "+genpts",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-vf",
            (
                f"fps={EXPORT_FPS},format=yuv420p,"
                "setparams=colorspace=bt709:color_primaries=bt709:"
                "color_trc=bt709:range=tv"
            ),
            "-af",
            "aformat=sample_rates=48000:channel_layouts=stereo,aresample=async=1:first_pts=0",
            *_x264_video_args(),
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(out),
        ]
        _run_ffmpeg(cmd)

    def _concat_or_stitch(
        self,
        ffmpeg: str,
        segments: list[Path],
        out: Path,
        config: StudioExportConfig,
    ) -> None:
        if _has_crossfade(config.clips):
            self._stitch(ffmpeg, segments, out, config)
            return
        self._concat(ffmpeg, segments, out)

    def _stitch(
        self,
        ffmpeg: str,
        segments: list[Path],
        out: Path,
        config: StudioExportConfig,
    ) -> None:
        """Join segments with concat and xfade. Source audio hard-cuts only."""
        clips = config.clips
        if len(segments) != len(clips):
            raise StudioExportError("Export stitch mismatch.")
        if len(segments) == 1:
            shutil.copyfile(segments[0], out)
            return
        filters = build_stitch_filters(clips)
        last = len(clips) - 2
        cmd: list[str] = [ffmpeg, "-y"]
        for seg in segments:
            cmd.extend(["-i", str(seg)])
        cmd.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                f"[xv{last}]",
                "-map",
                f"[xa{last}]",
                *_x264_video_args(),
                "-c:a",
                "aac",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
        try:
            _run_ffmpeg(cmd)
        except StudioExportError as exc:
            msg = str(exc).lower()
            if "xfade" in msg or "no such filter" in msg:
                raise StudioExportError(
                    "This ffmpeg build cannot render Crossfade.",
                    code="xfade_unavailable",
                ) from exc
            raise

    def _mix_music(
        self,
        ffmpeg: str,
        concat_path: Path,
        out: Path,
        config: StudioExportConfig,
    ) -> None:
        from orga_drone.export.music_mix import (
            build_music_amix_filter,
            require_readable_music,
        )

        music = config.music
        if music is None:
            raise StudioExportError("Music mix requested without a music track.")
        duration_s = music.duration_s
        if duration_s <= 0:
            duration_s = require_readable_music(music.source_path)
        else:
            require_readable_music(music.source_path)
        story_s = _export_story_length_s(config.clips)
        if story_s <= 0:
            raise StudioExportError("Studio project has no exportable duration.")
        filter_complex = build_music_amix_filter(
            volume=music.volume,
            fade_in_s=music.fade_in_s,
            fade_out_s=music.fade_out_s,
            story_s=story_s,
            music_s=duration_s,
            loop=music.loop,
        )
        cmd: list[str] = [ffmpeg, "-y", "-i", str(concat_path)]
        if music.loop:
            cmd.extend(["-stream_loop", "-1"])
        cmd.extend(
            [
                "-i",
                str(music.source_path),
                "-filter_complex",
                filter_complex,
                "-map",
                "0:v:0",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
        _run_ffmpeg(cmd)


def _materialize_photo_still(source: Path, dest: Path) -> Path:
    """Decode any library photo (incl. HEIC) to a JPEG ffmpeg can loop."""
    from PIL import Image

    from orga_drone.parse import ensure_heif_support

    ensure_heif_support()
    try:
        with Image.open(source) as img:
            rgb = img.convert("RGB")
            dest.parent.mkdir(parents=True, exist_ok=True)
            rgb.save(dest, "JPEG", quality=95, optimize=True)
    except OSError as exc:
        raise StudioExportError(f"Could not read photo: {source.name}") from exc
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise StudioExportError(f"Could not prepare photo for export: {source.name}")
    return dest


def os_access_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".orga_drone_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


_FFMPEG_ERR_HINT = re.compile(
    r"(error|option\b.+\bnot|invalid|failed|could not|no such|unknown|not found)",
    re.IGNORECASE,
)


def _ffmpeg_error_message(stderr: str) -> str:
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    interesting = [ln for ln in lines if _FFMPEG_ERR_HINT.search(ln)]
    chosen = interesting[-4:] if interesting else lines[-2:]
    text = " ".join(chosen).strip() if chosen else "unknown ffmpeg error"
    return text[-400:]


def _run_ffmpeg(
    cmd: list[str],
    *,
    on_time: Callable[[float], None] | None = None,
    duration_s: float | None = None,
) -> None:
    """Run ffmpeg; optionally stream ``-progress pipe:1`` for live time updates."""
    if on_time is None:
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=3600,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise StudioExportError(f"Export failed: {exc}") from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise StudioExportError(f"Export failed: {_ffmpeg_error_message(err)}")
        return

    # Insert progress reporting just before the output path (last arg).
    # Do NOT pipe stderr while reading stdout — ffmpeg fills the stderr buffer
    # and deadlocks (especially on Windows). Capture stderr to a temp file.
    if len(cmd) < 2:
        raise StudioExportError("Export failed: invalid ffmpeg command.")
    progress_cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]
    err_fd, err_name = tempfile.mkstemp(prefix="orga-ffmpeg-", suffix=".err")
    err_path = Path(err_name)
    last_emit = -1.0
    returncode = 1
    try:
        with open(err_fd, "w", encoding="utf-8", errors="replace") as err_file:
            try:
                popen = subprocess.Popen(
                    progress_cmd,
                    stdout=subprocess.PIPE,
                    stderr=err_file,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                raise StudioExportError(f"Export failed: {exc}") from exc
            assert popen.stdout is not None
            try:
                for line in popen.stdout:
                    media_s = parse_ffmpeg_out_time_seconds(line)
                    if media_s is None:
                        if "=" in line and line.strip().startswith(
                            (
                                "frame=",
                                "fps=",
                                "bitrate=",
                                "total_size=",
                                "progress=",
                            )
                        ):
                            if duration_s is not None and last_emit >= 0:
                                on_time(last_emit)
                        continue
                    if media_s - last_emit >= 0.25 or (
                        duration_s is not None and media_s >= duration_s
                    ):
                        last_emit = media_s
                        on_time(media_s)
                returncode = popen.wait(timeout=3600)
            except (OSError, subprocess.SubprocessError) as exc:
                popen.kill()
                raise StudioExportError(f"Export failed: {exc}") from exc
        try:
            stderr = err_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stderr = ""
        if returncode != 0:
            raise StudioExportError(f"Export failed: {_ffmpeg_error_message(stderr)}")
        if last_emit < 0 and duration_s is not None:
            on_time(duration_s)
    finally:
        err_path.unlink(missing_ok=True)


def get_default_encoder() -> StudioVideoEncoder:
    return FfmpegStudioEncoder()
