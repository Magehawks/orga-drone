"""Scan library roots and index media into SQLite."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from orga_drone.db import Database, track_from_json, track_to_json
from orga_drone.group import (
    ClipForGrouping,
    ClipForSession,
    altitude_edges_from_track,
    attach_photos_to_sessions,
    group_clips_into_flows,
    group_clips_into_sessions,
)
from orga_drone.parse import VIDEO_EXTS, PHOTO_EXTS, PROXY_EXTS, SUBTITLE_EXTS, parse_media_file

MEDIA_EXTS = VIDEO_EXTS | PHOTO_EXTS | PROXY_EXTS | SUBTITLE_EXTS


def iter_media_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in MEDIA_EXTS:
            files.append(path)
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


def scan_root(db: Database, root_id: int, root_path: Path) -> dict[str, int]:
    root_path = root_path.resolve()
    files = iter_media_files(root_path)

    by_stem: dict[str, list[Path]] = {}
    for f in files:
        by_stem.setdefault(f.stem, []).append(f)

    # Clear previous index for this root (simple full rescan for MVP)
    db.clear_root_media(root_id)

    counts = {"assets": 0, "videos": 0, "photos": 0}

    for path in files:
        parsed = parse_media_file(path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        asset_id = db.upsert_asset(
            root_id=root_id,
            path=path,
            kind=parsed.kind,
            size_bytes=parsed.size_bytes,
            mtime=mtime,
            stem_base=parsed.stem_base,
        )
        counts["assets"] += 1

        if parsed.kind not in {"video", "photo"}:
            continue

        sibs = _siblings(parsed.stem_base, by_stem)
        has_srt = ".srt" in sibs
        has_lrf = ".lrf" in sibs

        # If video lacked SRT parse because case mismatch, re-check
        if parsed.kind == "video" and not has_srt:
            # already handled in parser with .SRT/.srt
            pass

        recorded = parsed.recorded_at.isoformat(timespec="seconds") if parsed.recorded_at else None

        db.upsert_media(
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
        if parsed.kind == "video":
            counts["videos"] += 1
        else:
            counts["photos"] += 1

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
    return counts


def scan_all_roots(db: Database) -> list[dict]:
    results = []
    for root in db.list_roots():
        path = Path(root["path"])
        if not path.exists():
            results.append({"root_id": root["id"], "path": root["path"], "error": "missing"})
            continue
        counts = scan_root(db, int(root["id"]), path)
        results.append({"root_id": root["id"], "path": root["path"], **counts})
    return results
