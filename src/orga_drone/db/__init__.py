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
    width INTEGER,
    height INTEGER,
    recorded_at TEXT,
    sequence INTEGER,
    mode TEXT,
    drone_model TEXT,
    camera_model TEXT,
    source_type TEXT,
    latitude REAL,
    longitude REAL,
    abs_alt REAL,
    has_srt INTEGER NOT NULL DEFAULT 0,
    has_lrf INTEGER NOT NULL DEFAULT 0,
    track_json TEXT,
    auto_tags_json TEXT NOT NULL DEFAULT '[]',
    place_json TEXT,
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

-- Studio projects (non-destructive; Issue #16 / ADR 0004).
CREATE TABLE IF NOT EXISTS studio_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Clips reference library media by path (+ optional media.id); never copy files.
-- Multiple clips may share media_path / source_media_id.
CREATE TABLE IF NOT EXISTS studio_clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
    media_path TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    source_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
    position INTEGER NOT NULL,
    filename_snapshot TEXT NOT NULL,
    recorded_at_snapshot TEXT,
    kind_snapshot TEXT NOT NULL,
    photo_duration_s REAL,
    source_start REAL,
    source_end REAL,
    playback_speed REAL NOT NULL DEFAULT 1.0,
    volume REAL NOT NULL DEFAULT 1.0,
    transition TEXT,
    effect_settings TEXT NOT NULL DEFAULT '{}',
    added_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_studio_clips_project ON studio_clips(project_id);
CREATE INDEX IF NOT EXISTS idx_studio_clips_identity ON studio_clips(identity_key);
CREATE INDEX IF NOT EXISTS idx_studio_clips_position ON studio_clips(project_id, position);
CREATE INDEX IF NOT EXISTS idx_studio_clips_path ON studio_clips(media_path);
CREATE INDEX IF NOT EXISTS idx_studio_clips_source_media ON studio_clips(source_media_id);

-- Optional soundtrack per project (Issue #25 / ADR 0008). Reference only; never copies files.
CREATE TABLE IF NOT EXISTS studio_audio_clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
    lane TEXT NOT NULL DEFAULT 'music',
    position INTEGER NOT NULL DEFAULT 0,
    file_path TEXT NOT NULL,
    display_name TEXT NOT NULL,
    volume REAL NOT NULL DEFAULT 0.8
        CHECK (volume >= 0.0 AND volume <= 1.0),
    fade_in_s REAL NOT NULL DEFAULT 0.0
        CHECK (fade_in_s >= 0.0),
    fade_out_s REAL NOT NULL DEFAULT 0.0
        CHECK (fade_out_s >= 0.0),
    loop INTEGER NOT NULL DEFAULT 0
        CHECK (loop IN (0, 1)),
    added_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_studio_audio_clips_project
    ON studio_audio_clips(project_id, lane, position);
CREATE UNIQUE INDEX IF NOT EXISTS idx_studio_audio_clips_one_music
    ON studio_audio_clips(project_id) WHERE lane = 'music';

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    lat_key REAL NOT NULL,
    lon_key REAL NOT NULL,
    country TEXT,
    region TEXT,
    city TEXT,
    district TEXT,
    country_code TEXT,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (lat_key, lon_key)
);
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
    source_type: str | None
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
    auto_tags: list[str] = field(default_factory=list)
    place: dict[str, Any] | None = None
    width: int | None = None
    height: int | None = None


STUDIO_LAST_OPENED_KEY = "studio_last_opened_project_id"


@dataclass
class StudioAudioClip:
    """One optional soundtrack reference for a Studio project (never copies the file)."""

    id: int
    project_id: int
    lane: str
    position: int
    file_path: str
    display_name: str
    volume: float
    fade_in_s: float
    fade_out_s: float
    loop: bool
    added_at: str


@dataclass
class StudioProject:
    """One Studio project (title + timestamps). Does not own media files."""

    id: int
    title: str
    created_at: str
    updated_at: str
    clip_count: int = 0


@dataclass
class StudioClip:
    """One Story clip in a Studio project (references media; never copies it)."""

    id: int
    project_id: int
    media_path: str
    identity_key: str
    position: int
    filename_snapshot: str
    recorded_at_snapshot: str | None
    kind_snapshot: str
    photo_duration_s: float | None
    added_at: str
    available: bool
    source_media_id: int | None
    filename: str
    recorded_at: str | None
    kind: str | None = None
    duration_s: float | None = None
    source_start: float | None = None
    source_end: float | None = None
    playback_speed: float = 1.0
    volume: float = 1.0
    transition: str | None = None
    effect_settings: str = "{}"

    @property
    def media_id(self) -> int | None:
        """Live library id for streaming when the path resolves; else stored id."""
        return self.source_media_id if self.available else None

    @property
    def source_in_s(self) -> float | None:
        """Alias for estimate/cut helpers (ADR 0003 naming)."""
        return self.source_start

    @property
    def source_out_s(self) -> float | None:
        return self.source_end


# Backward-compatible name used by older tests/call sites.
StudioItem = StudioClip


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
        media_cols = {row[1] for row in conn.execute("PRAGMA table_info(media)").fetchall()}
        if "source_type" not in media_cols:
            conn.execute("ALTER TABLE media ADD COLUMN source_type TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_source ON media(source_type)"
        )
        media_cols = {row[1] for row in conn.execute("PRAGMA table_info(media)").fetchall()}
        if "auto_tags_json" not in media_cols:
            conn.execute(
                "ALTER TABLE media ADD COLUMN auto_tags_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "place_json" not in media_cols:
            conn.execute("ALTER TABLE media ADD COLUMN place_json TEXT")
        media_cols = {row[1] for row in conn.execute("PRAGMA table_info(media)").fetchall()}
        if "width" not in media_cols:
            conn.execute("ALTER TABLE media ADD COLUMN width INTEGER")
        if "height" not in media_cols:
            conn.execute("ALTER TABLE media ADD COLUMN height INTEGER")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS geocode_cache (
                lat_key REAL NOT NULL,
                lon_key REAL NOT NULL,
                country TEXT,
                region TEXT,
                city TEXT,
                district TEXT,
                country_code TEXT,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (lat_key, lon_key)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS studio_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        # Only touch legacy studio_items when upgrading an older DB that still
        # has that table. Do not recreate it on every startup.
        legacy_items = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_items'"
        ).fetchone()
        if legacy_items:
            studio_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(studio_items)").fetchall()
            }
            if studio_cols and "kind_snapshot" not in studio_cols:
                conn.execute("ALTER TABLE studio_items ADD COLUMN kind_snapshot TEXT")
                conn.execute(
                    """UPDATE studio_items
                       SET kind_snapshot = (
                         SELECT m.kind FROM media m WHERE m.path = studio_items.media_path
                       )
                       WHERE kind_snapshot IS NULL"""
                )
                conn.execute(
                    """UPDATE studio_items
                       SET kind_snapshot = 'photo'
                       WHERE kind_snapshot IS NULL"""
                )
            studio_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(studio_items)").fetchall()
            }
            if studio_cols and "photo_duration_s" not in studio_cols:
                conn.execute(
                    "ALTER TABLE studio_items ADD COLUMN photo_duration_s REAL"
                )
            studio_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(studio_items)").fetchall()
            }
            if studio_cols and "source_in_s" not in studio_cols:
                conn.execute("ALTER TABLE studio_items ADD COLUMN source_in_s REAL")
            if studio_cols and "source_out_s" not in studio_cols:
                conn.execute("ALTER TABLE studio_items ADD COLUMN source_out_s REAL")
            Database._migrate_studio_items_drop_unique_media_path(conn)
        Database._migrate_studio_projects_and_clips(conn)
        Database._migrate_studio_audio_clips(conn)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )"""
        )

    @staticmethod
    def _migrate_studio_items_drop_unique_media_path(conn: sqlite3.Connection) -> None:
        """Allow multiple Story clips from one source file (video cut)."""
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='studio_items'"
        ).fetchone()
        if row is None or not row[0]:
            return
        sql_upper = str(row[0]).upper().replace("\n", " ")
        if "MEDIA_PATH TEXT NOT NULL UNIQUE" not in sql_upper and (
            "MEDIA_PATH TEXT UNIQUE" not in sql_upper
        ):
            return
        cols = {
            r[1] for r in conn.execute("PRAGMA table_info(studio_items)").fetchall()
        }
        select_source_in = "source_in_s" if "source_in_s" in cols else "NULL"
        select_source_out = "source_out_s" if "source_out_s" in cols else "NULL"
        select_photo = "photo_duration_s" if "photo_duration_s" in cols else "NULL"
        select_kind = (
            "kind_snapshot" if "kind_snapshot" in cols else "'photo'"
        )
        conn.executescript(
            f"""
            CREATE TABLE studio_items__cut_mig (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_path TEXT NOT NULL,
                identity_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                filename_snapshot TEXT NOT NULL,
                recorded_at_snapshot TEXT,
                kind_snapshot TEXT NOT NULL DEFAULT 'photo',
                photo_duration_s REAL,
                source_in_s REAL,
                source_out_s REAL,
                added_at TEXT NOT NULL
            );
            INSERT INTO studio_items__cut_mig(
                id, media_path, identity_key, position,
                filename_snapshot, recorded_at_snapshot, kind_snapshot,
                photo_duration_s, source_in_s, source_out_s, added_at
            )
            SELECT id, media_path, identity_key, position,
                   filename_snapshot, recorded_at_snapshot, {select_kind},
                   {select_photo}, {select_source_in}, {select_source_out}, added_at
            FROM studio_items;
            DROP TABLE studio_items;
            ALTER TABLE studio_items__cut_mig RENAME TO studio_items;
            CREATE INDEX IF NOT EXISTS idx_studio_items_identity ON studio_items(identity_key);
            CREATE INDEX IF NOT EXISTS idx_studio_items_position ON studio_items(position);
            CREATE INDEX IF NOT EXISTS idx_studio_items_path ON studio_items(media_path);
            """
        )

    @staticmethod
    def _migrate_studio_projects_and_clips(conn: sqlite3.Connection) -> None:
        """Create studio_projects/studio_clips; migrate legacy studio_items once."""
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS studio_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS studio_clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
                media_path TEXT NOT NULL,
                identity_key TEXT NOT NULL,
                source_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
                position INTEGER NOT NULL,
                filename_snapshot TEXT NOT NULL,
                recorded_at_snapshot TEXT,
                kind_snapshot TEXT NOT NULL DEFAULT 'photo',
                photo_duration_s REAL,
                source_start REAL,
                source_end REAL,
                playback_speed REAL NOT NULL DEFAULT 1.0,
                volume REAL NOT NULL DEFAULT 1.0,
                transition TEXT,
                effect_settings TEXT NOT NULL DEFAULT '{}',
                added_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_clips_project ON studio_clips(project_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_clips_identity ON studio_clips(identity_key)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_clips_position ON studio_clips(project_id, position)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_clips_path ON studio_clips(media_path)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_clips_source_media ON studio_clips(source_media_id)"
        )

        clip_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(studio_clips)").fetchall()
        }
        # Forward-compatible column adds if an older partial migrate exists.
        alters = {
            "source_media_id": "ALTER TABLE studio_clips ADD COLUMN source_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL",
            "source_start": "ALTER TABLE studio_clips ADD COLUMN source_start REAL",
            "source_end": "ALTER TABLE studio_clips ADD COLUMN source_end REAL",
            "playback_speed": "ALTER TABLE studio_clips ADD COLUMN playback_speed REAL NOT NULL DEFAULT 1.0",
            "volume": "ALTER TABLE studio_clips ADD COLUMN volume REAL NOT NULL DEFAULT 1.0",
            "transition": "ALTER TABLE studio_clips ADD COLUMN transition TEXT",
            "effect_settings": "ALTER TABLE studio_clips ADD COLUMN effect_settings TEXT NOT NULL DEFAULT '{}'",
            "photo_duration_s": "ALTER TABLE studio_clips ADD COLUMN photo_duration_s REAL",
        }
        for col, sql in alters.items():
            if col not in clip_cols:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass

        items_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_items'"
        ).fetchone()
        item_count_n = 0
        clip_count_n = 0
        if items_exists:
            item_count = conn.execute(
                "SELECT COUNT(*) AS n FROM studio_items"
            ).fetchone()
            clip_count = conn.execute(
                "SELECT COUNT(*) AS n FROM studio_clips"
            ).fetchone()
            item_count_n = int(item_count["n"])
            clip_count_n = int(clip_count["n"])
        need_legacy = item_count_n > 0 and clip_count_n == 0

        project = conn.execute(
            "SELECT id FROM studio_projects ORDER BY id ASC LIMIT 1"
        ).fetchone()
        # Only create a default project when migrating leftover studio_items.
        # Fresh DBs stay empty until the user creates or opens a project.
        if project is None and need_legacy:
            cur = conn.execute(
                """INSERT INTO studio_projects(title, created_at, updated_at)
                   VALUES (?, ?, ?)""",
                ("Your story", now, now),
            )
            pid = cur.lastrowid
            assert pid is not None
            project_id = int(pid)
        elif project is not None:
            project_id = int(project["id"])
        else:
            project_id = None

        if not items_exists:
            return
        if need_legacy and project_id is not None:
            item_cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(studio_items)").fetchall()
            }
            start_expr = (
                "source_in_s" if "source_in_s" in item_cols else "NULL"
            )
            end_expr = "source_out_s" if "source_out_s" in item_cols else "NULL"
            photo_expr = (
                "photo_duration_s" if "photo_duration_s" in item_cols else "NULL"
            )
            kind_expr = (
                "kind_snapshot" if "kind_snapshot" in item_cols else "'photo'"
            )
            conn.execute(
                f"""
                INSERT INTO studio_clips(
                    id, project_id, media_path, identity_key, source_media_id,
                    position, filename_snapshot, recorded_at_snapshot, kind_snapshot,
                    photo_duration_s, source_start, source_end,
                    playback_speed, volume, transition, effect_settings, added_at
                )
                SELECT i.id, ?, i.media_path, i.identity_key, m.id,
                       i.position, i.filename_snapshot, i.recorded_at_snapshot,
                       COALESCE({kind_expr}, 'photo'),
                       {photo_expr}, {start_expr}, {end_expr},
                       1.0, 1.0, NULL, '{{}}', i.added_at
                FROM studio_items i
                LEFT JOIN media m ON m.path = i.media_path
                """,
                (project_id,),
            )
        conn.execute("DROP TABLE IF EXISTS studio_items")

    @staticmethod
    def _migrate_studio_audio_clips(conn: sqlite3.Connection) -> None:
        """Optional per-project music reference (Issue #25)."""
        conn.execute(
            """CREATE TABLE IF NOT EXISTS studio_audio_clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
                lane TEXT NOT NULL DEFAULT 'music',
                position INTEGER NOT NULL DEFAULT 0,
                file_path TEXT NOT NULL,
                display_name TEXT NOT NULL,
                volume REAL NOT NULL DEFAULT 0.8
                    CHECK (volume >= 0.0 AND volume <= 1.0),
                fade_in_s REAL NOT NULL DEFAULT 0.0
                    CHECK (fade_in_s >= 0.0),
                fade_out_s REAL NOT NULL DEFAULT 0.0
                    CHECK (fade_out_s >= 0.0),
                loop INTEGER NOT NULL DEFAULT 0
                    CHECK (loop IN (0, 1)),
                added_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_studio_audio_clips_project
               ON studio_audio_clips(project_id, lane, position)"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_studio_audio_clips_one_music
               ON studio_audio_clips(project_id) WHERE lane = 'music'"""
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
            root_id = cur.lastrowid
            assert root_id is not None
            return int(root_id)

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
        """Drop indexed media for a root.

        Does NOT touch media_meta or studio_clips / studio_projects (user curation).
        """
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
            asset_id = cur.lastrowid
            assert asset_id is not None
            return int(asset_id)

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
                "width",
                "height",
                "recorded_at",
                "sequence",
                "mode",
                "drone_model",
                "camera_model",
                "source_type",
                "latitude",
                "longitude",
                "abs_alt",
                "has_srt",
                "has_lrf",
                "track_json",
                "updated_at",
            ]
            if row:
                values = [data.get(c) for c in cols]
                sets = ", ".join(f"{c}=?" for c in cols)
                conn.execute(f"UPDATE media SET {sets} WHERE id=?", (*values, row["id"]))
                return int(row["id"])
            base_cols = [c for c in cols if c != "updated_at"]
            insert_cols = [*base_cols, "auto_tags_json", "place_json", "updated_at"]
            auto_tags = data.get("auto_tags_json") or "[]"
            place_json = data.get("place_json")
            values = [data.get(c) for c in base_cols] + [auto_tags, place_json, now]
            placeholders = ", ".join("?" for _ in insert_cols)
            cur = conn.execute(
                f"INSERT INTO media({', '.join(insert_cols)}) VALUES ({placeholders})",
                values,
            )
            media_id = cur.lastrowid
            assert media_id is not None
            return int(media_id)

    def update_media_dimensions(
        self,
        media_id: int,
        *,
        width: int | None,
        height: int | None,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """UPDATE media
                   SET width = ?, height = ?, updated_at = ?
                   WHERE id = ?""",
                (width, height, now, media_id),
            )

    def update_media_auto_tags(
        self,
        media_id: int,
        *,
        auto_tags_json: str,
        place_json: str | None,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """UPDATE media
                   SET auto_tags_json = ?, place_json = ?, updated_at = ?
                   WHERE id = ?""",
                (auto_tags_json, place_json, now, media_id),
            )

    def get_geocode_cache(self, lat_key: float, lon_key: float):
        from orga_drone.geocode import PlaceResult

        with self.connect() as conn:
            row = conn.execute(
                """SELECT country, region, city, district, country_code, source
                   FROM geocode_cache WHERE lat_key = ? AND lon_key = ?""",
                (lat_key, lon_key),
            ).fetchone()
        if not row:
            return None
        return PlaceResult(
            country=row["country"],
            region=row["region"],
            city=row["city"],
            district=row["district"],
            country_code=row["country_code"],
            source=row["source"] or "reverse_geocoder",
        )

    def upsert_geocode_cache(
        self,
        lat_key: float,
        lon_key: float,
        place,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO geocode_cache(
                       lat_key, lon_key, country, region, city, district,
                       country_code, source, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(lat_key, lon_key) DO UPDATE SET
                       country = excluded.country,
                       region = excluded.region,
                       city = excluded.city,
                       district = excluded.district,
                       country_code = excluded.country_code,
                       source = excluded.source,
                       updated_at = excluded.updated_at""",
                (
                    lat_key,
                    lon_key,
                    place.country,
                    place.region,
                    place.city,
                    place.district,
                    place.country_code,
                    place.source,
                    now,
                ),
            )

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
                durations = [
                    float(d)
                    for i in items
                    if (d := i.get("duration_s")) is not None
                ]
                total_dur = sum(durations) if durations else None
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
                flow_row_id = cur.lastrowid
                assert flow_row_id is not None
                flow_id = int(flow_row_id)
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
                    float(d)
                    for i in items
                    if i.get("kind") == "video" and (d := i.get("duration_s")) is not None
                ]
                total_dur = sum(durations) if durations else None
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
                session_row_id = cur.lastrowid
                assert session_row_id is not None
                session_id = int(session_row_id)
                for pos, mid in enumerate(group):
                    conn.execute(
                        "INSERT INTO session_items(session_id, media_id, position) VALUES (?, ?, ?)",
                        (session_id, mid, pos),
                    )
                    conn.execute(
                        "UPDATE media SET session_id = ? WHERE id = ?",
                        (session_id, mid),
                    )

    def _media_list_filters(
        self,
        *,
        drone: str | None = None,
        kind: str | None = None,
        source: str | None = None,
        has_gps: bool | None = None,
        flows_only: bool | None = None,
        sessions_only: bool | None = None,
        favorite: bool | None = None,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[list[str], list[Any], str]:
        """Return (where_clauses, params, collapse_sql) for browse list/count."""
        where = ["m.kind IN ('video', 'photo')"]
        params: list[Any] = []
        if drone:
            where.append("m.drone_model = ?")
            params.append(drone)
        if kind:
            where.append("m.kind = ?")
            params.append(kind)
        if source == "drone":
            where.append("m.source_type = 'drone'")
        elif source == "other":
            where.append("(m.source_type IS NULL OR m.source_type != 'drone')")
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
        if date_from:
            where.append("m.recorded_at IS NOT NULL AND date(m.recorded_at) >= date(?)")
            params.append(date_from)
        if date_to:
            where.append("m.recorded_at IS NOT NULL AND date(m.recorded_at) <= date(?)")
            params.append(date_to)
        # Multi-token AND: each whitespace-separated term must match somewhere.
        tokens = [t for t in (q or "").split() if t]
        for token in tokens:
            where.append(
                "(m.filename LIKE ? OR m.path LIKE ? OR m.drone_model LIKE ?"
                " OR IFNULL(mm.tags_json, '') LIKE ? OR IFNULL(mm.notes, '') LIKE ?"
                " OR IFNULL(m.auto_tags_json, '') LIKE ? OR IFNULL(m.place_json, '') LIKE ?)"
            )
            like = f"%{token}%"
            params.extend([like, like, like, like, like, like, like])

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
        return where, params, collapse

    def count_media(
        self,
        *,
        drone: str | None = None,
        kind: str | None = None,
        source: str | None = None,
        has_gps: bool | None = None,
        flows_only: bool | None = None,
        sessions_only: bool | None = None,
        favorite: bool | None = None,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        """Count browse rows after the same filters/collapse as ``list_media``."""
        where, params, collapse = self._media_list_filters(
            drone=drone,
            kind=kind,
            source=source,
            has_gps=has_gps,
            flows_only=flows_only,
            sessions_only=sessions_only,
            favorite=favorite,
            q=q,
            date_from=date_from,
            date_to=date_to,
        )
        sql = f"""
            SELECT COUNT(*)
            FROM media m
            LEFT JOIN flows f ON f.id = m.flow_id
            LEFT JOIN flow_items fi ON fi.media_id = m.id
            LEFT JOIN sessions s ON s.id = m.session_id
            LEFT JOIN session_items si ON si.media_id = m.id
            LEFT JOIN media_meta mm ON mm.media_path = m.path
            WHERE {' AND '.join(where)}
              AND {collapse}
        """
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def list_media(
        self,
        *,
        sort: str = "recorded_at",
        order: str = "desc",
        drone: str | None = None,
        kind: str | None = None,
        source: str | None = None,
        has_gps: bool | None = None,
        flows_only: bool | None = None,
        sessions_only: bool | None = None,
        favorite: bool | None = None,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int | None = None,
        offset: int = 0,
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
        where, params, collapse = self._media_list_filters(
            drone=drone,
            kind=kind,
            source=source,
            has_gps=has_gps,
            flows_only=flows_only,
            sessions_only=sessions_only,
            favorite=favorite,
            q=q,
            date_from=date_from,
            date_to=date_to,
        )

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
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
            off = max(0, int(offset))
            if off > 0:
                sql += " OFFSET ?"
                params.append(off)

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

    def ensure_default_studio_project(self, *, title: str = "Your story") -> StudioProject:
        """Return the first Studio project, creating one if the table is empty."""
        with self.connect() as conn:
            row = conn.execute(
                """SELECT id, title, created_at, updated_at
                   FROM studio_projects ORDER BY id ASC LIMIT 1"""
            ).fetchone()
            if row is not None:
                return StudioProject(
                    id=int(row["id"]),
                    title=str(row["title"]),
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                )
            now = datetime.now().isoformat(timespec="seconds")
            cur = conn.execute(
                """INSERT INTO studio_projects(title, created_at, updated_at)
                   VALUES (?, ?, ?)""",
                (title, now, now),
            )
            pid = cur.lastrowid
            assert pid is not None
            return StudioProject(
                id=int(pid), title=title, created_at=now, updated_at=now
            )

    def create_studio_project(self, title: str = "Your story") -> StudioProject:
        """Create a new Studio project (does not touch media)."""
        clean = (title or "").strip() or "Your story"
        if len(clean) > 120:
            clean = clean[:120]
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO studio_projects(title, created_at, updated_at)
                   VALUES (?, ?, ?)""",
                (clean, now, now),
            )
            pid = cur.lastrowid
            assert pid is not None
            return StudioProject(
                id=int(pid), title=clean, created_at=now, updated_at=now
            )

    def get_studio_project(self, project_id: int) -> StudioProject | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT id, title, created_at, updated_at
                   FROM studio_projects WHERE id = ?""",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return StudioProject(
            id=int(row["id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get_app_state(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_state WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def set_app_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO app_state(key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )

    def get_open_studio_project(self) -> StudioProject | None:
        """Return the last-opened project when the stored id still exists."""
        raw = self.get_app_state(STUDIO_LAST_OPENED_KEY)
        if raw is None or raw == "":
            return None
        try:
            project_id = int(raw)
        except ValueError:
            return None
        return self.get_studio_project(project_id)

    def set_open_studio_project_id(self, project_id: int | None) -> None:
        """Remember the open Studio project. ``None`` means browser mode."""
        self.set_app_state(
            STUDIO_LAST_OPENED_KEY,
            "" if project_id is None else str(int(project_id)),
        )

    def resolve_studio_page_project(self) -> StudioProject | None:
        """Project shown in Studio: last opened, or most recently edited if never set."""
        raw = self.get_app_state(STUDIO_LAST_OPENED_KEY)
        if raw is None:
            projects = self.list_studio_projects()
            if not projects:
                return None
            self.set_open_studio_project_id(projects[0].id)
            return projects[0]
        opened = self.get_open_studio_project()
        if opened is not None:
            return opened
        if raw != "":
            self.set_open_studio_project_id(None)
        return None

    def list_studio_projects(self) -> list[StudioProject]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT p.id, p.title, p.created_at, p.updated_at,
                          COUNT(c.id) AS clip_count
                   FROM studio_projects p
                   LEFT JOIN studio_clips c ON c.project_id = p.id
                   GROUP BY p.id
                   ORDER BY p.updated_at DESC, p.id DESC"""
            ).fetchall()
        return [
            StudioProject(
                id=int(r["id"]),
                title=str(r["title"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
                clip_count=int(r["clip_count"] or 0),
            )
            for r in rows
        ]

    def set_studio_project_title(self, project_id: int, title: str) -> StudioProject:
        """Persist an editable project title. Never renames source media."""
        clean = (title or "").strip()
        if not clean:
            raise ValueError("title must not be empty")
        if len(clean) > 120:
            clean = clean[:120]
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """UPDATE studio_projects
                   SET title = ?, updated_at = ?
                   WHERE id = ?""",
                (clean, now, project_id),
            )
            if cur.rowcount == 0:
                raise ValueError("studio project not found")
        project = self.get_studio_project(project_id)
        assert project is not None
        return project

    def delete_studio_project(self, project_id: int) -> bool:
        """Delete a project and its clips. Never deletes media assets or files."""
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM studio_projects WHERE id = ?",
                (project_id,),
            )
            if cur.rowcount == 0:
                return False
            opened = conn.execute(
                "SELECT value FROM app_state WHERE key = ?",
                (STUDIO_LAST_OPENED_KEY,),
            ).fetchone()
            if opened is not None and str(opened["value"]) == str(project_id):
                conn.execute(
                    """INSERT INTO app_state(key, value) VALUES (?, ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                    (STUDIO_LAST_OPENED_KEY, ""),
                )
            return True

    def _audio_clip_from_row(self, row: sqlite3.Row) -> StudioAudioClip:
        return StudioAudioClip(
            id=int(row["id"]),
            project_id=int(row["project_id"]),
            lane=str(row["lane"]),
            position=int(row["position"]),
            file_path=str(row["file_path"]),
            display_name=str(row["display_name"]),
            volume=float(row["volume"]),
            fade_in_s=float(row["fade_in_s"]),
            fade_out_s=float(row["fade_out_s"]),
            loop=bool(int(row["loop"])),
            added_at=str(row["added_at"]),
        )

    def get_studio_music(self, project_id: int) -> StudioAudioClip | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT id, project_id, lane, position, file_path, display_name,
                          volume, fade_in_s, fade_out_s, loop, added_at
                   FROM studio_audio_clips
                   WHERE project_id = ? AND lane = 'music'
                   ORDER BY position ASC, id ASC
                   LIMIT 1""",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return self._audio_clip_from_row(row)

    def set_studio_music(self, project_id: int, file_path: str) -> StudioAudioClip:
        """Upsert the project's one music clip. Never copies or modifies the file."""
        dest = Path(file_path)
        display = dest.name
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            project = conn.execute(
                "SELECT id FROM studio_projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise ValueError("studio project not found")
            existing = conn.execute(
                """SELECT id FROM studio_audio_clips
                   WHERE project_id = ? AND lane = 'music' LIMIT 1""",
                (project_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """INSERT INTO studio_audio_clips(
                           project_id, lane, position, file_path, display_name,
                           volume, fade_in_s, fade_out_s, loop, added_at
                       ) VALUES (?, 'music', 0, ?, ?, 0.8, 0.0, 0.0, 0, ?)""",
                    (project_id, str(dest), display, now),
                )
            else:
                conn.execute(
                    """UPDATE studio_audio_clips
                       SET file_path = ?, display_name = ?
                       WHERE id = ?""",
                    (str(dest), display, int(existing["id"])),
                )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        clip = self.get_studio_music(project_id)
        assert clip is not None
        return clip

    def patch_studio_music(
        self,
        project_id: int,
        *,
        volume: float | None = None,
        fade_in_s: float | None = None,
        fade_out_s: float | None = None,
        loop: bool | None = None,
    ) -> StudioAudioClip:
        current = self.get_studio_music(project_id)
        if current is None:
            raise ValueError("studio music not found")
        next_volume = current.volume if volume is None else max(0.0, min(1.0, float(volume)))
        next_fade_in = (
            current.fade_in_s if fade_in_s is None else max(0.0, min(10.0, float(fade_in_s)))
        )
        next_fade_out = (
            current.fade_out_s if fade_out_s is None else max(0.0, min(10.0, float(fade_out_s)))
        )
        next_loop = current.loop if loop is None else bool(loop)
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """UPDATE studio_audio_clips
                   SET volume = ?, fade_in_s = ?, fade_out_s = ?, loop = ?
                   WHERE project_id = ? AND lane = 'music'""",
                (
                    next_volume,
                    next_fade_in,
                    next_fade_out,
                    1 if next_loop else 0,
                    project_id,
                ),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        clip = self.get_studio_music(project_id)
        assert clip is not None
        return clip

    def delete_studio_music(self, project_id: int) -> bool:
        """Drop the music reference. Never deletes the audio file on disk."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """DELETE FROM studio_audio_clips
                   WHERE project_id = ? AND lane = 'music'""",
                (project_id,),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            return True

    def add_studio_item(
        self,
        media_path: str,
        *,
        identity_key: str,
        filename: str,
        recorded_at: str | None,
        kind: str,
        project_id: int | None = None,
        source_media_id: int | None = None,
    ) -> tuple[int, bool]:
        """Add a clip to a Studio project. Returns ``(clip_id, created)``.

        Always inserts a new clip so the same source media can appear multiple
        times in one project (Issue #16). Source files are never copied or
        modified. ``created`` is always ``True`` on success.
        """
        kind_snapshot = kind if kind in {"photo", "video"} else "photo"
        now = datetime.now().isoformat(timespec="seconds")
        project = (
            self.get_studio_project(project_id)
            if project_id is not None
            else self.ensure_default_studio_project()
        )
        if project is None:
            raise ValueError("studio project not found")
        pid = project.id
        with self.connect() as conn:
            if source_media_id is None:
                media_row = conn.execute(
                    "SELECT id FROM media WHERE path = ?",
                    (media_path,),
                ).fetchone()
                if media_row is not None:
                    source_media_id = int(media_row["id"])
            pos_row = conn.execute(
                """SELECT COALESCE(MAX(position), 0) + 1 AS next_pos
                   FROM studio_clips WHERE project_id = ?""",
                (pid,),
            ).fetchone()
            position = int(pos_row["next_pos"])
            cur = conn.execute(
                """INSERT INTO studio_clips(
                     project_id, media_path, identity_key, source_media_id, position,
                     filename_snapshot, recorded_at_snapshot, kind_snapshot,
                     photo_duration_s, source_start, source_end,
                     playback_speed, volume, transition, effect_settings, added_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 1.0, 1.0, NULL, '{}', ?)""",
                (
                    pid,
                    media_path,
                    identity_key,
                    source_media_id,
                    position,
                    filename,
                    recorded_at,
                    kind_snapshot,
                    now,
                ),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, pid),
            )
            item_id = cur.lastrowid
            assert item_id is not None
            return int(item_id), True

    def remove_studio_item(self, studio_item_id: int) -> bool:
        """Remove one Studio clip. Never deletes media assets."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT project_id FROM studio_clips WHERE id = ?",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                return False
            project_id = int(row["project_id"])
            conn.execute(
                "DELETE FROM studio_clips WHERE id = ?",
                (studio_item_id,),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            return True

    def clear_studio(self, project_id: int | None = None) -> int:
        """Remove all clips from a project (default project if omitted)."""
        project = (
            self.get_studio_project(project_id)
            if project_id is not None
            else self.ensure_default_studio_project()
        )
        if project is None:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM studio_clips WHERE project_id = ?",
                (project.id,),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project.id),
            )
            return int(cur.rowcount)

    def is_in_studio(
        self, media_path: str, project_id: int | None = None
    ) -> bool:
        with self.connect() as conn:
            if project_id is None:
                row = conn.execute(
                    "SELECT 1 FROM studio_clips WHERE media_path = ?",
                    (media_path,),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT 1 FROM studio_clips
                       WHERE media_path = ? AND project_id = ?""",
                    (media_path, project_id),
                ).fetchone()
        return row is not None

    def studio_paths_among(
        self, paths: list[str], project_id: int | None = None
    ) -> set[str]:
        if not paths:
            return set()
        placeholders = ",".join("?" for _ in paths)
        sql = (
            f"SELECT media_path FROM studio_clips WHERE media_path IN ({placeholders})"
        )
        params: list[Any] = list(paths)
        if project_id is not None:
            sql += " AND project_id = ?"
            params.append(project_id)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return {str(r["media_path"]) for r in rows}

    def list_studio_items(
        self, project_id: int | None = None
    ) -> list[StudioClip]:
        from orga_drone.studio_estimate import effective_kind

        project = (
            self.get_studio_project(project_id)
            if project_id is not None
            else self.ensure_default_studio_project()
        )
        if project is None:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT s.id, s.project_id, s.media_path, s.identity_key, s.position,
                          s.filename_snapshot, s.recorded_at_snapshot, s.added_at,
                          s.kind_snapshot, s.photo_duration_s,
                          s.source_start, s.source_end,
                          s.playback_speed, s.volume, s.transition, s.effect_settings,
                          s.source_media_id AS stored_media_id,
                          m.id AS media_id, m.filename AS live_filename,
                          m.recorded_at AS live_recorded_at, m.kind AS live_kind,
                          m.duration_s AS live_duration_s
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.project_id = ?
                   ORDER BY s.position ASC, s.id ASC""",
                (project.id,),
            ).fetchall()
        out: list[StudioClip] = []
        for r in rows:
            available = r["media_id"] is not None
            live_kind = (
                str(r["live_kind"]) if available and r["live_kind"] else None
            )
            kind_snapshot = str(r["kind_snapshot"] or "photo")
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=kind_snapshot,
            )
            photo_raw = r["photo_duration_s"]
            start_raw = r["source_start"]
            end_raw = r["source_end"]
            live_id = int(r["media_id"]) if r["media_id"] is not None else None
            stored_id = (
                int(r["stored_media_id"])
                if r["stored_media_id"] is not None
                else None
            )
            out.append(
                StudioClip(
                    id=int(r["id"]),
                    project_id=int(r["project_id"]),
                    media_path=str(r["media_path"]),
                    identity_key=str(r["identity_key"]),
                    position=int(r["position"]),
                    filename_snapshot=str(r["filename_snapshot"]),
                    recorded_at_snapshot=r["recorded_at_snapshot"],
                    kind_snapshot=kind_snapshot,
                    photo_duration_s=(
                        float(photo_raw) if photo_raw is not None else None
                    ),
                    added_at=str(r["added_at"]),
                    available=available,
                    source_media_id=live_id if live_id is not None else stored_id,
                    filename=(
                        str(r["live_filename"])
                        if available and r["live_filename"]
                        else str(r["filename_snapshot"])
                    ),
                    recorded_at=(
                        r["live_recorded_at"]
                        if available
                        else r["recorded_at_snapshot"]
                    ),
                    kind=kind if kind != "unknown" else None,
                    duration_s=(
                        float(r["live_duration_s"])
                        if available and r["live_duration_s"] is not None
                        else None
                    ),
                    source_start=(
                        float(start_raw) if start_raw is not None else None
                    ),
                    source_end=float(end_raw) if end_raw is not None else None,
                    playback_speed=float(r["playback_speed"] or 1.0),
                    volume=float(r["volume"] if r["volume"] is not None else 1.0),
                    transition=(
                        str(r["transition"]) if r["transition"] is not None else None
                    ),
                    effect_settings=str(r["effect_settings"] or "{}"),
                )
            )
        return out

    def reorder_studio_items(
        self, ordered_ids: list[int], project_id: int | None = None
    ) -> list[int]:
        """Set ``position`` to 1..n for an exact permutation of project clip IDs."""
        project = (
            self.get_studio_project(project_id)
            if project_id is not None
            else self.ensure_default_studio_project()
        )
        if project is None:
            raise ValueError("studio project not found")
        with self.connect() as conn:
            existing = {
                int(r["id"])
                for r in conn.execute(
                    "SELECT id FROM studio_clips WHERE project_id = ?",
                    (project.id,),
                ).fetchall()
            }
            if len(ordered_ids) != len(existing) or set(ordered_ids) != existing:
                raise ValueError(
                    "ordered_ids must be an exact permutation of studio clips"
                )
            for position, item_id in enumerate(ordered_ids, start=1):
                conn.execute(
                    "UPDATE studio_clips SET position = ? WHERE id = ? AND project_id = ?",
                    (position, item_id, project.id),
                )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project.id),
            )
        return list(ordered_ids)

    def set_studio_photo_duration(
        self,
        studio_item_id: int,
        duration_s: float | None,
    ) -> StudioClip:
        """Set or reset custom photo duration. Raises ``ValueError`` on bad input."""
        from orga_drone.studio_estimate import (
            clamp_photo_duration,
            effective_kind,
        )

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.kind_snapshot,
                          m.kind AS live_kind, m.id AS media_id
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            available = row["media_id"] is not None
            live_kind = (
                str(row["live_kind"]) if available and row["live_kind"] else None
            )
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind != "photo":
                raise ValueError("photo duration only applies to photos")
            if duration_s is None:
                value: float | None = None
            else:
                value = clamp_photo_duration(float(duration_s))
            conn.execute(
                "UPDATE studio_clips SET photo_duration_s = ? WHERE id = ?",
                (value, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def cut_studio_video_item(
        self,
        studio_item_id: int,
        local_cut_s: float,
    ) -> tuple[StudioClip, StudioClip]:
        """Split a video clip at ``local_cut_s`` within its trimmed range.

        Updates the original row to the left segment and inserts a new clip for
        the right segment (same source media). Source files are never modified.
        """
        from orga_drone.studio_cut import resolve_source_range, split_source_range
        from orga_drone.studio_estimate import effective_kind

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.media_path, s.identity_key, s.position,
                          s.filename_snapshot, s.recorded_at_snapshot,
                          s.kind_snapshot, s.photo_duration_s,
                          s.source_start, s.source_end, s.added_at,
                          s.source_media_id, s.playback_speed, s.volume,
                          s.transition, s.effect_settings,
                          m.id AS media_id, m.kind AS live_kind,
                          m.duration_s AS live_duration_s
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            available = row["media_id"] is not None
            live_kind = (
                str(row["live_kind"]) if available and row["live_kind"] else None
            )
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind != "video":
                raise ValueError("only video clips can be cut")
            if not available:
                raise ValueError("unavailable clips cannot be cut")
            media_duration = (
                float(row["live_duration_s"])
                if row["live_duration_s"] is not None
                else None
            )
            rang = resolve_source_range(
                source_in_s=(
                    float(row["source_start"])
                    if row["source_start"] is not None
                    else None
                ),
                source_out_s=(
                    float(row["source_end"])
                    if row["source_end"] is not None
                    else None
                ),
                media_duration_s=media_duration,
            )
            if rang is None:
                raise ValueError("video duration unknown")
            try:
                left, right = split_source_range(rang, float(local_cut_s))
            except ValueError as exc:
                raise ValueError(str(exc)) from exc

            position = int(row["position"])
            project_id = int(row["project_id"])
            conn.execute(
                """UPDATE studio_clips
                   SET position = position + 1
                   WHERE project_id = ? AND position > ?""",
                (project_id, position),
            )
            conn.execute(
                """UPDATE studio_clips
                   SET source_start = ?, source_end = ?
                   WHERE id = ?""",
                (left.source_in_s, left.source_out_s, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            source_media_id = (
                int(row["media_id"])
                if row["media_id"] is not None
                else (
                    int(row["source_media_id"])
                    if row["source_media_id"] is not None
                    else None
                )
            )
            cur = conn.execute(
                """INSERT INTO studio_clips(
                     project_id, media_path, identity_key, source_media_id, position,
                     filename_snapshot, recorded_at_snapshot, kind_snapshot,
                     photo_duration_s, source_start, source_end,
                     playback_speed, volume, transition, effect_settings, added_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    str(row["media_path"]),
                    str(row["identity_key"]),
                    source_media_id,
                    position + 1,
                    str(row["filename_snapshot"]),
                    row["recorded_at_snapshot"],
                    str(row["kind_snapshot"] or "video"),
                    right.source_in_s,
                    right.source_out_s,
                    float(row["playback_speed"] or 1.0),
                    float(row["volume"] if row["volume"] is not None else 1.0),
                    row["transition"],
                    str(row["effect_settings"] or "{}"),
                    now,
                ),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            right_id = cur.lastrowid
            assert right_id is not None

        by_id = {i.id: i for i in self.list_studio_items(project_id)}
        left_item = by_id.get(studio_item_id)
        right_item = by_id.get(int(right_id))
        if left_item is None or right_item is None:
            raise RuntimeError("cut succeeded but items missing from list")
        return left_item, right_item

    def repath_studio_item(self, old_path: str, new_path: str) -> None:
        if old_path == new_path:
            return
        with self.connect() as conn:
            conflict = conn.execute(
                "SELECT id FROM studio_clips WHERE media_path = ?",
                (new_path,),
            ).fetchone()
            if conflict:
                conn.execute(
                    "DELETE FROM studio_clips WHERE media_path = ?",
                    (old_path,),
                )
            else:
                conn.execute(
                    "UPDATE studio_clips SET media_path = ? WHERE media_path = ?",
                    (new_path, old_path),
                )

    def link_studio_item_for_path(
        self,
        media_path: str,
        *,
        filename: str,
        size_bytes: int,
        recorded_at: str | None,
    ) -> None:
        """After rescan/rename: refresh identity; relink orphan only if unambiguous.

        Rules:
        1. Exact ``media_path`` match → update ``identity_key`` + ``source_media_id``.
        2. Otherwise consider orphans with the same identity whose path is not
           currently in ``media``.
        3. Relink only when exactly one orphan path group exists (no guessing).
        """
        identity = make_identity_key(filename, size_bytes, recorded_at)
        with self.connect() as conn:
            media_row = conn.execute(
                "SELECT id FROM media WHERE path = ?",
                (media_path,),
            ).fetchone()
            live_id = int(media_row["id"]) if media_row is not None else None
            by_path = conn.execute(
                "SELECT id FROM studio_clips WHERE media_path = ?",
                (media_path,),
            ).fetchall()
            if by_path:
                conn.execute(
                    """UPDATE studio_clips
                       SET identity_key = ?, source_media_id = ?
                       WHERE media_path = ?""",
                    (identity, live_id, media_path),
                )
                return
            orphans = conn.execute(
                """SELECT id, media_path FROM studio_clips
                   WHERE identity_key = ?
                     AND media_path NOT IN (SELECT path FROM media)""",
                (identity,),
            ).fetchall()
            if not orphans:
                return
            orphan_paths = {str(r["media_path"]) for r in orphans}
            if len(orphan_paths) != 1:
                return
            conflict = conn.execute(
                "SELECT id FROM studio_clips WHERE media_path = ?",
                (media_path,),
            ).fetchone()
            if conflict:
                return
            orphan_ids = [int(r["id"]) for r in orphans]
            placeholders = ",".join("?" for _ in orphan_ids)
            conn.execute(
                f"""UPDATE studio_clips
                   SET media_path = ?, identity_key = ?, source_media_id = ?,
                       filename_snapshot = ?, recorded_at_snapshot = ?
                   WHERE id IN ({placeholders})""",
                (
                    media_path,
                    identity,
                    live_id,
                    filename,
                    recorded_at,
                    *orphan_ids,
                ),
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

    def list_media_for_duplicates(self) -> list[sqlite3.Row]:
        """All video/photo rows with root label/path for duplicate scanning."""
        with self.connect() as conn:
            return list(
                conn.execute(
                    """SELECT m.id, m.root_id, m.kind, m.filename, m.path,
                              m.size_bytes, m.duration_s, m.recorded_at,
                              r.label AS root_label, r.path AS root_path
                       FROM media m
                       LEFT JOIN library_roots r ON r.id = m.root_id
                       WHERE m.kind IN ('video', 'photo')
                       ORDER BY m.id"""
                )
            )

    def list_geo_media(
        self,
        *,
        north: float | None = None,
        south: float | None = None,
        east: float | None = None,
        west: float | None = None,
        with_gps: bool | None = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Lightweight media rows for the world map (GPS filter / bbox optional)."""
        where = ["m.kind IN ('video', 'photo')"]
        params: list[Any] = []
        if with_gps is True:
            where.append("m.latitude IS NOT NULL AND m.longitude IS NOT NULL")
        elif with_gps is False:
            where.append("(m.latitude IS NULL OR m.longitude IS NULL)")

        if (
            with_gps is not False
            and north is not None
            and south is not None
            and east is not None
            and west is not None
        ):
            # Handle antimeridian: east < west means bbox crosses 180°.
            if east >= west:
                where.append("m.latitude BETWEEN ? AND ? AND m.longitude BETWEEN ? AND ?")
                params.extend([south, north, west, east])
            else:
                where.append(
                    "m.latitude BETWEEN ? AND ?"
                    " AND (m.longitude >= ? OR m.longitude <= ?)"
                )
                params.extend([south, north, west, east])

        limit_sql = ""
        if limit is not None and limit > 0:
            limit_sql = " LIMIT ?"
            params.append(int(limit))

        sql = f"""
            SELECT m.id, m.kind, m.filename, m.recorded_at, m.duration_s,
                   m.size_bytes, m.drone_model, m.latitude, m.longitude,
                   COALESCE(mm.stars, 0) AS stars,
                   COALESCE(mm.favorite, 0) AS favorite
            FROM media m
            LEFT JOIN media_meta mm ON mm.media_path = m.path
            WHERE {' AND '.join(where)}
            ORDER BY m.recorded_at DESC, m.id DESC
            {limit_sql}
        """
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": int(r["id"]),
                    "kind": r["kind"],
                    "filename": r["filename"],
                    "recorded_at": r["recorded_at"],
                    "duration_s": r["duration_s"],
                    "size_bytes": int(r["size_bytes"] or 0),
                    "drone_model": r["drone_model"],
                    "lat": r["latitude"],
                    "lon": r["longitude"],
                    "stars": int(r["stars"] or 0),
                    "favorite": bool(r["favorite"]),
                }
            )
        return out

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            videos = conn.execute("SELECT COUNT(*) AS c FROM media WHERE kind='video'").fetchone()["c"]
            photos = conn.execute("SELECT COUNT(*) AS c FROM media WHERE kind='photo'").fetchone()["c"]
            flows = conn.execute("SELECT COUNT(*) AS c FROM flows WHERE clip_count > 1").fetchone()["c"]
            sessions = conn.execute(
                "SELECT COUNT(*) AS c FROM sessions WHERE video_count > 1"
            ).fetchone()["c"]
            roots = conn.execute("SELECT COUNT(*) AS c FROM library_roots").fetchone()["c"]
            with_gps = conn.execute(
                """SELECT COUNT(*) AS c FROM media
                   WHERE kind IN ('video', 'photo')
                     AND latitude IS NOT NULL AND longitude IS NOT NULL"""
            ).fetchone()["c"]
            favorites = conn.execute(
                """SELECT COUNT(*) AS c FROM media m
                   JOIN media_meta mm ON mm.media_path = m.path
                   WHERE m.kind IN ('video', 'photo') AND mm.favorite = 1"""
            ).fetchone()["c"]
        return {
            "videos": videos,
            "photos": photos,
            "flows": flows,
            "sessions": sessions,
            "roots": roots,
            "with_gps": with_gps,
            "favorites": favorites,
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
        self.repath_studio_item(old_path, new_path)

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
            self.repath_studio_item(old["path"], path)
        if old:
            self.link_media_meta_for_path(
                path,
                filename=filename,
                size_bytes=int(old["size_bytes"] or 0),
                recorded_at=old["recorded_at"],
            )
            self.link_studio_item_for_path(
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
        auto_tags = tags_from_json(row["auto_tags_json"] if "auto_tags_json" in keys else None)
        place_raw = row["place_json"] if "place_json" in keys else None
        place: dict[str, Any] | None = None
        if place_raw:
            try:
                parsed = json.loads(place_raw)
                place = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                place = None
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
            source_type=(row["source_type"] if "source_type" in keys else None),
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
            auto_tags=auto_tags,
            place=place,
            width=(
                int(row["width"])
                if "width" in keys and row["width"] is not None
                else None
            ),
            height=(
                int(row["height"])
                if "height" in keys and row["height"] is not None
                else None
            ),
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
