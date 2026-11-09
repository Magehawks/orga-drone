"""Ramp timing adapter around the existing picture builders and segment stitcher."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
import re

from orga_drone.export.studio_config import StudioExportClip
from orga_drone.studio_color_animation import expand_export_clip_for_color
from orga_drone.studio_forward_loop import plan_forward_loop


def ramp_passes(clip: StudioExportClip) -> list[tuple[StudioExportClip, float]]:
    """Expand source passes before color, retaining cumulative Story placement."""
    ramp = clip.speed_ramp
    assert ramp is not None and clip.source_end_s is not None
    start, end = clip.source_start_s, clip.source_end_s
    cycle = ramp.duration(start, end)
    join = float(clip.forward_transition_s)
    if clip.forward_loop:
        plan = plan_forward_loop(cycle, clip.duration_s, join)
        if plan is None:
            raise ValueError("invalid ramped loop")
        spans = plan.output_spans()
    else:
        spans = (cycle,) * max(1, clip.section_repeats)
    result = []
    cursor = 0.0
    for index, span in enumerate(spans):
        source_end = ramp.source_at(span, start, end)
        last = index == len(spans) - 1
        result.append(
            (
                replace(
                    clip,
                    source_end_s=source_end,
                    duration_s=span,
                    section_repeats=1,
                    forward_loop=False,
                    transition_type="crossfade" if join > 0 and not last else "cut",
                    transition_s=join if not last else 0,
                    transition_curve=clip.forward_transition_curve,
                ),
                cursor,
            )
        )
        cursor += span - (join if not last else 0)
    return result


def render_ramped_clip(
    encoder: Any,
    ffmpeg: str,
    clip: StudioExportClip,
    out: Path,
    width: int,
    height: int,
    **progress: Any,
) -> None:
    from orga_drone.export import studio_encoder as enc

    ramp = clip.speed_ramp
    assert ramp is not None and clip.source_end_s is not None
    pass_paths: list[Path] = []
    project_start = float(clip.export_frame_origin_s or 0)
    pass_configs: list[StudioExportClip] = []
    for pass_index, (one_pass, pass_start) in enumerate(ramp_passes(clip)):
        assert one_pass.source_end_s is not None
        # The unchanged color expander sees a normal source-speed pass.
        source_pass = replace(
            one_pass,
            speed_ramp=None,
            playback_speed=1,
            duration_s=one_pass.source_end_s - one_pass.source_start_s,
            slow_span=None,
            section_repeats=1,
            forward_loop=False,
            fade_in_s=0,
            fade_out_s=0,
        )
        source_origin = (
            clip.speed_ramp_source_in_s
            if clip.speed_ramp_source_in_s is not None
            else clip.source_start_s
        )
        object.__setattr__(
            source_pass, "color_local_origin", one_pass.source_start_s - source_origin
        )
        pieces = expand_export_clip_for_color(source_pass)
        paths: list[Path] = []
        piece_configs: list[StudioExportClip] = []
        total_frames = 0
        for piece_index, raw in enumerate(pieces):
            assert isinstance(raw, StudioExportClip) and raw.source_end_s is not None
            begin = (
                project_start
                + pass_start
                + ramp.duration(clip.source_start_s, raw.source_start_s)
            )
            finish = (
                project_start
                + pass_start
                + ramp.duration(clip.source_start_s, raw.source_end_s)
            )
            first_frame, last_frame = (
                int(begin * 30 + 0.5 + 1e-8),
                int(finish * 30 + 0.5 + 1e-8),
            )
            count = last_frame - first_frame
            if count <= 0:
                continue
            enc._raise_if_cancelled()
            path = out.with_name(f"{out.stem}-r{pass_index}-{piece_index}.mp4")
            _render_piece(
                encoder,
                ffmpeg,
                clip,
                raw,
                path,
                width,
                height,
                pass_start,
                first_frame,
                count,
                progress,
            )
            paths.append(path)
            piece_configs.append(
                replace(
                    raw,
                    duration_s=count / 30,
                    transition_type="cut",
                    transition_s=0,
                    export_frame_origin_s=first_frame / 30,
                    export_frame_count=count,
                )
            )
            total_frames += count
        if not paths:
            continue  # A subframe pass may own no sample on the project grid.
        pass_out = out.with_name(f"{out.stem}-r{pass_index}.mp4")
        if len(paths) == 1:
            paths[0].replace(pass_out)
        else:
            encoder._stitch_parts(ffmpeg, paths, pass_out, tuple(piece_configs))
        pass_paths.append(pass_out)
        end = project_start + pass_start + one_pass.duration_s
        from orga_drone.export.studio_frame_plan import frame_index

        overlap = frame_index(end) - frame_index(end - one_pass.transition_s)
        pass_configs.append(
            replace(
                one_pass,
                duration_s=total_frames / 30,
                transition_s=overlap / 30,
                export_frame_count=total_frames,
            )
        )
    if not pass_paths:
        raise enc.StudioExportError("The speed ramp is too short to export.")
    if len(pass_paths) == 1:
        pass_paths[0].replace(out)
    else:
        # Stitch video and audio independently: AAC packet padding must not
        # determine the next pass's video start, as in a demuxer concat.
        encoder._stitch_parts(ffmpeg, pass_paths, out, tuple(pass_configs))


def _render_piece(
    encoder: Any,
    ffmpeg: str,
    parent: StudioExportClip,
    piece: StudioExportClip,
    out: Path,
    width: int,
    height: int,
    pass_start: float,
    first_frame: int,
    count: int,
    progress: dict[str, Any],
) -> None:
    from orga_drone.export import studio_encoder as enc
    from orga_drone.studio_map import flight_map_overlay

    ramp = parent.speed_ramp
    assert ramp is not None and parent.source_end_s is not None
    assert piece.source_end_s is not None
    origin = (
        parent.speed_ramp_source_in_s
        if parent.speed_ramp_source_in_s is not None
        else parent.source_start_s
    )
    source_end = (
        parent.speed_ramp_source_out_s
        if parent.speed_ramp_source_out_s is not None
        else parent.source_end_s
    )
    source_picture = replace(
        piece,
        source_start_s=origin,
        source_end_s=source_end,
        duration_s=source_end - origin,
        speed_ramp=None,
        overlays=(),
        map_placement=replace(parent.map_placement, enabled=False),
        fade_in_s=0,
        fade_out_s=0,
        export_frame_count=None,
        export_frame_origin_s=None,
    )
    framing = None
    if parent.frame.is_animated or parent.zoom_span is not None:
        sw, sh = enc._source_frame_size(parent)
        frame = parent.frame
        duration = max(0.001, source_end - origin)
        u = f"min(1,max(0,t/{duration:.12g}))"
        zoom = (
            f"({frame.zoom_start:.12g}+({frame.zoom_end - frame.zoom_start:.12g})*{u})"
        )
        if parent.zoom_span is not None:
            a, b = parent.zoom_span
            zoom = f"if(between(t,{a:.12g},{b:.12g}),{max(frame.zoom_start, frame.zoom_end):.12g},1)"
        fx = f"({frame.x_start:.12g}+({frame.x_end - frame.x_start:.12g})*{u})"
        fy = f"({frame.y_start:.12g}+({frame.y_end - frame.y_start:.12g})*{u})"
        # zoompan regenerates timestamps at a fixed fps. Frame-evaluated scale
        # and crop preserve original sample PTS, including variable-rate input.
        framing = (
            f"scale=w='max({sw},ceil(iw*{zoom}/2)*2)':h='max({sh},ceil(ih*{zoom}/2)*2)':eval=frame,"
            f"crop=w={sw}:h={sh}:x='max(0,min(iw-{sw},{fx}*iw-{sw}/2))':"
            f"y='max(0,min(ih-{sh},{fy}*ih-{sh}/2))'"
        )
    extra, filters = enc._segment_filter_invocation(
        source_picture, width, height, out.parent, frame_chain=framing
    )
    assert not extra
    linear = enc._linear_filter_body(filters)
    body = (
        f"[0:v]{linear}[rsource]"
        if linear is not None
        else enc._complex_graph_body(filters).replace("[vout]", "[rsource]")
    )
    # Preserve input samples until nonlinear retiming. Pad on the source clock,
    # before setpts clears frame-rate metadata; the assigned count bounds the hold.
    body = re.sub(r"(?<![:\w])fps=30,", "", body)
    body = re.sub(r"\[0:v(?::0)?\]", "[rinput]", body)
    prefix = (
        f"[0:v]trim=start={piece.source_start_s:.9f}:end={piece.source_end_s:.9f},"
        f"tpad=stop_mode=clone:stop_duration=2,setpts=PTS-{origin:.12g}/TB[rinput];{body}"
    )

    def timing(variable: str) -> str:
        expression = ramp.ffmpeg_time(variable)
        start = float(parent.export_frame_origin_s or 0) + pass_start
        return (
            f"setpts='({start:.12g}+({expression})-{ramp.time_at(parent.source_start_s):.12g})/TB',"
            f"fps=30:start_time={first_frame / 30:.12g},setpts=N/(30*TB),"
            f"trim=end_frame={count}"
        )

    map_label = None
    if parent.map_placement.enabled:
        prefix += f";[rsource]split=2[rpicture][rmap];[rmap]format=rgba,colorchannelmixer=aa=0,setpts=PTS+{origin:.12g}/TB[rmapclock]"
        sw, sh = enc._source_frame_size(parent)
        map_inputs, fragment, label = flight_map_overlay(
            placement=parent.map_placement,
            track=parent.gps_track,
            media_duration_s=parent.media_duration_s,
            frame_width=width,
            frame_height=height,
            source_width=sw,
            source_height=sh,
            dest_dir=out.parent,
            first_input=1,
            picture_label="rmapclock",
            fps=30,
        )
        extra.extend(map_inputs)
        prefix += f";{fragment};[{label}]{timing('T')},format=rgba[rmaptime]"
        map_label = "rmaptime"
        picture = "rpicture"
    else:
        picture = "rsource"
    prefix += f";[{picture}]{timing(f'T+{origin:.12g}')}[rtime]"
    # Story overlays stay after retiming, including their animation clocks.
    local_start = (
        first_frame / 30 - float(parent.export_frame_origin_s or 0) - pass_start
    )
    # Keep the original Story clock through overlay animations, including when
    # a fade started in an earlier color piece. Negative fade starts are invalid.
    prefix += f";[rtime]settb=AVTB,setpts=(N/30+{local_start:.12g})/TB[rtimeStory]"
    cycle = ramp.duration(parent.source_start_s, parent.source_end_s)
    final = replace(
        piece,
        speed_ramp=None,
        source_start_s=0,
        source_end_s=count / 30,
        duration_s=cycle,
        masks=(),
        overlays=parent.overlays,
        hud_enabled=False,
        map_placement=replace(parent.map_placement, enabled=False),
        fade_in_s=0,
        fade_out_s=0,
        export_frame_count=None,
        export_frame_origin_s=None,
    )
    inputs, filters = enc._segment_filter_invocation(
        final, width, height, out.parent, prebuilt=(prefix, "rtimeStory", extra)
    )
    graph = enc._complex_graph_body(filters).replace("[vout]", "[rstory]")
    graph += ";[rstory]setpts=N/(30*TB)[rpiece]"
    output = "rpiece"
    if map_label:
        graph += f";[rpiece][{map_label}]overlay=0:0:format=auto[rjoined]"
        output = "rjoined"
    fades = []
    global_start = first_frame / 30 - float(parent.export_frame_origin_s or 0)
    if parent.fade_in_s > 0:
        fades.append(f"fade=t=in:st=0:d={parent.fade_in_s:.9f}")
    if parent.fade_out_s > 0:
        fades.append(
            f"fade=t=out:st={max(0, parent.duration_s - parent.fade_out_s):.9f}:d={parent.fade_out_s:.9f}"
        )
    tail = [
        "settb=AVTB",
        f"setpts=(N/30+{global_start:.12g})/TB",
        *fades,
        "setpts=N/(30*TB)",
        "format=yuv420p",
    ]
    graph += f";[{output}]" + ",".join(tail) + "[vout]"
    flags = enc._filter_args(graph, out.parent, complex_graph=True)
    audio = 1 + inputs.count("-i")
    duration = count / 30
    cmd = [
        ffmpeg,
        "-y",
        *(["-filter_complex_threads", "1"] if framing is not None else []),
        "-copyts",
        "-ss",
        f"{max(0, piece.source_start_s - 0.1):.9f}",
        "-t",
        f"{piece.source_end_s - max(0, piece.source_start_s - 0.1) + 0.1:.9f}",
        "-i",
        str(parent.source_path),
        *inputs,
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        *flags,
        "-map",
        f"{audio}:a:0",
        "-frames:v",
        str(count),
        "-r",
        "30",
        "-fps_mode",
        "cfr",
        "-t",
        f"{duration:.9f}",
        *enc._x264_video_args(),
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(out),
    ]
    callback = encoder._progress_cb(
        progress.get("on_progress"),
        clip=parent,
        clip_index=progress["clip_index"],
        clip_total=progress["clip_total"],
        duration_s=duration,
    )
    enc._run_ffmpeg(cmd, on_time=callback, duration_s=duration)
