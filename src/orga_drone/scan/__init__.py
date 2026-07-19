"""Scan library roots and index media into SQLite."""

from __future__ import annotations

from pathlib import Path

from orga_drone.db import Database, track_to_json
from orga_drone.group import ClipForGrouping, group_clips_into_flows
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
        recorded_at = None
        if row.get("recorded_at"):
            from datetime import datetime

            try:
                recorded_at = datetime.fromisoformat(row["recorded_at"])
            except ValueError:
                recorded_at = None
        clips.append(
            ClipForGrouping(
                media_id=mid,
                recorded_at=recorded_at,
                sequence=row.get("sequence"),
                size_bytes=int(row.get("size_bytes") or 0),
                duration_s=row.get("duration_s"),
            )
        )

    flows = group_clips_into_flows(clips)
    db.replace_flows_for_root(root_id, flows, media_map)
    db.mark_root_scanned(root_id)

    multi = sum(1 for g in flows if len(g) > 1)
    counts["flows"] = multi
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
