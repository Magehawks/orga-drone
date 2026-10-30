"""Studio video encoder boundary (Issue #17).

Encoder-specific details stay behind this interface so Studio UI / config remain
codec-agnostic. The default adapter uses the existing ffmpeg binary discovery.
"""

from __future__ import annotations

import contextvars
import errno
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from orga_drone.export.studio_config import (
    StudioExportClip,
    StudioExportConfig,
)
from orga_drone.media_mutation import hold_media_mutation
from orga_drone.export.studio_quality import (
    DEFAULT_EXPORT_QUALITY,
    coerce_export_quality,
    x264_preset_and_crf,
)
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_cut import MAX_SECTION_REPEATS
from orga_drone.studio_frame import (
    FrameTransform,
    ffmpeg_frame_prefix,
    ffmpeg_frame_suffix,
    ffmpeg_zoom_window,
)
from orga_drone.studio_audio import export_audio_args
from orga_drone.studio_image import ffmpeg_grade_chain, ffmpeg_saturation_ramp
from orga_drone.studio_detail import ffmpeg_detail_chain
from orga_drone.studio_lut import LutMissingError, ffmpeg_lut_chain
from orga_drone.studio_speed import (
    coerce_playback_speed,
    ffmpeg_slow_prefix,
    ffmpeg_slow_stretch,
    source_span_s,
)

ProgressCallback = Callable[[dict[str, Any]], None]

# High and Standard keep this preset. Best quality uses a slower one.
X264_PRESET = "veryfast"
_encode_quality: contextvars.ContextVar[str] = contextvars.ContextVar(
    "studio_encode_quality",
    default=DEFAULT_EXPORT_QUALITY,
)
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
    """H.264 args for the quality selected on the active export."""
    preset, crf = x264_preset_and_crf(_encode_quality.get())
    return ["-c:v", "libx264", "-preset", preset, "-crf", crf, *_x264_color_args()]


