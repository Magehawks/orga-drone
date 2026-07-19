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


def resolve_media_file(db: Database, item: MediaRow) -> Path | None:
    path = Path(item.path)
    if not path.exists() or not path.is_file():
        return None
    roots = {int(r["id"]): Path(r["path"]) for r in db.list_roots()}
    root = roots.get(item.root_id)
    if root is None or not is_under_root(path, root):
        return None
    return path.resolve()


def resolve_proxy_file(db: Database, item: MediaRow) -> Path | None:
    media = resolve_media_file(db, item)
    if media is None:
        return None
    proxy = find_proxy(media)
    if proxy is None:
        return None
    roots = {int(r["id"]): Path(r["path"]) for r in db.list_roots()}
    root = roots.get(item.root_id)
    if root is None or not is_under_root(proxy, root):
        return None
    return proxy.resolve()
