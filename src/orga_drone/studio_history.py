"""In-memory Undo/Redo for the open Studio story.

The stack keeps snapshots of ``studio_clips`` plus the project-level soundtrack
start for one project. It is not written to SQLite and is empty when the process
starts. Undo restores those Story values. It does not touch media files,
library rows, albums, or other projects.

A slider gesture sends the same ``X-Studio-History-Group`` on each save.
Those saves share one step, taken from the state before the gesture. A later
edit clears Redo.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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


@dataclass(frozen=True)
class Snapshot:
    clips: ClipSnapshot
    music_start_s: float

_lock = threading.Lock()


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


def capture_story(db: Database, project_id: int) -> Snapshot:
    columns = ", ".join(_CLIP_COLUMNS)
    with db.connect() as conn:
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
    return Snapshot(
        clips=tuple(tuple(row[name] for name in _CLIP_COLUMNS) for row in rows),
        music_start_s=(
            float(project["music_start_s"] or 0.0) if project is not None else 0.0
        ),
    )


def restore_story(db: Database, project_id: int, snapshot: Snapshot) -> None:
    """Replace one project's clip rows. Media files and other tables stay."""
    now = datetime.now().isoformat(timespec="seconds")
    keep_ids = [int(row[0]) for row in snapshot.clips]
    with db.connect() as conn:
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


def undo_story(db: Database, project_id: int) -> bool:
    with _lock:
        hist = _projects.get(project_id)
        if hist is None or not hist.undo:
            return False
        current = capture_story(db, project_id)
        before = hist.undo.pop()
        hist.open_group = None
        try:
            restore_story(db, project_id, before)
        except Exception:
            hist.undo.append(before)
            raise
        hist.redo.append(current)
        return True


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
        if not grouped:
            hist.undo.append(before)
            extra = len(hist.undo) - MAX_STORY_HISTORY
            if extra > 0:
                del hist.undo[:extra]
            hist.open_group = group or None
        if not group:
            hist.open_group = None