def _segment_vf(width: int, height: int) -> str:
    """Scale/pad + CFR + limited-range BT.709 yuv420p (photo and video match)."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"fps={EXPORT_FPS},format=yuv420p,"
        "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
    )


def _slow_timing(clip: StudioExportClip) -> tuple[str, str, float, float] | None:
    """Trim/stretch filters plus the pre-stretch framing clock, or ``None`` at 1×.

    Framing sees source time after the trim resets timestamps. Stretch runs
    after ``fps``, so fades and overlays that follow the chain see Story time.
    """
    if clip.kind != "video":
        return None
    speed = coerce_playback_speed(clip.playback_speed)
    if speed >= 1.0:
        return None
    start, end, _output = source_span_s(
        source_start_s=clip.source_start_s,
        source_end_s=clip.source_end_s,
        output_duration_s=clip.duration_s,
        speed=speed,
    )
    return (
        ffmpeg_slow_prefix(start, end),
        ffmpeg_slow_stretch(speed),
        0.0,
        max(0.001, end - start),
    )


def _slow_pieces(clip: StudioExportClip) -> list[StudioExportClip]:
    """Split a partial slow bar into 1× and slowed source ranges.

    A whole-clip slow section stays on the existing playback speed. Repeats
    and the soundtrack loop keep that path too.
    """
    span = clip.slow_span
    if (
        span is None
        or clip.kind != "video"
        or clip.section_repeats > 1
        or clip.forward_loop
    ):
        return [clip]
    start, end, speed = span
    origin = float(clip.source_start_s)
    if clip.source_end_s is None:
        return [clip]
    total = float(clip.source_end_s) - origin
    if total < 0.05:
        return [clip]
    bounds: list[tuple[float, float, float]] = []
    if start > 0.05:
        bounds.append((0.0, start, 1.0))
    bounds.append((max(0.0, start), min(end, total), speed))
    if end < total - 0.05:
        bounds.append((end, total, 1.0))
    pieces: list[StudioExportClip] = []
    for begin, finish, piece_speed in bounds:
        if finish - begin < 0.05:
            continue
        masks = []
        for mask in clip.masks:
            if mask.start_s is None or mask.end_s is None:
                masks.append(mask)
                continue
            overlap_start = max(begin, mask.start_s)
            overlap_end = min(finish, mask.end_s)
            if overlap_end - overlap_start < 0.05:
                continue
            if overlap_start <= begin + 0.05 and overlap_end >= finish - 0.05:
                masks.append(replace(mask, start_s=None, end_s=None))
            else:
                masks.append(
                    replace(
                        mask,
                        start_s=overlap_start - begin,
                        end_s=overlap_end - begin,
                    )
                )
        frame = clip.frame
        zoom_span = None
        if clip.zoom_span is not None:
            zoom_start, zoom_end = clip.zoom_span
            overlap_start = max(begin, zoom_start)
            overlap_end = min(finish, zoom_end)
            if overlap_end - overlap_start < 0.05:
                frame = FrameTransform()
            elif overlap_start <= begin + 0.05 and overlap_end >= finish - 0.05:
                zoom_span = None
            else:
                zoom_span = (overlap_start - begin, overlap_end - begin)
        pieces.append(
            replace(
                clip,
                source_start_s=origin + begin,
                source_end_s=origin + finish,
                duration_s=(finish - begin) / piece_speed,
                playback_speed=piece_speed,
                section_repeats=1,
                forward_loop=False,
                slow_span=None,
                zoom_span=zoom_span,
                frame=frame,
                masks=tuple(masks),
            )
        )
    return pieces or [clip]


def _segment_chain(width: int, height: int, clip: StudioExportClip) -> str:
    """Grade, optional saturation ramp, optional zoom/pan, then scale/pad.

    Fades stay separate so privacy masks and overlays can sit on the framed
    picture before them. Slow motion trims first and stretches after ``fps``.
    The saturation ramp follows the grade so a fade to black still ends on black.
    """
    base = _segment_vf(width, height)
    grade = ffmpeg_grade_chain(clip.image) if clip.kind in {"photo", "video"} else ""
    lut = ""
    if clip.kind in {"photo", "video"} and not clip.color_look.is_neutral:
        from orga_drone.config import settings

        try:
            lut = ffmpeg_lut_chain(
                clip.color_look,
                data_dir=settings.data_dir,
                work_dir=settings.data_dir / "export-work" / "luts",
            )
        except LutMissingError as exc:
            raise StudioExportError(
                "A LUT file is missing. Choose the .cube again in Bild, or clear the look.",
                code="lut_missing",
            ) from exc
    detail = (
        ffmpeg_detail_chain(clip.detail) if clip.kind in {"photo", "video"} else ""
    )
    ramp = (
        ffmpeg_saturation_ramp(clip.saturation_ramp, origin_s=0.0)
        if clip.kind == "video"
        else ""
    )
    prefix = ""
    suffix = ""
    slow = _slow_timing(clip)
    trim = ""
    stretch = ""
    frame_origin = 0.0
    frame_duration = clip.duration_s
    if slow is not None:
        trim, stretch, frame_origin, frame_duration = slow
    if (
        clip.kind in {"photo", "video"}
        and clip.zoom_span is not None
        and not clip.frame.is_neutral
    ):
        source_w, source_h = _source_frame_size(clip)
        prefix = ffmpeg_zoom_window(
            clip.frame,
            clip.zoom_span[0],
            clip.zoom_span[1],
            source_width=source_w,
            source_height=source_h,
        )
    elif clip.kind in {"photo", "video"} and not clip.frame.is_neutral:
        source_w, source_h = _source_frame_size(clip)
        prefix = ffmpeg_frame_prefix(
            clip.frame,
            source_width=source_w,
            source_height=source_h,
            kind=clip.kind,
            source_start_s=frame_origin,
            duration_s=frame_duration,
        )
        suffix = ffmpeg_frame_suffix(
            clip.frame,
            frame_width=width,
            frame_height=height,
            source_width=source_w,
            source_height=source_h,
            kind=clip.kind,
            source_start_s=frame_origin,
            duration_s=frame_duration,
        )
    return ",".join(
        part
        for part in (trim, grade, lut, detail, ramp, prefix, base, suffix, stretch)
        if part
    )


def _hud_filter_text(clip: StudioExportClip, height: int) -> str:
    """Elapsed time and altitude for a video whose HUD preset is on.

    An empty string leaves the existing grade, mask, and overlay chain alone.
    """
    if clip.kind != "video" or not clip.hud_enabled:
        return ""
    from orga_drone.studio_hud import ffmpeg_hud_chain
    from orga_drone.studio_title_card import TitleCardFontError, resolve_title_card_font

    try:
        font = resolve_title_card_font()
    except TitleCardFontError as exc:
        raise StudioExportError(
            "Telemetry HUD could not be rendered because no font was found.",
            code="hud_font_missing",
        ) from exc
    origin = 0.0 if _slow_timing(clip) is not None else float(clip.source_start_s)
    return ffmpeg_hud_chain(
        fontfile=font,
        height=height,
        intervals=clip.hud_intervals,
        origin_s=origin,
    )


_COMPLEX_FILTER_FLAGS = frozenset({"-filter_complex", "-filter_complex_script"})


def _uses_filter_graph(filters: list[str]) -> bool:
    """True when ffmpeg already maps the filtered ``[vout]`` stream.

    A long HUD chain is written to ``-filter_complex_script``. That flag is
    the same graph as ``-filter_complex`` and must not be followed by a map
    of the raw input picture.
    """
    return bool(filters) and filters[0] in _COMPLEX_FILTER_FLAGS


def _complex_graph_body(filters: list[str]) -> str:
    if filters[0] == "-filter_complex_script":
        return Path(filters[1]).read_text(encoding="utf-8")
    return filters[1]


def _linear_filter_body(filters: list[str]) -> str | None:
    """Comma-separated chain from ``-vf`` or a spilled ``-filter_script:v`` file.

    A telemetry HUD longer than the inline limit is the same chain as ``-vf``.
    The flight map has to read that file before it can sit on the picture.
    """
    if not filters:
        return None
    if filters[0] == "-vf":
        return filters[1]
    if filters[0] == "-filter_script:v":
        return Path(filters[1]).read_text(encoding="utf-8").rstrip("\r\n")
    return None


def _filter_args(body: str, work: Path, *, complex_graph: bool) -> list[str]:
    from orga_drone.studio_hud import video_filter_args

    return video_filter_args(
        body,
        script_path=work / f"filters-{uuid.uuid4().hex}.txt",
        complex_graph=complex_graph,
    )


def _chain_with_hud(chain: str, hud: str, fades: list[str]) -> str:
    parts = [chain]
    if hud:
        parts.append(hud)
    parts.extend(fades)
    return ",".join(part for part in parts if part)


def _graph_with_hud(graph: str, hud: str) -> str:
    if not hud:
        return graph
    from orga_drone.studio_hud import HudGraphError, insert_hud_chain

    try:
        return insert_hud_chain(graph, hud)
    except HudGraphError as exc:
        raise StudioExportError(
            "Telemetry HUD could not be rendered.",
            code="hud_render_failed",
        ) from exc


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
    body = _linear_filter_body(filters)
    if body is not None:
        for fade in reversed(fades):
            token = "," + fade
            if body.endswith(token):
                body = body[: -len(token)]
        picture = "pic"
        prefix = f"[0:v]{body}[{picture}]"
    elif _uses_filter_graph(filters):
        picture, prefix = _picture_before_format(_complex_graph_body(filters))
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
    return [*extra, *map_args], _filter_args(graph, work, complex_graph=True)


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
    hud = _hud_filter_text(clip, height)

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
                frame=clip.frame,
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
            return [], _filter_args(
                _chain_with_hud(chain, hud, fades),
                work,
                complex_graph=False,
            )
        graph, _count = privacy_graph(include_tail=True)
        return [], _filter_args(
            _graph_with_hud(graph, hud),
            work,
            complex_graph=True,
        )

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

    origin = (
        0.0
        if _slow_timing(clip) is not None
        else filter_time_origin(kind=clip.kind, source_start_s=clip.source_start_s)
    )
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
    extra_out, filters = _attach_flight_map(
        clip,
        width,
        height,
        work,
        extra,
        ["-filter_complex", graph, "-map", "[vout]"],
    )
    if _uses_filter_graph(filters):
        body = _graph_with_hud(_complex_graph_body(filters), hud)
        return extra_out, _filter_args(body, work, complex_graph=True)
    return extra_out, filters


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
            frame=clip.frame,
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


# Bundled FFmpeg 7.1 xfade custom expr returns a pixel. Measured on a red-to-blue
# blend: A is the incoming sample and B is the outgoing sample. P*P*(3-2*P) is
# smoothstep, so the incoming picture eases in, moves through the middle, and
# settles. transition=fade stays the linear crossfade.
XFADE_SMOOTH_EXPR = "B*(1-P*P*(3-2*P))+A*(P*P*(3-2*P))"


def _xfade_video(left: str, right: str, out: str, overlap: float, offset: float, curve: str) -> str:
    if curve == "smooth":
        return (
            f"[{left}][{right}]xfade=transition=custom:expr={XFADE_SMOOTH_EXPR}:"
            f"duration={overlap:.4f}:offset={offset:.4f}[{out}]"
        )
    return (
        f"[{left}][{right}]xfade=transition=fade:"
        f"duration={overlap:.4f}:offset={offset:.4f}[{out}]"
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
                _xfade_video(
                    left_v,
                    right_v,
                    v_out,
                    overlap,
                    offset,
                    outgoing.transition_curve,
                )
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


EXPORT_DESTINATION_PROTECTED = (
    "Export destination matches a library source or project asset. "
    "Choose a different file so the original is not overwritten."
)


def canonical_path_key(path: Path | str) -> str:
    """Absolute, symlink-resolved path key. Comparison is case-insensitive."""
    expanded = Path(path).expanduser()
    try:
        resolved = Path(os.path.realpath(expanded))
    except (OSError, ValueError):
        resolved = expanded.absolute()
    return os.path.normcase(os.path.normpath(str(resolved)))


def destination_matches_protected(
    dest: Path, protected: Iterable[Path | str]
) -> bool:
    """True when ``dest`` is the same file as any protected path.

    Matches resolved paths, Windows case aliases, symlinks, and hard links.
    """
    dest_key = canonical_path_key(dest)
    try:
        dest_exists = dest.exists()
    except OSError:
        dest_exists = False
    for raw in protected:
        other = Path(raw)
        try:
            if canonical_path_key(other) == dest_key:
                return True
        except (OSError, ValueError):
            continue
        if not dest_exists:
            continue
        try:
            if other.exists() and os.path.samefile(dest, other):
                return True
        except OSError:
            continue
    return False


def reject_protected_export_destination(
    dest: Path, protected: Iterable[Path | str]
) -> None:
    """Refuse to publish an export onto a source or other protected file."""
    if destination_matches_protected(dest, protected):
        raise StudioExportError(EXPORT_DESTINATION_PROTECTED)


# Test seam. Called immediately before a protected path is identified.
before_protected_identity: Callable[[Path], None] | None = None
# Test seam. Called immediately before an exclusive claim, after the name
# looked free. Runs while the mutation lock is held; it must not take that lock.
before_export_claim: Callable[[Path], None] | None = None

_MAX_EXPORT_NAME_TRIES = 10000
EXPORT_NO_FREE_NAME = "Export could not find a free file name."


def _protected_identities(
    protected: Iterable[Path | str],
) -> tuple[tuple[int, int], ...]:
    """File identities of protected originals that are present and readable.

    Missing or unreadable paths are skipped. An export never writes an existing
    file, so a missing catalog path does not block a free name. The caller holds
    ``hold_media_mutation`` when this snapshot must stay consistent with an
    in-app rename.
    """
    found: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for raw in protected:
        path = Path(raw)
        hook = before_protected_identity
        if hook is not None:
            hook(path)
        try:
            is_file = path.is_file()
        except OSError:
            is_file = False
        if not is_file:
            continue
        identity = _file_identity(path)
        if identity is None or identity in seen:
            continue
        seen.add(identity)
        found.append(identity)
    return tuple(found)


def _merge_identities(
    *groups: Iterable[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    found: list[tuple[int, int]] = []
    for group in groups:
        for identity in group:
            if identity not in found:
                found.append(identity)
    return tuple(found)


def export_candidate_names(dest: Path) -> Iterable[Path]:
    """Yield ``dest``, then ``stem_1.suffix``, ``stem_2.suffix``, and so on."""
    yield dest
    stem = dest.stem
    suffix = dest.suffix
    for number in range(1, _MAX_EXPORT_NAME_TRIES):
        yield dest.with_name(f"{stem}_{number}{suffix}")


def _file_identity(path: Path) -> tuple[int, int] | None:
    """Device and file id, or None when the id is missing or not reliable."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return _identity_from_stat(st)


