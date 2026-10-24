"""Studio video encoder boundary (Issue #17).

Encoder-specific details stay behind this interface so Studio UI / config remain
codec-agnostic. The default adapter uses the existing ffmpeg binary discovery.
"""

from __future__ import annotations

import contextvars
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_frame import ffmpeg_frame_prefix, ffmpeg_frame_suffix
from orga_drone.studio_image import ffmpeg_grade_chain

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


def _segment_chain(width: int, height: int, clip: StudioExportClip) -> str:
    """Grade, optional zoom/pan, then scale/pad.

    Fades stay separate so privacy masks and overlays can sit on the framed
    picture before them.
    """
    base = _segment_vf(width, height)
    grade = ffmpeg_grade_chain(clip.image) if clip.kind in {"photo", "video"} else ""
    prefix = ""
    suffix = ""
    if clip.kind in {"photo", "video"} and not clip.frame.is_neutral:
        source_w, source_h = _source_frame_size(clip)
        prefix = ffmpeg_frame_prefix(
            clip.frame,
            source_width=source_w,
            source_height=source_h,
            kind=clip.kind,
            source_start_s=clip.source_start_s,
            duration_s=clip.duration_s,
        )
        suffix = ffmpeg_frame_suffix(
            clip.frame,
            frame_width=width,
            frame_height=height,
            source_width=source_w,
            source_height=source_h,
            kind=clip.kind,
            source_start_s=clip.source_start_s,
            duration_s=clip.duration_s,
        )
    return ",".join(part for part in (grade, prefix, base, suffix) if part)


def _fade_filters(clip: StudioExportClip) -> list[str]:
    fades: list[str] = []
    fade_in = max(0.0, float(clip.fade_in_s))
    fade_out = max(0.0, float(clip.fade_out_s))
    if fade_in > 0:
        fades.append(f"fade=t=in:st=0:d={fade_in:.4f}")
    if fade_out > 0:
        start = max(0.0, float(clip.duration_s) - fade_out)
        fades.append(f"fade=t=out:st={start:.4f}:d={fade_out:.4f}")
    return fades


def _segment_vf_for_clip(width: int, height: int, clip: StudioExportClip) -> str:
    """Scale/pad chain, with an optional per-clip grade before fades.

    Photo and video grades are applied on the decoded frame, then the existing
    scale, timebase, and fade filters run. Title cards stay ungraded.
    A neutral clip adds nothing, so the chain matches ``_segment_vf``.
    Zoom and pan, when set, crop the fitted frame before fades.
    Overlays and privacy masks are not part of this string.
    """
    if clip.masks:
        raise RuntimeError("masked clips use _segment_video_args")
    chain = _segment_chain(width, height, clip)
    fades = _fade_filters(clip)
    if fades:
        return f"{chain},{','.join(fades)}"
    return chain


def _source_frame_size(clip: StudioExportClip) -> tuple[int, int]:
    """Pixel size of the media being fitted. Zero lets the frame stand in."""
    path = clip.source_path
    if path is None or not path.is_file():
        return 0, 0
    if clip.kind == "photo":
        try:
            from PIL import Image

            with Image.open(path) as image:
                return int(image.width), int(image.height)
        except OSError:
            return 0, 0
    from orga_drone.studio_export import probe_video_dimensions

    width, height = probe_video_dimensions(path)
    return int(width or 0), int(height or 0)


def _picture_before_format(graph: str) -> tuple[str, str]:
    """Split a finished segment graph into a picture label and the graph that defines it.

    The tail ``format=yuv420p`` and any fades after the picture are dropped so a
    flight map can sit on the fitted frame and still fade with the clip.
    """
    marker = "format=yuv420p["
    pos = graph.rfind(marker)
    if pos < 0:
        raise StudioExportError(
            "The flight map could not be placed on this clip.",
            code="map_render_failed",
        )
    seg_start = graph.rfind(";", 0, pos) + 1
    segment = graph[seg_start:pos]
    end = segment.find("]")
    if not segment.startswith("[") or end < 2:
        raise StudioExportError(
            "The flight map could not be placed on this clip.",
            code="map_render_failed",
        )
    label = segment[1:end]
    prefix = graph[:seg_start].rstrip(";")
    if not prefix or not label:
        raise StudioExportError(
            "The flight map could not be placed on this clip.",
            code="map_render_failed",
        )
    return label, prefix


