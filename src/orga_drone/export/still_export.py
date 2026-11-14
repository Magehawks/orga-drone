"""Local still-image export for one library photo.

Best quality copies a readable still (JPEG, PNG, and similar) when that is
safe. Share presets write a new JPEG. Custom writes a resized still inside the
source bounds. Nothing is uploaded.

A non-neutral grade uses the Studio ffmpeg filter chain
(``ffmpeg_grade_chain``) and then the same preset. Neutral leaves that chain
out, so a best-quality copy can stay the original bytes when the file has no
GPS/location EXIF. The library file is never written.

Processing after decode is 8-bit RGB. Re-encodes do not claim EXIF or ICC
preservation. GPS/location tags are never left in an export.
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
PRESET_CUSTOM = "custom"
SHARE_PRESETS: tuple[str, ...] = (
    PRESET_BEST,
    PRESET_WHATSAPP,
    PRESET_INSTAGRAM,
    PRESET_TIKTOK,
    PRESET_CUSTOM,
)
VIDEO_SHARE_PRESETS: tuple[str, ...] = (
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
CUSTOM_JPEG_QUALITY_DEFAULT = 95
CUSTOM_JPEG_QUALITY_MIN = 60
CUSTOM_JPEG_QUALITY_MAX = 100

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
    jpeg_quality: int | None = None
    geometry: str | None = None


@dataclass(frozen=True)
class CustomStillOptions:
    """Validated custom still geometry and JPEG quality."""

    width: int
    height: int
    jpeg_quality: int
    lock_aspect: bool


def normalize_share_preset(preset: str, *, allow_custom: bool = True) -> str:
    key = str(preset or "").strip().lower()
    allowed = SHARE_PRESETS if allow_custom else VIDEO_SHARE_PRESETS
    if key not in allowed:
        if key == PRESET_CUSTOM and not allow_custom:
            raise StudioExportError("Custom export is only for photos.")
        raise StudioExportError("Choose a share preset.")
    return key


def normalize_still_format(value: object) -> str | None:
    """``jpeg``, ``png``, or None when the caller left the format alone.

    PNG is a re-encode of the still. Share presets stay JPEG.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise StudioExportError("Choose JPEG or PNG.")
    key = value.strip().lower()
    if not key:
        return None
    if key in {"jpg", "jpeg"}:
        return "jpeg"
    if key == "png":
        return "png"
    raise StudioExportError("Choose JPEG or PNG.")