def _identity_from_stat(st: os.stat_result) -> tuple[int, int] | None:
    if not stat.S_ISREG(st.st_mode):
        return None
    ino = int(st.st_ino)
    if ino <= 0:
        return None
    return (int(st.st_dev), ino)


class _ExportNameTaken(Exception):
    """The candidate name was claimed by another file before publish."""


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _publish_export_file(
    partial: Path,
    dest: Path,
    *,
    protected: Iterable[Path | str] = (),
    protected_identities: Iterable[tuple[int, int]] = (),
) -> Path:
    """Create a new file for ``partial``. Never replace an existing file.

    The requested name is used when it is free and not a protected original,
    asset, or soundtrack. Otherwise the next numbered name is claimed
    exclusively. A name that appears between the check and the claim is left
    untouched, and the next free name is tried. The caller must not hold the
    mutation lock; this function holds it only around the claim.
    """
    protected_ids = set(protected_identities)
    with hold_media_mutation():
        for candidate in export_candidate_names(dest):
            if destination_matches_protected(candidate, protected):
                continue
            identity = _file_identity(candidate)
            if identity is not None and identity in protected_ids:
                continue
            if identity is not None or _path_exists(candidate):
                continue
            hook = before_export_claim
            if hook is not None:
                hook(candidate)
            try:
                _claim_new_export_file(partial, candidate)
            except _ExportNameTaken:
                continue
            return candidate
    raise StudioExportError(EXPORT_NO_FREE_NAME)


