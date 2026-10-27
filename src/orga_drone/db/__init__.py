"""SQLite persistence for library roots, assets, media, flows, sessions, and albums."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from orga_drone.browse_timeline import (
    recorded_span_clause,
    timeline_day_key_sql,
    timeline_order_sql,
)

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
    duration_probe INTEGER,
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

-- Clips: media references OR generated Title Cards (Issue #26 / ADR 0009).
-- Multiple media clips may share media_path / source_media_id.
-- Title Cards have NULL media_path/identity_key and never pretend to be files.
CREATE TABLE IF NOT EXISTS studio_clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
    item_kind TEXT NOT NULL DEFAULT 'media',
    media_path TEXT,
    identity_key TEXT,
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
    transition_duration_s REAL,
    effect_settings TEXT NOT NULL DEFAULT '{}',
    title_text TEXT,
    subtitle_text TEXT,
    card_duration_s REAL,
    background TEXT,
    added_at TEXT NOT NULL,
    CHECK (item_kind IN ('media', 'title_card')),
    CHECK (
        (item_kind = 'media' AND media_path IS NOT NULL AND identity_key IS NOT NULL)
        OR (
            item_kind = 'title_card'
            AND media_path IS NULL
            AND identity_key IS NULL
            AND source_media_id IS NULL
        )
    ),
    CHECK (background IS NULL OR background IN ('dark', 'light', 'accent'))
);
CREATE INDEX IF NOT EXISTS idx_studio_clips_project ON studio_clips(project_id);
CREATE INDEX IF NOT EXISTS idx_studio_clips_identity ON studio_clips(identity_key);
CREATE INDEX IF NOT EXISTS idx_studio_clips_position ON studio_clips(project_id, position);
CREATE INDEX IF NOT EXISTS idx_studio_clips_path ON studio_clips(media_path);
CREATE INDEX IF NOT EXISTS idx_studio_clips_source_media ON studio_clips(source_media_id);

-- Full recording kept beside a cut Story (Issue #156). Rows stay when the
-- Story clips of that file are removed. Source files are not copied.
CREATE TABLE IF NOT EXISTS studio_originals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
    media_path TEXT NOT NULL,
    source_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
    filename_snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (project_id, media_path)
);
CREATE INDEX IF NOT EXISTS idx_studio_originals_project ON studio_originals(project_id);

-- Optional soundtrack playlist per project (Issue #25 / #38 / ADR 0008).
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
    duration_s REAL,
    added_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_studio_audio_clips_project
    ON studio_audio_clips(project_id, lane, position);

-- Library albums (non-destructive references; independent of Studio projects).
CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS album_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    media_path TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    source_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
    filename_snapshot TEXT NOT NULL,
    kind_snapshot TEXT NOT NULL,
    recorded_at_snapshot TEXT,
    added_at TEXT NOT NULL,
    UNIQUE (album_id, media_path)
);
CREATE INDEX IF NOT EXISTS idx_album_items_album ON album_items(album_id);
CREATE INDEX IF NOT EXISTS idx_album_items_path ON album_items(media_path);
CREATE INDEX IF NOT EXISTS idx_album_items_identity ON album_items(identity_key);
CREATE INDEX IF NOT EXISTS idx_album_items_source ON album_items(source_media_id);

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


def remember_studio_original(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    media_path: str,
    source_media_id: int | None,
    filename: str,
    now: str,
) -> None:
    """Keep one Original row for a cut video. A second cut does not add another."""
    conn.execute(
        """INSERT INTO studio_originals (
             project_id, media_path, source_media_id, filename_snapshot, created_at
           ) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(project_id, media_path) DO UPDATE SET
             source_media_id = COALESCE(
               excluded.source_media_id, studio_originals.source_media_id
             ),
             filename_snapshot = excluded.filename_snapshot
        """,
        (project_id, media_path, source_media_id, filename, now),
    )


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
STUDIO_MUSIC_MAX_TRACKS = 8
STUDIO_MUSIC_LANE = "music"


@dataclass
class StudioAudioClip:
    """One soundtrack reference in a Studio project playlist (never copies the file)."""

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
    duration_s: float | None = None


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
    """One Story clip: media reference or generated Title Card (never copies files)."""

    id: int
    project_id: int
    media_path: str | None
    identity_key: str | None
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
    transition_duration_s: float | None = None
    effect_settings: str = "{}"
    item_kind: str = "media"
    title_text: str | None = None
    subtitle_text: str | None = None
    card_duration_s: float | None = None
    background: str | None = None

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

ALBUM_TITLE_MAX = 80


def clean_album_title(title: str | None) -> str | None:
    """Collapse whitespace and cap length. None when nothing remains."""
    collapsed = " ".join((title or "").split())
    if not collapsed:
        return None
    if len(collapsed) > ALBUM_TITLE_MAX:
        collapsed = collapsed[:ALBUM_TITLE_MAX].rstrip()
    return collapsed or None


def album_media_state(media_path: str) -> str:
    """``available`` when the referenced file is on disk, otherwise ``offline``.

    Album membership is kept either way. Offline covers a missing file or an
    unplugged drive; the original file is never changed here.
    """
    try:
        on_disk = Path(media_path).is_file()
    except OSError:
        on_disk = False
    return "available" if on_disk else "offline"


@dataclass
class Album:
    """A user-named library album. Does not own or copy media files."""

    id: int
    title: str
    created_at: str
    updated_at: str
    item_count: int = 0


@dataclass
class AlbumItem:
    """One media reference inside an album (path + identity, not a file copy)."""

    id: int
    album_id: int
    media_path: str
    identity_key: str
    filename: str
    kind: str
    recorded_at: str | None
    added_at: str
    state: str
    media_id: int | None


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
        if "srt_token" not in media_cols:
            conn.execute("ALTER TABLE media ADD COLUMN srt_token TEXT")
        if "duration_probe" not in media_cols:
            conn.execute("ALTER TABLE media ADD COLUMN duration_probe INTEGER")
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
        Database._migrate_studio_clips_title_cards(conn)
        Database._migrate_studio_clips_transition_duration(conn)
        Database._migrate_studio_audio_clips(conn)
        Database._migrate_albums(conn)
        Database._migrate_studio_originals(conn)
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
    def _migrate_studio_clips_title_cards(conn: sqlite3.Connection) -> None:
        """Allow generated Title Cards: nullable media identity + structured fields."""
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_clips'"
        ).fetchone()
        if not exists:
            return
        cols = {
            r[1] for r in conn.execute("PRAGMA table_info(studio_clips)").fetchall()
        }
        if "item_kind" in cols and "title_text" in cols and "card_duration_s" in cols:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_studio_clips_item_kind "
                "ON studio_clips(project_id, item_kind)"
            )
            return
        conn.executescript(
            """
            CREATE TABLE studio_clips__title_mig (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
                item_kind TEXT NOT NULL DEFAULT 'media',
                media_path TEXT,
                identity_key TEXT,
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
                title_text TEXT,
                subtitle_text TEXT,
                card_duration_s REAL,
                background TEXT,
                added_at TEXT NOT NULL,
                CHECK (item_kind IN ('media', 'title_card')),
                CHECK (
                    (item_kind = 'media' AND media_path IS NOT NULL AND identity_key IS NOT NULL)
                    OR (
                        item_kind = 'title_card'
                        AND media_path IS NULL
                        AND identity_key IS NULL
                        AND source_media_id IS NULL
                    )
                ),
                CHECK (background IS NULL OR background IN ('dark', 'light', 'accent'))
            );
            INSERT INTO studio_clips__title_mig(
                id, project_id, item_kind, media_path, identity_key, source_media_id,
                position, filename_snapshot, recorded_at_snapshot, kind_snapshot,
                photo_duration_s, source_start, source_end,
                playback_speed, volume, transition, effect_settings,
                title_text, subtitle_text, card_duration_s, background, added_at
            )
            SELECT id, project_id, 'media', media_path, identity_key, source_media_id,
                   position, filename_snapshot, recorded_at_snapshot, kind_snapshot,
                   photo_duration_s, source_start, source_end,
                   playback_speed, volume, transition, effect_settings,
                   NULL, NULL, NULL, NULL, added_at
            FROM studio_clips;
            DROP TABLE studio_clips;
            ALTER TABLE studio_clips__title_mig RENAME TO studio_clips;
            CREATE INDEX IF NOT EXISTS idx_studio_clips_project ON studio_clips(project_id);
            CREATE INDEX IF NOT EXISTS idx_studio_clips_identity ON studio_clips(identity_key);
            CREATE INDEX IF NOT EXISTS idx_studio_clips_position ON studio_clips(project_id, position);
            CREATE INDEX IF NOT EXISTS idx_studio_clips_path ON studio_clips(media_path);
            CREATE INDEX IF NOT EXISTS idx_studio_clips_source_media ON studio_clips(source_media_id);
            CREATE INDEX IF NOT EXISTS idx_studio_clips_item_kind ON studio_clips(project_id, item_kind);
            """
        )

    @staticmethod
    def _migrate_studio_clips_transition_duration(conn: sqlite3.Connection) -> None:
        """Outgoing transition duration (Issue #27). Type stays in ``transition``."""
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_clips'"
        ).fetchone()
        if not exists:
            return
        cols = {
            r[1] for r in conn.execute("PRAGMA table_info(studio_clips)").fetchall()
        }
        if "transition_duration_s" not in cols:
            conn.execute(
                "ALTER TABLE studio_clips ADD COLUMN transition_duration_s REAL"
            )

    @staticmethod
    def _migrate_studio_audio_clips(conn: sqlite3.Connection) -> None:
        """Optional per-project music playlist (Issue #25 / #38)."""
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
                duration_s REAL,
                added_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_studio_audio_clips_project
               ON studio_audio_clips(project_id, lane, position)"""
        )
        conn.execute("DROP INDEX IF EXISTS idx_studio_audio_clips_one_music")
        cols = {
            r[1] for r in conn.execute("PRAGMA table_info(studio_audio_clips)").fetchall()
        }
        if "duration_s" not in cols:
            conn.execute("ALTER TABLE studio_audio_clips ADD COLUMN duration_s REAL")

    @staticmethod
    def _migrate_albums(conn: sqlite3.Connection) -> None:
        """User-managed library albums. Membership survives media-row rebuilds."""
        conn.execute(
            """CREATE TABLE IF NOT EXISTS albums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS album_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
                media_path TEXT NOT NULL,
                identity_key TEXT NOT NULL,
                source_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
                filename_snapshot TEXT NOT NULL,
                kind_snapshot TEXT NOT NULL,
                recorded_at_snapshot TEXT,
                added_at TEXT NOT NULL,
                UNIQUE (album_id, media_path)
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_album_items_album ON album_items(album_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_album_items_path ON album_items(media_path)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_album_items_identity ON album_items(identity_key)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_album_items_source ON album_items(source_media_id)"
        )

    @staticmethod
    def _migrate_studio_originals(conn: sqlite3.Connection) -> None:
        """One Original row per cut video in a project. Existing libraries gain the table."""
        conn.execute(
            """CREATE TABLE IF NOT EXISTS studio_originals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
                media_path TEXT NOT NULL,
                source_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
                filename_snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (project_id, media_path)
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_originals_project ON studio_originals(project_id)"
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

        Does NOT touch media_meta, album_items, or studio_clips / studio_projects
        (user curation). Deleting media rows sets album_items.source_media_id
        to NULL; the album reference itself stays.
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

    def indexed_assets_for_root(self, root_id: int) -> dict[str, dict[str, Any]]:
        """Asset rows for one root, with the media id when this path is library media.

        Used to skip metadata extraction when size and mtime are unchanged.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT a.id AS asset_id, a.path, a.kind, a.size_bytes, a.mtime,
                          a.stem_base, m.id AS media_id, m.has_srt, m.has_lrf, m.srt_token,
                          m.duration_s, m.duration_probe
                   FROM assets a
                   LEFT JOIN media m
                     ON m.path = a.path AND m.root_id = a.root_id
                   WHERE a.root_id = ?""",
                (root_id,),
            ).fetchall()
        found: dict[str, dict[str, Any]] = {}
        for row in rows:
            media_id = None if row["media_id"] is None else int(row["media_id"])
            found[str(row["path"])] = {
                "asset_id": int(row["asset_id"]),
                "kind": str(row["kind"]),
                "size_bytes": int(row["size_bytes"]),
                "mtime": None if row["mtime"] is None else float(row["mtime"]),
                "stem_base": row["stem_base"],
                "media_id": media_id,
                "has_srt": int(row["has_srt"] or 0) if media_id is not None else 0,
                "has_lrf": int(row["has_lrf"] or 0) if media_id is not None else 0,
                "srt_token": None if row["srt_token"] is None else str(row["srt_token"]),
                "duration_s": None if row["duration_s"] is None else float(row["duration_s"]),
                "duration_probe": (
                    None if row["duration_probe"] is None else int(row["duration_probe"])
                ),
            }
        return found

    def remove_root_index_except(self, root_id: int, keep_paths: set[str]) -> int:
        """Drop asset and media rows for this root that were not rediscovered.

        Does not delete files on disk, ``media_meta``, or Studio clips. Call
        this only after a completed walk of a root that is still readable.
        Returns how many asset rows were removed.
        """
        with self.connect() as conn:
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS scan_keep_paths(path TEXT PRIMARY KEY)"
            )
            conn.execute("DELETE FROM scan_keep_paths")
            conn.executemany(
                "INSERT OR IGNORE INTO scan_keep_paths(path) VALUES (?)",
                [(path,) for path in keep_paths],
            )
            conn.execute(
                """DELETE FROM media
                   WHERE root_id = ?
                     AND path NOT IN (SELECT path FROM scan_keep_paths)""",
                (root_id,),
            )
            cur = conn.execute(
                """DELETE FROM assets
                   WHERE root_id = ?
                     AND path NOT IN (SELECT path FROM scan_keep_paths)""",
                (root_id,),
            )
            removed = cur.rowcount
        return int(removed) if removed is not None and removed > 0 else 0

    def set_asset_kind(self, asset_id: int, kind: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE assets SET kind = ? WHERE id = ?",
                (kind, asset_id),
            )

    def delete_media_row(self, media_id: int) -> None:
        """Drop one indexed media row.

        Does not delete the file, ``media_meta``, or Studio clips. A Studio
        ``source_media_id`` for this row becomes NULL.
        """
        with self.connect() as conn:
            conn.execute("DELETE FROM media WHERE id = ?", (media_id,))

    def set_media_srt_token(self, media_id: int, token: str) -> None:
        """Remember the sibling SRT size and mtime used for this media row."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE media SET srt_token = ? WHERE id = ?",
                (token, media_id),
            )

    def set_media_sidecar_flags(
        self,
        media_id: int,
        *,
        has_srt: bool,
        has_lrf: bool,
    ) -> None:
        """Update SRT/LRF flags without rewriting extracted metadata."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE media SET has_srt = ?, has_lrf = ? WHERE id = ?",
                (1 if has_srt else 0, 1 if has_lrf else 0, media_id),
            )

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
            if "duration_probe" in data:
                cols.append("duration_probe")
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

    def fill_video_duration_if_missing(self, media_id: int) -> float | None:
        """Store a container duration when a video was indexed without one.

        A Studio export has no sibling SRT. The Windows package has no ffprobe,
        so an earlier scan can leave ``duration_s`` empty. Reading the file
        header here lets Studio show the clip without a full library rescan.
        A missing file is left unmarked so a later open can try again.
        """
        with self.connect() as conn:
            row = conn.execute(
                """SELECT path, kind, duration_s, duration_probe
                   FROM media WHERE id = ?""",
                (media_id,),
            ).fetchone()
        if row is None or str(row["kind"]) != "video":
            return None
        if row["duration_s"] is not None:
            try:
                return float(row["duration_s"])
            except (TypeError, ValueError):
                return None
        if row["duration_probe"]:
            return None
        path = Path(str(row["path"]))
        if not path.is_file():
            return None
        from orga_drone.parse import probe_video_with_ffprobe

        duration = probe_video_with_ffprobe(path)[2]
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """UPDATE media
                   SET duration_s = ?, duration_probe = 1, updated_at = ?
                   WHERE id = ? AND duration_s IS NULL""",
                (duration, now, media_id),
            )
        return duration

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
        recorded_span: str | None = None,
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
            # Parentheses required: AND binds tighter than OR, so an ungrouped
            # predicate lets rows skip kind, drone, and session collapse.
            where.append("(m.latitude IS NULL OR m.longitude IS NULL)")
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
        span_sql, span_params = recorded_span_clause(recorded_span)
        if span_sql:
            where.append(span_sql)
            params.extend(span_params)
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
        recorded_span: str | None = None,
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
            recorded_span=recorded_span,
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

    def timeline_day_counts(
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
    ) -> list[tuple[str | None, int]]:
        """Calendar-day counts for the Browse timeline navigator.

        Uses the same filters and row collapse as ``list_media``. A NULL day
        means the recording date is missing or not a calendar day. The timeline
        focus itself is not applied, so year/month/day links stay visible.
        """
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
        day_key = timeline_day_key_sql()
        sql = f"""
            SELECT {day_key} AS day_key,
                   COUNT(*) AS n
            FROM media m
            LEFT JOIN flows f ON f.id = m.flow_id
            LEFT JOIN flow_items fi ON fi.media_id = m.id
            LEFT JOIN sessions s ON s.id = m.session_id
            LEFT JOIN session_items si ON si.media_id = m.id
            LEFT JOIN media_meta mm ON mm.media_path = m.path
            WHERE {' AND '.join(where)}
              AND {collapse}
            GROUP BY day_key
        """
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [(None if row[0] is None else str(row[0]), int(row[1])) for row in rows]

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
        recorded_span: str | None = None,
        date_order: str | None = None,
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
            recorded_span=recorded_span,
        )
        if date_order in {"asc", "desc"}:
            direction = "ASC" if date_order == "asc" else "DESC"
            order_clause = timeline_order_sql(direction)
        else:
            order_clause = f"{sort_sql} {order_sql}, m.id DESC"

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
            ORDER BY {order_clause}
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
        raw_duration = row["duration_s"] if "duration_s" in row.keys() else None
        duration_s = float(raw_duration) if raw_duration is not None else None
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
            duration_s=duration_s,
        )

    def _probe_music_duration_s(self, file_path: str) -> float | None:
        try:
            from orga_drone.export.music_mix import probe_audio_duration_s

            probed = probe_audio_duration_s(Path(file_path))
        except (OSError, ValueError):
            return None
        if probed is None or probed <= 0:
            return None
        return float(probed)

    def _compact_studio_music_positions(
        self, conn: sqlite3.Connection, project_id: int
    ) -> None:
        rows = conn.execute(
            """SELECT id FROM studio_audio_clips
               WHERE project_id = ? AND lane = ?
               ORDER BY position ASC, id ASC""",
            (project_id, STUDIO_MUSIC_LANE),
        ).fetchall()
        for position, row in enumerate(rows):
            conn.execute(
                """UPDATE studio_audio_clips SET position = ?
                   WHERE id = ? AND project_id = ?""",
                (position, int(row["id"]), project_id),
            )

    def list_studio_music(self, project_id: int) -> list[StudioAudioClip]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id, project_id, lane, position, file_path, display_name,
                          volume, fade_in_s, fade_out_s, loop, duration_s, added_at
                   FROM studio_audio_clips
                   WHERE project_id = ? AND lane = ?
                   ORDER BY position ASC, id ASC""",
                (project_id, STUDIO_MUSIC_LANE),
            ).fetchall()
        return [self._audio_clip_from_row(row) for row in rows]

    def get_studio_music(self, project_id: int) -> StudioAudioClip | None:
        """First soundtrack clip, if any (single-song compatibility)."""
        tracks = self.list_studio_music(project_id)
        return tracks[0] if tracks else None

    def get_studio_music_clip(
        self, project_id: int, clip_id: int
    ) -> StudioAudioClip | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT id, project_id, lane, position, file_path, display_name,
                          volume, fade_in_s, fade_out_s, loop, duration_s, added_at
                   FROM studio_audio_clips
                   WHERE project_id = ? AND id = ? AND lane = ?""",
                (project_id, clip_id, STUDIO_MUSIC_LANE),
            ).fetchone()
        if row is None:
            return None
        return self._audio_clip_from_row(row)

    def append_studio_music(self, project_id: int, file_path: str) -> StudioAudioClip:
        """Insert a soundtrack at the end of the playlist. Never copies the file."""
        dest = Path(file_path)
        display = dest.name
        now = datetime.now().isoformat(timespec="seconds")
        duration_s = self._probe_music_duration_s(str(dest))
        with self.connect() as conn:
            project = conn.execute(
                "SELECT id FROM studio_projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise ValueError("studio project not found")
            count_row = conn.execute(
                """SELECT COUNT(*) AS n FROM studio_audio_clips
                   WHERE project_id = ? AND lane = ?""",
                (project_id, STUDIO_MUSIC_LANE),
            ).fetchone()
            count = int(count_row["n"]) if count_row is not None else 0
            if count >= STUDIO_MUSIC_MAX_TRACKS:
                raise ValueError("music_limit")
            cur = conn.execute(
                """INSERT INTO studio_audio_clips(
                       project_id, lane, position, file_path, display_name,
                       volume, fade_in_s, fade_out_s, loop, duration_s, added_at
                   ) VALUES (?, ?, ?, ?, ?, 0.8, 0.0, 0.0, 0, ?, ?)""",
                (
                    project_id,
                    STUDIO_MUSIC_LANE,
                    count,
                    str(dest),
                    display,
                    duration_s,
                    now,
                ),
            )
            clip_id = int(cur.lastrowid or 0)
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        clip = self.get_studio_music_clip(project_id, clip_id)
        assert clip is not None
        return clip

    def set_studio_music(self, project_id: int, file_path: str) -> StudioAudioClip:
        """Append a soundtrack song. Never copies or modifies the file."""
        return self.append_studio_music(project_id, file_path)

    def patch_studio_music_clip(
        self,
        project_id: int,
        clip_id: int,
        *,
        volume: float | None = None,
        fade_in_s: float | None = None,
        fade_out_s: float | None = None,
        loop: bool | None = None,
        file_path: str | None = None,
    ) -> StudioAudioClip:
        current = self.get_studio_music_clip(project_id, clip_id)
        if current is None:
            raise ValueError("studio music not found")
        tracks = self.list_studio_music(project_id)
        if loop is not None and len(tracks) != 1:
            raise ValueError("loop_single_only")
        next_volume = current.volume if volume is None else max(0.0, min(1.0, float(volume)))
        next_fade_in = (
            current.fade_in_s if fade_in_s is None else max(0.0, min(10.0, float(fade_in_s)))
        )
        next_fade_out = (
            current.fade_out_s if fade_out_s is None else max(0.0, min(10.0, float(fade_out_s)))
        )
        next_loop = current.loop if loop is None else bool(loop)
        next_path = current.file_path
        next_name = current.display_name
        next_duration = current.duration_s
        if file_path is not None:
            dest = Path(file_path)
            next_path = str(dest)
            next_name = dest.name
            next_duration = self._probe_music_duration_s(next_path)
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """UPDATE studio_audio_clips
                   SET volume = ?, fade_in_s = ?, fade_out_s = ?, loop = ?,
                       file_path = ?, display_name = ?, duration_s = ?
                   WHERE id = ? AND project_id = ? AND lane = ?""",
                (
                    next_volume,
                    next_fade_in,
                    next_fade_out,
                    1 if next_loop else 0,
                    next_path,
                    next_name,
                    next_duration,
                    clip_id,
                    project_id,
                    STUDIO_MUSIC_LANE,
                ),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        clip = self.get_studio_music_clip(project_id, clip_id)
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
        return self.patch_studio_music_clip(
            project_id,
            current.id,
            volume=volume,
            fade_in_s=fade_in_s,
            fade_out_s=fade_out_s,
            loop=loop,
        )

    def delete_studio_music_clip(self, project_id: int, clip_id: int) -> bool:
        """Drop one soundtrack reference. Never deletes the audio file on disk."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """DELETE FROM studio_audio_clips
                   WHERE project_id = ? AND id = ? AND lane = ?""",
                (project_id, clip_id, STUDIO_MUSIC_LANE),
            )
            if cur.rowcount == 0:
                return False
            self._compact_studio_music_positions(conn, project_id)
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            return True

    def delete_studio_music(self, project_id: int) -> bool:
        """Drop all soundtrack references. Never deletes audio files on disk."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """DELETE FROM studio_audio_clips
                   WHERE project_id = ? AND lane = ?""",
                (project_id, STUDIO_MUSIC_LANE),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            return True

    def reorder_studio_music(self, project_id: int, ordered_ids: list[int]) -> list[int]:
        """Set ``position`` to 0..n-1 for an exact permutation of music ids."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            existing = {
                int(r["id"])
                for r in conn.execute(
                    """SELECT id FROM studio_audio_clips
                       WHERE project_id = ? AND lane = ?""",
                    (project_id, STUDIO_MUSIC_LANE),
                ).fetchall()
            }
            if len(ordered_ids) != len(existing) or set(ordered_ids) != existing:
                raise ValueError(
                    "ordered_ids must be an exact permutation of soundtrack clips"
                )
            for position, item_id in enumerate(ordered_ids):
                conn.execute(
                    """UPDATE studio_audio_clips SET position = ?
                       WHERE id = ? AND project_id = ?""",
                    (position, item_id, project_id),
                )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        return [clip.id for clip in self.list_studio_music(project_id)]

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
                     project_id, item_kind, media_path, identity_key, source_media_id, position,
                     filename_snapshot, recorded_at_snapshot, kind_snapshot,
                     photo_duration_s, source_start, source_end,
                     playback_speed, volume, transition, effect_settings, added_at
                   ) VALUES (?, 'media', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 1.0, 1.0, NULL, '{}', ?)""",
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

    def add_studio_media_ids(
        self,
        media_ids: list[int],
        *,
        project_id: int,
    ) -> tuple[int, int]:
        """Add media to a Studio project, skipping paths already present.

        Reuses :meth:`add_studio_item` for each new clip. Invalid / missing
        media IDs are ignored. Returns ``(added_count, skipped_existing)``.
        Source files are never copied. Unlike repeated single-add (which may
        insert duplicate rows for Issue #16), this bulk path is membership-safe.
        """
        if self.get_studio_project(project_id) is None:
            raise ValueError("studio project not found")

        seen_ids: set[int] = set()
        ordered_ids: list[int] = []
        for raw in media_ids:
            try:
                mid = int(raw)
            except (TypeError, ValueError):
                continue
            if mid <= 0 or mid in seen_ids:
                continue
            seen_ids.add(mid)
            ordered_ids.append(mid)

        items: list[Any] = []
        for mid in ordered_ids:
            item = self.get_media(mid)
            if item is not None:
                items.append(item)

        known_paths = self.studio_paths_among(
            [item.path for item in items],
            project_id=project_id,
        )
        added = 0
        skipped = 0
        for item in items:
            if item.path in known_paths:
                skipped += 1
                continue
            self.add_studio_item(
                item.path,
                identity_key=make_identity_key(
                    item.filename, item.size_bytes, item.recorded_at
                ),
                filename=item.filename,
                recorded_at=item.recorded_at,
                kind=item.kind,
                project_id=project_id,
                source_media_id=item.id,
            )
            known_paths.add(item.path)
            added += 1
        return added, skipped

    def add_studio_title_card(
        self,
        project_id: int,
        *,
        title_text: str,
        subtitle_text: str = "",
        card_duration_s: float | None = None,
        background: str | None = None,
    ) -> StudioClip:
        """Append a generated Title Card. Never copies or creates media files."""
        from orga_drone.studio_title_card import (
            DEFAULT_BACKGROUND,
            DEFAULT_DURATION_S,
            ITEM_KIND_TITLE_CARD,
            TITLE_CARD_KIND,
            clamp_card_duration,
            normalize_background,
            normalize_subtitle,
            normalize_title,
        )

        project = self.get_studio_project(project_id)
        if project is None:
            raise ValueError("studio project not found")
        title = normalize_title(title_text)
        subtitle = normalize_subtitle(subtitle_text)
        duration = clamp_card_duration(
            DEFAULT_DURATION_S if card_duration_s is None else float(card_duration_s)
        )
        bg = normalize_background(background or DEFAULT_BACKGROUND)
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            pos_row = conn.execute(
                """SELECT COALESCE(MAX(position), 0) + 1 AS next_pos
                   FROM studio_clips WHERE project_id = ?""",
                (project.id,),
            ).fetchone()
            position = int(pos_row["next_pos"])
            cur = conn.execute(
                """INSERT INTO studio_clips(
                     project_id, item_kind, media_path, identity_key, source_media_id,
                     position, filename_snapshot, recorded_at_snapshot, kind_snapshot,
                     photo_duration_s, source_start, source_end,
                     playback_speed, volume, transition, effect_settings,
                     title_text, subtitle_text, card_duration_s, background, added_at
                   ) VALUES (?, ?, NULL, NULL, NULL, ?, '', NULL, ?, NULL, NULL, NULL,
                             1.0, 1.0, NULL, '{}', ?, ?, ?, ?, ?)""",
                (
                    project.id,
                    ITEM_KIND_TITLE_CARD,
                    position,
                    TITLE_CARD_KIND,
                    title,
                    subtitle,
                    duration,
                    bg,
                    now,
                ),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project.id),
            )
            item_id = cur.lastrowid
            assert item_id is not None
        items = {i.id: i for i in self.list_studio_items(project.id)}
        clip = items.get(int(item_id))
        assert clip is not None
        return clip

    def update_studio_title_card(
        self,
        studio_item_id: int,
        *,
        title_text: str | None = None,
        subtitle_text: str | None = None,
        card_duration_s: float | None = None,
        background: str | None = None,
    ) -> StudioClip:
        """Patch Title Card fields. Raises ValueError if the row is not a card."""
        from orga_drone.studio_title_card import (
            ITEM_KIND_TITLE_CARD,
            clamp_card_duration,
            normalize_background,
            normalize_subtitle,
            normalize_title,
        )

        current = None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT project_id, item_kind FROM studio_clips WHERE id = ?",
                (studio_item_id,),
            ).fetchone()
        if row is None:
            raise ValueError("studio item not found")
        if str(row["item_kind"] or "") != ITEM_KIND_TITLE_CARD:
            raise ValueError("not a title card")
        items = {i.id: i for i in self.list_studio_items(int(row["project_id"]))}
        current = items.get(studio_item_id)
        if current is None:
            raise ValueError("studio item not found")
        if current.item_kind != ITEM_KIND_TITLE_CARD:
            raise ValueError("not a title card")
        next_title = (
            current.title_text or "" if title_text is None else normalize_title(title_text)
        )
        next_sub = (
            current.subtitle_text or ""
            if subtitle_text is None
            else normalize_subtitle(subtitle_text)
        )
        next_dur = (
            current.card_duration_s
            if card_duration_s is None
            else clamp_card_duration(float(card_duration_s))
        )
        next_bg = (
            current.background
            if background is None
            else normalize_background(background)
        )
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """UPDATE studio_clips
                   SET title_text = ?, subtitle_text = ?, card_duration_s = ?, background = ?
                   WHERE id = ? AND item_kind = ?""",
                (next_title, next_sub, next_dur, next_bg, studio_item_id, ITEM_KIND_TITLE_CARD),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, current.project_id),
            )
        items = {i.id: i for i in self.list_studio_items(current.project_id)}
        clip = items.get(studio_item_id)
        if clip is None:
            raise ValueError("studio item not found")
        return clip

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
                    "SELECT 1 FROM studio_clips WHERE media_path = ? AND item_kind = 'media'",
                    (media_path,),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT 1 FROM studio_clips
                       WHERE media_path = ? AND project_id = ? AND item_kind = 'media'""",
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
            f"SELECT media_path FROM studio_clips WHERE item_kind = 'media' AND media_path IN ({placeholders})"
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
                """SELECT s.id, s.project_id, s.item_kind, s.media_path, s.identity_key,
                          s.position, s.filename_snapshot, s.recorded_at_snapshot, s.added_at,
                          s.kind_snapshot, s.photo_duration_s,
                          s.source_start, s.source_end,
                          s.playback_speed, s.volume, s.transition, s.transition_duration_s,
                          s.effect_settings,
                          s.title_text, s.subtitle_text, s.card_duration_s, s.background,
                          s.source_media_id AS stored_media_id,
                          m.id AS media_id, m.filename AS live_filename,
                          m.recorded_at AS live_recorded_at, m.kind AS live_kind,
                          m.duration_s AS live_duration_s
                   FROM studio_clips s
                   LEFT JOIN media m ON s.item_kind = 'media' AND m.path = s.media_path
                   WHERE s.project_id = ?
                   ORDER BY s.position ASC, s.id ASC""",
                (project.id,),
            ).fetchall()
        out: list[StudioClip] = []
        for r in rows:
            item_kind = str(r["item_kind"] or "media")
            is_title = item_kind == "title_card"
            available = True if is_title else r["media_id"] is not None
            live_kind = (
                str(r["live_kind"]) if available and r["live_kind"] else None
            )
            kind_snapshot = str(r["kind_snapshot"] or "photo")
            kind = (
                "title_card"
                if is_title
                else effective_kind(
                    available=available,
                    live_kind=live_kind,
                    kind_snapshot=kind_snapshot,
                )
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
            title_text = (
                str(r["title_text"]) if r["title_text"] is not None else None
            )
            subtitle_text = (
                str(r["subtitle_text"]) if r["subtitle_text"] is not None else None
            )
            card_raw = r["card_duration_s"]
            caption = title_text or ""
            out.append(
                StudioClip(
                    id=int(r["id"]),
                    project_id=int(r["project_id"]),
                    media_path=(
                        None if is_title or r["media_path"] is None else str(r["media_path"])
                    ),
                    identity_key=(
                        None
                        if is_title or r["identity_key"] is None
                        else str(r["identity_key"])
                    ),
                    position=int(r["position"]),
                    filename_snapshot=str(r["filename_snapshot"]),
                    recorded_at_snapshot=r["recorded_at_snapshot"],
                    kind_snapshot=kind_snapshot,
                    photo_duration_s=(
                        float(photo_raw) if photo_raw is not None else None
                    ),
                    added_at=str(r["added_at"]),
                    available=available,
                    source_media_id=None if is_title else (live_id if live_id is not None else stored_id),
                    filename=(
                        caption
                        if is_title
                        else (
                            str(r["live_filename"])
                            if available and r["live_filename"]
                            else str(r["filename_snapshot"])
                        )
                    ),
                    recorded_at=(
                        None
                        if is_title
                        else (
                            r["live_recorded_at"]
                            if available
                            else r["recorded_at_snapshot"]
                        )
                    ),
                    kind=kind if kind != "unknown" else None,
                    duration_s=(
                        float(card_raw)
                        if is_title and card_raw is not None
                        else (
                            float(r["live_duration_s"])
                            if available and r["live_duration_s"] is not None
                            else None
                        )
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
                    transition_duration_s=(
                        float(r["transition_duration_s"])
                        if r["transition_duration_s"] is not None
                        else None
                    ),
                    effect_settings=str(r["effect_settings"] or "{}"),
                    item_kind=item_kind,
                    title_text=title_text if is_title else None,
                    subtitle_text=subtitle_text if is_title else None,
                    card_duration_s=(
                        float(card_raw) if is_title and card_raw is not None else None
                    ),
                    background=(
                        str(r["background"]) if is_title and r["background"] else None
                    ),
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

    def set_studio_image_adjust(
        self,
        studio_item_id: int,
        patch: dict[str, object],
    ) -> StudioClip:
        """Store per-clip image sliders. Raises ``ValueError`` on bad input.

        Photos and videos accept a grade. Settings are clip instance data in
        ``effect_settings`` and do not change the source file.
        """
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_image import (
            dump_effect_settings,
            image_adjust_from_effect_settings,
            parse_image_adjust_patch,
        )
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings,
                          m.kind AS live_kind, m.id AS media_id
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("image adjustment only applies to photos and videos")
            available = row["media_id"] is not None
            live_kind = (
                str(row["live_kind"]) if available and row["live_kind"] else None
            )
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind not in {"photo", "video"}:
                raise ValueError("image adjustment only applies to photos and videos")
            current = image_adjust_from_effect_settings(str(row["effect_settings"] or ""))
            updated = parse_image_adjust_patch(patch, current)
            blob = dump_effect_settings(str(row["effect_settings"] or ""), updated)
            conn.execute(
                "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                (blob, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def set_studio_saturation_ramp(
        self,
        studio_item_id: int,
        payload: dict[str, object],
    ) -> StudioClip:
        """Store a video clip's saturation ramp. Raises ``ValueError`` on bad input.

        The ramp is clip instance data in ``effect_settings`` and does not
        change the source file. Photos and Title Cards are rejected.
        """
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_image import (
            dump_saturation_ramp,
            parse_saturation_ramp_payload,
        )
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings,
                          m.kind AS live_kind, m.id AS media_id
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("saturation ramp only applies to video")
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
                raise ValueError("saturation ramp only applies to video")
            ramp = parse_saturation_ramp_payload(payload)
            blob = dump_saturation_ramp(str(row["effect_settings"] or ""), ramp)
            conn.execute(
                "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                (blob, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def set_studio_overlays(
        self,
        studio_item_id: int,
        payload: object,
    ) -> tuple[StudioClip, bool]:
        """Replace per-clip overlays. Raises ``ValueError`` on bad input.

        Photos and videos accept overlays. Times are clamped to the clip's
        visible duration. The returned flag is true when a value was clamped.
        """
        from orga_drone.studio_estimate import effective_kind, effective_seconds
        from orga_drone.studio_overlay import dump_overlays, parse_overlays
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings, s.photo_duration_s, s.source_start,
                          s.source_end, s.card_duration_s, s.playback_speed,
                          m.kind AS live_kind, m.id AS media_id, m.duration_s
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("overlays only apply to photos and videos")
            available = row["media_id"] is not None
            live_kind = str(row["live_kind"]) if available and row["live_kind"] else None
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind not in {"photo", "video"}:
                raise ValueError("overlays only apply to photos and videos")
            duration = effective_seconds(
                kind=kind,
                photo_duration_s=(
                    float(row["photo_duration_s"])
                    if row["photo_duration_s"] is not None
                    else None
                ),
                duration_s=float(row["duration_s"]) if row["duration_s"] is not None else None,
                available=available,
                source_in_s=(
                    float(row["source_start"]) if row["source_start"] is not None else None
                ),
                source_out_s=float(row["source_end"]) if row["source_end"] is not None else None,
                card_duration_s=(
                    float(row["card_duration_s"])
                    if row["card_duration_s"] is not None
                    else None
                ),
                playback_speed=(
                    float(row["playback_speed"])
                    if row["playback_speed"] is not None
                    else None
                ),
            )
            if duration is None or duration <= 0:
                raise ValueError("clip is too short for an overlay")
            overlays, clamped = parse_overlays(payload, duration_s=float(duration))
            blob = dump_overlays(str(row["effect_settings"] or ""), overlays)
            conn.execute(
                "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                (blob, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id], clamped

    def set_studio_masks(
        self,
        studio_item_id: int,
        payload: dict[str, object],
    ) -> StudioClip:
        """Replace privacy masks on one photo or video clip.

        Settings stay in ``effect_settings`` and do not change the source file.
        """
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_mask import dump_masks, parse_masks_payload
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings,
                          m.kind AS live_kind, m.id AS media_id
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("privacy masks only apply to photos and videos")
            available = row["media_id"] is not None
            live_kind = (
                str(row["live_kind"]) if available and row["live_kind"] else None
            )
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind not in {"photo", "video"}:
                raise ValueError("privacy masks only apply to photos and videos")
            masks = parse_masks_payload(payload)
            blob = dump_masks(str(row["effect_settings"] or ""), masks)
            conn.execute(
                "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                (blob, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def set_studio_frame(
        self,
        studio_item_id: int,
        payload: dict[str, object],
    ) -> StudioClip:
        """Store per-clip zoom and pan. Raises ``ValueError`` on bad input.

        Photos and videos accept a framing. Settings are clip instance data in
        ``effect_settings`` and do not change the source file.
        """
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_frame import dump_frame, parse_frame_payload
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings,
                          m.kind AS live_kind, m.id AS media_id
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("framing only applies to photos and videos")
            available = row["media_id"] is not None
            live_kind = (
                str(row["live_kind"]) if available and row["live_kind"] else None
            )
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind not in {"photo", "video"}:
                raise ValueError("framing only applies to photos and videos")
            frame = parse_frame_payload(payload)
            blob = dump_frame(str(row["effect_settings"] or ""), frame)
            conn.execute(
                "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                (blob, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def set_studio_map(
        self,
        studio_item_id: int,
        payload: dict[str, object],
    ) -> StudioClip:
        """Store the optional flight-map box. Raises ``ValueError`` on bad input.

        Photos and videos accept the overlay. The box is clip instance data in
        ``effect_settings`` and does not change the source file or download tiles.
        """
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_map import dump_map, parse_map_payload
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings,
                          m.kind AS live_kind, m.id AS media_id
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("flight map only applies to photos and videos")
            available = row["media_id"] is not None
            live_kind = (
                str(row["live_kind"]) if available and row["live_kind"] else None
            )
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind not in {"photo", "video"}:
                raise ValueError("flight map only applies to photos and videos")
            placement = parse_map_payload(payload)
            blob = dump_map(str(row["effect_settings"] or ""), placement)
            conn.execute(
                "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                (blob, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def set_studio_hud(
        self,
        studio_item_id: int,
        payload: dict[str, object],
    ) -> StudioClip:
        """Turn the telemetry HUD on or off for one video clip.

        The preset lives in ``effect_settings`` and does not change the file.
        Enabling requires a sibling SRT the existing parser can time.
        """
        from pathlib import Path

        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_hud import cues_from_srt, dump_hud, parse_hud_enabled, sibling_srt
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings,
                          m.kind AS live_kind, m.id AS media_id, m.path AS media_path
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("telemetry HUD only applies to videos")
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
                raise ValueError("telemetry HUD only applies to videos")
            enabled = parse_hud_enabled(payload)
            if enabled:
                media_path = Path(str(row["media_path"])) if row["media_path"] else None
                srt = sibling_srt(media_path) if media_path is not None else None
                cues = cues_from_srt(srt) if srt is not None else ()
                if not cues:
                    raise ValueError("This clip has no telemetry to show.")
            blob = dump_hud(str(row["effect_settings"] or ""), enabled)
            conn.execute(
                "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                (blob, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def set_studio_transition(
        self,
        studio_item_id: int,
        type_raw: str | None,
        duration_s: float | None = None,
    ) -> StudioClip:
        """Persist outgoing transition type + remembered duration on one clip."""
        from orga_drone.studio_transition import (
            DEFAULT_DURATION_S,
            TYPE_CUT,
            clamp_user_duration,
            normalize_type,
        )

        stored_type = normalize_type(type_raw)
        with self.connect() as conn:
            row = conn.execute(
                """SELECT id, project_id, transition_duration_s
                   FROM studio_clips WHERE id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            current_dur = (
                float(row["transition_duration_s"])
                if row["transition_duration_s"] is not None
                else None
            )
            if duration_s is not None:
                new_dur: float | None = clamp_user_duration(float(duration_s))
            elif stored_type == TYPE_CUT:
                new_dur = current_dur
            elif current_dur is not None:
                new_dur = clamp_user_duration(current_dur)
            else:
                new_dur = DEFAULT_DURATION_S
            conn.execute(
                """UPDATE studio_clips
                   SET transition = ?, transition_duration_s = ?
                   WHERE id = ?""",
                (stored_type, new_dur, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def set_studio_playback_speed(
        self,
        studio_item_id: int,
        speed: float,
        range_in_s: float | None = None,
        range_out_s: float | None = None,
    ) -> tuple[list[StudioClip], int]:
        """Apply 1×, 0.5×, or 0.25× to a source range inside one video clip.

        A partial range splits the clip. Sections outside the range keep their
        speed. Source files are never modified. Returns the resulting clips in
        order and the id of the clip that received ``speed``.
        """
        from orga_drone.studio_cut import resolve_source_range
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_speed import coerce_playback_speed, plan_speed_segments

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.media_path, s.identity_key, s.position,
                          s.filename_snapshot, s.recorded_at_snapshot,
                          s.kind_snapshot, s.photo_duration_s,
                          s.source_start, s.source_end, s.added_at,
                          s.source_media_id, s.playback_speed, s.volume,
                          s.transition, s.transition_duration_s, s.effect_settings,
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
                raise ValueError("only video clips can change speed")
            if not available:
                raise ValueError("unavailable clips cannot change speed")
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
            current = coerce_playback_speed(
                float(row["playback_speed"])
                if row["playback_speed"] is not None
                else 1.0
            )
            try:
                segments, selected_index = plan_speed_segments(
                    rang,
                    current_speed=current,
                    range_in_s=range_in_s,
                    range_out_s=range_out_s,
                    speed=speed,
                )
            except ValueError as exc:
                raise ValueError(str(exc)) from exc

            project_id = int(row["project_id"])
            position = int(row["position"])
            ids: list[int] = [studio_item_id]
            now = datetime.now().isoformat(timespec="seconds")
            if len(segments) == 1:
                conn.execute(
                    "UPDATE studio_clips SET playback_speed = ? WHERE id = ?",
                    (segments[0].speed, studio_item_id),
                )
            else:
                extra = len(segments) - 1
                conn.execute(
                    """UPDATE studio_clips
                       SET position = position + ?
                       WHERE project_id = ? AND position > ?""",
                    (extra, project_id, position),
                )
                conn.execute(
                    """UPDATE studio_clips
                       SET source_start = ?, source_end = ?, playback_speed = ?,
                           transition = 'cut'
                       WHERE id = ?""",
                    (
                        segments[0].source_in_s,
                        segments[0].source_out_s,
                        segments[0].speed,
                        studio_item_id,
                    ),
                )
                source_media_id = (
                    int(row["media_id"])
                    if row["media_id"] is not None
                    else (
                        int(row["source_media_id"])
                        if row["source_media_id"] is not None
                        else None
                    )
                )
                volume = float(row["volume"] if row["volume"] is not None else 1.0)
                from orga_drone.studio_forward_loop import without_loop_to_soundtrack

                original_effects = str(row["effect_settings"] or "{}")
                copied_settings = without_loop_to_soundtrack(original_effects)
                if copied_settings != original_effects:
                    conn.execute(
                        "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                        (copied_settings, studio_item_id),
                    )
                remembered = (
                    float(row["transition_duration_s"])
                    if row["transition_duration_s"] is not None
                    else None
                )
                for offset, seg in enumerate(segments[1:], start=1):
                    is_last = offset == len(segments) - 1
                    cur = conn.execute(
                        """INSERT INTO studio_clips(
                             project_id, media_path, identity_key, source_media_id,
                             position, filename_snapshot, recorded_at_snapshot,
                             kind_snapshot, photo_duration_s, source_start, source_end,
                             playback_speed, volume, transition, transition_duration_s,
                             effect_settings, added_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            project_id,
                            str(row["media_path"]),
                            str(row["identity_key"]),
                            source_media_id,
                            position + offset,
                            str(row["filename_snapshot"]),
                            row["recorded_at_snapshot"],
                            str(row["kind_snapshot"] or "video"),
                            seg.source_in_s,
                            seg.source_out_s,
                            seg.speed,
                            volume,
                            row["transition"] if is_last else "cut",
                            remembered,
                            copied_settings,
                            now,
                        ),
                    )
                    new_id = cur.lastrowid
                    assert new_id is not None
                    ids.append(int(new_id))
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )

        by_id = {item.id: item for item in self.list_studio_items(project_id)}
        ordered = [by_id[item_id] for item_id in ids if item_id in by_id]
        if len(ordered) != len(ids):
            raise RuntimeError("speed change succeeded but clips are missing")
        return ordered, ids[selected_index]


    def set_studio_section(
        self,
        studio_item_id: int,
        *,
        source_in_s: float,
        source_out_s: float,
        repeats: object,
    ) -> StudioClip:
        """Set a video in/out range and how many times that range plays.

        Source files are not modified. A full-media range is stored as NULL,
        matching Cut. Repeat count 1 omits the effect key. Raises ``ValueError``
        on bad input.
        """
        from orga_drone.studio_cut import (
            MIN_SEGMENT_S,
            dump_section_repeats,
            parse_section_repeats,
            resolve_source_range,
        )
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        count = parse_section_repeats(repeats)
        if isinstance(source_in_s, bool) or not isinstance(source_in_s, (int, float)):
            raise ValueError("source in must be a number")
        if isinstance(source_out_s, bool) or not isinstance(source_out_s, (int, float)):
            raise ValueError("source out must be a number")
        start = float(source_in_s)
        end = float(source_out_s)
        if start < 0 or end <= start:
            raise ValueError("source out must be after source in")
        if end - start < MIN_SEGMENT_S:
            raise ValueError("section is too short")

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings, s.media_path, s.filename_snapshot,
                          s.source_media_id,
                          m.kind AS live_kind, m.id AS media_id, m.duration_s
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("section repeat only applies to videos")
            available = row["media_id"] is not None
            live_kind = str(row["live_kind"]) if available and row["live_kind"] else None
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind != "video":
                raise ValueError("section repeat only applies to videos")
            media_duration = (
                float(row["duration_s"]) if row["duration_s"] is not None else None
            )
            rang = resolve_source_range(
                source_in_s=start,
                source_out_s=end,
                media_duration_s=media_duration,
            )
            if rang is None or rang.duration_s < MIN_SEGMENT_S:
                raise ValueError("section is outside the video")
            start_s = rang.source_in_s
            end_s = rang.source_out_s
            store_start: float | None = start_s
            store_end: float | None = end_s
            if (
                media_duration is not None
                and start_s <= 1e-4
                and end_s >= media_duration - 1e-3
            ):
                store_start = None
                store_end = None
            blob = dump_section_repeats(str(row["effect_settings"] or ""), count)
            conn.execute(
                """UPDATE studio_clips
                   SET source_start = ?, source_end = ?, effect_settings = ?
                   WHERE id = ?""",
                (store_start, store_end, blob, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            if store_start is not None or store_end is not None:
                media_id = int(row["media_id"]) if row["media_id"] is not None else None
                if media_id is None and row["source_media_id"] is not None:
                    media_id = int(row["source_media_id"])
                path = row["media_path"]
                if path:
                    remember_studio_original(
                        conn,
                        project_id=project_id,
                        media_path=str(path),
                        source_media_id=media_id,
                        filename=str(row["filename_snapshot"] or ""),
                        now=now,
                    )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def set_studio_forward_loop(
        self,
        studio_item_id: int,
        enabled: bool,
        *,
        transition: str | None = None,
        transition_s: float | None = None,
    ) -> StudioClip:
        """Remember that one video should repeat forward to the soundtrack.

        The play count is not stored. Source files are not modified. A second
        clip in the same project cannot take the flag. ``transition`` is the
        join between those plays (``off`` or ``crossfade``). The duration is
        the request; a short section clamps it when the story is measured.
        """
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_forward_loop import (
            dump_loop_to_soundtrack,
            dump_loop_transition,
            loop_transition_choice,
            loop_transition_requested_s,
            rejection_reason,
            soundtrack_once_s,
        )
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        if not isinstance(enabled, bool):
            raise ValueError("enabled must be true or false")
        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings,
                          m.kind AS live_kind, m.id AS media_id
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("forward_loop_video_only")
            available = row["media_id"] is not None
            live_kind = str(row["live_kind"]) if available and row["live_kind"] else None
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind != "video":
                raise ValueError("forward_loop_video_only")
            blob = dump_loop_to_soundtrack(str(row["effect_settings"] or ""), enabled)
            if transition is not None or transition_s is not None:
                choice = (
                    transition
                    if transition is not None
                    else loop_transition_choice(blob)
                )
                if choice not in {"off", "crossfade"}:
                    raise ValueError("loop_transition")
                duration = (
                    float(transition_s)
                    if transition_s is not None
                    else loop_transition_requested_s(blob)
                )
                blob = dump_loop_transition(blob, choice, duration)
            if enabled:
                reason = rejection_reason(
                    self.list_studio_items(project_id),
                    soundtrack_once_s(self.list_studio_music(project_id)),
                    studio_item_id,
                    settings_override=(studio_item_id, blob),
                )
                if reason:
                    raise ValueError(reason)
            conn.execute(
                "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                (blob, studio_item_id),
            )
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        items = {i.id: i for i in self.list_studio_items(project_id)}
        return items[studio_item_id]

    def set_studio_loop_effect(
        self,
        studio_item_id: int,
        *,
        transition: str,
        duration_s: float | None,
        curve: str | None = None,
    ) -> StudioClip:
        """Store the join used between plays of one repeated section.

        Manual repeats and Repeat to soundtrack share this setting. Smart
        frame matching may store a seam. It does not rewrite the user's
        in/out or the file on disk.
        """
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_forward_loop import (
            LOOP_TRANSITION_MATCH,
            dump_loop_transition,
            loop_transition_requested_s,
        )
        from orga_drone.studio_loop_match import (
            analyze_loop_seam,
            dump_loop_match,
            loop_match_key,
        )
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        if transition not in {"off", "crossfade", "cinematic", LOOP_TRANSITION_MATCH}:
            raise ValueError("loop_transition")
        if curve is not None and curve not in {"linear", "smooth"}:
            raise ValueError("loop_transition_curve")
        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.kind_snapshot,
                          s.effect_settings, s.media_path, s.source_start, s.source_end,
                          m.kind AS live_kind, m.id AS media_id, m.duration_s AS live_duration_s
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (studio_item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("studio item not found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ValueError("loop_effect_video_only")
            available = row["media_id"] is not None
            live_kind = str(row["live_kind"]) if available and row["live_kind"] else None
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind != "video":
                raise ValueError("loop_effect_video_only")
            duration = (
                float(duration_s)
                if duration_s is not None
                else loop_transition_requested_s(str(row["effect_settings"] or ""))
            )
            blob = dump_loop_transition(
                str(row["effect_settings"] or ""), transition, duration, curve
            )
            if transition == LOOP_TRANSITION_MATCH:
                media_path = Path(str(row["media_path"])) if row["media_path"] else None
                start = float(row["source_start"] or 0.0)
                end = (
                    float(row["source_end"])
                    if row["source_end"] is not None
                    else (
                        float(row["live_duration_s"])
                        if row["live_duration_s"] is not None
                        else start
                    )
                )
                if media_path is None or not media_path.is_file() or end <= start:
                    from orga_drone.studio_loop_match import SeamChoice

                    choice = SeamChoice(False, start, end, "low", 0.0, 1.0)
                    key = ""
                else:
                    choice = analyze_loop_seam(media_path, start, end)
                    key = loop_match_key(media_path, start, end) or ""
                blob = dump_loop_match(blob, choice, key)
            conn.execute(
                "UPDATE studio_clips SET effect_settings = ? WHERE id = ?",
                (blob, studio_item_id),
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
        from orga_drone.studio_image import shift_saturation_ramp_settings

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.media_path, s.identity_key, s.position,
                          s.filename_snapshot, s.recorded_at_snapshot,
                          s.kind_snapshot, s.photo_duration_s,
                          s.source_start, s.source_end, s.added_at,
                          s.source_media_id, s.playback_speed, s.volume,
                          s.transition, s.transition_duration_s, s.effect_settings,
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

            from orga_drone.studio_overlay import split_overlay_settings
            from orga_drone.studio_speed import coerce_playback_speed, timeline_offset_s

            original_settings = str(row["effect_settings"] or "{}")
            speed = coerce_playback_speed(row["playback_speed"])
            left_len = float(left.source_out_s) - float(left.source_in_s)
            right_len = float(right.source_out_s) - float(right.source_in_s)
            # Overlay times are clip-local; ``local_cut_s`` is the source offset.
            left_settings, right_base = split_overlay_settings(
                original_settings,
                timeline_offset_s(float(local_cut_s), speed),
                left_s=timeline_offset_s(left_len, speed),
                right_s=timeline_offset_s(right_len, speed),
            )
            right_settings = shift_saturation_ramp_settings(
                right_base,
                float(local_cut_s),
            )
            from orga_drone.studio_forward_loop import without_loop_to_soundtrack

            # A cut makes two sections. The soundtrack loop stays a single
            # explicit choice, so neither half keeps it.
            left_settings = without_loop_to_soundtrack(left_settings)
            right_settings = without_loop_to_soundtrack(right_settings)
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
                   SET source_start = ?, source_end = ?, transition = 'cut',
                       effect_settings = ?
                   WHERE id = ?""",
                (left.source_in_s, left.source_out_s, left_settings, studio_item_id),
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
                     playback_speed, volume, transition, transition_duration_s,
                     effect_settings, added_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    (
                        float(row["transition_duration_s"])
                        if row["transition_duration_s"] is not None
                        else None
                    ),
                    right_settings,
                    now,
                ),
            )
            remember_studio_original(
                conn,
                project_id=project_id,
                media_path=str(row["media_path"]),
                source_media_id=source_media_id,
                filename=str(row["filename_snapshot"] or ""),
                now=now,
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

    def merge_studio_with_previous(self, right_id: int) -> StudioClip:
        """Join ``right_id`` with the previous Story clip when that is lossless.

        Extends the left row's source end and settings, then deletes the right
        row. The media file is not modified. Raises ``MergeBlocked`` when the
        join would drop a setting, a gap, or a different file.
        """
        from orga_drone.studio_merge import MergeBlocked, plan_merge

        with self.connect() as conn:
            located = conn.execute(
                "SELECT project_id FROM studio_clips WHERE id = ?",
                (right_id,),
            ).fetchone()
        if located is None:
            raise MergeBlocked("not_found")
        project_id = int(located["project_id"])
        plan = plan_merge(self.list_studio_items(project_id), right_id)
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """UPDATE studio_clips
                   SET source_end = ?, effect_settings = ?, transition = ?,
                       transition_duration_s = ?
                   WHERE id = ? AND project_id = ?""",
                (
                    plan.source_end,
                    plan.effect_settings,
                    plan.transition if plan.transition is not None else "cut",
                    plan.transition_duration_s,
                    plan.left_id,
                    project_id,
                ),
            )
            conn.execute(
                "DELETE FROM studio_clips WHERE id = ? AND project_id = ?",
                (plan.right_id, project_id),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        merged = next(
            (item for item in self.list_studio_items(project_id) if item.id == plan.left_id),
            None,
        )
        if merged is None:
            raise RuntimeError("merge succeeded but the clip is missing")
        return merged

    def reuse_studio_source(
        self,
        anchor_id: int,
        source_in_s: object,
        source_out_s: object,
    ) -> StudioClip:
        """Insert a new Story clip after ``anchor_id`` for another source range.

        The new row uses the same media path and library id. Speed is 1, effects
        are empty, and the outgoing transition is a hard cut. The anchor row is
        not updated. Source files are not copied or modified. Raises
        ``ReuseBlocked`` before any write when the range cannot be added.
        """
        from orga_drone.media_files import resolve_media_file
        from orga_drone.studio_estimate import effective_kind
        from orga_drone.studio_reuse import ReuseBlocked, stored_source_range
        from orga_drone.studio_title_card import ITEM_KIND_TITLE_CARD

        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.id, s.project_id, s.item_kind, s.media_path, s.identity_key,
                          s.source_media_id, s.position, s.filename_snapshot,
                          s.recorded_at_snapshot, s.kind_snapshot,
                          m.id AS media_id, m.kind AS live_kind, m.duration_s AS live_duration_s
                   FROM studio_clips s
                   LEFT JOIN media m ON m.path = s.media_path
                   WHERE s.id = ?""",
                (anchor_id,),
            ).fetchone()
            if row is None:
                raise ReuseBlocked("not_found")
            project_id = int(row["project_id"])
            if str(row["item_kind"] or "media") == ITEM_KIND_TITLE_CARD:
                raise ReuseBlocked("not_video")
            available = row["media_id"] is not None
            live_kind = str(row["live_kind"]) if available and row["live_kind"] else None
            kind = effective_kind(
                available=available,
                live_kind=live_kind,
                kind_snapshot=str(row["kind_snapshot"] or "photo"),
            )
            if kind != "video":
                raise ReuseBlocked("not_video")
            media_id = int(row["media_id"]) if row["media_id"] is not None else None
            if media_id is None:
                raise ReuseBlocked("offline")
            duration = (
                float(row["live_duration_s"])
                if row["live_duration_s"] is not None
                else None
            )
            ordered = conn.execute(
                """SELECT id, position FROM studio_clips
                   WHERE project_id = ?
                   ORDER BY position ASC, id ASC""",
                (project_id,),
            ).fetchall()

        media = self.get_media(media_id)
        if media is None or resolve_media_file(self, media) is None:
            raise ReuseBlocked("offline")
        if duration is None or duration <= 0:
            raise ReuseBlocked("duration_unknown")
        store_start, store_end = stored_source_range(source_in_s, source_out_s, duration)

        anchor_position = int(row["position"])
        ordered_ids = [int(item["id"]) for item in ordered]
        if anchor_id not in ordered_ids:
            raise ReuseBlocked("not_found")
        tail = ordered[ordered_ids.index(anchor_id) + 1 :]
        source_media_id = (
            int(row["source_media_id"])
            if row["source_media_id"] is not None
            else media_id
        )
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            remember_studio_original(
                conn,
                project_id=project_id,
                media_path=str(row["media_path"]),
                source_media_id=source_media_id,
                filename=str(row["filename_snapshot"] or ""),
                now=now,
            )
            for offset, tail_row in enumerate(tail, start=2):
                conn.execute(
                    "UPDATE studio_clips SET position = ? WHERE id = ? AND project_id = ?",
                    (anchor_position + offset, int(tail_row["id"]), project_id),
                )
            cur = conn.execute(
                """INSERT INTO studio_clips(
                     project_id, item_kind, media_path, identity_key, source_media_id,
                     position, filename_snapshot, recorded_at_snapshot, kind_snapshot,
                     photo_duration_s, source_start, source_end,
                     playback_speed, volume, transition, transition_duration_s,
                     effect_settings, added_at
                   ) VALUES (?, 'media', ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1.0, 1.0,
                             NULL, NULL, '{}', ?)""",
                (
                    project_id,
                    str(row["media_path"]),
                    str(row["identity_key"]),
                    source_media_id,
                    anchor_position + 1,
                    str(row["filename_snapshot"]),
                    row["recorded_at_snapshot"],
                    str(row["kind_snapshot"] or "video"),
                    store_start,
                    store_end,
                    now,
                ),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            new_id = cur.lastrowid
            assert new_id is not None
            present = conn.execute(
                "SELECT id FROM studio_clips WHERE id = ? AND project_id = ?",
                (int(new_id), project_id),
            ).fetchone()
            if present is None:
                raise ReuseBlocked("not_found")

        created = next(
            (item for item in self.list_studio_items(project_id) if item.id == int(new_id)),
            None,
        )
        if created is None:
            raise RuntimeError("reuse succeeded but the clip is missing")
        return created

    def sync_studio_originals(self, project_id: int) -> None:
        """Remember Original rows for videos that are already trimmed or split.

        Rows that outlive their Story clips stay. A full, uncut clip does not
        gain one.
        """
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT media_path,
                          MAX(source_media_id) AS source_media_id,
                          MAX(filename_snapshot) AS filename_snapshot
                   FROM studio_clips
                   WHERE project_id = ?
                     AND item_kind = 'media'
                     AND kind_snapshot = 'video'
                     AND media_path IS NOT NULL
                     AND (source_start IS NOT NULL OR source_end IS NOT NULL)
                   GROUP BY media_path""",
                (project_id,),
            ).fetchall()
            for item in rows:
                remember_studio_original(
                    conn,
                    project_id=project_id,
                    media_path=str(item["media_path"]),
                    source_media_id=(
                        int(item["source_media_id"])
                        if item["source_media_id"] is not None
                        else None
                    ),
                    filename=str(item["filename_snapshot"] or ""),
                    now=now,
                )

    def list_studio_originals(self, project_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT o.id, o.media_path, o.filename_snapshot,
                          COALESCE(m.id, o.source_media_id) AS media_id,
                          m.duration_s, m.kind, m.filename AS live_filename
                   FROM studio_originals o
                   LEFT JOIN media m ON m.path = o.media_path
                   WHERE o.project_id = ?
                   ORDER BY o.id ASC""",
                (project_id,),
            ).fetchall()
        listed: list[dict[str, Any]] = []
        for row in rows:
            listed.append(
                {
                    "id": int(row["id"]),
                    "media_path": str(row["media_path"]),
                    "media_id": int(row["media_id"]) if row["media_id"] is not None else None,
                    "filename": str(row["live_filename"] or row["filename_snapshot"] or ""),
                    "duration_s": (
                        float(row["duration_s"]) if row["duration_s"] is not None else None
                    ),
                    "kind": str(row["kind"]) if row["kind"] else "video",
                }
            )
        return listed

    def insert_studio_original_scene(
        self,
        project_id: int,
        media_id: int,
        source_in_s: object,
        source_out_s: object,
        *,
        before_id: int | None = None,
    ) -> StudioClip:
        """Append a Story clip from a saved Original, or insert it before ``before_id``.

        The Original row must already exist. Existing clips keep their trims and
        effects. Source files are not copied. Raises ``ReuseBlocked`` before any
        clip write when the range cannot be added.
        """
        from orga_drone.media_files import resolve_media_file
        from orga_drone.studio_reuse import ReuseBlocked, stored_source_range

        media = self.get_media(media_id)
        if media is None or media.kind != "video":
            raise ReuseBlocked("not_video")
        if resolve_media_file(self, media) is None:
            raise ReuseBlocked("offline")
        if media.duration_s is None or float(media.duration_s) <= 0:
            filled = self.fill_video_duration_if_missing(media_id)
            if filled is not None:
                media = self.get_media(media_id)
        duration = (
            float(media.duration_s)
            if media is not None and media.duration_s is not None
            else None
        )
        if media is None or duration is None or duration <= 0:
            raise ReuseBlocked("duration_unknown")
        store_start, store_end = stored_source_range(source_in_s, source_out_s, duration)
        with self.connect() as conn:
            kept = conn.execute(
                """SELECT id FROM studio_originals
                   WHERE project_id = ? AND media_path = ?""",
                (project_id, media.path),
            ).fetchone()
            if kept is None:
                raise ReuseBlocked("not_found")
            ordered = conn.execute(
                """SELECT id, position FROM studio_clips
                   WHERE project_id = ?
                   ORDER BY position ASC, id ASC""",
                (project_id,),
            ).fetchall()
            if before_id is None:
                pos_row = conn.execute(
                    """SELECT COALESCE(MAX(position), 0) + 1 AS next_pos
                       FROM studio_clips WHERE project_id = ?""",
                    (project_id,),
                ).fetchone()
                position = int(pos_row["next_pos"])
            else:
                ordered_ids = [int(item["id"]) for item in ordered]
                if before_id not in ordered_ids:
                    raise ReuseBlocked("not_found")
                index = ordered_ids.index(before_id)
                position = int(ordered[index]["position"])
                for offset, tail_row in enumerate(ordered[index:]):
                    conn.execute(
                        """UPDATE studio_clips SET position = ?
                           WHERE id = ? AND project_id = ?""",
                        (position + 1 + offset, int(tail_row["id"]), project_id),
                    )
            now = datetime.now().isoformat(timespec="seconds")
            cur = conn.execute(
                """INSERT INTO studio_clips(
                     project_id, item_kind, media_path, identity_key, source_media_id,
                     position, filename_snapshot, recorded_at_snapshot, kind_snapshot,
                     photo_duration_s, source_start, source_end,
                     playback_speed, volume, transition, transition_duration_s,
                     effect_settings, added_at
                   ) VALUES (?, 'media', ?, ?, ?, ?, ?, ?, 'video', NULL, ?, ?,
                             1.0, 1.0, NULL, NULL, '{}', ?)""",
                (
                    project_id,
                    media.path,
                    make_identity_key(media.filename, media.size_bytes, media.recorded_at),
                    media.id,
                    position,
                    media.filename,
                    media.recorded_at,
                    store_start,
                    store_end,
                    now,
                ),
            )
            conn.execute(
                "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            new_id = cur.lastrowid
            assert new_id is not None
        created = next(
            (item for item in self.list_studio_items(project_id) if item.id == int(new_id)),
            None,
        )
        if created is None:
            raise RuntimeError("original scene succeeded but the clip is missing")
        return created

    def protected_export_paths(self) -> list[str]:
        """Files an export must never replace.

        Indexed media and assets, soundtrack files, and this database. Path
        identity (case, symlinks, hard links) is applied by the caller.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT path FROM media
                UNION
                SELECT path FROM assets
                UNION
                SELECT file_path FROM studio_audio_clips
                """
            ).fetchall()
        paths = [str(row[0]) for row in rows if row[0]]
        paths.append(str(self.path))
        return paths

    def repath_studio_item(self, old_path: str, new_path: str) -> None:
        """Point existing Story clips at a renamed path.

        Another project may already reference ``new_path``. Those clips stay.
        Clips on ``old_path`` keep their ids, trims, effects, masks, and order.
        """
        if old_path == new_path:
            return
        with self.connect() as conn:
            conn.execute(
                """UPDATE studio_clips
                   SET media_path = ?
                   WHERE item_kind = 'media' AND media_path = ?""",
                (new_path, old_path),
            )
            conn.execute(
                """UPDATE studio_originals
                   SET media_path = ?
                   WHERE media_path = ?
                     AND NOT EXISTS (
                       SELECT 1 FROM studio_originals newer
                       WHERE newer.project_id = studio_originals.project_id
                         AND newer.media_path = ?
                     )""",
                (new_path, old_path, new_path),
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
                "SELECT id FROM studio_clips WHERE item_kind = 'media' AND media_path = ?",
                (media_path,),
            ).fetchall()
            if by_path:
                conn.execute(
                    """UPDATE studio_clips
                       SET identity_key = ?, source_media_id = ?
                       WHERE item_kind = 'media' AND media_path = ?""",
                    (identity, live_id, media_path),
                )
                return
            orphans = conn.execute(
                """SELECT id, media_path FROM studio_clips
                   WHERE item_kind = 'media'
                     AND identity_key = ?
                     AND media_path NOT IN (SELECT path FROM media)""",
                (identity,),
            ).fetchall()
            if not orphans:
                return
            orphan_paths = {str(r["media_path"]) for r in orphans}
            if len(orphan_paths) != 1:
                return
            conflict = conn.execute(
                "SELECT id FROM studio_clips WHERE item_kind = 'media' AND media_path = ?",
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

    def list_albums(self) -> list[Album]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT a.id, a.title, a.created_at, a.updated_at,
                          COUNT(i.id) AS item_count
                   FROM albums a
                   LEFT JOIN album_items i ON i.album_id = a.id
                   GROUP BY a.id
                   ORDER BY a.title COLLATE NOCASE, a.id"""
            ).fetchall()
        return [
            Album(
                id=int(r["id"]),
                title=str(r["title"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
                item_count=int(r["item_count"]),
            )
            for r in rows
        ]

    def get_album(self, album_id: int) -> Album | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT a.id, a.title, a.created_at, a.updated_at,
                          COUNT(i.id) AS item_count
                   FROM albums a
                   LEFT JOIN album_items i ON i.album_id = a.id
                   WHERE a.id = ?
                   GROUP BY a.id""",
                (album_id,),
            ).fetchone()
        if row is None:
            return None
        return Album(
            id=int(row["id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            item_count=int(row["item_count"]),
        )

    def create_album(self, title: str) -> Album:
        """Create an empty album. Raises ValueError when the title is blank."""
        clean = clean_album_title(title)
        if clean is None:
            raise ValueError("empty album title")
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO albums(title, created_at, updated_at)
                   VALUES (?, ?, ?)""",
                (clean, now, now),
            )
            album_id = cur.lastrowid
        assert album_id is not None
        created = self.get_album(int(album_id))
        assert created is not None
        return created

    def rename_album(self, album_id: int, title: str) -> Album | None:
        """Rename an album. None when it does not exist.

        Raises ValueError when the title is blank.
        """
        clean = clean_album_title(title)
        if clean is None:
            raise ValueError("empty album title")
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM albums WHERE id = ?",
                (album_id,),
            ).fetchone()
            if existing is None:
                return None
            conn.execute(
                "UPDATE albums SET title = ?, updated_at = ? WHERE id = ?",
                (clean, now, album_id),
            )
        return self.get_album(album_id)

    def delete_album(self, album_id: int) -> bool:
        """Delete the album and its references. Media files and rows stay."""
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))
            return cur.rowcount > 0

    def albums_for_path(self, media_path: str) -> list[Album]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT a.id, a.title, a.created_at, a.updated_at
                   FROM albums a
                   JOIN album_items i ON i.album_id = a.id
                   WHERE i.media_path = ?
                   ORDER BY a.title COLLATE NOCASE, a.id""",
                (media_path,),
            ).fetchall()
        return [
            Album(
                id=int(r["id"]),
                title=str(r["title"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def add_media_to_album(self, album_id: int, media_id: int) -> str:
        """Reference a library item from an album.

        Returns ``added``, ``exists``, ``missing_album``, or ``missing_media``.
        Does not copy or modify the file.
        """
        media = self.get_media(media_id)
        if media is None:
            return "missing_media"
        identity = make_identity_key(
            media.filename, media.size_bytes, media.recorded_at
        )
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            album = conn.execute(
                "SELECT id FROM albums WHERE id = ?",
                (album_id,),
            ).fetchone()
            if album is None:
                return "missing_album"
            existing = conn.execute(
                """SELECT id FROM album_items
                   WHERE album_id = ? AND media_path = ?""",
                (album_id, media.path),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE album_items
                       SET identity_key = ?, source_media_id = ?,
                           filename_snapshot = ?, kind_snapshot = ?,
                           recorded_at_snapshot = ?
                       WHERE id = ?""",
                    (
                        identity,
                        media.id,
                        media.filename,
                        media.kind,
                        media.recorded_at,
                        existing["id"],
                    ),
                )
                return "exists"
            conn.execute(
                """INSERT INTO album_items(
                     album_id, media_path, identity_key, source_media_id,
                     filename_snapshot, kind_snapshot, recorded_at_snapshot, added_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    album_id,
                    media.path,
                    identity,
                    media.id,
                    media.filename,
                    media.kind,
                    media.recorded_at,
                    now,
                ),
            )
            conn.execute(
                "UPDATE albums SET updated_at = ? WHERE id = ?",
                (now, album_id),
            )
        return "added"

    def remove_album_item(self, album_id: int, item_id: int) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM album_items WHERE id = ? AND album_id = ?",
                (item_id, album_id),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "UPDATE albums SET updated_at = ? WHERE id = ?",
                (now, album_id),
            )
        return True

    def remove_media_from_album(self, album_id: int, media_path: str) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM album_items WHERE album_id = ? AND media_path = ?",
                (album_id, media_path),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "UPDATE albums SET updated_at = ? WHERE id = ?",
                (now, album_id),
            )
        return True

    def list_album_items(self, album_id: int) -> list[AlbumItem]:
        """Album contents, including references whose files are offline."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT i.id, i.album_id, i.media_path, i.identity_key,
                          i.filename_snapshot, i.kind_snapshot,
                          i.recorded_at_snapshot, i.added_at,
                          m.id AS media_id, m.filename AS live_filename,
                          m.recorded_at AS live_recorded_at, m.kind AS live_kind
                   FROM album_items i
                   LEFT JOIN media m ON m.path = i.media_path
                   WHERE i.album_id = ?
                   ORDER BY COALESCE(m.recorded_at, i.recorded_at_snapshot) DESC,
                            i.id ASC""",
                (album_id,),
            ).fetchall()
        items: list[AlbumItem] = []
        for row in rows:
            path = str(row["media_path"])
            state = album_media_state(path)
            live_id = int(row["media_id"]) if row["media_id"] is not None else None
            filename = (
                str(row["live_filename"])
                if row["live_filename"]
                else str(row["filename_snapshot"])
            )
            kind = (
                str(row["live_kind"])
                if row["live_kind"]
                else str(row["kind_snapshot"])
            )
            recorded = (
                row["live_recorded_at"]
                if row["media_id"] is not None
                else row["recorded_at_snapshot"]
            )
            items.append(
                AlbumItem(
                    id=int(row["id"]),
                    album_id=int(row["album_id"]),
                    media_path=path,
                    identity_key=str(row["identity_key"]),
                    filename=filename,
                    kind=kind,
                    recorded_at=str(recorded) if recorded else None,
                    added_at=str(row["added_at"]),
                    state=state,
                    media_id=live_id if state == "available" else None,
                )
            )
        return items

    def repath_album_items(self, old_path: str, new_path: str) -> None:
        """Follow a library rename. Drops a duplicate reference in the same album."""
        if old_path == new_path:
            return
        new_name = Path(new_path).name
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, album_id FROM album_items WHERE media_path = ?",
                (old_path,),
            ).fetchall()
            for row in rows:
                conflict = conn.execute(
                    """SELECT id FROM album_items
                       WHERE album_id = ? AND media_path = ? AND id != ?""",
                    (row["album_id"], new_path, row["id"]),
                ).fetchone()
                if conflict:
                    conn.execute(
                        "DELETE FROM album_items WHERE id = ?",
                        (row["id"],),
                    )
                else:
                    conn.execute(
                        """UPDATE album_items
                           SET media_path = ?, filename_snapshot = ?
                           WHERE id = ?""",
                        (new_path, new_name, row["id"]),
                    )

    def link_album_items_for_path(
        self,
        media_path: str,
        *,
        filename: str,
        size_bytes: int,
        recorded_at: str | None,
    ) -> None:
        """After rescan/rename: refresh identity and relink an unambiguous orphan.

        Same rules as Studio clip relink: exact path wins; otherwise one orphan
        path group with the same identity may move onto this path.
        """
        identity = make_identity_key(filename, size_bytes, recorded_at)
        with self.connect() as conn:
            media_row = conn.execute(
                "SELECT id FROM media WHERE path = ?",
                (media_path,),
            ).fetchone()
            live_id = int(media_row["id"]) if media_row is not None else None
            by_path = conn.execute(
                "SELECT id FROM album_items WHERE media_path = ?",
                (media_path,),
            ).fetchall()
            if by_path:
                conn.execute(
                    """UPDATE album_items
                       SET identity_key = ?, source_media_id = ?,
                           filename_snapshot = ?, recorded_at_snapshot = ?
                       WHERE media_path = ?""",
                    (identity, live_id, filename, recorded_at, media_path),
                )
                return
            orphans = conn.execute(
                """SELECT id, album_id, media_path FROM album_items
                   WHERE identity_key = ?
                     AND media_path NOT IN (SELECT path FROM media)""",
                (identity,),
            ).fetchall()
            if not orphans:
                return
            orphan_paths = {str(r["media_path"]) for r in orphans}
            if len(orphan_paths) != 1:
                return
            for orphan in orphans:
                conflict = conn.execute(
                    """SELECT id FROM album_items
                       WHERE album_id = ? AND media_path = ?""",
                    (orphan["album_id"], media_path),
                ).fetchone()
                if conflict:
                    conn.execute(
                        "DELETE FROM album_items WHERE id = ?",
                        (orphan["id"],),
                    )
                    continue
                conn.execute(
                    """UPDATE album_items
                       SET media_path = ?, identity_key = ?, source_media_id = ?,
                           filename_snapshot = ?, recorded_at_snapshot = ?
                       WHERE id = ?""",
                    (
                        media_path,
                        identity,
                        live_id,
                        filename,
                        recorded_at,
                        orphan["id"],
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
            SELECT m.id, m.root_id, m.kind, m.filename, m.recorded_at, m.duration_s,
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
                    "root_id": int(r["root_id"]),
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
        self.repath_album_items(old_path, new_path)

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
            self.repath_album_items(old["path"], path)
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
            self.link_album_items_for_path(
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