def _attach_flight_map(
    clip: StudioExportClip,
    width: int,
    height: int,
    work: Path,
    extra: list[str],
    filters: list[str],
) -> tuple[list[str], list[str]]:
    """Composite the local GPS panel before fades. A disabled map leaves the graph unchanged."""
    placement = clip.map_placement
    if not placement.enabled or clip.kind not in {"photo", "video"}:
        return extra, filters
    from orga_drone.studio_map import MapRenderError, flight_map_overlay

    fades = _fade_filters(clip)
    source_w, source_h = _source_frame_size(clip)
    first_input = 1 + extra.count("-i")
    if filters and filters[0] == "-vf":
        body = filters[1]
        for fade in reversed(fades):
            token = "," + fade
            if body.endswith(token):
                body = body[: -len(token)]
        picture = "pic"
        prefix = f"[0:v]{body}[{picture}]"
    elif filters and filters[0] == "-filter_complex":
        picture, prefix = _picture_before_format(filters[1])
    else:
        raise StudioExportError(
            "The flight map could not be placed on this clip.",
            code="map_render_failed",
        )
    try:
        map_args, fragment, label = flight_map_overlay(
            placement=placement,
            track=clip.gps_track,
            media_duration_s=clip.media_duration_s,
            frame_width=width,
            frame_height=height,
            source_width=source_w,
            source_height=source_h,
            dest_dir=work,
            first_input=first_input,
            picture_label=picture,
            fps=EXPORT_FPS,
        )
    except MapRenderError as exc:
        raise StudioExportError(
            "The flight map could not be drawn for this clip.",
            code="map_render_failed",
        ) from exc
    tail = ",".join([*fades, "format=yuv420p"])
    graph = f"{prefix};{fragment};[{label}]{tail}[vout]"
    if "http://" in graph or "https://" in graph:
        raise StudioExportError(
            "The flight map could not be drawn for this clip.",
            code="map_render_failed",
        )
    return [*extra, *map_args], ["-filter_complex", graph, "-map", "[vout]"]