def _claim_new_export_file(partial: Path, dest: Path) -> None:
    """Create ``dest`` only while the name is still absent."""
    try:
        os.link(partial, dest)
        return
    except FileExistsError as exc:
        raise _ExportNameTaken from exc
    except OSError as exc:
        if _already_exists(exc) or _path_exists(dest):
            raise _ExportNameTaken from exc
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(dest, flags)
    except FileExistsError as exc:
        raise _ExportNameTaken from exc
    except OSError as exc:
        if _already_exists(exc) or _path_exists(dest):
            raise _ExportNameTaken from exc
        raise StudioExportError(f"Export failed: {exc}") from exc
    try:
        written = _copy_file_into_fd(fd, partial)
        if written <= 0:
            raise StudioExportError("Export failed: empty output.")
        os.ftruncate(fd, written)
        os.fsync(fd)
    except Exception:
        os.close(fd)
        try:
            dest.unlink()
        except OSError:
            pass
        raise
    os.close(fd)


def _unlink_export_temp(path: Path) -> None:
    """Remove a temp export file without failing the export.

    Windows can return WinError 32 while a killed ffmpeg still holds the file.
    A short retry covers that. Cleanup must not replace a successful publish
    or a cancel with that lock error.
    """
    for attempt in range(3):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError as exc:
            winerror = getattr(exc, "winerror", None)
            locked = winerror in {5, 32} or exc.errno in {
                errno.EACCES,
                errno.EPERM,
                errno.EBUSY,
            }
            if not locked or attempt == 2:
                return
            time.sleep(0.05)


