"""SQLite persistence for library roots, assets, media, and flows."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS library_roots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    label TEXT,
    added_at TEXT NOT NULL,
    last_scanned_at TEXT
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id INTEGER NOT NULL REFERENCES library_roots(id) ON DELETE CASCADE,
    path TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime REAL,
    stem_base TEXT,
    UNIQUE(path)
);

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id INTEGER NOT NULL REFERENCES library_roots(id) ON DELETE CASCADE,
    primary_asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    duration_s REAL,
    recorded_at TEXT,
    sequence INTEGER,
    mode TEXT,
    drone_model TEXT,
    camera_model TEXT,
    latitude REAL,
    longitude REAL,
    abs_alt REAL,
    has_srt INTEGER NOT NULL DEFAULT 0,
    has_lrf INTEGER NOT NULL DEFAULT 0,
    track_json TEXT,
    flow_id INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id INTEGER REFERENCES library_roots(id) ON DELETE SET NULL,
    title TEXT,
    recorded_at TEXT,
    total_size_bytes INTEGER NOT NULL DEFAULT 0,
    total_duration_s REAL,
    clip_count INTEGER NOT NULL DEFAULT 1,
    latitude REAL,
    longitude REAL,
    drone_model TEXT
);

CREATE TABLE IF NOT EXISTS flow_items (
    flow_id INTEGER NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY (flow_id, media_id)
);

CREATE INDEX IF NOT EXISTS idx_media_recorded ON media(recorded_at);
CREATE INDEX IF NOT EXISTS idx_media_drone ON media(drone_model);
CREATE INDEX IF NOT EXISTS idx_media_size ON media(size_bytes);
CREATE INDEX IF NOT EXISTS idx_media_flow ON media(flow_id);
"""


