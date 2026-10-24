"""Scan library roots and index media into SQLite.

A rescan still walks a listable root and rebuilds flows and sessions.
Metadata extraction is skipped when an indexed file has the same size and
mtime. Issue #96 does not define a content fingerprint; those filesystem
signals are the skip check. If a root cannot be listed, or disappears
before the index is replaced, catalog entries stay and the source is
offline. Files, user metadata, and Studio clips are never deleted.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

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
    ParsedMedia,
    live_photo_video_sidecars,
    parse_media_file,
    should_index_as_library_video,
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
    start_rel, end_rel, start_lat, start_lon, end_lat, end_lon = (
        altitude_edges_from_track(track_from_json(row.get("track_json")))
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


def _empty_scan_counts() -> dict[str, int]:
    return {
        "assets": 0,
        "videos": 0,
        "photos": 0,
        "live_sidecars": 0,
        "non_video": 0,
        "flows": 0,
        "sessions": 0,
        "unchanged": 0,
        "removed": 0,
        "unavailable": 0,
        "offline": 0,
        "preserved": 0,
    }


def root_source_available(path: Path) -> bool:
    """True when ``path`` is a directory that can be listed.

    A missing drive, disconnected share, or other OS error is unavailable.
    An empty directory that lists successfully is available, so a later scan
    can treat files that are gone as confirmed deletions.
    """
    try:
        with os.scandir(path) as entries:
            next(entries, None)
        return True
    except OSError:
        return False


def offline_root_ids(db: Database) -> set[int]:
    """Ids of library roots whose folder cannot be listed right now."""
    offline: set[int] = set()
    for root in db.list_roots():
        if not root_source_available(Path(str(root["path"]))):
            offline.add(int(root["id"]))
    return offline


def _offline_preserved() -> dict[str, int]:
    """Scan result that leaves the existing catalog rows in place."""
    counts = _empty_scan_counts()
    counts["unavailable"] = 1
    counts["offline"] = 1
    counts["preserved"] = 1
    return counts


def _finish_offline(
    on_progress: ProgressCallback | None,
    root_id: int,
) -> dict[str, int]:
    _emit(
        on_progress,
        phase="done",
        discovered=0,
        processed=0,
        current_path=None,
        root_id=root_id,
    )
    return _offline_preserved()


def _resolved_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _file_fingerprint(path: Path) -> tuple[int, float] | None:
    """Return ``(size_bytes, st_mtime)``.

    Issue #96 asks for a safe fingerprint but does not name one. Size plus
    mtime avoids hashing large videos. It is not a content hash: a same-size
    edit that also preserves mtime is not detected.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (int(st.st_size), float(st.st_mtime))


def _fingerprint_matches(
    indexed: dict[str, Any],
    fingerprint: tuple[int, float] | None,
) -> bool:
    if fingerprint is None or indexed.get("mtime") is None:
        return False
    size, mtime = fingerprint
    return int(indexed["size_bytes"]) == size and float(indexed["mtime"]) == mtime


def _reuse_unchanged_file(
    db: Database,
    *,
    indexed: dict[str, Any],
    path: Path,
    resolved: Path,
    by_stem: dict[str, list[Path]],
    live_sidecars: set[Path],
    counts: dict[str, int],
) -> bool:
    """Keep an indexed file when size and mtime match.

    Returns False when the row must be parsed again (missing media row, or a
    Live Photo companion that is no longer paired and needs classification).
    """
    kind = str(indexed["kind"])
    in_live = resolved in live_sidecars
    if kind == "video" and in_live:
        db.set_asset_kind(int(indexed["asset_id"]), "live_sidecar")
        media_id = indexed.get("media_id")
        if media_id is not None:
            db.delete_media_row(int(media_id))
        counts["assets"] += 1
        counts["live_sidecars"] += 1
        return True
    if kind == "live_sidecar" and not in_live:
        return False
    if kind in {"video", "photo"} and indexed.get("media_id") is None:
        return False

    counts["assets"] += 1
    counts["unchanged"] += 1
    if kind == "live_sidecar":
        counts["live_sidecars"] += 1
        return True
    if kind == "other":
        counts["non_video"] += 1
        return True
    if kind not in {"video", "photo"}:
        return True

    stem = indexed.get("stem_base") or path.stem
    sibs = _siblings(str(stem), by_stem)
    has_srt = ".srt" in sibs
    has_lrf = ".lrf" in sibs
    media_id = int(indexed["media_id"])
    if has_srt != bool(indexed.get("has_srt")) or has_lrf != bool(indexed.get("has_lrf")):
        db.set_media_sidecar_flags(media_id, has_srt=has_srt, has_lrf=has_lrf)
    if kind == "video":
        counts["videos"] += 1
    else:
        counts["photos"] += 1
    return True