def _already_exists(exc: OSError) -> bool:
    if isinstance(exc, FileExistsError):
        return True
    if exc.errno == errno.EEXIST:
        return True
    winerror = getattr(exc, "winerror", None)
    return winerror == 183


def _copy_file_into_fd(fd: int, source: Path) -> int:
    written = 0
    with source.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise StudioExportError("Export failed: could not write output.")
                view = view[count:]
                written += count
    return written


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


def _forward_loop_slices(clip: StudioExportClip) -> tuple[StudioExportClip, ...]:
    """One encode per forward play, last play trimmed to the soundtrack.

    The returned clips have ``forward_loop`` cleared so rendering them does
    not recurse. A single full play is still a new clip object for that reason.
    A positive ``forward_transition_s`` marks a forward crossfade on every
    join except the last slice. Fades stay on the first and last play.
    The story transition on the parent clip is not copied onto those joins.
    """
    from orga_drone.studio_forward_loop import plan_forward_loop
    from orga_drone.studio_speed import coerce_playback_speed

    cycle = float(clip.forward_cycle_s or 0.0)
    overlap = float(clip.forward_transition_s or 0.0)
    plan = plan_forward_loop(cycle, float(clip.duration_s), overlap)
    if plan is None:
        return (replace(clip, forward_loop=False, section_repeats=1),)
    speed = coerce_playback_speed(clip.playback_speed)
    start = max(0.0, float(clip.source_start_s))
    if clip.source_end_s is not None:
        source_cycle = max(0.0, float(clip.source_end_s) - start)
    else:
        source_cycle = max(0.0, cycle * speed)
    spans = plan.output_spans()
    if not spans:
        return (replace(clip, forward_loop=False, section_repeats=1),)
    last = len(spans) - 1
    join = float(plan.overlap_s) if plan.play_count > 1 else 0.0
    slices: list[StudioExportClip] = []
    for index, output_s in enumerate(spans):
        if plan.partial_s > 0 and index == last and cycle > 0:
            source_span = source_cycle * (float(output_s) / cycle)
        else:
            source_span = source_cycle
        cross = join > 0 and index < last
        curve = clip.forward_transition_curve if cross else "linear"
        slices.append(
            replace(
                clip,
                duration_s=float(output_s),
                source_start_s=start,
                source_end_s=start + source_span,
                section_repeats=1,
                forward_loop=False,
                forward_cycle_s=0.0,
                forward_transition_s=0.0,
                forward_transition_curve="linear",
                exact_span=True,
                transition_type="crossfade" if cross else "cut",
                transition_s=join if cross else 0.0,
                transition_curve="smooth" if curve == "smooth" else "linear",
                fade_in_s=clip.fade_in_s if index == 0 else 0.0,
                fade_out_s=clip.fade_out_s if index == last else 0.0,
            )
        )
    return tuple(slices)


def section_repeat_slices(clip: StudioExportClip) -> tuple[StudioExportClip, ...]:
    """Expand a video into one encode per play of its in/out range.

    One repeat returns the clip unchanged, so ordinary exports stay on the
    existing path. Each extra play is the same source span at the same speed.
    Fades stay on the first and last play. Joins between plays are cuts,
    or a forward crossfade when the clip carries a loop overlap.

    A forward loop joins those plays with a cut, or with a forward crossfade
    when the clip carries an overlap. Its last play is shorter when the
    soundtrack is not an integer multiple of the stepped cycle. The soundtrack
    is not restarted here; it is mixed once after the picture is joined.
    """
    if clip.forward_loop:
        return _forward_loop_slices(clip)
    repeats = int(clip.section_repeats or 1)
    if clip.kind != "video" or repeats <= 1:
        return (clip,)
    repeats = max(1, min(MAX_SECTION_REPEATS, repeats))
    start = max(0.0, float(clip.source_start_s))
    if clip.source_end_s is not None:
        cycle = max(0.0, float(clip.source_end_s) - start)
    else:
        cycle = max(0.0, float(clip.duration_s) / repeats)
    if cycle <= 0:
        return (clip,)
    # Story transitions stay on the assembled clip. Joins inside the repeat
    # follow the loop effect, which is a hard cut when no overlap is set.
    join = float(clip.forward_transition_s or 0.0) if repeats > 1 else 0.0
    if join >= cycle:
        join = 0.0
    slices: list[StudioExportClip] = []
    last = repeats - 1
    for index in range(repeats):
        cross = join > 0 and index < last
        curve = clip.forward_transition_curve if cross else "linear"
        slices.append(
            replace(
                clip,
                duration_s=cycle,
                section_repeats=1,
                forward_loop=False,
                forward_transition_s=0.0,
                forward_transition_curve="linear",
                exact_span=True,
                transition_type="crossfade" if cross else "cut",
                transition_s=join if cross else 0.0,
                transition_curve="smooth" if curve == "smooth" else "linear",
                fade_in_s=clip.fade_in_s if index == 0 else 0.0,
                fade_out_s=clip.fade_out_s if index == last else 0.0,
            )
        )
    return tuple(slices)


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
        """Render ``config`` to a new file.

        The returned path is the file that was created. An existing file,
        including ``config.output_path`` when that name is taken, is not
        replaced. Must not modify source media, overlay images, or soundtrack
        files. When ``cancel_event`` is set, stop the work and leave existing
        files untouched.
        """


