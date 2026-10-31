"""Sizes and clearing for caches the app can build again.

Original media, the catalog database, Studio projects, and exports are not
caches and are never deleted here.
"""

from __future__ import annotations

from pathlib import Path

REBUILDABLE_CACHE_DIRS = (
    "thumbs",
    "osm-tiles",
    "preview-stills",
    "hsl-luts",
    "color-wheel-luts",
)


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def directory_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        if not _inside(path, item):
            continue
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def cache_sizes(data_dir: Path) -> dict[str, int]:
    root = data_dir.resolve()
    sizes = {name: directory_size(root / name) for name in REBUILDABLE_CACHE_DIRS}
    sizes["total"] = sum(sizes.values())
    return sizes


def clear_regenerable_cache(data_dir: Path) -> int:
    """Delete thumbnail, map-tile, and preview-still files under the app data folder.

    Returns the number of bytes removed. The folders are recreated empty.
    """
    root = data_dir.resolve()
    removed = 0
    for name in REBUILDABLE_CACHE_DIRS:
        folder = (root / name).resolve()
        if not _inside(root, folder) or folder == root or not folder.is_dir():
            continue
        for item in sorted(folder.rglob("*"), reverse=True):
            if not _inside(folder, item):
                continue
            try:
                if item.is_file() or item.is_symlink():
                    removed += item.stat().st_size if item.is_file() else 0
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            except OSError:
                continue
        folder.mkdir(parents=True, exist_ok=True)
    return removed


def format_bytes(size: int) -> str:
    value = max(0, int(size))
    if value < 1024:
        return f"{value} B"
    units = ("KB", "MB", "GB")
    amount = float(value)
    for unit in units:
        amount /= 1024
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}"
    return f"{amount:.1f} GB"
