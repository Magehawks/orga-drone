"""Existing project lifecycle shared by Studio transports and Control API.

Projects are already committed on each edit. There is no additional save format.
All writes serialize with Story history and may join one caller-owned transaction.
"""

from __future__ import annotations

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
}


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
