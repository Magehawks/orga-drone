"""Choose a Home hero from media that already has a local thumbnail.

Home markup points at the mid-resolution hero endpoint. Selection still
requires an existing grid or hero cache so the page does not invent media
from nothing. A missing, offline, or not-yet-cached file falls back to the
app logo.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from orga_drone.thumbs import HERO_CACHE_PREFIX


def cached_thumbnail(data_dir: Path, media_id: int) -> Path | None:
    """Return an existing grid thumbnail file for this media id, if on disk."""
    return _cached_image(data_dir, media_id, prefix="")


def cached_hero_thumbnail(data_dir: Path, media_id: int) -> Path | None:
    """Return an existing mid-resolution hero JPEG for this media id, if on disk."""
    return _cached_image(data_dir, media_id, prefix=HERO_CACHE_PREFIX)


def _cached_image(data_dir: Path, media_id: int, *, prefix: str) -> Path | None:
    folder = (data_dir / "thumbs").resolve()
    if not folder.is_dir():
        return None
    matches: list[Path] = []
    for path in folder.glob(f"{prefix}{int(media_id)}_*.jpg"):
        if not path.is_file():
            continue
        # Skip temporary ffmpeg extracts written next to a hero cache.
        if path.name.endswith("_raw.jpg"):
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
    """First recent item whose source file and a cached preview JPEG are present."""
    for item in items:
        media_id = getattr(item, "id", None)
        if not isinstance(media_id, int):
            continue
        if file_ready(item) is None:
            continue
        if (
            cached_thumbnail(data_dir, media_id) is None
            and cached_hero_thumbnail(data_dir, media_id) is None
        ):
            continue
        return media_id
    return None