def _must_reparse(
    indexed: dict[str, Any],
    resolved: Path,
    live_sidecars: set[Path],
) -> bool:
    """True when a size/mtime match still needs ``parse_media_file``."""
    kind = str(indexed["kind"])
    in_live = resolved in live_sidecars
    if kind == "live_sidecar" and not in_live:
        return True
    if kind in {"video", "photo"} and indexed.get("media_id") is None:
        return True
    return False


def scan_root(
    db: Database,
    root_id: int,
    root_path: Path,
    on_progress: ProgressCallback | None = None,
) -> dict[str, int]:
    """Index one library root.

    Unchanged files skip metadata extraction. If the source is missing or
    disappears before index rows are replaced, the existing catalog stays.
    An empty but listable folder is a confirmed deletion.
    """
    try:
        root_path = root_path.resolve()
    except OSError:
        return _finish_offline(on_progress, root_id)
    if not root_source_available(root_path):
        return _finish_offline(on_progress, root_id)

    _emit(on_progress, phase="discovering", discovered=0, processed=0, root_id=root_id)
    try:
        files = iter_media_files(root_path, on_progress, root_id=root_id)
    except OSError:
        if root_source_available(root_path):
            raise
        return _finish_offline(on_progress, root_id)
    if not root_source_available(root_path):
        return _finish_offline(on_progress, root_id)

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
    seen_paths = {str(_resolved_path(path)) for path in files}
    existing = db.indexed_assets_for_root(root_id)

    # Parse changed files before deleting index rows. A drive that drops
    # during this read must not wipe catalog rows from the last successful scan.
    # Unchanged files (size + mtime) are not parsed.
    prepared: list[tuple[Path, ParsedMedia, float | None]] = []
    reuse_paths: list[Path] = []
    try:
        for index, path in enumerate(files, start=1):
            resolved_key = _resolved_path(path)
            indexed = existing.get(str(resolved_key))
            if (
                indexed is not None
                and _fingerprint_matches(indexed, _file_fingerprint(path))
                and not _must_reparse(indexed, resolved_key, live_sidecars)
            ):
                reuse_paths.append(path)
            else:
                parsed = parse_media_file(path)
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = None
                prepared.append((path, parsed, mtime))
            _emit(
                on_progress,
                phase="indexing",
                discovered=discovered,
                processed=index,
                current_path=display_scan_path(path, root_path),
                root_id=root_id,
            )
    except OSError:
        if root_source_available(root_path):
            raise
        return _finish_offline(on_progress, root_id)
    if not root_source_available(root_path):
        return _finish_offline(on_progress, root_id)

    removed = db.remove_root_index_except(root_id, seen_paths)
    counts = _empty_scan_counts()
    counts["removed"] = removed

    for index, path in enumerate(reuse_paths, start=1):
        resolved_key = _resolved_path(path)
        indexed = existing.get(str(resolved_key))
        if indexed is None:
            continue
        _reuse_unchanged_file(
            db,
            indexed=indexed,
            path=path,
            resolved=resolved_key,
            by_stem=by_stem,
            live_sidecars=live_sidecars,
            counts=counts,
        )

    for index, (path, parsed, mtime) in enumerate(prepared, start=1):
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        # Live Photo companion MOV: keep as asset only, never as library video.
        asset_kind = parsed.kind
        if resolved in live_sidecars:
            asset_kind = "live_sidecar"
        elif parsed.kind == "video" and not should_index_as_library_video(path):
            # Video extension without a real motion video stream (e.g. HEVC
            # "Main Still Picture" poster MOVs). Keep as asset, skip media.
            asset_kind = "other"

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

        if asset_kind == "other" and parsed.kind == "video":
            counts["non_video"] += 1
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

        recorded = (
            parsed.recorded_at.isoformat(timespec="seconds")
            if parsed.recorded_at
            else None
        )
        stored_path = str(resolved)

        media_id = db.upsert_media(
            {
                "root_id": root_id,
                "primary_asset_id": asset_id,
                "kind": parsed.kind,
                "filename": path.name,
                "path": stored_path,
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
        # Relink user metadata and Studio clips for parsed paths (new, changed, or repaired).
        db.link_media_meta_for_path(
            stored_path,
            filename=path.name,
            size_bytes=parsed.size_bytes,
            recorded_at=recorded,
        )
        db.link_studio_item_for_path(
            stored_path,
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
        if not root_source_available(path):
            results.append(
                {
                    "root_id": root["id"],
                    "path": root["path"],
                    "error": "missing",
                    "offline": 1,
                    "preserved": 1,
                }
            )
            continue
        counts = scan_root(db, int(root["id"]), path, on_progress=on_progress)
        if counts.get("unavailable"):
            results.append(
                {
                    "root_id": root["id"],
                    "path": root["path"],
                    "error": "missing",
                    **counts,
                }
            )
            continue
        results.append({"root_id": root["id"], "path": root["path"], **counts})
    return results
