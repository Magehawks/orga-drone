"""Helpers to resolve and safely serve library media files."""

from __future__ import annotations

from pathlib import Path

from orga_drone.db import Database, MediaRow
from orga_drone.thumbs import find_proxy


def is_under_root(file_path: Path, root_path: Path) -> bool:
    try:
        file_path.resolve().relative_to(root_path.resolve())
        return True
    except ValueError:
        return False


def _roots_map(db: Database) -> dict[int, Path]:
    return {int(r["id"]): Path(r["path"]) for r in db.list_roots()}


def resolve_media_file(
    db: Database,
    item: MediaRow,
    *,
    roots: dict[int, Path] | None = None,
) -> Path | None:
    """Resolve a media row to a real file under a configured library root.

    Paths always come from the user's library roots on disk — never from a
    PyInstaller bundle (_MEIPASS). Only templates/static live in the package.
    """
    path = Path(item.path)
    # Cheap existence check before resolve()/root walk (AV-sensitive on Windows).
    if not path.is_file():
        return None
    root_map = roots if roots is not None else _roots_map(db)
    root = root_map.get(item.root_id)
    if root is None or not is_under_root(path, root):
        return None
    return path.resolve()


def resolve_proxy_file(
    db: Database,
    item: MediaRow,
    *,
    roots: dict[int, Path] | None = None,
) -> Path | None:
    root_map = roots if roots is not None else _roots_map(db)
    media = resolve_media_file(db, item, roots=root_map)
    if media is None:
        return None
    proxy = find_proxy(media)
    if proxy is None:
        return None
    root = root_map.get(item.root_id)
    if root is None or not is_under_root(proxy, root):
        return None
    return proxy.resolve()
