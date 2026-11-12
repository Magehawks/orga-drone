"""Choose a Home hero from media that already has a local thumbnail.

Home markup points at the mid-resolution hero endpoint. Selection still
requires an existing grid or hero cache so the page does not invent media
from nothing. A missing, offline, or not-yet-cached file falls back to the
app logo.

Issue #335: hero caches warm asynchronously after Home renders (grid
thumbnails exist after a scan), so the first paint keeps the logo/480
fallback instead of waiting on an ffmpeg/Pillow mid-res generation.
"""

from __future__ import annotations

import threading
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


# One warm pass at a time; a second Home hit while warming must not stack
# worker threads.
_warm_lock = threading.Lock()
_warm_running = False


def warm_hero_cache(db, *, limit: int = 24) -> int:  # type: ignore[no-untyped-def]
    """Generate mid-res hero JPEGs for the most recent items, skipping ones
    already cached. Never raises for individual files: offline or
    unrenderable media are skipped so the hero falls back as before. Cache
    location follows the same settings source as ``ensure_hero_thumbnail``."""
    from orga_drone.config import settings
    from orga_drone.media_files import resolve_media_file
    from orga_drone.thumbs import ensure_hero_thumbnail

    data_dir = settings.data_dir
    warmed = 0
    for item in db.list_media(sort="recorded_at", order="desc", limit=limit):
        media_id = getattr(item, "id", None)
        path = resolve_media_file(db, item)
        if not isinstance(media_id, int) or path is None:
            continue
        if cached_hero_thumbnail(data_dir, media_id) is not None:
            continue
        try:
            ensure_hero_thumbnail(
                media_id=media_id, path=path, kind=item.kind, filename=item.filename
            )
        except OSError:
            continue
        warmed += 1
    return warmed


def warm_hero_cache_async(db, *, limit: int = 24) -> bool:  # type: ignore[no-untyped-def]
    """Start one background warm pass; False when one is already running."""
    global _warm_running
    with _warm_lock:
        if _warm_running:
            return False
        _warm_running = True

    def _run() -> None:
        global _warm_running
        try:
            warm_hero_cache(db, limit=limit)
        finally:
            _warm_running = False

    threading.Thread(target=_run, daemon=True, name="home-hero-warm").start()
    return True
