"""Choose a Home hero from media that already has a local thumbnail.

The page does not decode videos or create thumbnails. A missing, offline, or
not-yet-cached file falls back to the app logo.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def cached_thumbnail(data_dir: Path, media_id: int) -> Path | None:
    """Return an existing thumbnail file for this media id, if one is on disk."""
    folder = (data_dir / "thumbs").resolve()
    if not folder.is_dir():
        return None
    matches: list[Path] = []
    for path in folder.glob(f"{int(media_id)}_*.jpg"):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(folder)
        except ValueError:
            continue
        matches.append(path)
    if not matches:
        return None
    return max(matches, key=lambda item: item.stat().st_mtime)


def pick_home_media_id(
    items: Sequence[object],
    data_dir: Path,
    *,
    file_ready,
) -> int | None:
    """First recent item whose source file and cached thumbnail are both present."""
    for item in items:
        media_id = getattr(item, "id", None)
        if not isinstance(media_id, int):
            continue
        if file_ready(item) is None:
            continue
        if cached_thumbnail(data_dir, media_id) is None:
            continue
        return media_id
    return None
