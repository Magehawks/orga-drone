"""SQLite persistence for library roots, assets, media, flows, and sessions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
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
    session_id INTEGER,
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

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id INTEGER REFERENCES library_roots(id) ON DELETE SET NULL,
    title TEXT,
    recorded_at TEXT,
    total_size_bytes INTEGER NOT NULL DEFAULT 0,
    total_duration_s REAL,
    clip_count INTEGER NOT NULL DEFAULT 1,
    video_count INTEGER NOT NULL DEFAULT 1,
    latitude REAL,
    longitude REAL,
    drone_model TEXT
);

CREATE TABLE IF NOT EXISTS session_items (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY (session_id, media_id)
);

-- User metadata survives clear_root_media / rescan (keyed by path + identity).
CREATE TABLE IF NOT EXISTS media_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_path TEXT NOT NULL UNIQUE,
    identity_key TEXT,
    stars INTEGER NOT NULL DEFAULT 0 CHECK (stars >= 0 AND stars <= 5),
    favorite INTEGER NOT NULL DEFAULT 0,
    tags_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_media_recorded ON media(recorded_at);
CREATE INDEX IF NOT EXISTS idx_media_drone ON media(drone_model);
CREATE INDEX IF NOT EXISTS idx_media_size ON media(size_bytes);
CREATE INDEX IF NOT EXISTS idx_media_flow ON media(flow_id);
CREATE INDEX IF NOT EXISTS idx_media_meta_identity ON media_meta(identity_key);
CREATE INDEX IF NOT EXISTS idx_media_meta_favorite ON media_meta(favorite);
"""


def make_identity_key(
    filename: str,
    size_bytes: int,
    recorded_at: str | None,
) -> str:
    """Stable key across rescans when path is unchanged or rematched."""
    payload = f"{filename.lower()}|{int(size_bytes)}|{recorded_at or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_tags(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = raw
    else:
        parts = raw.replace(";", ",").split(",")
    seen: set[str] = set()
    tags: list[str] = []
    for part in parts:
        tag = str(part).strip()
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tags


def tags_to_json(tags: list[str]) -> str:
    return json.dumps(tags, ensure_ascii=False)