@dataclass
class MediaRow:
    id: int
    root_id: int
    kind: str
    filename: str
    path: str
    size_bytes: int
    duration_s: float | None
    recorded_at: str | None
    sequence: int | None
    mode: str | None
    drone_model: str | None
    camera_model: str | None
    latitude: float | None
    longitude: float | None
    abs_alt: float | None
    has_srt: bool
    has_lrf: bool
    track_json: str | None
    flow_id: int | None
    clip_count: int | None = None
    flow_total_size: int | None = None
    flow_total_duration: float | None = None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def list_roots(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM library_roots ORDER BY id"))

    def add_root(self, path: Path, label: str | None = None) -> int:
        resolved = str(path.resolve())
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM library_roots WHERE path = ?", (resolved,)
            ).fetchone()
            if existing:
                return int(existing["id"])
            cur = conn.execute(
                "INSERT INTO library_roots(path, label, added_at) VALUES (?, ?, ?)",
                (resolved, label or path.name, now),
            )
            return int(cur.lastrowid)

    def remove_root(self, root_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM library_roots WHERE id = ?", (root_id,))

    def mark_root_scanned(self, root_id: int) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                "UPDATE library_roots SET last_scanned_at = ? WHERE id = ?",
                (now, root_id),
            )

    def clear_root_media(self, root_id: int) -> None:
        with self.connect() as conn:
            # flows that only belong to this root
            conn.execute("DELETE FROM flow_items WHERE media_id IN (SELECT id FROM media WHERE root_id = ?)", (root_id,))
            conn.execute("DELETE FROM flows WHERE root_id = ?", (root_id,))
            conn.execute("DELETE FROM media WHERE root_id = ?", (root_id,))
            conn.execute("DELETE FROM assets WHERE root_id = ?", (root_id,))

    def upsert_asset(
        self,
        *,
        root_id: int,
        path: Path,
        kind: str,
        size_bytes: int,
        mtime: float | None,
        stem_base: str | None,
    ) -> int:
        p = str(path.resolve())
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM assets WHERE path = ?", (p,)).fetchone()
            if row:
                conn.execute(
                    """UPDATE assets SET root_id=?, kind=?, size_bytes=?, mtime=?, stem_base=?
                       WHERE id=?""",
                    (root_id, kind, size_bytes, mtime, stem_base, row["id"]),
                )
                return int(row["id"])
            cur = conn.execute(
                """INSERT INTO assets(root_id, path, kind, size_bytes, mtime, stem_base)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (root_id, p, kind, size_bytes, mtime, stem_base),
            )
            return int(cur.lastrowid)

    def upsert_media(self, data: dict[str, Any]) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        data = {**data, "updated_at": now}
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM media WHERE path = ?", (data["path"],)).fetchone()
            cols = [
                "root_id",
                "primary_asset_id",
                "kind",
                "filename",
                "path",
                "size_bytes",
                "duration_s",
                "recorded_at",
                "sequence",
                "mode",
                "drone_model",
                "camera_model",
                "latitude",
                "longitude",
                "abs_alt",
                "has_srt",
                "has_lrf",
                "track_json",
                "updated_at",
            ]
            values = [data.get(c) for c in cols]
            if row:
                sets = ", ".join(f"{c}=?" for c in cols)
                conn.execute(f"UPDATE media SET {sets} WHERE id=?", (*values, row["id"]))
                return int(row["id"])
            placeholders = ", ".join("?" for _ in cols)
            cur = conn.execute(
                f"INSERT INTO media({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            return int(cur.lastrowid)

    def replace_flows_for_root(self, root_id: int, flows: list[list[int]], media_lookup: dict[int, dict]) -> None:
        with self.connect() as conn:
            old = conn.execute("SELECT id FROM flows WHERE root_id = ?", (root_id,)).fetchall()
            for f in old:
                conn.execute("DELETE FROM flow_items WHERE flow_id = ?", (f["id"],))
            conn.execute("DELETE FROM flows WHERE root_id = ?", (root_id,))
            conn.execute("UPDATE media SET flow_id = NULL WHERE root_id = ?", (root_id,))

            for group in flows:
                if not group:
                    continue
                items = [media_lookup[mid] for mid in group if mid in media_lookup]
                if not items:
                    continue
                first = items[0]
                total_size = sum(int(i.get("size_bytes") or 0) for i in items)
                durations = [i.get("duration_s") for i in items if i.get("duration_s") is not None]
                total_dur = sum(float(d) for d in durations) if durations else None
                title = first.get("filename")
                if len(items) > 1:
                    title = f"{first.get('filename')} (+{len(items) - 1})"
                cur = conn.execute(
                    """INSERT INTO flows(root_id, title, recorded_at, total_size_bytes,
                       total_duration_s, clip_count, latitude, longitude, drone_model)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        root_id,
                        title,
                        first.get("recorded_at"),
                        total_size,
                        total_dur,
                        len(items),
                        first.get("latitude"),
                        first.get("longitude"),
                        first.get("drone_model"),
                    ),
                )
                flow_id = int(cur.lastrowid)
                for pos, mid in enumerate(group):
                    conn.execute(
                        "INSERT INTO flow_items(flow_id, media_id, position) VALUES (?, ?, ?)",
                        (flow_id, mid, pos),
                    )
                    conn.execute("UPDATE media SET flow_id = ? WHERE id = ?", (flow_id, mid))

    def list_media(
        self,
        *,
        sort: str = "recorded_at",
        order: str = "desc",
        drone: str | None = None,
        kind: str | None = None,
        has_gps: bool | None = None,
        flows_only: bool | None = None,
        q: str | None = None,
    ) -> list[MediaRow]:
        allowed_sort = {
            "recorded_at": "m.recorded_at",
            "size": "COALESCE(f.total_size_bytes, m.size_bytes)",
            "duration": "COALESCE(f.total_duration_s, m.duration_s)",
            "drone": "m.drone_model",
            "filename": "m.filename",
            "flow": "m.flow_id",
        }
        sort_sql = allowed_sort.get(sort, "m.recorded_at")
        order_sql = "ASC" if order.lower() == "asc" else "DESC"

        where = ["m.kind IN ('video', 'photo')"]
        params: list[Any] = []
        if drone:
            where.append("m.drone_model = ?")
            params.append(drone)
        if kind:
            where.append("m.kind = ?")
            params.append(kind)
        if has_gps is True:
            where.append("m.latitude IS NOT NULL AND m.longitude IS NOT NULL")
        if has_gps is False:
            where.append("m.latitude IS NULL OR m.longitude IS NULL")
        if flows_only is True:
            where.append("f.clip_count > 1")
        if flows_only is False:
            where.append("(m.flow_id IS NULL OR f.clip_count = 1)")
        if q:
            where.append("(m.filename LIKE ? OR m.path LIKE ? OR m.drone_model LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])

        # One row per flow (representative = first clip) + singles
        sql = f"""
            SELECT m.*, f.clip_count, f.total_size_bytes AS flow_total_size,
                   f.total_duration_s AS flow_total_duration
            FROM media m
            LEFT JOIN flows f ON f.id = m.flow_id
            LEFT JOIN flow_items fi ON fi.media_id = m.id
            WHERE {' AND '.join(where)}
              AND (m.flow_id IS NULL OR fi.position = 0 OR f.clip_count IS NULL OR f.clip_count = 1)
            ORDER BY {sort_sql} {order_sql} NULLS LAST, m.id DESC
        """
        # SQLite may not support NULLS LAST on older versions - use workaround
        sql = sql.replace(" NULLS LAST", "")

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_media(r) for r in rows]

    def get_media(self, media_id: int) -> MediaRow | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT m.*, f.clip_count, f.total_size_bytes AS flow_total_size,
                          f.total_duration_s AS flow_total_duration
                   FROM media m
                   LEFT JOIN flows f ON f.id = m.flow_id
                   WHERE m.id = ?""",
                (media_id,),
            ).fetchone()
        return self._row_to_media(row) if row else None

    def flow_clips(self, flow_id: int) -> list[MediaRow]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT m.*, f.clip_count, f.total_size_bytes AS flow_total_size,
                          f.total_duration_s AS flow_total_duration
                   FROM flow_items fi
                   JOIN media m ON m.id = fi.media_id
                   LEFT JOIN flows f ON f.id = fi.flow_id
                   WHERE fi.flow_id = ?
                   ORDER BY fi.position""",
                (flow_id,),
            ).fetchall()
        return [self._row_to_media(r) for r in rows]

    def distinct_drones(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT drone_model FROM media
                   WHERE drone_model IS NOT NULL AND drone_model != ''
                   ORDER BY drone_model"""
            ).fetchall()
        return [r["drone_model"] for r in rows]

    def media_map_for_root(self, root_id: int) -> dict[int, dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM media WHERE root_id = ? AND kind = 'video'",
                (root_id,),
            ).fetchall()
        return {int(r["id"]): dict(r) for r in rows}

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            videos = conn.execute("SELECT COUNT(*) AS c FROM media WHERE kind='video'").fetchone()["c"]
            photos = conn.execute("SELECT COUNT(*) AS c FROM media WHERE kind='photo'").fetchone()["c"]
            flows = conn.execute("SELECT COUNT(*) AS c FROM flows WHERE clip_count > 1").fetchone()["c"]
            roots = conn.execute("SELECT COUNT(*) AS c FROM library_roots").fetchone()["c"]
        return {"videos": videos, "photos": photos, "flows": flows, "roots": roots}

    def repath_file(self, old_path: str, new_path: str, *, new_stem: str | None = None) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            if new_stem is not None:
                conn.execute(
                    "UPDATE assets SET path = ?, stem_base = ? WHERE path = ?",
                    (new_path, new_stem, old_path),
                )
            else:
                conn.execute("UPDATE assets SET path = ? WHERE path = ?", (new_path, old_path))
            row = conn.execute("SELECT id, filename FROM media WHERE path = ?", (old_path,)).fetchone()
            if row:
                new_name = Path(new_path).name
                conn.execute(
                    "UPDATE media SET path = ?, filename = ?, updated_at = ? WHERE id = ?",
                    (new_path, new_name, now, row["id"]),
                )

    def update_media_identity(
        self,
        media_id: int,
        *,
        filename: str,
        path: str,
        has_lrf: int,
        has_srt: int,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """UPDATE media
                   SET filename = ?, path = ?, has_lrf = ?, has_srt = ?, updated_at = ?
                   WHERE id = ?""",
                (filename, path, has_lrf, has_srt, now, media_id),
            )

    def find_media_by_path(self, path: str) -> MediaRow | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT m.*, f.clip_count, f.total_size_bytes AS flow_total_size,
                          f.total_duration_s AS flow_total_duration
                   FROM media m
                   LEFT JOIN flows f ON f.id = m.flow_id
                   WHERE m.path = ?""",
                (path,),
            ).fetchone()
        return self._row_to_media(row) if row else None

    @staticmethod
    def _row_to_media(row: sqlite3.Row) -> MediaRow:
        return MediaRow(
            id=int(row["id"]),
            root_id=int(row["root_id"]),
            kind=row["kind"],
            filename=row["filename"],
            path=row["path"],
            size_bytes=int(row["size_bytes"] or 0),
            duration_s=row["duration_s"],
            recorded_at=row["recorded_at"],
            sequence=row["sequence"],
            mode=row["mode"],
            drone_model=row["drone_model"],
            camera_model=row["camera_model"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            abs_alt=row["abs_alt"],
            has_srt=bool(row["has_srt"]),
            has_lrf=bool(row["has_lrf"]),
            track_json=row["track_json"],
            flow_id=row["flow_id"],
            clip_count=row["clip_count"] if "clip_count" in row.keys() else None,
            flow_total_size=row["flow_total_size"] if "flow_total_size" in row.keys() else None,
            flow_total_duration=row["flow_total_duration"] if "flow_total_duration" in row.keys() else None,
        )


def track_to_json(track: list | None) -> str | None:
    if not track:
        return None
    payload = [
        {
            "lat": p.lat,
            "lon": p.lon,
            "abs_alt": p.abs_alt,
            "rel_alt": p.rel_alt,
        }
        for p in track
    ]
    return json.dumps(payload)


def track_from_json(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
