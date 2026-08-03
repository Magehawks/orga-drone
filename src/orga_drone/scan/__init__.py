"""Scan library roots and index media into SQLite."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from orga_drone.auto_tags import apply_auto_tags_to_media
from orga_drone.db import Database, track_from_json, track_to_json
from orga_drone.group import (
    ClipForGrouping,
    ClipForSession,
    altitude_edges_from_track,
    attach_photos_to_sessions,
    group_clips_into_flows,
    group_clips_into_sessions,
)
from orga_drone.parse import (
    VIDEO_EXTS,
    PHOTO_EXTS,
    PROXY_EXTS,
    SUBTITLE_EXTS,
    live_photo_video_sidecars,
    parse_media_file,
)
from orga_drone.scan.progress import ProgressCallback, ScanProgress, display_scan_path

MEDIA_EXTS = VIDEO_EXTS | PHOTO_EXTS | PROXY_EXTS | SUBTITLE_EXTS


def iter_media_files(
    root: Path,
    on_found: ProgressCallback | None = None,
    *,
    root_id: int | None = None,
) -> list[Path]:
    """Collect media-extension files under ``root``.

    Optional ``on_found`` receives discovering progress (discovered count,
    UI-safe current path). Non-media files are not counted.
    """
    root_resolved = root.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in MEDIA_EXTS:
            continue
        files.append(path)
        if on_found is not None:
            on_found(
                ScanProgress(
                    phase="discovering",
                    discovered=len(files),
                    processed=0,
                    current_path=display_scan_path(path, root_resolved),
                    root_id=root_id,
                )
            )
    return sorted(files)


def _siblings(stem_base: str, by_stem: dict[str, list[Path]]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for p in by_stem.get(stem_base, []):
        found[p.suffix.lower()] = p
    return found


def _parse_recorded(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _clip_for_session(mid: int, row: dict) -> ClipForSession:
    start_rel, end_rel, start_lat, start_lon, end_lat, end_lon = altitude_edges_from_track(
        track_from_json(row.get("track_json"))
    )
    # Fall back to media abs_alt as a coarse start hint when SRT track lacks rel_alt.
    if start_rel is None and row.get("abs_alt") is not None:
        # abs_alt alone is not relative; leave None unless we only have abs.
        pass
    return ClipForSession(
        media_id=mid,
        recorded_at=_parse_recorded(row.get("recorded_at")),
        duration_s=row.get("duration_s"),
        flow_id=row.get("flow_id"),
        size_bytes=int(row.get("size_bytes") or 0),
        start_rel_alt=start_rel,
        end_rel_alt=end_rel,
        start_lat=start_lat if start_lat is not None else row.get("latitude"),
        start_lon=start_lon if start_lon is not None else row.get("longitude"),
        end_lat=end_lat,
        end_lon=end_lon,
    )


def _emit(
    on_progress: ProgressCallback | None,
    *,
    phase: str,
    discovered: int = 0,
    processed: int = 0,
    current_path: str | None = None,
    root_id: int | None = None,
) -> None:
    if on_progress is None:
        return
    on_progress(
        ScanProgress(
            phase=phase,
            discovered=discovered,
            processed=processed,
            current_path=current_path,
            root_id=root_id,
        )
    )


def scan_root(
    db: Database,
    root_id: int,
    root_path: Path,
    on_progress: ProgressCallback | None = None,
) -> dict[str, int]:
    root_path = root_path.resolve()
    _emit(on_progress, phase="discovering", discovered=0, processed=0, root_id=root_id)
    files = iter_media_files(root_path, on_progress, root_id=root_id)
    discovered = len(files)
    _emit(
        on_progress,
        phase="indexing",
        discovered=discovered,
        processed=0,
        root_id=root_id,
    )

    by_stem: dict[str, list[Path]] = {}
    for f in files:
        by_stem.setdefault(f.stem, []).append(f)

    live_sidecars = live_photo_video_sidecars(files)

    # Clear previous index for this root (simple full rescan for MVP)
    db.clear_root_media(root_id)

    counts = {"assets": 0, "videos": 0, "photos": 0, "live_sidecars": 0}

    for index, path in enumerate(files, start=1):
        parsed = parse_media_file(path)
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        # Live Photo companion MOV: keep as asset only, never as library video.
        asset_kind = parsed.kind
        if resolved in live_sidecars:
            asset_kind = "live_sidecar"

        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        asset_id = db.upsert_asset(
            root_id=root_id,
            path=path,
            kind=asset_kind,
            size_bytes=parsed.size_bytes,
            mtime=mtime,
            stem_base=parsed.stem_base,
        )
        counts["assets"] += 1

        if asset_kind == "live_sidecar":
            counts["live_sidecars"] += 1
            _emit(
                on_progress,
                phase="indexing",
                discovered=discovered,
                processed=index,
                current_path=display_scan_path(path, root_path),
                root_id=root_id,
            )
            continue

        if parsed.kind not in {"video", "photo"}:
            _emit(
                on_progress,
                phase="indexing",
                discovered=discovered,
                processed=index,
                current_path=display_scan_path(path, root_path),
                root_id=root_id,
            )
            continue

        sibs = _siblings(parsed.stem_base, by_stem)
        has_srt = ".srt" in sibs
        has_lrf = ".lrf" in sibs

        # If video lacked SRT parse because case mismatch, re-check
        if parsed.kind == "video" and not has_srt:
            # already handled in parser with .SRT/.srt
            pass

        recorded = parsed.recorded_at.isoformat(timespec="seconds") if parsed.recorded_at else None

        media_id = db.upsert_media(
            {
                "root_id": root_id,
                "primary_asset_id": asset_id,
                "kind": parsed.kind,
                "filename": path.name,
                "path": str(path.resolve()),
                "size_bytes": parsed.size_bytes,
                "duration_s": parsed.duration_s,
                "recorded_at": recorded,
                "sequence": parsed.sequence,
                "mode": parsed.mode,
                "drone_model": parsed.drone_model,
                "camera_model": parsed.camera_model,
                "source_type": parsed.source_type,
                "latitude": parsed.latitude,
                "longitude": parsed.longitude,
                "abs_alt": parsed.abs_alt,
                "has_srt": 1 if has_srt else 0,
                "has_lrf": 1 if has_lrf else 0,
                "track_json": track_to_json(parsed.track),
            }
        )
        # Re-attach user metadata that survived clear_root_media (path / identity).
        db.link_media_meta_for_path(
            str(path.resolve()),
            filename=path.name,
            size_bytes=parsed.size_bytes,
            recorded_at=recorded,
        )
        db.link_studio_item_for_path(
            str(path.resolve()),
            filename=path.name,
            size_bytes=parsed.size_bytes,
            recorded_at=recorded,
        )
        apply_auto_tags_to_media(
            db,
            media_id,
            recorded_at=recorded,
            latitude=parsed.latitude,
            longitude=parsed.longitude,
        )
        if parsed.kind == "video":
            counts["videos"] += 1
        else:
            counts["photos"] += 1

        _emit(
            on_progress,
            phase="indexing",
            discovered=discovered,
            processed=index,
            current_path=display_scan_path(path, root_path),
            root_id=root_id,
        )

    _emit(
        on_progress,
        phase="grouping",
        discovered=discovered,
        processed=discovered,
        current_path=None,
        root_id=root_id,
    )

    # Build flows for videos
    media_map = db.media_map_for_root(root_id)
    clips: list[ClipForGrouping] = []
    for mid, row in media_map.items():
        clips.append(
            ClipForGrouping(
                media_id=mid,
                recorded_at=_parse_recorded(row.get("recorded_at")),
                sequence=row.get("sequence"),
                size_bytes=int(row.get("size_bytes") or 0),
                duration_s=row.get("duration_s"),
            )
        )

    flows = group_clips_into_flows(clips)
    db.replace_flows_for_root(root_id, flows, media_map)

    # Rebuild map so flow_id is available for session grouping
    media_map = db.media_map_for_root(root_id)
    session_clips = [_clip_for_session(mid, row) for mid, row in media_map.items()]
    sessions = group_clips_into_sessions(session_clips)
    video_lookup = {c.media_id: c for c in session_clips}

    photo_map = db.media_map_for_root(root_id, kind="photo")
    photo_clips = [_clip_for_session(mid, row) for mid, row in photo_map.items()]
    sessions = attach_photos_to_sessions(sessions, video_lookup, photo_clips)

    all_media = db.media_map_for_root(root_id, kind=None)
    db.replace_sessions_for_root(root_id, sessions, all_media)
    db.mark_root_scanned(root_id)

    multi_flows = sum(1 for g in flows if len(g) > 1)
    multi_sessions = sum(
        1
        for g in sessions
        if sum(1 for mid in g if all_media.get(mid, {}).get("kind") == "video") > 1
    )
    counts["flows"] = multi_flows
    counts["sessions"] = multi_sessions
    _emit(
        on_progress,
        phase="done",
        discovered=discovered,
        processed=discovered,
        current_path=None,
        root_id=root_id,
    )
    return counts


def scan_all_roots(
    db: Database,
    on_progress: ProgressCallback | None = None,
) -> list[dict]:
    results = []
    for root in db.list_roots():
        path = Path(root["path"])
        if not path.exists():
            results.append({"root_id": root["id"], "path": root["path"], "error": "missing"})
            continue
        counts = scan_root(db, int(root["id"]), path, on_progress=on_progress)
        results.append({"root_id": root["id"], "path": root["path"], **counts})
    return results