def tags_from_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return parse_tags([str(x) for x in data])


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
    session_id: int | None = None
    clip_count: int | None = None
    flow_total_size: int | None = None
    flow_total_duration: float | None = None
    session_clip_count: int | None = None
    session_video_count: int | None = None
    session_total_size: int | None = None
    session_total_duration: float | None = None
    stars: int = 0
    favorite: bool = False
    tags: list[str] = field(default_factory=list)
    notes: str = ""


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
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns/tables introduced after the initial schema."""
        media_cols = {row[1] for row in conn.execute("PRAGMA table_info(media)").fetchall()}
        if "session_id" not in media_cols:
            conn.execute("ALTER TABLE media ADD COLUMN session_id INTEGER")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                root_id INTEGER REFERENCES library_roots(id) ON DELETE SET NULL,
                title TEXT,
                recorded_at TEXT,
                total_size_bytes INTEGER NOT NULL DEFAULT 0,
                total_duration_s REAL,
                clip_count INTEGER NOT NULL DEFAULT 1,
                video_count INTEGER NOT NULL DEFAULT 1,
                latitude REAL,
                longitude REAL,
                drone_model TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS session_items (
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                PRIMARY KEY (session_id, media_id)
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_session ON media(session_id)"
        )
        session_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if session_cols and "video_count" not in session_cols:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN video_count INTEGER NOT NULL DEFAULT 1"
            )

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
        """Drop indexed media for a root. Does NOT touch media_meta (user data)."""
        with self.connect() as conn:
            # flows / sessions that only belong to this root
            conn.execute(
                "DELETE FROM session_items WHERE media_id IN (SELECT id FROM media WHERE root_id = ?)",
                (root_id,),
            )
            conn.execute("DELETE FROM sessions WHERE root_id = ?", (root_id,))
            conn.execute(
                "DELETE FROM flow_items WHERE media_id IN (SELECT id FROM media WHERE root_id = ?)",
                (root_id,),
            )
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

    def replace_sessions_for_root(
        self,
        root_id: int,
        sessions: list[list[int]],
        media_lookup: dict[int, dict],
    ) -> None:
        with self.connect() as conn:
            old = conn.execute("SELECT id FROM sessions WHERE root_id = ?", (root_id,)).fetchall()
            for s in old:
                conn.execute("DELETE FROM session_items WHERE session_id = ?", (s["id"],))
            conn.execute("DELETE FROM sessions WHERE root_id = ?", (root_id,))
            conn.execute("UPDATE media SET session_id = NULL WHERE root_id = ?", (root_id,))

            for group in sessions:
                if not group:
                    continue
                items = [media_lookup[mid] for mid in group if mid in media_lookup]
                if not items:
                    continue
                videos = [i for i in items if i.get("kind") == "video"]
                first = videos[0] if videos else items[0]
                total_size = sum(int(i.get("size_bytes") or 0) for i in items)
                durations = [
                    i.get("duration_s")
                    for i in items
                    if i.get("kind") == "video" and i.get("duration_s") is not None
                ]
                total_dur = sum(float(d) for d in durations) if durations else None
                video_count = len(videos) if videos else 0
                title = first.get("filename")
                if video_count > 1:
                    title = f"{first.get('filename')} (+{video_count - 1})"
                elif len(items) > 1:
                    title = f"{first.get('filename')} (+{len(items) - 1})"
                cur = conn.execute(
                    """INSERT INTO sessions(
                         root_id, title, recorded_at, total_size_bytes,
                         total_duration_s, clip_count, video_count,
                         latitude, longitude, drone_model
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        root_id,
                        title,
                        first.get("recorded_at"),
                        total_size,
                        total_dur,
                        len(items),
                        video_count or len(items),
                        first.get("latitude"),
                        first.get("longitude"),
                        first.get("drone_model"),
                    ),
                )
                session_id = int(cur.lastrowid)
                for pos, mid in enumerate(group):
                    conn.execute(
                        "INSERT INTO session_items(session_id, media_id, position) VALUES (?, ?, ?)",
                        (session_id, mid, pos),
                    )
                    conn.execute(
                        "UPDATE media SET session_id = ? WHERE id = ?",
                        (session_id, mid),
                    )

    def list_media(
        self,
        *,
        sort: str = "recorded_at",
        order: str = "desc",
        drone: str | None = None,
        kind: str | None = None,
        has_gps: bool | None = None,
        flows_only: bool | None = None,
        sessions_only: bool | None = None,
        favorite: bool | None = None,
        q: str | None = None,
    ) -> list[MediaRow]:
        allowed_sort = {
            "recorded_at": "m.recorded_at",
            "size": "COALESCE(s.total_size_bytes, f.total_size_bytes, m.size_bytes)",
            "duration": "COALESCE(s.total_duration_s, f.total_duration_s, m.duration_s)",
            "drone": "m.drone_model",
            "filename": "m.filename",
            "flow": "m.flow_id",
            "session": "m.session_id",
            "stars": "COALESCE(mm.stars, 0)",
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
        if sessions_only is True:
            where.append("COALESCE(s.video_count, s.clip_count, 0) > 1")
        if sessions_only is False:
            where.append(
                "(m.session_id IS NULL OR COALESCE(s.video_count, s.clip_count, 0) <= 1)"
            )
        if favorite is True:
            where.append("COALESCE(mm.favorite, 0) = 1")
        if favorite is False:
            where.append("COALESCE(mm.favorite, 0) = 0")
        if q:
            where.append(
                "(m.filename LIKE ? OR m.path LIKE ? OR m.drone_model LIKE ?"
                " OR IFNULL(mm.tags_json, '') LIKE ? OR IFNULL(mm.notes, '') LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like, like, like])

        # Collapse rows:
        # - sessions_only / default: one row per multi-clip session (first item)
        # - flows_only: one row per multi-clip flow (first flow item)
        # - otherwise: session first, else flow first, else single
        if flows_only is True and sessions_only is not True:
            collapse = "(fi.position = 0 OR f.clip_count IS NULL OR f.clip_count = 1)"
        elif sessions_only is True:
            collapse = (
                "(m.kind = 'photo' OR si.position = 0"
                " OR s.clip_count IS NULL OR COALESCE(s.video_count, 0) <= 1)"
            )
        else:
            # Prefer session rows for multi-clip flights; keep photos visible;
            # otherwise fall back to flow collapsing.
            collapse = """(
              m.kind = 'photo'
              OR (COALESCE(s.video_count, 0) > 1 AND si.position = 0)
              OR (
                (s.video_count IS NULL OR s.video_count <= 1)
                AND (m.flow_id IS NULL OR fi.position = 0 OR f.clip_count IS NULL OR f.clip_count = 1)
              )
            )"""

        sql = f"""
            SELECT m.*, f.clip_count, f.total_size_bytes AS flow_total_size,
                   f.total_duration_s AS flow_total_duration,
                   s.clip_count AS session_clip_count,
                   s.video_count AS session_video_count,
                   s.total_size_bytes AS session_total_size,
                   s.total_duration_s AS session_total_duration,
                   mm.stars AS meta_stars, mm.favorite AS meta_favorite,
                   mm.tags_json AS meta_tags_json, mm.notes AS meta_notes
            FROM media m
            LEFT JOIN flows f ON f.id = m.flow_id
            LEFT JOIN flow_items fi ON fi.media_id = m.id
            LEFT JOIN sessions s ON s.id = m.session_id
            LEFT JOIN session_items si ON si.media_id = m.id
            LEFT JOIN media_meta mm ON mm.media_path = m.path
            WHERE {' AND '.join(where)}
              AND {collapse}
            ORDER BY {sort_sql} {order_sql}, m.id DESC
        """

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_media(r) for r in rows]

    def get_media(self, media_id: int) -> MediaRow | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT m.*, f.clip_count, f.total_size_bytes AS flow_total_size,
                          f.total_duration_s AS flow_total_duration,
                          s.clip_count AS session_clip_count,
                          s.video_count AS session_video_count,
                          s.total_size_bytes AS session_total_size,
                          s.total_duration_s AS session_total_duration,
                          mm.stars AS meta_stars, mm.favorite AS meta_favorite,
                          mm.tags_json AS meta_tags_json, mm.notes AS meta_notes
                   FROM media m
                   LEFT JOIN flows f ON f.id = m.flow_id
                   LEFT JOIN sessions s ON s.id = m.session_id
                   LEFT JOIN media_meta mm ON mm.media_path = m.path
                   WHERE m.id = ?""",
                (media_id,),
            ).fetchone()
        return self._row_to_media(row) if row else None

    def flow_clips(self, flow_id: int) -> list[MediaRow]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT m.*, f.clip_count, f.total_size_bytes AS flow_total_size,
                          f.total_duration_s AS flow_total_duration,
                          s.clip_count AS session_clip_count,
                          s.video_count AS session_video_count,
                          s.total_size_bytes AS session_total_size,
                          s.total_duration_s AS session_total_duration,
                          mm.stars AS meta_stars, mm.favorite AS meta_favorite,
                          mm.tags_json AS meta_tags_json, mm.notes AS meta_notes
                   FROM flow_items fi
                   JOIN media m ON m.id = fi.media_id
                   LEFT JOIN flows f ON f.id = fi.flow_id
                   LEFT JOIN sessions s ON s.id = m.session_id
                   LEFT JOIN media_meta mm ON mm.media_path = m.path
                   WHERE fi.flow_id = ?
                   ORDER BY fi.position""",
                (flow_id,),
            ).fetchall()
        return [self._row_to_media(r) for r in rows]

    def session_clips(self, session_id: int) -> list[MediaRow]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT m.*, f.clip_count, f.total_size_bytes AS flow_total_size,
                          f.total_duration_s AS flow_total_duration,
                          s.clip_count AS session_clip_count,
                          s.video_count AS session_video_count,
                          s.total_size_bytes AS session_total_size,
                          s.total_duration_s AS session_total_duration,
                          mm.stars AS meta_stars, mm.favorite AS meta_favorite,
                          mm.tags_json AS meta_tags_json, mm.notes AS meta_notes
                   FROM session_items si
                   JOIN media m ON m.id = si.media_id
                   LEFT JOIN flows f ON f.id = m.flow_id
                   LEFT JOIN sessions s ON s.id = si.session_id
                   LEFT JOIN media_meta mm ON mm.media_path = m.path
                   WHERE si.session_id = ?
                   ORDER BY si.position""",
                (session_id,),
            ).fetchall()
        return [self._row_to_media(r) for r in rows]

    def upsert_media_meta(
        self,
        media_path: str,
        *,
        stars: int = 0,
        favorite: bool = False,
        tags: list[str] | None = None,
        notes: str = "",
        identity_key: str | None = None,
    ) -> None:
        stars_n = max(0, min(5, int(stars)))
        tags_list = parse_tags(tags)
        notes_text = (notes or "").strip()
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM media_meta WHERE media_path = ?",
                (media_path,),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE media_meta
                       SET identity_key = COALESCE(?, identity_key),
                           stars = ?, favorite = ?, tags_json = ?, notes = ?, updated_at = ?
                       WHERE media_path = ?""",
                    (
                        identity_key,
                        stars_n,
                        1 if favorite else 0,
                        tags_to_json(tags_list),
                        notes_text,
                        now,
                        media_path,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO media_meta(
                         media_path, identity_key, stars, favorite, tags_json, notes, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        media_path,
                        identity_key,
                        stars_n,
                        1 if favorite else 0,
                        tags_to_json(tags_list),
                        notes_text,
                        now,
                    ),
                )

    def repath_media_meta(self, old_path: str, new_path: str) -> None:
        if old_path == new_path:
            return
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            # Prefer keeping meta attached to the renamed path.
            conflict = conn.execute(
                "SELECT id FROM media_meta WHERE media_path = ?",
                (new_path,),
            ).fetchone()
            if conflict:
                conn.execute("DELETE FROM media_meta WHERE media_path = ?", (old_path,))
            else:
                conn.execute(
                    "UPDATE media_meta SET media_path = ?, updated_at = ? WHERE media_path = ?",
                    (new_path, now, old_path),
                )

    def link_media_meta_for_path(
        self,
        media_path: str,
        *,
        filename: str,
        size_bytes: int,
        recorded_at: str | None,
    ) -> None:
        """After rescan/rename: ensure identity_key is set; rematch by identity if needed."""
        identity = make_identity_key(filename, size_bytes, recorded_at)
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            by_path = conn.execute(
                "SELECT id FROM media_meta WHERE media_path = ?",
                (media_path,),
            ).fetchone()
            if by_path:
                conn.execute(
                    "UPDATE media_meta SET identity_key = ?, updated_at = ? WHERE id = ?",
                    (identity, now, by_path["id"]),
                )
                return
            orphan = conn.execute(
                """SELECT id FROM media_meta
                   WHERE identity_key = ?
                     AND media_path NOT IN (SELECT path FROM media)""",
                (identity,),
            ).fetchone()
            if orphan:
                conflict = conn.execute(
                    "SELECT id FROM media_meta WHERE media_path = ?",
                    (media_path,),
                ).fetchone()
                if conflict:
                    return
                conn.execute(
                    "UPDATE media_meta SET media_path = ?, updated_at = ? WHERE id = ?",
                    (media_path, now, orphan["id"]),
                )

    def distinct_drones(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT drone_model FROM media
                   WHERE drone_model IS NOT NULL AND drone_model != ''
                   ORDER BY drone_model"""
            ).fetchall()
        return [r["drone_model"] for r in rows]

    def media_map_for_root(self, root_id: int, *, kind: str | None = "video") -> dict[int, dict]:
        with self.connect() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM media WHERE root_id = ? AND kind = ?",
                    (root_id, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM media WHERE root_id = ?",
                    (root_id,),
                ).fetchall()
        return {int(r["id"]): dict(r) for r in rows}

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            videos = conn.execute("SELECT COUNT(*) AS c FROM media WHERE kind='video'").fetchone()["c"]
            photos = conn.execute("SELECT COUNT(*) AS c FROM media WHERE kind='photo'").fetchone()["c"]
            flows = conn.execute("SELECT COUNT(*) AS c FROM flows WHERE clip_count > 1").fetchone()["c"]
            sessions = conn.execute(
                "SELECT COUNT(*) AS c FROM sessions WHERE video_count > 1"
            ).fetchone()["c"]
            roots = conn.execute("SELECT COUNT(*) AS c FROM library_roots").fetchone()["c"]
        return {
            "videos": videos,
            "photos": photos,
            "flows": flows,
            "sessions": sessions,
            "roots": roots,
        }

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
        self.repath_media_meta(old_path, new_path)

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
            old = conn.execute("SELECT path, size_bytes, recorded_at FROM media WHERE id = ?", (media_id,)).fetchone()
            conn.execute(
                """UPDATE media
                   SET filename = ?, path = ?, has_lrf = ?, has_srt = ?, updated_at = ?
                   WHERE id = ?""",
                (filename, path, has_lrf, has_srt, now, media_id),
            )
        if old and old["path"] != path:
            self.repath_media_meta(old["path"], path)
        if old:
            self.link_media_meta_for_path(
                path,
                filename=filename,
                size_bytes=int(old["size_bytes"] or 0),
                recorded_at=old["recorded_at"],
            )

    def find_media_by_path(self, path: str) -> MediaRow | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT m.*, f.clip_count, f.total_size_bytes AS flow_total_size,
                          f.total_duration_s AS flow_total_duration,
                          s.clip_count AS session_clip_count,
                          s.video_count AS session_video_count,
                          s.total_size_bytes AS session_total_size,
                          s.total_duration_s AS session_total_duration,
                          mm.stars AS meta_stars, mm.favorite AS meta_favorite,
                          mm.tags_json AS meta_tags_json, mm.notes AS meta_notes
                   FROM media m
                   LEFT JOIN flows f ON f.id = m.flow_id
                   LEFT JOIN sessions s ON s.id = m.session_id
                   LEFT JOIN media_meta mm ON mm.media_path = m.path
                   WHERE m.path = ?""",
                (path,),
            ).fetchone()
        return self._row_to_media(row) if row else None

    @staticmethod
    def _row_to_media(row: sqlite3.Row) -> MediaRow:
        keys = row.keys()
        stars = int(row["meta_stars"] or 0) if "meta_stars" in keys else 0
        favorite = bool(row["meta_favorite"]) if "meta_favorite" in keys else False
        tags = tags_from_json(row["meta_tags_json"] if "meta_tags_json" in keys else None)
        notes = (row["meta_notes"] or "") if "meta_notes" in keys else ""
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
            session_id=row["session_id"] if "session_id" in keys else None,
            clip_count=row["clip_count"] if "clip_count" in keys else None,
            flow_total_size=row["flow_total_size"] if "flow_total_size" in keys else None,
            flow_total_duration=row["flow_total_duration"] if "flow_total_duration" in keys else None,
            session_clip_count=row["session_clip_count"] if "session_clip_count" in keys else None,
            session_video_count=row["session_video_count"] if "session_video_count" in keys else None,
            session_total_size=row["session_total_size"] if "session_total_size" in keys else None,
            session_total_duration=row["session_total_duration"] if "session_total_duration" in keys else None,
            stars=stars,
            favorite=favorite,
            tags=tags,
            notes=notes,
        )


def track_to_json(track: list | None) -> str | None:
    if not track:
        return None
    payload = []
    for p in track:
        point = {
            "lat": p.lat,
            "lon": p.lon,
            "abs_alt": p.abs_alt,
            "rel_alt": p.rel_alt,
        }
        t = getattr(p, "t", None)
        if t is not None:
            point["t"] = t
        payload.append(point)
    return json.dumps(payload)


def track_from_json(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