def _segment_filter_invocation(
    clip: StudioExportClip,
    width: int,
    height: int,
    work: Path,
) -> tuple[list[str], list[str]]:
    """Extra inputs and the filter flags for one segment.

    No overlays or masks: ``-vf`` only, identical to the pre-overlay command.
    Masks run after grade and scale. Overlays sit on that picture, then fades.
    With either effect: ``-filter_complex`` mapped to ``[vout]``.
    The caller still maps audio.
    """
    chain = _segment_chain(width, height, clip)
    fades = _fade_filters(clip)
    masks = tuple(clip.masks) if clip.kind in {"photo", "video"} else ()

    def privacy_graph(*, include_tail: bool) -> tuple[str, int]:
        source_w, source_h = _source_frame_size(clip)
        if source_w <= 0 or source_h <= 0:
            raise StudioExportError(
                "A privacy mask could not be rendered. Make the region larger and export again.",
                code="mask_render_failed",
            )
        from orga_drone.studio_mask import MaskRenderError, ffmpeg_mask_graph, mask_windows

        try:
            placed = mask_windows(
                masks,
                frame_width=width,
                frame_height=height,
                source_width=source_w,
                source_height=source_h,
            )
            graph = ffmpeg_mask_graph(
                base_chain=chain,
                fades=fades if include_tail else (),
                windows=placed,
                include_tail=include_tail,
            )
        except MaskRenderError as exc:
            raise StudioExportError(
                "A privacy mask could not be rendered. Make the region larger and export again.",
                code="mask_render_failed",
            ) from exc
        return graph, len(placed)

    def plain_or_masks() -> tuple[list[str], list[str]]:
        if not masks:
            vf = f"{chain},{','.join(fades)}" if fades else chain
            return [], ["-vf", vf]
        graph, _count = privacy_graph(include_tail=True)
        return [], ["-filter_complex", graph, "-map", "[vout]"]

    active = [
        item
        for item in clip.overlays
        if float(item.end_s) - float(item.start_s) >= 0.1
        and float(item.start_s) < float(clip.duration_s)
    ]
    if not active:
        return _attach_flight_map(clip, width, height, work, *plain_or_masks())
    from orga_drone.config import settings
    from orga_drone.studio_overlay import (
        MIN_SPAN_S,
        OverlayAssetMissing,
        OverlayFontMissing,
        OverlayWindow,
        content_rect,
        ffmpeg_overlay_graph,
        filter_time_origin,
        overlay_box_pixels,
        render_overlay_png,
        resolve_overlay_asset,
    )

    origin = filter_time_origin(kind=clip.kind, source_start_s=clip.source_start_s)
    source_w, source_h = _source_frame_size(clip)
    fitted = content_rect(width, height, source_w, source_h)
    extra: list[str] = []
    windows: list[OverlayWindow] = []
    for index, overlay in enumerate(active):
        end = min(float(overlay.end_s), float(clip.duration_s))
        if end - float(overlay.start_s) < MIN_SPAN_S:
            continue
        asset: Path | None = None
        if overlay.kind == "image":
            try:
                asset = resolve_overlay_asset(settings.data_dir, overlay.asset_name)
            except ValueError as exc:
                raise StudioExportError(
                    "An overlay image is missing. Remove it or choose the image again.",
                    code="overlay_asset_missing",
                ) from exc
            if not asset.is_file():
                raise StudioExportError(
                    "An overlay image is missing. Remove it or choose the image again.",
                    code="overlay_asset_missing",
                )
        png = work / f"overlay-{index}.png"
        try:
            render_overlay_png(
                overlay,
                frame_width=width,
                frame_height=height,
                source_width=source_w,
                source_height=source_h,
                asset_path=asset,
                dest=png,
            )
        except OverlayAssetMissing as exc:
            raise StudioExportError(
                "An overlay image is missing. Remove it or choose the image again.",
                code="overlay_asset_missing",
            ) from exc
        except OverlayFontMissing as exc:
            raise StudioExportError(str(exc), code="overlay_font_missing") from exc
        extra.extend(["-loop", "1", "-framerate", str(EXPORT_FPS), "-i", str(png)])
        left, top, box_w, box_h = overlay_box_pixels(overlay, fitted)
        origin_x, origin_y, content_w, content_h = fitted
        windows.append(
            OverlayWindow(
                start_s=origin + float(overlay.start_s),
                end_s=origin + end,
                animation=overlay.animation,
                animation_s=float(overlay.animation_s),
                slide_from=overlay.slide_from,
                frame_w=width,
                frame_h=height,
                px=left,
                py=top,
                pw=box_w,
                ph=box_h,
                ox=origin_x,
                oy=origin_y,
                cw=content_w,
                ch=content_h,
            )
        )
    if not windows:
        return _attach_flight_map(clip, width, height, work, *plain_or_masks())
    source_label = None
    if masks:
        prefix, count = privacy_graph(include_tail=False)
        source_label = f"mbase{count}"
    else:
        prefix = ""
    graph = ffmpeg_overlay_graph(
        base_chain=chain,
        fades=fades,
        windows=windows,
        first_input=1,
        source_label=source_label,
    )
    if prefix:
        graph = f"{prefix};{graph}"
    return _attach_flight_map(
        clip,
        width,
        height,
        work,
        extra,
        ["-filter_complex", graph, "-map", "[vout]"],
    )


