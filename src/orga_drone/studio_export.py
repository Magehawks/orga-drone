"""Orchestrate Studio export options and rendering (Issue #17)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from orga_drone.app_prefs import (
    get_last_export_directory,
    get_last_export_quality,
    set_last_export_directory,
    set_last_export_quality,
)
from orga_drone.export.studio_quality import (
    DEFAULT_EXPORT_QUALITY,
    SHARE_EXPORT_QUALITY,
    coerce_export_quality,
    export_quality_ids,
)
from orga_drone.config import settings
from orga_drone.db import Database, MediaRow, StudioClip, StudioProject, track_from_json
from orga_drone.export.studio_config import (
    StudioExportClip,
    StudioExportConfig,
    StudioExportMusic,
)
from orga_drone.export.studio_encoder import (
    ProgressCallback,
    ExportCancelled,
    StudioExportError,
    StudioVideoEncoder,
    _protected_identities,
    get_default_encoder,
    os_access_writable,
)
from orga_drone.media_mutation import hold_media_mutation
from orga_drone.media_files import resolve_media_file
from orga_drone.studio_estimate import DEFAULT_PHOTO_DURATION_S, effective_seconds
from orga_drone.studio_frame import FrameTransform, frame_from_effect_settings
from orga_drone.studio_hud import HudInterval, hud_client_state
from orga_drone.studio_image import (
    ImageAdjust,
    image_adjust_from_effect_settings,
    saturation_ramp_from_effect_settings,
)
from orga_drone.studio_detail import detail_from_effect_settings
from orga_drone.studio_lut import color_look_from_effect_settings
from orga_drone.studio_map import gps_from_stored, map_from_effect_settings
from orga_drone.studio_mask import masks_from_effect_settings
from orga_drone.studio_overlay import overlays_from_effect_settings
from orga_drone.studio_export_resolution import (
    ExportResolutionOption,
    available_export_resolutions,
    default_export_height,
    generated_only_default_height,
    generated_only_export_resolutions,
    height_to_width,
    resolve_export_directory,
    suggested_export_filename,
)
from orga_drone.export.still_export import (
    SOCIAL_VIDEO_HEIGHT,
    SOCIAL_VIDEO_WIDTH,
    export_photo_file,
    inspect_photo_preset,
    normalize_share_preset,
)
from orga_drone.studio_title_card import TITLE_CARD_KIND, display_lines


def probe_video_dimensions(path: Path) -> tuple[int | None, int | None]:
    """Best-effort width/height via ffprobe, or ffmpeg ``-i`` when ffprobe is absent.

    Bundled imageio-ffmpeg often ships only ``ffmpeg`` (no ffprobe). DJI files may
    also expose a small attached-pic stream; prefer the largest real video frame.
    """
    import json
    import re
    import subprocess

    from orga_drone.ffmpeg_bin import (
        find_ffmpeg,
        find_ffprobe,
        subprocess_no_window_kwargs,
    )

    def _best(pairs: list[tuple[int, int]]) -> tuple[int | None, int | None]:
        if not pairs:
            return None, None
        w, h = max(pairs, key=lambda wh: wh[0] * wh[1])
        return w, h

    ffprobe = find_ffprobe()
    if ffprobe:
        cmd = [
            ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-select_streams",
            "v",
            str(path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                **subprocess_no_window_kwargs(),
            )
        except (OSError, subprocess.SubprocessError):
            proc = None
        if proc is not None and proc.returncode == 0 and proc.stdout:
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                data = None
            if data is not None:
                pairs: list[tuple[int, int]] = []
                for stream in data.get("streams") or []:
                    if stream.get("codec_type") not in (None, "video"):
                        continue
                    # Skip cover / attached pictures when disposition is present.
                    disp = stream.get("disposition") or {}
                    if isinstance(disp, dict) and int(disp.get("attached_pic") or 0):
                        continue
                    try:
                        w = (
                            int(stream["width"])
                            if stream.get("width") is not None
                            else None
                        )
                        h = (
                            int(stream["height"])
                            if stream.get("height") is not None
                            else None
                        )
                    except (TypeError, ValueError):
                        continue
                    if w and h and w > 0 and h > 0:
                        pairs.append((w, h))
                best = _best(pairs)
                if best[0] is not None:
                    return best

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None, None
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            **subprocess_no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    # ffmpeg prints stream info to stderr and exits non-zero without an output file.
    blob = f"{proc.stderr or ''}\n{proc.stdout or ''}"
    pairs_ff: list[tuple[int, int]] = []
    dim_re = re.compile(
        r"Stream\s+#\d+:\d+[^\n]*Video:\s+[^\n]*?(\d{2,5})x(\d{2,5})",
        re.IGNORECASE,
    )
    for match in dim_re.finditer(blob):
        line_start = blob.rfind("\n", 0, match.start()) + 1
        line = blob[line_start : blob.find("\n", match.start())]
        if "attached pic" in line.lower():
            continue
        try:
            w, h = int(match.group(1)), int(match.group(2))
        except ValueError:
            continue
        if w > 0 and h > 0:
            pairs_ff.append((w, h))
    return _best(pairs_ff)


def _resolve_export_project(db: Database, project_id: int | None) -> StudioProject:
    if project_id is not None:
        project = db.get_studio_project(project_id)
        if project is None:
            raise StudioExportError("Studio project not found.")
        return project
    project = db.resolve_studio_page_project()
    if project is None:
        raise StudioExportError("No Studio project is open.")
    return project


def media_frame_height(db: Database, media: MediaRow) -> int | None:
    """Stored frame height, or a one-time probe stored back on the media row."""
    stored = media.height
    if stored is not None and int(stored) > 0:
        return int(stored)
    path = resolve_media_file(db, media)
    if path is None:
        return None
    width, probed_h = probe_video_dimensions(path)
    if probed_h is not None:
        db.update_media_dimensions(media.id, width=width, height=probed_h)
    return probed_h


def collect_project_video_heights(
    db: Database, project_id: int | None = None
) -> list[int | None]:
    """Heights for available video clips in the Studio project."""
    heights: list[int | None] = []
    for clip in db.list_studio_items(project_id):
        if clip.kind != "video" or not clip.available or clip.media_id is None:
            continue
        media = db.get_media(clip.media_id)
        if media is None:
            heights.append(None)
            continue
        heights.append(media_frame_height(db, media))
    return heights


def _project_has_title_cards(db: Database, project_id: int) -> bool:
    return any(
        clip.item_kind == TITLE_CARD_KIND for clip in db.list_studio_items(project_id)
    )


def _project_has_available_photos(db: Database, project_id: int) -> bool:
    return any(
        clip.kind == "photo" and clip.available and clip.media_id is not None
        for clip in db.list_studio_items(project_id)
    )


def _unlock_generated_only_resolutions(db: Database, project_id: int) -> bool:
    """Title cards or photos may unlock 720/1080 when no video heights exist."""
    return _project_has_title_cards(db, project_id) or _project_has_available_photos(
        db, project_id
    )


def build_export_options_payload(db: Database, project_id: int | None = None) -> dict:
    project = _resolve_export_project(db, project_id)
    heights = collect_project_video_heights(db, project.id)
    options = available_export_resolutions(heights)
    default_h = default_export_height(heights)
    if not options and _unlock_generated_only_resolutions(db, project.id):
        options = generated_only_export_resolutions()
        default_h = generated_only_default_height()
    last_dir = get_last_export_directory()
    directory = resolve_export_directory(last_dir)
    try:
        default_quality = coerce_export_quality(get_last_export_quality())
    except ValueError:
        default_quality = DEFAULT_EXPORT_QUALITY
    option_rows: list[dict[str, int | str | bool]] = []
    for option in options:
        row = option.as_dict()
        row["suggested_filename"] = suggested_export_filename(
            project.title, height=option.height
        )
        option_rows.append(row)
    suggested = suggested_export_filename(
        project.title, height=default_h if default_h is not None else None
    )
    return {
        "project_id": project.id,
        "project_title": project.title,
        "suggested_filename": suggested,
        "default_directory": str(directory),
        "last_export_directory": last_dir,
        "default_height": default_h,
        "default_quality": default_quality,
        "qualities": list(export_quality_ids()),
        "options": option_rows,
        "has_video_resolution": bool(options),
    }


def _clip_to_export_clip(
    db: Database,
    clip: StudioClip,
    *,
    locale: str = "en",
    forward: object | None = None,
) -> StudioExportClip | None:
    if clip.item_kind == TITLE_CARD_KIND or clip.kind == TITLE_CARD_KIND:
        seconds = effective_seconds(
            kind=TITLE_CARD_KIND,
            photo_duration_s=None,
            duration_s=clip.duration_s,
            available=True,
            card_duration_s=clip.card_duration_s,
        )
        if seconds is None or seconds <= 0:
            return None
        primary, secondary = display_lines(clip.title_text, clip.subtitle_text, locale)
        return StudioExportClip(
            source_path=None,
            kind=TITLE_CARD_KIND,
            duration_s=float(seconds),
            title_text=clip.title_text or "",
            subtitle_text=clip.subtitle_text or "",
            background=clip.background or "dark",
            locale=locale,
            label=primary or secondary or "Title card",
        )
    if not clip.available or clip.media_id is None:
        return None
    media = db.get_media(clip.media_id)
    if media is None:
        return None
    path = resolve_media_file(db, media)
    if path is None:
        return None
    kind = clip.kind if clip.kind in {"photo", "video"} else media.kind
    from orga_drone.studio_speed import coerce_playback_speed
    from orga_drone.studio_cut import section_repeats_from_effect_settings

    speed = coerce_playback_speed(clip.playback_speed) if kind == "video" else 1.0
    repeats = (
        section_repeats_from_effect_settings(clip.effect_settings)
        if kind == "video"
        else 1
    )
    forward_active = False
    forward_cycle = 0.0
    forward_total_s = 0.0
    forward_total = getattr(forward, "total_s", None)
    forward_cycle_raw = getattr(forward, "cycle_s", None)
    if (
        kind == "video"
        and getattr(forward, "active", False)
        and getattr(forward, "item_id", None) == clip.id
        and isinstance(forward_total, (int, float))
        and not isinstance(forward_total, bool)
        and isinstance(forward_cycle_raw, (int, float))
        and not isinstance(forward_cycle_raw, bool)
        and float(forward_total) > 0
        and float(forward_cycle_raw) > 0
    ):
        forward_active = True
        forward_cycle = float(forward_cycle_raw)
        forward_total_s = float(forward_total)
        repeats = 1
    from orga_drone.studio_forward_loop import (
        _playback_bounds,
        applied_join_s,
        loop_transition_curve,
    )

    play_in, play_out, media_path = _playback_bounds(clip)
    if play_in is None:
        play_in = clip.source_start
    if play_out is None:
        play_out = clip.source_end
    one_play = effective_seconds(
        kind=kind or "unknown",
        photo_duration_s=clip.photo_duration_s,
        duration_s=clip.duration_s,
        available=True,
        source_in_s=play_in,
        source_out_s=play_out,
        playback_speed=speed,
        section_repeats=1,
        effect_settings=clip.effect_settings if kind == "video" else None,
    )
    seconds = effective_seconds(
        kind=kind or "unknown",
        photo_duration_s=clip.photo_duration_s,
        duration_s=clip.duration_s,
        available=True,
        source_in_s=play_in,
        source_out_s=play_out,
        playback_speed=speed,
        section_repeats=repeats,
        effect_settings=clip.effect_settings if kind == "video" else None,
    )
    if forward_active:
        seconds = forward_total_s
    if seconds is None or seconds <= 0:
        if kind == "photo":
            seconds = (
                float(clip.photo_duration_s)
                if clip.photo_duration_s is not None
                else DEFAULT_PHOTO_DURATION_S
            )
        else:
            return None
    start = float(play_in) if play_in is not None else 0.0
    end = float(play_out) if play_out is not None else None
    loop_join = 0.0
    if kind == "video" and one_play is not None and not forward_active and repeats > 1:
        loop_join = applied_join_s(
            clip.effect_settings,
            float(one_play),
            path=media_path,
            source_in_s=float(clip.source_start) if clip.source_start is not None else None,
            source_out_s=float(clip.source_end) if clip.source_end is not None else None,
        )
        if loop_join > 0 and seconds is not None:
            seconds = float(seconds) - loop_join * (repeats - 1)
    image = (
        image_adjust_from_effect_settings(clip.effect_settings)
        if kind in {"photo", "video"}
        else ImageAdjust()
    )
    color_look = (
        color_look_from_effect_settings(clip.effect_settings)
        if kind in {"photo", "video"}
        else color_look_from_effect_settings(None)
    )
    detail = (
        detail_from_effect_settings(clip.effect_settings)
        if kind in {"photo", "video"}
        else detail_from_effect_settings(None)
    )
    overlay_span = one_play if kind == "video" and one_play else seconds
    saturation_ramp = (
        saturation_ramp_from_effect_settings(clip.effect_settings)
        if kind == "video"
        else saturation_ramp_from_effect_settings(None)
    )
    overlays = (
        overlays_from_effect_settings(
            clip.effect_settings, duration_s=float(overlay_span)
        )
        if kind in {"photo", "video"} and overlay_span
        else ()
    )
    masks = (
        masks_from_effect_settings(clip.effect_settings)
        if kind in {"photo", "video"}
        else ()
    )
    frame = (
        frame_from_effect_settings(clip.effect_settings)
        if kind in {"photo", "video"}
        else FrameTransform()
    )
    placement = (
        map_from_effect_settings(clip.effect_settings)
        if kind in {"photo", "video"}
        else map_from_effect_settings(None)
    )
    gps_track = (
        gps_from_stored(
            track_from_json(media.track_json),
            latitude=media.latitude,
            longitude=media.longitude,
        )
        if kind in {"photo", "video"}
        else ()
    )
    hud_enabled = False
    hud_intervals: tuple[HudInterval, ...] = ()
    if kind == "video":
        hud_state = hud_client_state(
            path,
            effect_settings=clip.effect_settings,
            source_start_s=start,
            source_end_s=end,
            media_duration_s=None,
            fallback_duration_s=float(seconds),
        )
        if hud_state["enabled"] is True and hud_state["available"] is True:
            hud_enabled = True
            raw_intervals = hud_state["intervals"]
            if isinstance(raw_intervals, list):
                hud_intervals = tuple(
                    HudInterval(
                        start_s=float(row["start"]),
                        end_s=float(row["end"]),
                        altitude_m=float(row["alt"]),
                    )
                    for row in raw_intervals
                    if isinstance(row, dict)
                )
    zoom_span = None
    slow_span = None
    detached = None
    if kind == "video" and end is not None:
        from orga_drone.studio_audio import detached_audio_from_effect_settings
        from orga_drone.studio_effect_lane import slow_bar, zoom_bar

        source_len = max(0.0, float(end) - float(start))
        zoom = zoom_bar(clip.effect_settings, source_len)
        if zoom is not None and not (
            zoom.start_s <= 0.05 and zoom.end_s >= source_len - 0.05
        ):
            zoom_span = (zoom.start_s, zoom.end_s)
        slowed = slow_bar(clip.effect_settings, source_len, speed)
        if slowed is not None:
            full = slowed.start_s <= 0.05 and slowed.end_s >= source_len - 0.05
            if full:
                speed = slowed.speed
            else:
                slow_span = (slowed.start_s, slowed.end_s, slowed.speed)
                speed = 1.0
        detached = detached_audio_from_effect_settings(clip.effect_settings)
        if detached is not None and not detached.is_heard:
            detached = None
    return StudioExportClip(
        source_path=path,
        kind=kind or "video",
        duration_s=float(seconds),
        source_start_s=start,
        source_end_s=end,
        playback_speed=speed,
        zoom_span=zoom_span,
        slow_span=slow_span,
        detached_audio=detached,
        section_repeats=repeats if kind == "video" else 1,
        forward_loop=forward_active,
        forward_cycle_s=forward_cycle if forward_active else 0.0,
        forward_transition_s=(
            float(getattr(getattr(forward, "plan", None), "overlap_s", 0.0) or 0.0)
            if forward_active
            else loop_join
        ),
        forward_transition_curve=(
            loop_transition_curve(clip.effect_settings) if kind == "video" else "linear"
        ),
        image=image,
        color_look=color_look,
        detail=detail,
        saturation_ramp=saturation_ramp,
        frame=frame,
        masks=masks,
        overlays=overlays,
        map_placement=placement,
        gps_track=gps_track,
        media_duration_s=media.duration_s,
        hud_enabled=hud_enabled,
        hud_intervals=hud_intervals,
    )


def _protected_export_paths(db: Database) -> list[Path]:
    """Indexed sources, soundtrack files, overlay assets, and the database."""
    paths = [Path(item) for item in db.protected_export_paths()]
    overlay_root = settings.data_dir / "overlay-assets"
    lut_root = settings.data_dir / "luts"
    try:
        if overlay_root.is_dir():
            paths.extend(path for path in overlay_root.iterdir() if path.is_file())
        if lut_root.is_dir():
            paths.extend(path for path in lut_root.iterdir() if path.is_file())
    except OSError:
        return paths
    return paths


def _snapshot_export_destination(
    db: Database,
    output_path: Path,
    *,
    overwrite: bool,
    suffix: str,
) -> tuple[Path, tuple[tuple[int, int], ...], tuple[str, ...]]:
    """Resolve a destination. ``overwrite`` is ignored.

    An existing file is never replaced. The protected snapshot is fixed here.
    The lock is not held while clips are built or while encoding runs.
    """
    _ = overwrite
    dest = Path(output_path).expanduser()
    if dest.suffix.lower() != suffix.lower():
        dest = dest.with_suffix(suffix)
    dest = dest.resolve()
    if not dest.parent.is_dir():
        raise StudioExportError("Export folder does not exist.")
    if not os_access_writable(dest.parent):
        raise StudioExportError("Export folder is not writable.")
    protected_paths = _protected_export_paths(db)
    with hold_media_mutation():
        protected_identities = _protected_identities(protected_paths)
    return dest, protected_identities, tuple(str(path) for path in protected_paths)


def prepare_studio_export(
    db: Database,
    *,
    height: int,
    output_path: Path,
    overwrite: bool = False,
    project_id: int | None = None,
    quality: str | None = None,
) -> StudioExportConfig:
    """Validate export request and build a codec-agnostic config (no render)."""
    project = _resolve_export_project(db, project_id)
    heights = collect_project_video_heights(db, project.id)
    options = available_export_resolutions(heights)
    if not options and _unlock_generated_only_resolutions(db, project.id):
        options = generated_only_export_resolutions()
    allowed = {o.height for o in options}
    if int(height) not in allowed:
        raise StudioExportError(
            "Selected export resolution is not available for this project."
        )
    try:
        chosen_quality = coerce_export_quality(quality)
    except ValueError as exc:
        raise StudioExportError(str(exc)) from exc
    width = height_to_width(int(height))
    dest, protected_identities, protected_path_strs = _snapshot_export_destination(
        db,
        output_path,
        overwrite=overwrite,
        suffix=".mp4",
    )

    from orga_drone.studio_forward_loop import resolve_forward_loop, soundtrack_once_s

    export_clips: list[StudioExportClip] = []
    source_items: list[StudioClip] = []
    source_rows = db.list_studio_items(project.id)
    forward = resolve_forward_loop(
        source_rows, soundtrack_once_s(db.list_studio_music(project.id))
    )
    for clip in source_rows:
        built = _clip_to_export_clip(db, clip, forward=forward)
        if built is not None:
            export_clips.append(built)
            source_items.append(clip)
    if not export_clips:
        raise StudioExportError("No available media to export.")

    from dataclasses import replace

    from orga_drone.studio_transition import (
        apply_boundaries,
        fade_in_s,
        fade_out_s,
    )

    durs = [c.duration_s for c in export_clips]
    types = [it.transition for it in source_items]
    stored_d = [it.transition_duration_s for it in source_items]
    applied = apply_boundaries(durs, types, stored_d)
    decorated: list[StudioExportClip] = []
    for index, built in enumerate(export_clips):
        incoming = applied[index - 1] if index > 0 else None
        outgoing = applied[index] if index < len(applied) else None
        decorated.append(
            replace(
                built,
                transition_type=outgoing.type if outgoing is not None else "cut",
                transition_s=outgoing.duration_s if outgoing is not None else 0.0,
                fade_in_s=fade_in_s(incoming),
                fade_out_s=fade_out_s(outgoing),
            )
        )
    export_clips = decorated

    from orga_drone.export.music_mix import require_readable_music

    music_rows = db.list_studio_music(project.id)
    music_tracks: list[StudioExportMusic] = []
    single_loop = len(music_rows) == 1
    for music_row in music_rows:
        music_path = Path(music_row.file_path)
        duration_s = require_readable_music(music_path)
        music_tracks.append(
            StudioExportMusic(
                source_path=music_path,
                volume=float(music_row.volume),
                fade_in_s=float(music_row.fade_in_s),
                fade_out_s=float(music_row.fade_out_s),
                loop=bool(music_row.loop) and single_loop,
                duration_s=duration_s,
            )
        )

    set_last_export_quality(chosen_quality)
    return StudioExportConfig(
        output_path=dest,
        width=width,
        height=int(height),
        quality=chosen_quality,
        clips=tuple(export_clips),
        project_title=project.title,
        music_tracks=tuple(music_tracks),
        music_start_s=project.music_start_s,
        protected_identities=protected_identities,
        protected_paths=protected_path_strs,
    )


def append_export_log(message: str) -> None:
    """Append a short line to the local Studio export log (for support/debugging)."""
    try:
        log_dir = settings.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "studio-export.log"
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message.rstrip()}\n")
    except OSError:
        return


def run_studio_export(
    db: Database,
    *,
    height: int,
    output_path: Path,
    overwrite: bool = False,
    project_id: int | None = None,
    quality: str | None = None,
    encoder: StudioVideoEncoder | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    config = prepare_studio_export(
        db,
        height=height,
        output_path=output_path,
        overwrite=overwrite,
        project_id=project_id,
        quality=quality,
    )
    return _execute_export_config(
        config,
        encoder=encoder,
        on_progress=on_progress,
        cancel_event=cancel_event,
    )


def _execute_export_config(
    config: StudioExportConfig,
    *,
    encoder: StudioVideoEncoder | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    if on_progress is not None:
        on_progress(
            {
                "phase": "preparing",
                "clip_index": 0,
                "clip_total": len(config.clips),
                "percent": 0,
            }
        )
    enc = encoder or get_default_encoder()
    try:
        result = enc.render(
            config,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
    except ExportCancelled:
        append_export_log(
            f"CANCEL title={config.project_title!r} height={config.height} "
            f"clips={len(config.clips)} dest={config.output_path}"
        )
        raise
    except StudioExportError as exc:
        append_export_log(
            f"FAIL title={config.project_title!r} height={config.height} "
            f"clips={len(config.clips)} dest={config.output_path} error={exc}"
        )
        raise
    except Exception as exc:
        append_export_log(
            f"FAIL title={config.project_title!r} height={config.height} "
            f"clips={len(config.clips)} dest={config.output_path} error={exc}"
        )
        raise
    set_last_export_directory(result.parent)
    append_export_log(
        f"OK title={config.project_title!r} height={config.height} "
        f"clips={len(config.clips)} dest={result}"
    )
    return result


@dataclass(frozen=True)
class MediaExportPlan:
    """Validated one-file export. A photo has no encoder config."""

    kind: str
    preset: str
    output_path: Path
    config: StudioExportConfig | None = None
    protected_identities: tuple[tuple[int, int], ...] = ()
    protected_paths: tuple[str, ...] = ()


def _require_export_media(db: Database, media_id: int) -> tuple[MediaRow, Path]:
    media = db.get_media(int(media_id))
    if media is None:
        raise StudioExportError("Media not found.")
    if media.kind not in {"photo", "video"}:
        raise StudioExportError("This item cannot be exported.")
    from orga_drone.scan import offline_root_ids

    if int(media.root_id) in offline_root_ids(db):
        raise StudioExportError("The source file is not available.")
    path = resolve_media_file(db, media)
    if path is None:
        raise StudioExportError("The source file is not available.")
    return media, path


def _export_stem(media: MediaRow) -> str:
    stem = Path(media.filename).stem.strip()
    return stem or "export"


def _best_video_option(heights: list[int | None]) -> ExportResolutionOption:
    options = available_export_resolutions(heights)
    if not options:
        raise StudioExportError("No exportable resolution for this file.")
    return max(options, key=lambda option: option.height)


def _preset_filename(stem: str, preset: str, *, suffix: str, height: int | None = None, size_tag: str | None = None) -> str:
    label = preset if not size_tag else f"{preset}_{size_tag}"
    return suggested_export_filename(stem, height=height, suffix=suffix, label=label)


def build_media_export_options_payload(db: Database, media_id: int) -> dict:
    """Resolution or still presets for one library photo or video."""
    media, path = _require_export_media(db, media_id)
    stem = _export_stem(media)
    last_dir = get_last_export_directory()
    directory = resolve_export_directory(last_dir)
    presets: list[dict[str, object]] = []
    if media.kind == "photo":
        for preset in ("best", "whatsapp", "instagram", "tiktok"):
            spec = inspect_photo_preset(path, preset)
            size_tag = None
            if preset == "instagram":
                size_tag = "1080x1350"
            elif preset == "tiktok":
                size_tag = "1080x1920"
            presets.append(
                {
                    "id": preset,
                    "suggested_filename": _preset_filename(
                        stem, preset, suffix=spec.suffix, size_tag=size_tag
                    ),
                    "width": spec.width,
                    "height": spec.height,
                    "copied": spec.copied,
                }
            )
        default_preset = "best"
    else:
        heights = [media_frame_height(db, media)]
        try:
            best = _best_video_option(heights)
        except StudioExportError:
            best = None
        if best is not None:
            presets.append(
                {
                    "id": "best",
                    "suggested_filename": _preset_filename(
                        stem, "best", suffix=".mp4", height=best.height
                    ),
                    "width": best.width,
                    "height": best.height,
                    "copied": False,
                }
            )
        size_tag = f"{SOCIAL_VIDEO_WIDTH}x{SOCIAL_VIDEO_HEIGHT}"
        for preset in ("whatsapp", "instagram", "tiktok"):
            presets.append(
                {
                    "id": preset,
                    "suggested_filename": _preset_filename(
                        stem, preset, suffix=".mp4", size_tag=size_tag
                    ),
                    "width": SOCIAL_VIDEO_WIDTH,
                    "height": SOCIAL_VIDEO_HEIGHT,
                    "copied": False,
                }
            )
        default_preset = "best" if best is not None else "whatsapp"
    if not presets:
        raise StudioExportError("No exportable resolution for this file.")
    return {
        "media_id": media.id,
        "filename": media.filename,
        "kind": media.kind,
        "default_directory": str(directory),
        "last_export_directory": last_dir,
        "default_preset": default_preset,
        "presets": presets,
    }


def _video_export_config(
    db: Database,
    media: MediaRow,
    path: Path,
    *,
    preset: str,
    output_path: Path,
    overwrite: bool,
) -> StudioExportConfig:
    if preset == "best":
        option = _best_video_option([media_frame_height(db, media)])
        width, height = option.width, option.height
    else:
        width, height = SOCIAL_VIDEO_WIDTH, SOCIAL_VIDEO_HEIGHT
    seconds = effective_seconds(
        kind="video",
        photo_duration_s=None,
        duration_s=media.duration_s,
        available=True,
    )
    if seconds is None or seconds <= 0:
        raise StudioExportError("This file has no exportable duration.")
    dest, protected_identities, protected_paths = _snapshot_export_destination(
        db,
        output_path,
        overwrite=overwrite,
        suffix=".mp4",
    )
    clip = StudioExportClip(
        source_path=path,
        kind="video",
        duration_s=float(seconds),
        source_start_s=0.0,
        source_end_s=None,
        playback_speed=1.0,
        section_repeats=1,
        media_duration_s=media.duration_s,
    )
    return StudioExportConfig(
        output_path=dest,
        width=width,
        height=height,
        quality=SHARE_EXPORT_QUALITY,
        clips=(clip,),
        project_title=_export_stem(media),
        music_tracks=(),
        protected_identities=protected_identities,
        protected_paths=protected_paths,
    )


def prepare_media_export(
    db: Database,
    media_id: int,
    *,
    preset: str,
    output_path: Path,
    overwrite: bool = False,
    image: ImageAdjust | None = None,
    still_format: str | None = None,
) -> MediaExportPlan:
    """Validate one photo or video export. Does not render.

    ``image`` grades a photo before the preset. None uses the saved grade.
    A video ignores both the grade and ``still_format``.
    """
    key = normalize_share_preset(preset)
    media, path = _require_export_media(db, media_id)
    if media.kind == "photo":
        adjust = image if image is not None else db.get_image_adjust(path)
        spec = inspect_photo_preset(path, key, image=adjust, still_format=still_format)
        dest, identities, protected = _snapshot_export_destination(
            db,
            output_path,
            overwrite=overwrite,
            suffix=spec.suffix,
        )
        return MediaExportPlan(
            kind="photo",
            preset=key,
            output_path=dest,
            protected_identities=identities,
            protected_paths=protected,
        )
    config = _video_export_config(
        db,
        media,
        path,
        preset=key,
        output_path=output_path,
        overwrite=overwrite,
    )
    return MediaExportPlan(
        kind="video",
        preset=key,
        output_path=config.output_path,
        config=config,
        protected_identities=config.protected_identities,
        protected_paths=config.protected_paths,
    )


def run_media_export(
    db: Database,
    media_id: int,
    *,
    preset: str,
    output_path: Path,
    overwrite: bool = False,
    encoder: StudioVideoEncoder | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    image: ImageAdjust | None = None,
    still_format: str | None = None,
) -> Path:
    """Export one library photo as a still, or one video through the Studio encoder.

    ``image`` grades a photo before the preset. None uses the saved grade.
    A video ignores both the grade and ``still_format``.
    """
    media, path = _require_export_media(db, media_id)
    adjust = image
    fmt = None
    if media.kind == "photo":
        if adjust is None:
            adjust = db.get_image_adjust(path)
        fmt = still_format
    plan = prepare_media_export(
        db,
        media_id,
        preset=preset,
        output_path=output_path,
        overwrite=overwrite,
        image=adjust,
        still_format=fmt,
    )
    if plan.kind == "photo":
        if on_progress is not None:
            on_progress(
                {
                    "phase": "preparing",
                    "clip_index": 1,
                    "clip_total": 1,
                    "percent": 0,
                }
            )
        media, path = _require_export_media(db, media_id)
        try:
            result = export_photo_file(
                path,
                plan.output_path,
                plan.preset,
                protected=plan.protected_paths,
                protected_identities=plan.protected_identities,
                cancel_event=cancel_event,
                image=adjust,
                still_format=fmt,
            )
        except ExportCancelled:
            append_export_log(
                f"CANCEL title={_export_stem(media)!r} preset={plan.preset} dest={plan.output_path}"
            )
            raise
        except StudioExportError as exc:
            append_export_log(
                f"FAIL title={_export_stem(media)!r} preset={plan.preset} "
                f"dest={plan.output_path} error={exc}"
            )
            raise
        set_last_export_directory(result.parent)
        append_export_log(
            f"OK title={_export_stem(media)!r} preset={plan.preset} dest={result}"
        )
        return result
    if plan.config is None:
        raise StudioExportError("This item cannot be exported.")
    return _execute_export_config(
        plan.config,
        encoder=encoder,
        on_progress=on_progress,
        cancel_event=cancel_event,
    )
