"""In-memory Undo/Redo for the open Studio story.

The stack keeps snapshots of ``studio_clips``, the project-level soundtrack
start, and SFX lane rows for one project. It is not written to SQLite and is
empty when the process starts. Undo restores those Story values. It does not
touch media files, library rows, albums, music playlist rows, or other projects.

A slider gesture sends the same ``X-Studio-History-Group`` on each save.
Those saves share one step, taken from the state before the gesture. A later
edit clears Redo.
"""

from __future__ import annotations

import threading
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from orga_drone.db import Database

MAX_STORY_HISTORY = 50

_CLIP_COLUMNS: tuple[str, ...] = (
    "id",
    "project_id",
    "item_kind",
    "media_path",
    "identity_key",
    "source_media_id",
    "position",
    "filename_snapshot",
    "recorded_at_snapshot",
    "kind_snapshot",
    "photo_duration_s",
    "source_start",
    "source_end",
    "playback_speed",
    "volume",
    "transition",
    "transition_duration_s",
    "effect_settings",
    "title_text",
    "subtitle_text",
    "card_duration_s",
    "background",
    "added_at",
)

ClipSnapshot = tuple[tuple[Any, ...], ...]
SfxSnapshot = tuple[tuple[Any, ...], ...]

_SFX_COLUMNS: tuple[str, ...] = (
    "id",
    "project_id",
    "lane",
    "position",
    "file_path",
    "display_name",
    "volume",
    "fade_in_s",
    "fade_out_s",
    "loop",
    "duration_s",
    "start_s",
    "source_in_s",
    "source_out_s",
    "added_at",
)


@dataclass(frozen=True)
class Snapshot:
    clips: ClipSnapshot
    music_start_s: float
    sfx: SfxSnapshot = ()

_lock = threading.RLock()
_revision = 0


@contextmanager
def history_guard() -> Iterator[None]:
    """Serialize control validation with ordinary Story history operations."""
    with _lock:
        yield


def history_revision() -> int:
    with _lock:
        return _revision


def invalidate_control_revision() -> None:
    """Conservatively invalidate control on a manual Studio mutation request."""
    global _revision
    with _lock:
        _revision += 1


@dataclass
class _ProjectHistory:
    undo: list[Snapshot] = field(default_factory=list)
    redo: list[Snapshot] = field(default_factory=list)
    open_group: str | None = None


_projects: dict[int, _ProjectHistory] = {}


def clear_studio_history() -> None:
    """Drop every project's stack. Used when the app process starts."""
    with _lock:
        _projects.clear()


def history_flags(project_id: int | None) -> dict[str, bool]:
    if project_id is None:
        return {"can_undo": False, "can_redo": False}
    with _lock:
        hist = _projects.get(project_id)
        if hist is None:
            return {"can_undo": False, "can_redo": False}
        return {"can_undo": bool(hist.undo), "can_redo": bool(hist.redo)}


def guarded_undo_values(db: Database, project_id: int, clip_id: int) -> str:
    """Read target values from the existing latest Story step before restoring."""
    with _lock:
        hist = _projects.get(project_id)
        if hist and hist.undo:
            for row in hist.undo[-1].clips:
                if row[0] == clip_id:
                    return str(row[_CLIP_COLUMNS.index("effect_settings")])
        raise ValueError("No matching Undo step")


def capture_story(db: Database, project_id: int, *, connection: sqlite3.Connection | None = None) -> Snapshot:
    with (nullcontext(connection) if connection is not None else db.connect()) as conn:
        return _capture_story(conn, project_id)


