"""Local still-image export for one library photo.

Best quality copies a readable still (JPEG, PNG, and similar). Share presets
write a new JPEG. Nothing is uploaded.

A non-neutral grade uses the Studio ffmpeg filter chain
(``ffmpeg_grade_chain``) and then the same preset. Neutral leaves that chain
out, so a best-quality copy stays the original bytes. The library file is
never written.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from orga_drone.export.studio_encoder import (
    ExportCancelled,
    StudioExportError,
    _publish_export_file,
)
from orga_drone.studio_image import ImageAdjust, ffmpeg_grade_chain

PRESET_BEST = "best"
PRESET_WHATSAPP = "whatsapp"
PRESET_INSTAGRAM = "instagram"
PRESET_TIKTOK = "tiktok"
SHARE_PRESETS: tuple[str, ...] = (
    PRESET_BEST,
    PRESET_WHATSAPP,
    PRESET_INSTAGRAM,
    PRESET_TIKTOK,
)

WHATSAPP_LONGEST = 1600
WHATSAPP_QUALITY = 85
INSTAGRAM_SIZE = (1080, 1350)
TIKTOK_SIZE = (1080, 1920)
SOCIAL_JPEG_QUALITY = 90
BEST_JPEG_QUALITY = 95

# The Studio encoder scales and pads to an explicit frame. These presets use
# that frame. The picture is fitted inside it, not cropped.
SOCIAL_VIDEO_WIDTH = 1080
SOCIAL_VIDEO_HEIGHT = 1920

# Formats Pillow can write back after a grade. HEIC and similar become JPEG.
_REENCODE_SUFFIXES = {".jpg", ".png", ".webp", ".gif", ".tif", ".bmp"}


@dataclass(frozen=True)
class PhotoPresetSpec:
    """What a photo preset will write. ``copied`` means the original bytes."""

    suffix: str
    width: int | None
    height: int | None
    copied: bool


def normalize_share_preset(preset: str) -> str:
    key = str(preset or "").strip().lower()
    if key not in SHARE_PRESETS:
        raise StudioExportError("Choose a share preset.")
    return key


def _is_graded(image: ImageAdjust | None) -> bool:
    return image is not None and not image.is_neutral


def _best_suffix(copy_suffix: str | None, *, graded: bool) -> tuple[str, bool]:
    """Return ``(suffix, copied)`` for best quality."""
    if copy_suffix is not None and not graded:
        return copy_suffix, True
    if graded and copy_suffix in _REENCODE_SUFFIXES:
        return copy_suffix, False
    return ".jpg", False


def inspect_photo_preset(
    source: Path,
    preset: str,
    *,
    image: ImageAdjust | None = None,
) -> PhotoPresetSpec:
    """Pixel size and suffix for one photo preset. Does not write a file."""
    key = normalize_share_preset(preset)
    graded = _is_graded(image)
    img = _load_still(source)
    try:
        if key == PRESET_BEST:
            suffix, copied = _best_suffix(
                _copy_suffix(source, img.format or ""),
                graded=graded,
            )
            if copied:
                return PhotoPresetSpec(suffix=suffix, width=None, height=None, copied=True)
            rgb = _oriented_rgb(img)
            width, height = rgb.size
            return PhotoPresetSpec(suffix=suffix, width=width, height=height, copied=False)
        if key == PRESET_WHATSAPP:
            fitted = _fit_longest(_oriented_rgb(img), WHATSAPP_LONGEST)
            width, height = fitted.size
            return PhotoPresetSpec(suffix=".jpg", width=width, height=height, copied=False)
        if key == PRESET_INSTAGRAM:
            width, height = INSTAGRAM_SIZE
        else:
            width, height = TIKTOK_SIZE
        return PhotoPresetSpec(suffix=".jpg", width=width, height=height, copied=False)
    finally:
        img.close()


def export_photo_file(
    source: Path,
    dest: Path,
    preset: str,
    *,
    protected: Iterable[Path | str] = (),
    protected_identities: Iterable[tuple[int, int]] = (),
    cancel_event: threading.Event | None = None,
    image: ImageAdjust | None = None,
) -> Path:
    """Write one photo preset and publish it without replacing an existing file."""
    if cancel_event is not None and cancel_event.is_set():
        raise ExportCancelled()
    key = normalize_share_preset(preset)
    if not source.is_file():
        raise StudioExportError("The source file is not available.")
    tmp_dir = Path(tempfile.mkdtemp(prefix="orga-drone-export-"))
    partial = tmp_dir / "still.bin"
    try:
        _write_preset(source, partial, key, image=image, cancel_event=cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            raise ExportCancelled()
        if not partial.is_file() or partial.stat().st_size <= 0:
            raise StudioExportError("Could not read this photo.")
        return _publish_export_file(
            partial,
            dest,
            protected=protected,
            protected_identities=protected_identities,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_preset(
    source: Path,
    dest: Path,
    preset: str,
    *,
    image: ImageAdjust | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    graded = _is_graded(image)
    img = _load_still(source)
    try:
        copy_suffix = _copy_suffix(source, img.format or "")
        if preset == PRESET_BEST and not graded and copy_suffix is not None:
            shutil.copyfile(source, dest)
            return
        rgb = _oriented_rgb(img)
        if graded:
            rgb = _grade_rgb(rgb, image, cancel_event=cancel_event)
        if preset == PRESET_BEST:
            _save_best(rgb, dest, copy_suffix if graded else None)
            return
        if preset == PRESET_WHATSAPP:
            fitted = _fit_longest(rgb, WHATSAPP_LONGEST)
            _save_jpeg(fitted, dest, WHATSAPP_QUALITY)
            return
        target = INSTAGRAM_SIZE if preset == PRESET_INSTAGRAM else TIKTOK_SIZE
        framed = _cover_crop(rgb, target[0], target[1])
        _save_jpeg(framed, dest, SOCIAL_JPEG_QUALITY)
    finally:
        img.close()


def _grade_rgb(rgb, image: ImageAdjust | None, *, cancel_event: threading.Event | None):
    """Run the Studio grade on one still. The source file is not an ffmpeg input."""
    if image is None or image.is_neutral:
        return rgb
    if cancel_event is not None and cancel_event.is_set():
        raise ExportCancelled()
    chain = ffmpeg_grade_chain(image)
    if not chain:
        return rgb
    from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise StudioExportError("Install ffmpeg or: pip install imageio-ffmpeg")
    tmp_dir = Path(tempfile.mkdtemp(prefix="orga-drone-grade-"))
    src = tmp_dir / "in.png"
    dst = tmp_dir / "out.png"
    try:
        rgb.save(src, format="PNG")
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-vf",
            f"{chain},format=rgb24",
            "-frames:v",
            "1",
            str(dst),
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **subprocess_no_window_kwargs(),
        )
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                proc.wait(timeout=5)
                raise ExportCancelled()
            try:
                proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode != 0 or not dst.is_file():
            raise StudioExportError("Could not read this photo.")
        from PIL import Image

        graded = Image.open(dst)
        try:
            graded.load()
            return graded.convert("RGB").copy()
        finally:
            graded.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _save_best(img, dest: Path, copy_suffix: str | None) -> None:
    suffix, _copied = _best_suffix(copy_suffix, graded=True)
    if suffix == ".png":
        _save_image(img, dest, "PNG")
        return
    if suffix == ".webp":
        _save_image(img, dest, "WEBP", quality=BEST_JPEG_QUALITY)
        return
    if suffix == ".gif":
        _save_image(img, dest, "GIF")
        return
    if suffix == ".tif":
        _save_image(img, dest, "TIFF")
        return
    if suffix == ".bmp":
        _save_image(img, dest, "BMP")
        return
    _save_jpeg(img, dest, BEST_JPEG_QUALITY)


def _copy_suffix(source: Path, image_format: str) -> str | None:
    """Suffix for a byte copy, or None when the still must be re-encoded."""
    fmt = (image_format or "").upper()
    if fmt == "JPEG":
        return ".jpg"
    if fmt == "PNG":
        return ".png"
    if fmt == "WEBP":
        return ".webp"
    if fmt == "GIF":
        return ".gif"
    if fmt == "TIFF":
        return ".tif"
    if fmt == "BMP":
        return ".bmp"
    if fmt == "HEIF":
        ext = source.suffix.lower()
        return ext if ext in {".heic", ".heif"} else ".heic"
    return None


def _load_still(source: Path):
    from PIL import Image

    from orga_drone.parse import ensure_heif_support

    if not source.is_file():
        raise StudioExportError("The source file is not available.")
    ensure_heif_support()
    try:
        img = Image.open(source)
        img.load()
    except OSError as exc:
        raise StudioExportError("Could not read this photo.") from exc
    return img


def _oriented_rgb(img):
    from PIL import ImageOps

    oriented = ImageOps.exif_transpose(img) or img
    if oriented.mode == "RGB":
        return oriented
    return oriented.convert("RGB")


def _fit_longest(img, longest: int):
    """Shrink so the longest side is at most ``longest``. Never stretches or upscales."""
    width, height = img.size
    if width < 1 or height < 1:
        raise StudioExportError("Could not read this photo.")
    if max(width, height) <= longest:
        return img
    if width >= height:
        new_w = longest
        new_h = max(1, int(round(height * longest / width)))
    else:
        new_h = longest
        new_w = max(1, int(round(width * longest / height)))
    return img.resize((new_w, new_h), _lanczos())


def _cover_crop(img, target_w: int, target_h: int):
    """Scale until the frame is covered, then crop the center. No stretching."""
    width, height = img.size
    if width < 1 or height < 1:
        raise StudioExportError("Could not read this photo.")
    scale = max(target_w / width, target_h / height)
    new_w = max(target_w, int(round(width * scale)))
    new_h = max(target_h, int(round(height * scale)))
    resized = img.resize((new_w, new_h), _lanczos())
    left = max(0, (new_w - target_w) // 2)
    top = max(0, (new_h - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _lanczos():
    from PIL import Image

    return Image.Resampling.LANCZOS


def _save_jpeg(img, dest: Path, quality: int) -> None:
    try:
        img.save(dest, format="JPEG", quality=int(quality), optimize=True)
    except OSError as exc:
        raise StudioExportError("Could not read this photo.") from exc


def _save_image(img, dest: Path, fmt: str, **kwargs: object) -> None:
    try:
        img.save(dest, format=fmt, **kwargs)
    except OSError as exc:
        raise StudioExportError("Could not read this photo.") from exc