def _segment_video_args(clip: StudioExportClip, width: int, height: int) -> list[str]:
    """``-vf`` for an unmasked clip, or ``-filter_complex`` when masks exist.

    Masks are applied after grade, zoom/pan, and scale, and before fades.
    A failure raises ``StudioExportError`` instead of falling back to an
    unmasked chain.
    """
    chain = _segment_chain(width, height, clip)
    fades = _fade_filters(clip)
    masks = clip.masks if clip.kind in {"photo", "video"} else ()
    if not masks:
        vf = f"{chain},{','.join(fades)}" if fades else chain
        return ["-vf", vf]
    source_w, source_h = _source_frame_size(clip)
    if source_w <= 0 or source_h <= 0:
        raise StudioExportError(
            "A privacy mask could not be rendered. Make the region larger and export again.",
            code="mask_render_failed",
        )
    from orga_drone.studio_mask import MaskRenderError, ffmpeg_mask_graph, mask_windows

    try:
        windows = mask_windows(
            masks,
            frame_width=width,
            frame_height=height,
            source_width=source_w,
            source_height=source_h,
        )
        graph = ffmpeg_mask_graph(base_chain=chain, fades=fades, windows=windows)
    except MaskRenderError as exc:
        raise StudioExportError(
            "A privacy mask could not be rendered. Make the region larger and export again.",
            code="mask_render_failed",
        ) from exc
    return ["-filter_complex", graph]


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


def _norm_video_pad(src: str, alias: str) -> str:
    """Force a shared CFR timebase so chained xfade/concat graphs can configure.

    xfade of a previous xfade/concat pad uses 1/1000000 while segment files use
    the MP4 tbn (e.g. 1/15360). FFmpeg then fails with encoder-EOF symptoms.
    """
    return f"[{src}]fps={EXPORT_FPS},format=yuv420p,settb=1/{EXPORT_FPS}[{alias}]"


def _norm_audio_pad(src: str, alias: str) -> str:
    return (
        f"[{src}]aformat=sample_rates=48000:channel_layouts=stereo,"
        f"aresample=async=1:first_pts=0[{alias}]"
    )


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
        left_v = f"vl{index}"
        right_v = f"vr{index}"
        left_a = f"al{index}"
        right_a = f"ar{index}"
        v_out = f"xv{index}"
        a_out = f"xa{index}"
        filters.append(_norm_video_pad(current_v, left_v))
        filters.append(_norm_video_pad(next_v, right_v))
        filters.append(_norm_audio_pad(current_a, left_a))
        filters.append(_norm_audio_pad(next_a, right_a))
        outgoing = clips[index]
        if outgoing.transition_type == "crossfade" and outgoing.transition_s > 0:
            overlap = float(outgoing.transition_s)
            offset = max(0.0, current_dur - overlap)
            filters.append(
                f"[{left_v}][{right_v}]xfade=transition=fade:"
                f"duration={overlap:.4f}:offset={offset:.4f}[{v_out}]"
            )
            a_keep = max(0.0, current_dur - overlap / 2.0)
            b_start = overlap / 2.0
            filters.append(
                f"[{left_a}]atrim=0:{a_keep:.4f},asetpts=PTS-STARTPTS[at{index}l]"
            )
            filters.append(
                f"[{right_a}]atrim={b_start:.4f},asetpts=PTS-STARTPTS[at{index}r]"
            )
            filters.append(f"[at{index}l][at{index}r]concat=n=2:v=0:a=1[{a_out}]")
            current_dur = current_dur + next_dur - overlap
        else:
            filters.append(f"[{left_v}][{right_v}]concat=n=2:v=1:a=0[{v_out}]")
            filters.append(f"[{left_a}][{right_a}]concat=n=2:v=0:a=1[{a_out}]")
            current_dur += next_dur
        current_v = v_out
        current_a = a_out
    return filters


