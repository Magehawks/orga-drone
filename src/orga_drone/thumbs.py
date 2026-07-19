"""Thumbnail cache for photos (Pillow) and optional video frames (ffmpeg)."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from orga_drone.config import settings

THUMB_SIZE = (480, 270)


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


def _cache_path(media_id: int, source: Path) -> Path:
    try:
        mtime = source.stat().st_mtime_ns
    except OSError:
        mtime = 0
    digest = hashlib.sha1(f"{media_id}:{source}:{mtime}".encode()).hexdigest()[:16]
    return thumbs_dir() / f"{media_id}_{digest}.jpg"


def _placeholder(kind: str, label: str) -> Image.Image:
    img = Image.new("RGB", THUMB_SIZE, (18, 28, 36))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, THUMB_SIZE[0] - 1, THUMB_SIZE[1] - 1), outline=(45, 70, 82), width=2)
    text = label[:28] or kind.upper()
    draw.text((16, THUMB_SIZE[1] // 2 - 10), text, fill=(180, 200, 210))
    return img


def _save_image(img: Image.Image, dest: Path) -> Path:
    img = img.convert("RGB")
    img.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", THUMB_SIZE, (12, 18, 24))
    x = (THUMB_SIZE[0] - img.width) // 2
    y = (THUMB_SIZE[1] - img.height) // 2
    canvas.paste(img, (x, y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, "JPEG", quality=82, optimize=True)
    return dest


def _ffmpeg_frame(source: Path, dest: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
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
        # Soft fallback: still image placeholder (grid may use <video> instead)
        _save_image(_placeholder("video", filename), cache)
        return cache

    _save_image(_placeholder(kind, filename), cache)
    return cache
