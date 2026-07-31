"""Thumbnail cache for photos (Pillow) and optional video frames (ffmpeg)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from orga_drone.config import settings
from orga_drone.ffmpeg_bin import find_ffmpeg

if TYPE_CHECKING:
    from PIL import Image

THUMB_SIZE = (480, 270)
# Detail-page JPEG for formats browsers cannot show natively (HEIC/HEIF/DNG).
PHOTO_PREVIEW_MAX = (1920, 1920)

# Suffixes most browsers can render in <img src> without conversion.
BROWSER_NATIVE_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def thumbs_dir() -> Path:
    path = settings.data_dir / "thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sibling_with_suffix(path: Path, suffix: str) -> Path | None:
    for candidate in (path.with_suffix(suffix), path.with_suffix(suffix.lower()), path.with_suffix(suffix.upper())):
        if candidate.exists():
            return candidate
    return None


def find_proxy(path: Path) -> Path | None:
    return sibling_with_suffix(path, ".LRF") or sibling_with_suffix(path, ".lrf")


def browser_can_display_photo(path: Path) -> bool:
    """True when a typical browser can show this photo file in an <img> tag."""
    return path.suffix.lower() in BROWSER_NATIVE_PHOTO_EXTS


def _cache_path(media_id: int, source: Path, *, prefix: str = "") -> Path:
    try:
        mtime = source.stat().st_mtime_ns
    except OSError:
        mtime = 0
    digest = hashlib.sha1(f"{media_id}:{source}:{mtime}".encode()).hexdigest()[:16]
    name = f"{prefix}{media_id}_{digest}.jpg" if prefix else f"{media_id}_{digest}.jpg"
    return thumbs_dir() / name


def _placeholder(kind: str, label: str) -> Image.Image:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", THUMB_SIZE, (18, 28, 36))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, THUMB_SIZE[0] - 1, THUMB_SIZE[1] - 1), outline=(45, 70, 82), width=2)
    text = label[:28] or kind.upper()
    draw.text((16, THUMB_SIZE[1] // 2 - 10), text, fill=(180, 200, 210))
    return img


def _save_image(
    img: Image.Image,
    dest: Path,
    *,
    size: tuple[int, int] = THUMB_SIZE,
    letterbox: bool = True,
    quality: int = 82,
) -> Path:
    from PIL import Image

    img = img.convert("RGB")
    img.thumbnail(size, Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if letterbox:
        canvas = Image.new("RGB", size, (12, 18, 24))
        x = (size[0] - img.width) // 2
        y = (size[1] - img.height) // 2
        canvas.paste(img, (x, y))
        canvas.save(dest, "JPEG", quality=quality, optimize=True)
    else:
        img.save(dest, "JPEG", quality=quality, optimize=True)
    return dest


def _ffmpeg_frame(source: Path, dest: Path) -> bool:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        "0.5",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-q:v",
        "4",
        str(dest),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        return dest.exists() and dest.stat().st_size > 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_thumbnail(*, media_id: int, path: Path, kind: str, filename: str) -> Path:
    """Return path to a JPEG thumbnail, creating it if needed."""
    from PIL import Image

    from orga_drone.parse import ensure_heif_support

    ensure_heif_support()

    source = path
    if kind == "video":
        proxy = find_proxy(path)
        if proxy is not None:
            source = proxy

    cache = _cache_path(media_id, source)
    if cache.exists():
        return cache

    if kind == "photo":
        try:
            with Image.open(path) as img:
                _save_image(img, cache)
            return cache
        except OSError:
            pass

    if kind == "video":
        if _ffmpeg_frame(source, cache):
            return cache
        _save_image(_placeholder("video", filename), cache)
        return cache

    _save_image(_placeholder(kind, filename), cache)
    return cache


def ensure_photo_preview(
    *, media_id: int, path: Path, filename: str | None = None
) -> Path:
    """JPEG suitable for detail <img> when the original is HEIC/HEIF/DNG/etc.

    Falls back to the map/grid thumbnail (including placeholder) so the detail
    page never ends up with a broken image while thumbs still render.
    """
    from PIL import Image

    from orga_drone.parse import ensure_heif_support

    ensure_heif_support()
    cache = _cache_path(media_id, path, prefix="prev_")
    if cache.exists():
        return cache
    try:
        with Image.open(path) as img:
            _save_image(
                img,
                cache,
                size=PHOTO_PREVIEW_MAX,
                letterbox=False,
                quality=88,
            )
        return cache
    except OSError:
        return ensure_thumbnail(
            media_id=media_id,
            path=path,
            kind="photo",
            filename=filename or path.name,
        )