def export_progress_percent(
    *,
    clip_index: int,
    clip_total: int,
    phase: str,
    clip_fraction: float = 0.0,
) -> int:
    """Map clip encodes and the final concat re-encode onto one bar.

    Each clip is one step. Concat re-encodes the whole story and is one more
    step of the same weight, so a single clip is half the bar until that
    second pass reports time. ``clip_fraction`` is 0..1 inside the current
    step: ffmpeg output time divided by that step's real duration, not twice
    that duration. ``done`` is 100 when the file is published. Earlier phases
    stay under 100.
    """
    total_steps = max(1, int(clip_total) + 1)
    if phase == "done":
        return 100
    if phase == "concat":
        frac = max(0.0, min(1.0, float(clip_fraction)))
        value = 100.0 * (float(max(0, int(clip_total))) + frac) / total_steps
        return max(0, min(99, int(round(value))))
    if phase == "mixing":
        # Concat has already filled its step. Mixing copies the picture.
        return 99
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
        dest = config.output_path.expanduser().resolve()
        parent = dest.parent
        if not parent.is_dir():
            raise StudioExportError("Export folder does not exist.")
        if not os_access_writable(parent):
            raise StudioExportError("Export folder is not writable.")
        protected = [
            *_config_protected_paths(config),
            *[Path(path) for path in config.protected_paths],
        ]
        protected_identities = config.protected_identities
        with hold_media_mutation():
            source_identities = _protected_identities(protected)
            protected_identities = _merge_identities(
                config.protected_identities, source_identities
            )
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise StudioExportError(
                "ffmpeg is not available. Install ffmpeg or use a build that includes it."
            )

        clip_total = len(config.clips)
        tmp_dir = Path(tempfile.mkdtemp(prefix="orga-drone-export-"))
        tmp_out = tmp_dir / "export_tmp.mp4"
        partial = parent / f".{dest.name}.{uuid.uuid4().hex}.partial"
        try:
            chosen_quality = coerce_export_quality(config.quality)
        except ValueError as exc:
            raise StudioExportError(str(exc)) from exc
        token = _cancel_event.set(cancel_event)
        quality_token = _encode_quality.set(chosen_quality)
        try:
            _raise_if_cancelled()
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
            self._concat_or_stitch(
                ffmpeg,
                segments,
                tmp_out,
                config,
                on_progress=on_progress,
                clip_total=clip_total,
            )
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
            published = _publish_export_file(
                partial,
                dest,
                protected=protected,
                protected_identities=protected_identities,
            )
            _emit(
                on_progress,
                phase="done",
                clip_index=clip_total,
                clip_total=clip_total,
                current_label=None,
            )
            return published
        except StudioExportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StudioExportError(f"Export failed: {exc}") from exc
        finally:
            _unlink_export_temp(partial)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _encode_quality.reset(quality_token)
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
            from orga_drone.studio_color_animation import expand_export_clip_for_color

            pieces: list[StudioExportClip] = []
            for slow_piece in _slow_pieces(clip):
                pieces.extend(expand_export_clip_for_color(slow_piece))  # type: ignore[arg-type]
            if len(pieces) == 1:
                self._render_video(
                    ffmpeg,
                    pieces[0],
                    out,
                    width,
                    height,
                    on_progress=on_progress,
                    clip_index=clip_index,
                    clip_total=clip_total,
                )
                return
            paths: list[Path] = []
            for index, piece in enumerate(pieces):
                piece_out = out.with_name(f"{out.stem}-fx{index}.mp4")
                self._render_video(
                    ffmpeg,
                    piece,
                    piece_out,
                    width,
                    height,
                    on_progress=on_progress,
                    clip_index=clip_index,
                    clip_total=clip_total,
                )
                paths.append(piece_out)
            self._concat(
                ffmpeg,
                paths,
                out,
                duration_s=sum(piece.duration_s for piece in pieces),
            )
            for path in paths:
                path.unlink(missing_ok=True)

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
        phase: str = "rendering",
    ) -> Callable[[float], None] | None:
        if on_progress is None:
            return None
        label = _clip_progress_label(clip) if phase == "rendering" else None

        def _on_time(media_s: float) -> None:
            # Denominator is this step's real duration (clip or concat output).
            frac = 0.0 if duration_s <= 0 else max(0.0, min(1.0, media_s / duration_s))
            _emit(
                on_progress,
                phase=phase,
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
        uses_graph = _uses_filter_graph(filters)
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

    def _render_slow_video(
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
        """Encode one slowed section with muted source audio.

        ``trim`` selects the source range. ``setpts`` holds those frames.
        Silence replaces the source track so concat stays stereo AAC without
        time-stretching the original sound.
        """
        speed = coerce_playback_speed(clip.playback_speed)
        _start, _end, output_dur = source_span_s(
            source_start_s=clip.source_start_s,
            source_end_s=clip.source_end_s,
            output_duration_s=clip.duration_s,
            speed=speed,
        )
        dur = max(0.1, output_dur)
        on_time = self._progress_cb(
            on_progress,
            clip=clip,
            clip_index=clip_index,
            clip_total=clip_total,
            duration_s=dur,
        )
        extra, filters = _segment_filter_invocation(clip, width, height, out.parent)
        overlay_count = extra.count("-i")
        audio_index = 1 + overlay_count
        uses_graph = _uses_filter_graph(filters)
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(clip.source_path),
            *extra,
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
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
            cmd.extend(["-map", f"{audio_index}:a:0"])
        else:
            cmd.extend(["-map", "0:v:0", "-map", f"{audio_index}:a:0"])
        cmd.append(str(out))
        _run_ffmpeg(cmd, on_time=on_time, duration_s=dur)

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
        slices = section_repeat_slices(clip)
        if not (len(slices) == 1 and slices[0] is clip):
            if len(slices) == 1:
                self._render_video(
                    ffmpeg,
                    slices[0],
                    out,
                    width,
                    height,
                    on_progress=on_progress,
                    clip_index=clip_index,
                    clip_total=clip_total,
                )
                return
            parts: list[Path] = []
            for index, slice_clip in enumerate(slices):
                _raise_if_cancelled()
                part = out.parent / f"{out.stem}-loop-{index:04d}{out.suffix}"
                self._render_video(
                    ffmpeg,
                    slice_clip,
                    part,
                    width,
                    height,
                    on_progress=on_progress,
                    clip_index=clip_index,
                    clip_total=clip_total,
                )
                parts.append(part)
            _raise_if_cancelled()
            if any(
                part.transition_type == "crossfade" and part.transition_s > 0
                for part in slices[:-1]
            ):
                self._stitch_parts(ffmpeg, parts, out, slices)
            else:
                self._concat(ffmpeg, parts, out)
            return
        if _slow_timing(clip) is not None:
            self._render_slow_video(
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
        start = max(0.0, float(clip.source_start_s))
        if clip.source_end_s is not None:
            end = float(clip.source_end_s)
            span = end - start
            dur = span if clip.exact_span else max(0.1, span)
        else:
            dur = float(clip.duration_s) if clip.exact_span else max(0.1, float(clip.duration_s))
        if clip.exact_span:
            dur = max(0.05, dur)
        on_time = self._progress_cb(
            on_progress,
            clip=clip,
            clip_index=clip_index,
            clip_total=clip_total,
            duration_s=dur,
        )
        extra, filters = _segment_filter_invocation(clip, width, height, out.parent)
        overlay_count = extra.count("-i")
        uses_graph = _uses_filter_graph(filters)
        # Prefer accurate cuts on HEVC/DJI: decode then seek (slower, correct).
        # Explicit maps: DJI files often carry an attached JPEG that must not win.
        cmd = [
            ffmpeg,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(clip.source_path),
            *extra,
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
            *export_audio_args(
                video_start_s=start,
                video_duration_s=dur,
                detached=clip.detached_audio,
                slow=False,
            ),
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
                "-ss",
                f"{start:.3f}",
                "-i",
                str(clip.source_path),
                *extra,
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
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

    def _concat(
        self,
        ffmpeg: str,
        segments: list[Path],
        out: Path,
        *,
        on_time: Callable[[float], None] | None = None,
        duration_s: float | None = None,
    ) -> None:
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
        _run_ffmpeg(cmd, on_time=on_time, duration_s=duration_s)

    def _concat_or_stitch(
        self,
        ffmpeg: str,
        segments: list[Path],
        out: Path,
        config: StudioExportConfig,
        *,
        on_progress: ProgressCallback | None = None,
        clip_total: int = 0,
    ) -> None:
        story_s = _export_story_length_s(config.clips)
        total = clip_total if clip_total > 0 else len(config.clips)
        on_time: Callable[[float], None] | None = None
        if story_s > 0 and config.clips and total > 0:
            on_time = self._progress_cb(
                on_progress,
                clip=config.clips[-1],
                clip_index=total,
                clip_total=total,
                duration_s=story_s,
                phase="concat",
            )
        if _has_crossfade(config.clips):
            self._stitch(
                ffmpeg,
                segments,
                out,
                config,
                on_time=on_time,
                duration_s=story_s if story_s > 0 else None,
            )
            return
        self._concat(
            ffmpeg,
            segments,
            out,
            on_time=on_time,
            duration_s=story_s if story_s > 0 else None,
        )

    def _stitch_parts(
        self,
        ffmpeg: str,
        segments: list[Path],
        out: Path,
        clips: tuple[StudioExportClip, ...] | list[StudioExportClip],
    ) -> None:
        """Crossfade forward-loop plays. Source audio stays a hard cut."""
        self._stitch(
            ffmpeg,
            segments,
            out,
            StudioExportConfig(
                output_path=out,
                width=1,
                height=1,
                clips=tuple(clips),
            ),
        )

    def _stitch(
        self,
        ffmpeg: str,
        segments: list[Path],
        out: Path,
        config: StudioExportConfig,
        *,
        on_time: Callable[[float], None] | None = None,
        duration_s: float | None = None,
    ) -> None:
        """Join segments with concat and xfade. Source audio hard-cuts only."""
        clips = config.clips
        if len(segments) != len(clips):
            raise StudioExportError("Export stitch mismatch.")
        if len(segments) == 1:
            shutil.copyfile(segments[0], out)
            if on_time is not None and duration_s is not None and duration_s > 0:
                on_time(duration_s)
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
            _run_ffmpeg(cmd, on_time=on_time, duration_s=duration_s)
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
        # A forward loop already made the picture as long as one soundtrack
        # pass. Do not restart that audio at the video joins or after it.
        video_fills_soundtrack = any(clip.forward_loop for clip in config.clips)
        use_loop = (
            len(tracks) == 1 and bool(single.loop) and not video_fills_soundtrack
        )
        cmd: list[str] = [ffmpeg, "-y", "-i", str(concat_path)]
        if use_loop:
            filter_complex = build_music_amix_filter(
                volume=single.volume,
                fade_in_s=single.fade_in_s,
                fade_out_s=single.fade_out_s,
                story_s=story_s,
                music_s=probed[0],
                loop=True,
                start_s=config.music_start_s,
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
                start_s=config.music_start_s,
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


def _config_protected_paths(config: StudioExportConfig) -> list[Path]:
    """Files this encode reads and must not replace.

    Clip media, soundtrack files, image overlays, and a font the encode will
    open. Comparison includes canonical paths and hard-link aliases.
    """
    protected: list[Path] = []
    needs_font = False
    for clip in config.clips:
        if clip.source_path is not None:
            protected.append(clip.source_path)
        if clip.kind == "title_card":
            needs_font = True
        for overlay in clip.overlays:
            if overlay.kind == "image" and overlay.asset_name:
                asset = _overlay_asset_path(overlay.asset_name)
                if asset is not None:
                    protected.append(asset)
            elif overlay.kind == "text" and overlay.text.strip():
                needs_font = True
    for track in config.music_tracks:
        protected.append(track.source_path)
    if needs_font:
        font = _export_font_path()
        if font is not None:
            protected.append(font)
    return protected


def _overlay_asset_path(asset_name: str) -> Path | None:
    from orga_drone.config import settings
    from orga_drone.studio_overlay import resolve_overlay_asset

    try:
        return resolve_overlay_asset(settings.data_dir, asset_name)
    except (ValueError, OSError):
        return None


def _export_font_path() -> Path | None:
    from orga_drone.studio_title_card import TitleCardFontError, resolve_title_card_font

    try:
        return resolve_title_card_font()
    except (TitleCardFontError, OSError):
        return None


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
                        stripped = line.strip()
                        # progress=end means this encode finished. Snap to the
                        # real step duration so the bar is not left on a short
                        # last out_time (half the story, then a jump to done).
                        if duration_s is not None and stripped.startswith("progress=end"):
                            last_emit = duration_s
                            on_time(duration_s)
                            continue
                        if "=" in line and stripped.startswith(
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
        proc = popen
        if proc is not None and event is not None:
            _unbind_export_process(event, proc)
        stdout = getattr(proc, "stdout", None) if proc is not None else None
        close = getattr(stdout, "close", None)
        if callable(close) and callable(getattr(stdout, "fileno", None)):
            try:
                close()
            except OSError:
                pass
        poll = getattr(proc, "poll", None) if proc is not None else None
        if proc is not None and callable(poll) and poll() is None:
            _terminate_ffmpeg(proc)
        # A killed ffmpeg can still hold this temp file for a moment on Windows.
        _unlink_export_temp(err_path)


def get_default_encoder() -> StudioVideoEncoder:
    return FfmpegStudioEncoder()