def normalize_jpeg_quality(value: object | None, *, default: int = CUSTOM_JPEG_QUALITY_DEFAULT) -> int:
    """Clamp a JPEG quality to the supported Custom range."""
    if value is None:
        return int(default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StudioExportError(
            f"JPEG quality must be from {CUSTOM_JPEG_QUALITY_MIN} to {CUSTOM_JPEG_QUALITY_MAX}."
        )
    number = float(value)
    if not number == number:  # NaN
        raise StudioExportError(
            f"JPEG quality must be from {CUSTOM_JPEG_QUALITY_MIN} to {CUSTOM_JPEG_QUALITY_MAX}."
        )
    quality = int(round(number))
    if quality < CUSTOM_JPEG_QUALITY_MIN or quality > CUSTOM_JPEG_QUALITY_MAX:
        raise StudioExportError(
            f"JPEG quality must be from {CUSTOM_JPEG_QUALITY_MIN} to {CUSTOM_JPEG_QUALITY_MAX}."
        )
    return quality


def resolve_custom_dimensions(
    source_w: int,
    source_h: int,
    *,
    width: object | None = None,
    height: object | None = None,
    lock_aspect: bool = True,
) -> tuple[int, int]:
    """Return export WxH inside the oriented source box. Never upscales."""
    src_w = int(source_w)
    src_h = int(source_h)
    if src_w < 1 or src_h < 1:
        raise StudioExportError("Could not read this photo.")

    def _parse_side(value: object | None, label: str) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StudioExportError(f"{label} must be a positive pixel size.")
        number = float(value)
        if not number == number or number <= 0:
            raise StudioExportError(f"{label} must be a positive pixel size.")
        return max(1, int(round(number)))

    req_w = _parse_side(width, "Width")
    req_h = _parse_side(height, "Height")
    if req_w is None and req_h is None:
        return src_w, src_h

    if lock_aspect:
        if req_w is not None and req_h is not None:
            scale = min(req_w / src_w, req_h / src_h, 1.0)
            out_w = max(1, int(round(src_w * scale)))
            out_h = max(1, int(round(src_h * scale)))
            return min(out_w, src_w), min(out_h, src_h)
        if req_w is not None:
            out_w = min(req_w, src_w)
            out_h = max(1, int(round(src_h * (out_w / src_w))))
            return out_w, min(out_h, src_h)
        assert req_h is not None
        out_h = min(req_h, src_h)
        out_w = max(1, int(round(src_w * (out_h / src_h))))
        return min(out_w, src_w), out_h

    out_w = min(req_w if req_w is not None else src_w, src_w)
    out_h = min(req_h if req_h is not None else src_h, src_h)
    return max(1, out_w), max(1, out_h)


def _is_graded(image: ImageAdjust | None) -> bool:
    return image is not None and not image.is_neutral


def _still_has_gps(img) -> bool:
    """True when the open still carries a GPS/location IFD."""
    try:
        from PIL.ExifTags import Base

        exif = img.getexif()
        if not exif:
            return False
        if exif.get(Base.GPSInfo):
            return True
        try:
            gps_ifd = exif.get_ifd(Base.GPSInfo)
        except Exception:
            gps_ifd = None
        return bool(gps_ifd)
    except Exception:
        return False


def _best_suffix(copy_suffix: str | None, *, graded: bool) -> tuple[str, bool]:
    """Return ``(suffix, copied)`` for best quality (ignores GPS; caller gates copy)."""
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
    still_format: str | None = None,
    width: object | None = None,
    height: object | None = None,
    lock_aspect: bool = True,
    jpeg_quality: object | None = None,
) -> PhotoPresetSpec:
    """Pixel size and suffix for one photo preset. Does not write a file."""
    key = normalize_share_preset(preset, allow_custom=True)
    graded = _is_graded(image)
    as_png = (
        key in {PRESET_BEST, PRESET_CUSTOM}
        and normalize_still_format(still_format) == "png"
    )
    img = _load_still(source)
    try:
        rgb = _oriented_rgb(img)
        src_w, src_h = rgb.size
        if key == PRESET_CUSTOM:
            out_w, out_h = resolve_custom_dimensions(
                src_w,
                src_h,
                width=width,
                height=height,
                lock_aspect=lock_aspect,
            )
            quality = normalize_jpeg_quality(jpeg_quality)
            suffix = ".png" if as_png else ".jpg"
            return PhotoPresetSpec(
                suffix=suffix,
                width=out_w,
                height=out_h,
                copied=False,
                jpeg_quality=None if as_png else quality,
                geometry="custom",
            )
        if key == PRESET_BEST and as_png:
            return PhotoPresetSpec(
                suffix=".png",
                width=src_w,
                height=src_h,
                copied=False,
                geometry="source",
            )
        if key == PRESET_BEST:
            copy_suffix = _copy_suffix(source, img.format or "")
            suffix, would_copy = _best_suffix(copy_suffix, graded=graded)
            can_copy = (
                would_copy
                and not graded
                and not as_png
                and copy_suffix is not None
                and not _still_has_gps(img)
            )
            if not can_copy and would_copy and _still_has_gps(img):
                # GPS-safe re-encode keeps the readable suffix when possible.
                if copy_suffix in _REENCODE_SUFFIXES:
                    suffix = copy_suffix
                else:
                    suffix = ".jpg"
            return PhotoPresetSpec(
                suffix=suffix,
                width=src_w,
                height=src_h,
                copied=can_copy,
                jpeg_quality=None if suffix == ".png" or can_copy else BEST_JPEG_QUALITY,
                geometry="source",
            )
        if key == PRESET_WHATSAPP:
            fitted = _fit_longest(rgb, WHATSAPP_LONGEST)
            width_out, height_out = fitted.size
            return PhotoPresetSpec(
                suffix=".jpg",
                width=width_out,
                height=height_out,
                copied=False,
                jpeg_quality=WHATSAPP_QUALITY,
                geometry="fit",
            )
        if key == PRESET_INSTAGRAM:
            width_out, height_out = INSTAGRAM_SIZE
            geometry = "cover_crop"
        else:
            width_out, height_out = TIKTOK_SIZE
            geometry = "cover_crop"
        return PhotoPresetSpec(
            suffix=".jpg",
            width=width_out,
            height=height_out,
            copied=False,
            jpeg_quality=SOCIAL_JPEG_QUALITY,
            geometry=geometry,
        )
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
    still_format: str | None = None,
    width: object | None = None,
    height: object | None = None,
    lock_aspect: bool = True,
    jpeg_quality: object | None = None,
) -> Path:
    """Write one photo preset and publish it without replacing an existing file."""
    if cancel_event is not None and cancel_event.is_set():
        raise ExportCancelled()
    key = normalize_share_preset(preset, allow_custom=True)
    if not source.is_file():
        raise StudioExportError("The source file is not available.")
    tmp_dir = Path(tempfile.mkdtemp(prefix="orga-drone-export-"))
    partial = tmp_dir / "still.bin"
    try:
        _write_preset(
            source,
            partial,
            key,
            image=image,
            cancel_event=cancel_event,
            still_format=still_format,
            width=width,
            height=height,
            lock_aspect=lock_aspect,
            jpeg_quality=jpeg_quality,
        )
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
    still_format: str | None = None,
    width: object | None = None,
    height: object | None = None,
    lock_aspect: bool = True,
    jpeg_quality: object | None = None,
) -> None:
    graded = _is_graded(image)
    as_png = (
        preset in {PRESET_BEST, PRESET_CUSTOM}
        and normalize_still_format(still_format) == "png"
    )
    img = _load_still(source)
    try:
        copy_suffix = _copy_suffix(source, img.format or "")
        has_gps = _still_has_gps(img)
        if (
            preset == PRESET_BEST
            and not graded
            and not as_png
            and copy_suffix is not None
            and not has_gps
        ):
            shutil.copyfile(source, dest)
            return

        rgb = _oriented_rgb(img)
        if graded:
            rgb = _grade_rgb(rgb, image, cancel_event=cancel_event)

        if preset == PRESET_CUSTOM:
            out_w, out_h = resolve_custom_dimensions(
                rgb.size[0],
                rgb.size[1],
                width=width,
                height=height,
                lock_aspect=lock_aspect,
            )
            if (out_w, out_h) != rgb.size:
                rgb = rgb.resize((out_w, out_h), _lanczos())
            if as_png:
                _save_image(rgb, dest, "PNG")
            else:
                _save_jpeg(rgb, dest, normalize_jpeg_quality(jpeg_quality))
            return

        if as_png or preset == PRESET_BEST:
            if as_png:
                _save_image(rgb, dest, "PNG")
                return
            # Graded or GPS-stripped best path.
            _save_best(rgb, dest, copy_suffix if graded or has_gps else None)
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
        # Explicitly omit exif= so GPS/location never rides along on re-encode.
        img.save(dest, format="JPEG", quality=int(quality), optimize=True)
    except OSError as exc:
        raise StudioExportError("Could not read this photo.") from exc


def _save_image(img, dest: Path, fmt: str, **kwargs: object) -> None:
    try:
        img.save(dest, format=fmt, **kwargs)
    except OSError as exc:
        raise StudioExportError("Could not read this photo.") from exc
