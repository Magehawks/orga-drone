"""Existing project lifecycle shared by Studio transports and Control API.

Projects are already committed on each edit. There is no additional save format.
All writes serialize with Story history and may join one caller-owned transaction.
"""

from __future__ import annotations

import math
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, TypedDict

from orga_drone.db import Database, StudioProject
from orga_drone.studio_history import history_guard, invalidate_control_revision


class ProjectActionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProjectView(TypedDict):
    id: int
    title: str
    created_at: str
    updated_at: str
    music_start_s: float
    clip_count: int


def project_view(project: StudioProject) -> ProjectView:
    return {
        "id": project.id,
        "title": project.title,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "music_start_s": project.music_start_s,
        "clip_count": project.clip_count,
    }


PROJECT_PARAMETERS: dict[str, dict[str, dict[str, Any]]] = {
    "project.list": {},
    "project.get": {},
    "project.create": {"title": {"type": "string", "max_length": 120}},
    "project.open": {
        "project_id": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1}
    },
    "project.rename": {"title": {"type": "string", "max_length": 120}},
    "project.delete": {},
    "music.append": {"file_path": {"type": "string", "max_length": 1024}},
    "music.update": {
        "clip_id": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1},
        "volume": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "fade_in_s": {"type": "number", "minimum": 0.0, "maximum": 10.0},
        "fade_out_s": {"type": "number", "minimum": 0.0, "maximum": 10.0},
        "loop": {"type": "boolean"},
    },
    "music.remove": {
        "clip_id": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1}
    },
    "music.reorder": {"ordered_ids": {"type": "integer_array"}},
    "music.set_start": {"start_s": {"type": "number", "minimum": 0.0}},
    # SFX placement is project-scoped like music, but every write is a Story
    # history step (the UI route uses story_edit; music playlist edits do not).
    "sfx.append": {
        "file_path": {"type": "string", "max_length": 1024},
        "start_s": {"type": "number", "minimum": 0.0, "maximum": 86400.0},
    },
    "sfx.update": {
        "clip_id": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1},
        "start_s": {"type": "number", "minimum": 0.0, "maximum": 86400.0},
        "source_in_s": {"type": "number", "minimum": 0.0, "maximum": 86400.0},
        "source_out_s": {"type": "number", "minimum": 0.0, "maximum": 86400.0},
        "volume": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "fade_in_s": {"type": "number", "minimum": 0.0, "maximum": 10.0},
        "fade_out_s": {"type": "number", "minimum": 0.0, "maximum": 10.0},
    },
    "sfx.remove": {
        "clip_id": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1}
    },
}


