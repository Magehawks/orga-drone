"""Orchestrate Studio export options and rendering (Issue #17)."""

from __future__ import annotations

from pathlib import Path

from orga_drone.app_prefs import get_last_export_directory, set_last_export_directory
from orga_drone.config import settings
from orga_drone.db import Database, StudioClip
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import (
    ProgressCallback,
    StudioExportError,
    StudioVideoEncoder,
    get_default_encoder,
    os_access_writable,
)
from orga_drone.media_files import resolve_media_file
from orga_drone.studio_estimate import DEFAULT_PHOTO_DURATION_S, effective_seconds
from orga_drone.studio_export_resolution import (
    available_export_resolutions,
    default_export_height,
    height_to_width,
    resolve_export_directory,
    suggested_export_filename,
)


def probe_video_dimensions(path: Path) -> tuple[int | None, int | None]:
    """Best-effort width/height via ffprobe, or ffmpeg ``-i`` when ffprobe is absent.

    Bundled imageio-ffmpeg often ships only ``ffmpeg`` (no ffprobe). DJI files may
    also expose a small attached-pic stream; prefer the largest real video frame.
    """
    import json
    import re
    import subprocess

    from orga_drone.ffmpeg_bin import find_ffmpeg, find_ffprobe

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


def collect_project_video_heights(db: Database, project_id: int | None = None) -> list[int | None]:
    """Heights for available video clips in the Studio project."""
    heights: list[int | None] = []
    for clip in db.list_studio_items(project_id):
        if clip.kind != "video" or not clip.available or clip.media_id is None:
            continue
        media = db.get_media(clip.media_id)
        if media is None:
            heights.append(None)
            continue
        h = getattr(media, "height", None)
        if h is not None and int(h) > 0:
            heights.append(int(h))
            continue
        path = resolve_media_file(db, media)
        if path is None:
            heights.append(None)
            continue
        _w, probed_h = probe_video_dimensions(path)
        if probed_h is not None:
            db.update_media_dimensions(media.id, width=_w, height=probed_h)
        heights.append(probed_h)
    return heights


def build_export_options_payload(db: Database, project_id: int | None = None) -> dict:
    project = (
        db.get_studio_project(project_id)
        if project_id is not None
        else db.ensure_default_studio_project()
    )
    if project is None:
        raise StudioExportError("Studio project not found.")
    heights = collect_project_video_heights(db, project.id)
    options = available_export_resolutions(heights)
    default_h = default_export_height(heights)
    last_dir = get_last_export_directory()
    directory = resolve_export_directory(last_dir)
    return {
        "project_id": project.id,
        "project_title": project.title,
        "suggested_filename": suggested_export_filename(project.title),
        "default_directory": str(directory),
        "last_export_directory": last_dir,
        "default_height": default_h,
        "options": [o.as_dict() for o in options],
        "has_video_resolution": bool(options),
    }


def _clip_to_export_clip(db: Database, clip: StudioClip) -> StudioExportClip | None:
    if not clip.available or clip.media_id is None:
        return None
    media = db.get_media(clip.media_id)
    if media is None:
        return None
    path = resolve_media_file(db, media)
    if path is None:
        return None
    kind = clip.kind if clip.kind in {"photo", "video"} else media.kind
    seconds = effective_seconds(
        kind=kind or "unknown",
        photo_duration_s=clip.photo_duration_s,
        duration_s=clip.duration_s,
        available=True,
        source_in_s=clip.source_start,
        source_out_s=clip.source_end,
    )
    if seconds is None or seconds <= 0:
        if kind == "photo":
            seconds = (
                float(clip.photo_duration_s)
                if clip.photo_duration_s is not None
                else DEFAULT_PHOTO_DURATION_S
            )
        else:
            return None
    start = float(clip.source_start) if clip.source_start is not None else 0.0
    end = float(clip.source_end) if clip.source_end is not None else None
    return StudioExportClip(
        source_path=path,
        kind=kind or "video",
        duration_s=float(seconds),
        source_start_s=start,
        source_end_s=end,
    )


def prepare_studio_export(
    db: Database,
    *,
    height: int,
    output_path: Path,
    overwrite: bool = False,
    project_id: int | None = None,
) -> StudioExportConfig:
    """Validate export request and build a codec-agnostic config (no render)."""
    project = (
        db.get_studio_project(project_id)
        if project_id is not None
        else db.ensure_default_studio_project()
    )
    if project is None:
        raise StudioExportError("Studio project not found.")
    heights = collect_project_video_heights(db, project.id)
    options = available_export_resolutions(heights)
    allowed = {o.height for o in options}
    if int(height) not in allowed:
        raise StudioExportError("Selected export resolution is not available for this project.")
    width = height_to_width(int(height))
    dest = Path(output_path).expanduser()
    if dest.suffix.lower() != ".mp4":
        dest = dest.with_suffix(".mp4")
    dest = dest.resolve()
    if not dest.parent.is_dir():
        raise StudioExportError("Export folder does not exist.")
    if not os_access_writable(dest.parent):
        raise StudioExportError("Export folder is not writable.")
    if dest.exists() and not overwrite:
        raise StudioExportError("File already exists. Confirm overwrite to continue.")

    export_clips: list[StudioExportClip] = []
    for clip in db.list_studio_items(project.id):
        built = _clip_to_export_clip(db, clip)
        if built is not None:
            export_clips.append(built)
    if not export_clips:
        raise StudioExportError("No available media to export.")

    return StudioExportConfig(
        output_path=dest,
        width=width,
        height=int(height),
        clips=tuple(export_clips),
        project_title=project.title,
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
    encoder: StudioVideoEncoder | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    config = prepare_studio_export(
        db,
        height=height,
        output_path=output_path,
        overwrite=overwrite,
        project_id=project_id,
    )
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
        result = enc.render(config, on_progress=on_progress)
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
