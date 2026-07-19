"""Rename media files and matching siblings (LRF/SRT/…)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from orga_drone.db import Database, MediaRow
from orga_drone.media_files import is_under_root, resolve_media_file

SAFE_STEM_RE = re.compile(r"^[\w.\- ()\[\]]+$", re.UNICODE)


@dataclass
class RenameResult:
    media_id: int
    renamed: list[tuple[str, str]]
    new_filename: str


class RenameError(ValueError):
    pass


def sanitize_stem(raw: str) -> str:
    stem = raw.strip()
    lower = stem.lower()
    for ext in (".mp4", ".mov", ".jpg", ".jpeg", ".lrf", ".srt", ".dng", ".png", ".mkv"):
        if lower.endswith(ext):
            stem = Path(stem).stem
            break
    if not stem or stem in {".", ".."}:
        raise RenameError("empty name")
    if "/" in stem or "\\" in stem or ":" in stem:
        raise RenameError("invalid characters")
    if not SAFE_STEM_RE.match(stem):
        raise RenameError("invalid characters")
    return stem


def sibling_files(path: Path) -> list[Path]:
    return sorted(p for p in path.parent.iterdir() if p.is_file() and p.stem == path.stem)


def rename_media(db: Database, item: MediaRow, new_stem: str) -> RenameResult:
    stem = sanitize_stem(new_stem)
    source = resolve_media_file(db, item)
    if source is None:
        raise RenameError("file missing")

    roots = {int(r["id"]): Path(r["path"]) for r in db.list_roots()}
    root = roots.get(item.root_id)
    if root is None:
        raise RenameError("library root missing")

    siblings = sibling_files(source) or [source]

    planned: list[tuple[Path, Path]] = []
    for old in siblings:
        new_path = old.with_name(stem + old.suffix)
        if new_path.resolve() == old.resolve():
            continue
        if new_path.exists():
            raise RenameError(f"target exists: {new_path.name}")
        if not is_under_root(new_path, root):
            raise RenameError("target outside library")
        planned.append((old, new_path))

    if not planned:
        return RenameResult(media_id=item.id, renamed=[], new_filename=item.filename)

    renamed: list[tuple[str, str]] = []
    for old, new_path in planned:
        old.rename(new_path)
        renamed.append((old.name, new_path.name))
        db.repath_file(str(old.resolve()), str(new_path.resolve()), new_stem=new_path.stem)

    media_path = source.parent / (stem + source.suffix)
    has_lrf = media_path.with_suffix(".LRF").exists() or media_path.with_suffix(".lrf").exists()
    has_srt = media_path.with_suffix(".SRT").exists() or media_path.with_suffix(".srt").exists()
    db.update_media_identity(
        item.id,
        filename=media_path.name,
        path=str(media_path.resolve()),
        has_lrf=1 if has_lrf else 0,
        has_srt=1 if has_srt else 0,
    )

    return RenameResult(media_id=item.id, renamed=renamed, new_filename=media_path.name)