class StudioExportError(Exception):
    """User-facing export failure (message is safe to show)."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ExportCancelled(StudioExportError):
    """The user stopped the export before a finished file was published."""

    def __init__(self) -> None:
        super().__init__("Export cancelled.", code="cancelled")


_cancel_event: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "studio_export_cancel",
    default=None,
)
_export_procs: dict[int, subprocess.Popen[str]] = {}
_export_procs_lock = threading.Lock()


def cancel_export_process(cancel_event: threading.Event) -> None:
    """Mark an export cancelled and stop its current ffmpeg process."""
    cancel_event.set()
    with _export_procs_lock:
        proc = _export_procs.get(id(cancel_event))
    if proc is not None and proc.poll() is None:
        proc.kill()


def _raise_if_cancelled() -> None:
    event = _cancel_event.get()
    if event is not None and event.is_set():
        raise ExportCancelled()


def _bind_export_process(event: threading.Event, proc: subprocess.Popen[str]) -> None:
    with _export_procs_lock:
        _export_procs[id(event)] = proc
        should_kill = event.is_set()
    if should_kill and proc.poll() is None:
        proc.kill()


def _unbind_export_process(event: threading.Event, proc: subprocess.Popen[str]) -> None:
    with _export_procs_lock:
        if _export_procs.get(id(event)) is proc:
            del _export_procs[id(event)]


def _watch_export_cancel(event: threading.Event, proc: subprocess.Popen[str]) -> None:
    while proc.poll() is None:
        if event.wait(timeout=0.2):
            if proc.poll() is None:
                proc.kill()
            return


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
        cancel_event: threading.Event | None = None,
    ) -> Path:
        """Render ``config`` to a finished file at ``config.output_path``.

        Implementations should write via a temporary file and only place the
        final destination after success. Must not modify source media.
        When ``cancel_event`` is set, stop the work and leave the destination
        untouched.
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
        cancel_event: threading.Event | None = None,
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
        partial = parent / f".{dest.name}.{uuid.uuid4().hex}.partial"
        token = _cancel_event.set(cancel_event)
        try:
            segments: list[Path] = []
            for index, clip in enumerate(config.clips):
                _raise_if_cancelled()
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
            _raise_if_cancelled()
            _emit(
                on_progress,
                phase="concat",
                clip_index=clip_total,
                clip_total=clip_total,
                current_label=None,
            )
            self._concat_or_stitch(ffmpeg, segments, tmp_out, config)
            _raise_if_cancelled()
            if config.music_tracks:
                _emit(
                    on_progress,
                    phase="mixing",
                    clip_index=clip_total,
                    clip_total=clip_total,
                    current_label=config.music_tracks[0].source_path.name,
                )
                mixed = tmp_dir / "export_mixed.mp4"
                self._mix_music(ffmpeg, tmp_out, mixed, config)
                tmp_out = mixed
            if not tmp_out.is_file() or tmp_out.stat().st_size <= 0:
                raise StudioExportError("Export failed: empty output.")
            _raise_if_cancelled()
            shutil.move(str(tmp_out), partial)
            _raise_if_cancelled()
            partial.replace(dest)
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
            partial.unlink(missing_ok=True)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _cancel_event.reset(token)

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
        if clip.kind == "photo":
            self._render_photo(
                ffmpeg,
                clip,
                out,
                width,
                height,
                on_progress=on_progress,
                clip_index=clip_index,
                clip_total=clip_total,
            )
        else:
            self._render_video(
                ffmpeg,
                clip,
                out,
                width,
                height,
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
        from orga_drone.studio_title_card import (
            TitleCardFontError,
            render_title_card_image,
        )

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
        self._render_photo(
            ffmpeg,
            photo_clip,
            out,
            width,
            height,
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
        width: int,
        height: int,
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
        sized = replace(clip, source_path=still, kind="photo")
        dur = max(0.1, float(clip.duration_s))
        extra, filters = _segment_filter_invocation(sized, width, height, out.parent)
        overlay_count = extra.count("-i")
        audio_index = 1 + overlay_count
        uses_graph = bool(filters) and filters[0] == "-filter_complex"
        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(EXPORT_FPS),
            "-i",
            str(still),
            *extra,
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            f"{dur:.3f}",
            *filters,
        ]
        if uses_graph:
            cmd.extend(["-map", f"{audio_index}:a:0"])
        cmd.extend(
            [
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
        )
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
        width: int,
        height: int,
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
        extra, filters = _segment_filter_invocation(clip, width, height, out.parent)
        overlay_count = extra.count("-i")
        uses_graph = bool(filters) and filters[0] == "-filter_complex"
        # Prefer accurate cuts on HEVC/DJI: decode then seek (slower, correct).
        # Explicit maps: DJI files often carry an attached JPEG that must not win.
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(clip.source_path),
            *extra,
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{dur:.3f}",
            *filters,
            *_x264_video_args(),
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
        ]
        if uses_graph:
            cmd.extend(["-map", "0:a:0"])
        else:
            cmd.extend(["-map", "0:v:0", "-map", "0:a:0"])
        cmd.append(str(out))
        try:
            _run_ffmpeg(cmd, on_time=on_time, duration_s=dur)
        except StudioExportError:
            # Some clips have no audio track; add silence so concat stays uniform.
            # The same video graph is kept, including masks and overlays.
            audio_index = 1 + overlay_count
            cmd_silent = [
                ffmpeg,
                "-y",
                "-i",
                str(clip.source_path),
                *extra,
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                # Keep decode-then-seek semantics: after the inputs, -ss is an
                # output option and trims the video source rather than anullsrc.
                "-ss",
                f"{start:.3f}",
                "-t",
                f"{dur:.3f}",
                *filters,
                *_x264_video_args(),
                "-c:a",
                "aac",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-shortest",
            ]
            if uses_graph:
                cmd_silent.extend(["-map", f"{audio_index}:a:0"])
            else:
                cmd_silent.extend(["-map", "0:v:0", "-map", "1:a:0"])
            cmd_silent.append(str(out))
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
            # Only remap a missing xfade filter — not timebase / configure errors
            # whose messages also mention "xfade".
            if "no such filter" in str(exc).lower():
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
            build_playlist_amix_filter,
            require_readable_music,
        )

        tracks = config.music_tracks
        if not tracks:
            raise StudioExportError("Music mix requested without a music track.")
        story_s = _export_story_length_s(config.clips)
        if story_s <= 0:
            raise StudioExportError("Studio project has no exportable duration.")
        probed: list[float] = []
        for music in tracks:
            duration_s = music.duration_s
            if duration_s <= 0:
                duration_s = require_readable_music(music.source_path)
            else:
                require_readable_music(music.source_path)
            probed.append(duration_s)
        single = tracks[0]
        use_loop = len(tracks) == 1 and bool(single.loop)
        cmd: list[str] = [ffmpeg, "-y", "-i", str(concat_path)]
        if use_loop:
            filter_complex = build_music_amix_filter(
                volume=single.volume,
                fade_in_s=single.fade_in_s,
                fade_out_s=single.fade_out_s,
                story_s=story_s,
                music_s=probed[0],
                loop=True,
            )
            cmd.extend(["-stream_loop", "-1", "-i", str(single.source_path)])
        else:
            filter_complex = build_playlist_amix_filter(
                story_s=story_s,
                tracks=[
                    {
                        "volume": music.volume,
                        "fade_in_s": music.fade_in_s,
                        "fade_out_s": music.fade_out_s,
                        "music_s": duration_s,
                    }
                    for music, duration_s in zip(tracks, probed, strict=True)
                ],
            )
            for music in tracks:
                cmd.extend(["-i", str(music.source_path)])
        cmd.extend(
            [
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
    r"(error|option\b.+\bnot|invalid|failed|could not|no such|unknown|not found|timebase)",
    re.IGNORECASE,
)


def _ffmpeg_error_message(stderr: str) -> str:
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    for line in lines:
        lower = line.lower()
        if "timebase" in lower or "failed to configure" in lower:
            return line[-400:]
    interesting = [ln for ln in lines if _FFMPEG_ERR_HINT.search(ln)]
    chosen = interesting[-4:] if interesting else lines[-2:]
    text = " ".join(chosen).strip() if chosen else "unknown ffmpeg error"
    return text[-400:]


def _persist_ffmpeg_failure(cmd: list[str], stderr: str) -> None:
    """Keep the full ffmpeg command + stderr for review (not just the last line)."""
    try:
        from datetime import datetime, timezone

        from orga_drone.config import settings

        log_dir = settings.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "studio-export-ffmpeg.log"
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        command = subprocess.list2cmdline([str(part) for part in cmd])
        body = (
            f"{stamp}\nCMD {command}\n--- stderr ---\n{stderr.rstrip()}\n{'=' * 72}\n"
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(body)
    except OSError:
        return


def _terminate_ffmpeg(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return


def _run_ffmpeg(
    cmd: list[str],
    *,
    on_time: Callable[[float], None] | None = None,
    duration_s: float | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Run ffmpeg; optionally stream ``-progress pipe:1`` for live time updates.

    A set cancel event kills the process. The destination file is not this
    function's concern; callers publish it only after a successful return.
    """
    event = _cancel_event.get() if cancel_event is None else cancel_event
    if event is not None and event.is_set():
        raise ExportCancelled()
    if len(cmd) < 2:
        raise StudioExportError("Export failed: invalid ffmpeg command.")
    progress_cmd = cmd
    if on_time is not None:
        # Insert progress reporting just before the output path (last arg).
        progress_cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]
    err_fd, err_name = tempfile.mkstemp(prefix="orga-ffmpeg-", suffix=".err")
    err_path = Path(err_name)
    last_emit = -1.0
    returncode = 1
    popen: subprocess.Popen[str] | None = None
    watcher: threading.Thread | None = None
    try:
        with open(err_fd, "w", encoding="utf-8", errors="replace") as err_file:
            try:
                popen = subprocess.Popen(
                    progress_cmd,
                    stdout=subprocess.PIPE,
                    stderr=err_file,
                    text=True,
                    bufsize=1,
                    **subprocess_no_window_kwargs(),
                )
            except OSError as exc:
                raise StudioExportError(f"Export failed: {exc}") from exc
            if event is not None:
                _bind_export_process(event, popen)
                watcher = threading.Thread(
                    target=_watch_export_cancel,
                    args=(event, popen),
                    name="studio-export-cancel",
                    daemon=True,
                )
                watcher.start()
            assert popen.stdout is not None
            try:
                for line in popen.stdout:
                    if event is not None and event.is_set():
                        _terminate_ffmpeg(popen)
                        raise ExportCancelled()
                    if on_time is None:
                        continue
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
            except ExportCancelled:
                raise
            except (OSError, subprocess.SubprocessError) as exc:
                _terminate_ffmpeg(popen)
                if event is not None and event.is_set():
                    raise ExportCancelled() from exc
                raise StudioExportError(f"Export failed: {exc}") from exc
        if event is not None and event.is_set():
            raise ExportCancelled()
        try:
            stderr = err_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stderr = ""
        if returncode != 0:
            _persist_ffmpeg_failure(progress_cmd, stderr)
            raise StudioExportError(f"Export failed: {_ffmpeg_error_message(stderr)}")
        if on_time is not None and last_emit < 0 and duration_s is not None:
            on_time(duration_s)
    finally:
        if popen is not None and event is not None:
            _unbind_export_process(event, popen)
        err_path.unlink(missing_ok=True)


def get_default_encoder() -> StudioVideoEncoder:
    return FfmpegStudioEncoder()