def _require_range(value: Any, *, minimum: float, maximum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectActionError("INVALID_PARAMS")
    number = float(value)
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise ProjectActionError("INVALID_PARAMS")


def _require_unit_interval(value: Any) -> None:
    _require_range(value, minimum=0.0, maximum=1.0)


def validate_project_params(action: str, params: Any) -> dict[str, Any]:
    if action not in PROJECT_PARAMETERS:
        raise ProjectActionError("UNKNOWN_ACTION")
    expected = PROJECT_PARAMETERS[action]
    if not isinstance(params, dict) or set(params) != set(expected):
        raise ProjectActionError("INVALID_PARAMS")
    if "title" in params:
        title = params["title"]
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise ProjectActionError("INVALID_PARAMS")
    if "project_id" in params:
        pid = params["project_id"]
        if type(pid) is not int or not 0 < pid <= 2**53 - 1:
            raise ProjectActionError("INVALID_IDENTIFIER")
    if "file_path" in params:
        file_path = params["file_path"]
        if not isinstance(file_path, str) or not file_path.strip() or len(file_path) > 1024:
            raise ProjectActionError("INVALID_PARAMS")
    if "clip_id" in params:
        clip_id = params["clip_id"]
        if type(clip_id) is not int or not 0 < clip_id <= 2**53 - 1:
            raise ProjectActionError("INVALID_IDENTIFIER")
    if "ordered_ids" in params:
        ids = params["ordered_ids"]
        if (
            not isinstance(ids, list)
            or any(type(item) is not int or item < 1 for item in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ProjectActionError("INVALID_PARAMS")
    if action == "music.update":
        # All-or-nothing updates keep the shared schema strict: the client
        # reads the current track first (issue #292 current-state-read rule).
        volume, fade_in, fade_out, loop = (
            params["volume"], params["fade_in_s"], params["fade_out_s"], params["loop"],
        )
        if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not math.isfinite(float(volume)):
            raise ProjectActionError("INVALID_PARAMS")
        for value in (fade_in, fade_out):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ProjectActionError("INVALID_PARAMS")
        if type(loop) is not bool:
            raise ProjectActionError("INVALID_PARAMS")
    if action == "sfx.update":
        _require_unit_interval(params["volume"])
        for key in ("fade_in_s", "fade_out_s"):
            _require_range(params[key], minimum=0.0, maximum=10.0)
        _require_range(params["source_in_s"], minimum=0.0, maximum=86400.0)
        _require_range(params["source_out_s"], minimum=0.0, maximum=86400.0)
        if float(params["source_out_s"]) <= float(params["source_in_s"]):
            raise ProjectActionError("INVALID_PARAMS")
    if action in {"sfx.append", "sfx.update"}:
        _require_range(params["start_s"], minimum=0.0, maximum=86400.0)
    if "start_s" in params and action not in {"sfx.append", "sfx.update"}:
        start = params["start_s"]
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(float(start)) or start < 0.0:
            raise ProjectActionError("INVALID_PARAMS")
    return dict(params)


@contextmanager
def project_transaction(db: Database) -> Iterator[sqlite3.Connection]:
    with history_guard():
        with db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
        invalidate_control_revision()


def create_project(
    db: Database,
    title: str,
    *,
    open_created: bool = False,
    connection: sqlite3.Connection | None = None,
) -> StudioProject:
    if connection is None:
        with project_transaction(db) as conn:
            return create_project(db, title, open_created=open_created, connection=conn)
    project = db.create_studio_project(title, connection=connection)
    if open_created:
        db.set_open_studio_project_id(project.id, connection=connection)
    return project


def open_project(
    db: Database, project_id: int, *, connection: sqlite3.Connection | None = None
) -> StudioProject:
    if connection is None:
        with project_transaction(db) as conn:
            return open_project(db, project_id, connection=conn)
    project = db.get_studio_project(project_id, connection=connection)
    if project is None:
        raise ProjectActionError("TARGET_NOT_FOUND")
    db.set_open_studio_project_id(project.id, connection=connection)
    return project


def rename_project(
    db: Database,
    project_id: int,
    title: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> StudioProject:
    if connection is None:
        with project_transaction(db) as conn:
            return rename_project(db, project_id, title, connection=conn)
    return db.set_studio_project_title(project_id, title, connection=connection)


def delete_project(
    db: Database, project_id: int, *, connection: sqlite3.Connection | None = None
) -> bool:
    if connection is None:
        with project_transaction(db) as conn:
            return delete_project(db, project_id, connection=conn)
    return db.delete_studio_project(project_id, connection=connection)


def read_projects(db: Database, action: str, target: dict[str, Any]) -> dict[str, Any]:
    if action == "project.list":
        if target:
            raise ProjectActionError("INVALID_TARGET")
        opened = db.get_open_studio_project()
        return {
            "current_id": opened.id if opened else None,
            "projects": [project_view(p) for p in db.list_studio_projects()],
        }
    if action != "project.get" or set(target) != {"project_id"}:
        raise ProjectActionError("INVALID_TARGET")
    pid = target["project_id"]
    if type(pid) is not int or not 0 < pid <= 2**53 - 1:
        raise ProjectActionError("INVALID_IDENTIFIER")
    project = db.get_studio_project(pid)
    if project is None:
        raise ProjectActionError("TARGET_NOT_FOUND")
    # Only identity/type is exposed; source paths, raw settings and soundtrack
    # filenames are deliberately absent from this lifecycle read surface.
    clips = db.list_studio_items(pid)
    view = project_view(project)
    view["clip_count"] = len(clips)
    return {
        "project": view,
        "clips": [
            {
                "id": c.id,
                "kind": c.kind,
                "item_kind": c.item_kind,
                "media_id": c.media_id,
            }
            for c in clips
        ],
    }