def _capture_story(conn: sqlite3.Connection, project_id: int) -> Snapshot:
    columns = ", ".join(_CLIP_COLUMNS)
    rows = conn.execute(
        f"""SELECT {columns}
                FROM studio_clips
                WHERE project_id = ?
                ORDER BY position ASC, id ASC""",
        (project_id,),
    ).fetchall()
    project = conn.execute(
        "SELECT music_start_s FROM studio_projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    sfx_columns = ", ".join(_SFX_COLUMNS)
    sfx_rows = conn.execute(
        f"""SELECT {sfx_columns}
                FROM studio_audio_clips
                WHERE project_id = ? AND lane = 'sfx'
                ORDER BY start_s ASC, position ASC, id ASC""",
        (project_id,),
    ).fetchall()
    return Snapshot(
        clips=tuple(tuple(row[name] for name in _CLIP_COLUMNS) for row in rows),
        music_start_s=(
            float(project["music_start_s"] or 0.0) if project is not None else 0.0
        ),
        sfx=tuple(tuple(row[name] for name in _SFX_COLUMNS) for row in sfx_rows),
    )


def restore_story(db: Database, project_id: int, snapshot: Snapshot, *, connection: sqlite3.Connection | None = None) -> None:
    """Replace one project's clip rows. Media files and other tables stay."""
    now = datetime.now().isoformat(timespec="seconds")
    keep_ids = [int(row[0]) for row in snapshot.clips]
    with (nullcontext(connection) if connection is not None else db.connect()) as conn:
        if keep_ids:
            placeholders = ",".join("?" for _ in keep_ids)
            conn.execute(
                f"""DELETE FROM studio_clips
                    WHERE project_id = ? AND id NOT IN ({placeholders})""",
                (project_id, *keep_ids),
            )
        else:
            conn.execute(
                "DELETE FROM studio_clips WHERE project_id = ?",
                (project_id,),
            )
        existing = {
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM studio_clips WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        }
        assignments = ", ".join(
            f"{name} = ?" for name in _CLIP_COLUMNS if name not in {"id", "project_id"}
        )
        insert_columns = ", ".join(_CLIP_COLUMNS)
        insert_values = ", ".join("?" for _ in _CLIP_COLUMNS)
        for row in snapshot.clips:
            if int(row[0]) in existing:
                conn.execute(
                    f"""UPDATE studio_clips
                        SET {assignments}
                        WHERE id = ? AND project_id = ?""",
                    (*row[2:], row[0], project_id),
                )
            else:
                conn.execute(
                    f"""INSERT INTO studio_clips ({insert_columns})
                        VALUES ({insert_values})""",
                    row,
                )
        conn.execute(
            """UPDATE studio_projects
               SET music_start_s = ?, updated_at = ?
               WHERE id = ?""",
            (snapshot.music_start_s, now, project_id),
        )
        _restore_sfx(conn, project_id, snapshot.sfx, now=now)


def _restore_sfx(
    conn: sqlite3.Connection,
    project_id: int,
    sfx: SfxSnapshot,
    *,
    now: str,
) -> None:
    keep_ids = [int(row[0]) for row in sfx]
    if keep_ids:
        placeholders = ",".join("?" for _ in keep_ids)
        conn.execute(
            f"""DELETE FROM studio_audio_clips
                WHERE project_id = ? AND lane = 'sfx' AND id NOT IN ({placeholders})""",
            (project_id, *keep_ids),
        )
    else:
        conn.execute(
            """DELETE FROM studio_audio_clips
               WHERE project_id = ? AND lane = 'sfx'""",
            (project_id,),
        )
    existing = {
        int(row["id"])
        for row in conn.execute(
            """SELECT id FROM studio_audio_clips
               WHERE project_id = ? AND lane = 'sfx'""",
            (project_id,),
        ).fetchall()
    }
    assignments = ", ".join(
        f"{name} = ?" for name in _SFX_COLUMNS if name not in {"id", "project_id"}
    )
    insert_columns = ", ".join(_SFX_COLUMNS)
    insert_values = ", ".join("?" for _ in _SFX_COLUMNS)
    for row in sfx:
        if int(row[0]) in existing:
            conn.execute(
                f"""UPDATE studio_audio_clips
                    SET {assignments}
                    WHERE id = ? AND project_id = ? AND lane = 'sfx'""",
                (*row[2:], row[0], project_id),
            )
        else:
            conn.execute(
                f"""INSERT INTO studio_audio_clips ({insert_columns})
                    VALUES ({insert_values})""",
                row,
            )
    conn.execute(
        "UPDATE studio_projects SET updated_at = ? WHERE id = ?",
        (now, project_id),
    )


@contextmanager
def transactional_story_undo(db: Database, project_id: int, *, validate: Callable[[sqlite3.Connection], None] | None = None) -> Iterator[sqlite3.Connection | None]:
    """Restore the existing latest snapshot and publish stacks only after commit."""
    with _lock:
        hist = _projects.get(project_id)
        if hist is None or not hist.undo:
            yield None
            return
        before = hist.undo[-1]
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _capture_story(conn, project_id)
            if validate is not None:
                validate(conn)
            restore_story(db, project_id, before, connection=conn)
            yield conn
        hist.undo.pop()
        hist.redo.append(current)
        hist.open_group = None
        invalidate_control_revision()


def undo_story(db: Database, project_id: int) -> bool:
    with transactional_story_undo(db, project_id) as conn:
        return conn is not None


def redo_story(db: Database, project_id: int) -> bool:
    with _lock:
        hist = _projects.get(project_id)
        if hist is None or not hist.redo:
            return False
        current = capture_story(db, project_id)
        after = hist.redo.pop()
        hist.open_group = None
        try:
            restore_story(db, project_id, after)
        except Exception:
            hist.redo.append(after)
            raise
        hist.undo.append(current)
        invalidate_control_revision()
        return True


@contextmanager
def story_edit(
    db: Database,
    project_id: int | None,
    *,
    group: str | None = None,
) -> Iterator[None]:
    """Remember the story before a successful edit.

    ``group`` coalesces a drag or slider into the step taken at its start.
    A failed edit leaves the stacks unchanged. A real edit clears Redo.
    """
    if project_id is None:
        yield
        return
    with _lock:
        hist = _projects.setdefault(project_id, _ProjectHistory())
        before = capture_story(db, project_id)
        grouped = bool(group) and group == hist.open_group
        saved_redo = list(hist.redo)
        if not grouped:
            hist.redo.clear()
        try:
            yield
        except Exception:
            if not grouped:
                hist.redo[:] = saved_redo
            raise
        after = capture_story(db, project_id)
        if after == before:
            if not grouped:
                hist.redo[:] = saved_redo
            return
        invalidate_control_revision()
        if not grouped:
            hist.undo.append(before)
            extra = len(hist.undo) - MAX_STORY_HISTORY
            if extra > 0:
                del hist.undo[:extra]
            hist.open_group = group or None
        if not group:
            hist.open_group = None


@contextmanager
def transactional_story_edit(db: Database, project_id: int, *, group: str | None = None) -> Iterator[sqlite3.Connection]:
    """Prepare snapshots inside the write transaction; publish only after commit.

    No database access follows commit. A failed write, snapshot, or commit leaves
    the existing Undo/Redo stacks untouched.
    """
    with _lock:
        hist = _projects.setdefault(project_id, _ProjectHistory())
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = _capture_story(conn, project_id)
            yield conn
            after = _capture_story(conn, project_id)
        if before != after:
            if not group or group != hist.open_group:
                hist.undo.append(before)
                del hist.undo[:-MAX_STORY_HISTORY]
            hist.redo.clear()
            hist.open_group = group or None
            invalidate_control_revision()
