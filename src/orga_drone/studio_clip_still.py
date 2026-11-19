"""Full-resolution still export for one Studio photo clip (#499).

Applies the clip's color grade in source space (including managed spatial
selections), then writes JPG/PNG through the existing still preset writer.
Story framing, overlays, and privacy masks are intentionally omitted: this
path publishes the graded photograph, not a Story frame composite.

Source library files are never modified.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from orga_drone.config import settings
from orga_drone.db import Database
from orga_drone.export.still_export import (
    BEST_JPEG_QUALITY,
    PRESET_BEST,
    export_photo_file,
    inspect_photo_preset,
    normalize_share_preset,
    normalize_still_format,
)
from orga_drone.export.studio_encoder import ExportCancelled, StudioExportError
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.media_files import resolve_media_file
from orga_drone.studio_color_wheels import color_wheels_from_effect_settings
from orga_drone.studio_hsl import hsl_adjust_from_effect_settings
from orga_drone.studio_image import ImageAdjust, image_adjust_from_effect_settings
from orga_drone.studio_lut import ColorLook, color_look_from_effect_settings
from orga_drone.studio_managed_apply import (
    ManagedApplyError,
    grade_is_managed_pointwise,
    grade_is_managed_sdr,
    grade_needs_cpu_materialize,
    managed_grade_digest,
    require_managed_executable,
)
from orga_drone.studio_preview_frame import color_filter_chain

ProgressFn = Callable[[float], None]


def _project_id_for_clip(db: Database, studio_item_id: int) -> int | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT project_id FROM studio_clips WHERE id = ?",
            (studio_item_id,),
        ).fetchone()
    if row is None:
        return None
    return int(row["project_id"])


def _require_photo_clip(db: Database, studio_item_id: int):
    project_id = _project_id_for_clip(db, studio_item_id)
    if project_id is None:
        raise StudioExportError("Studio item not found.")
    clip = next(
        (item for item in db.list_studio_items(project_id) if item.id == studio_item_id),
        None,
    )
    if clip is None:
        raise StudioExportError("Studio item not found.")
    if str(clip.kind) != "photo":
        raise StudioExportError("Still export is only for photo clips.")
    if clip.source_media_id is None:
        raise StudioExportError("This photo clip has no library source.")
    media = db.get_media(int(clip.source_media_id))
    if media is None:
        raise StudioExportError("Media not found.")
    path = resolve_media_file(db, media)
    if path is None or not path.is_file():
        raise StudioExportError("The source file is not available.")
    return clip, media, path


def effect_settings_has_color(effect_settings: str | None) -> bool:
    """True when legacy or managed color would change the still."""
    if grade_is_managed_sdr(effect_settings):
        return True
    image = image_adjust_from_effect_settings(effect_settings)
    if not image.is_neutral:
        return True
    if not color_look_from_effect_settings(effect_settings).is_neutral:
        return True
    if not hsl_adjust_from_effect_settings(effect_settings).is_neutral:
        return True
    if not color_wheels_from_effect_settings(effect_settings).is_neutral:
        return True
    return False


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ExportCancelled()


def _load_oriented_rgb(source: Path):
    from PIL import Image, ImageOps

    from orga_drone.parse import ensure_heif_support

    ensure_heif_support()
    try:
        img = Image.open(source)
        img.load()
    except OSError as exc:
        raise StudioExportError("Could not read this photo.") from exc
    try:
        oriented = ImageOps.exif_transpose(img) or img
        return oriented.convert("RGB")
    finally:
        img.close()


def _ffmpeg_grade_still(
    source: Path,
    dest: Path,
    effect_settings: str | None,
    *,
    cancel_event: threading.Event | None,
) -> Path:
    """Apply pointwise managed bake or legacy color stack at full resolution."""
    from PIL import Image

    image = image_adjust_from_effect_settings(effect_settings)
    look = color_look_from_effect_settings(effect_settings)
    hsl = hsl_adjust_from_effect_settings(effect_settings)
    wheels = color_wheels_from_effect_settings(effect_settings)
    managed = effect_settings if grade_is_managed_sdr(effect_settings) else None
    if managed is not None and not grade_is_managed_pointwise(effect_settings):
        raise StudioExportError(
            "This managed grade needs spatial materialization before still export."
        )

    work_dir = settings.data_dir / "export-work" / "studio-clip-still"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        chain = color_filter_chain(
            image if managed is None else ImageAdjust(),
            look if managed is None else ColorLook(),
            data_dir=settings.data_dir,
            work_dir=work_dir,
            hsl=hsl if managed is None else None,
            color_wheels=wheels if managed is None else None,
            effect_settings=managed,
        )
    except Exception as exc:  # noqa: BLE001 — surface as export error
        raise StudioExportError(
            str(exc) or "Could not build the photo color filters."
        ) from exc

    rgb = _load_oriented_rgb(source)
    if not chain:
        rgb.save(dest, format="PNG")
        return dest
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise StudioExportError("Install ffmpeg or: pip install imageio-ffmpeg")
    tmp_dir = Path(tempfile.mkdtemp(prefix="orga-drone-clip-still-"))
    src = tmp_dir / "in.png"
    out = tmp_dir / "out.png"
    try:
        rgb.save(src, format="PNG")
        _check_cancel(cancel_event)
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
            str(out),
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **subprocess_no_window_kwargs(),
        )
        while proc.poll() is None:
            _check_cancel(cancel_event)
            try:
                proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode != 0 or not out.is_file():
            raise StudioExportError("Could not grade this photo.")
        graded = Image.open(out)
        try:
            graded.load()
            graded.convert("RGB").save(dest, format="PNG")
        finally:
            graded.close()
        return dest
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def materialize_studio_photo_grade_source(
    source: Path,
    effect_settings: str | None,
    *,
    data_dir: Path | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressFn | None = None,
) -> Path:
    """Return a full-resolution still path with color applied (or ``source``).

    Spatial managed grades reuse ``materialize_spatial_managed_media``.
    Pointwise managed and legacy grades use the shared FFmpeg color chain.
    """
    _check_cancel(cancel_event)
    if not effect_settings_has_color(effect_settings):
        if on_progress is not None:
            on_progress(1.0)
        return source

    base = (data_dir or settings.data_dir) / "export-work" / "studio-clip-still"
    base.mkdir(parents=True, exist_ok=True)

    if grade_is_managed_sdr(effect_settings):
        try:
            require_managed_executable(effect_settings)
        except ManagedApplyError as exc:
            raise StudioExportError(str(exc), code=exc.code.lower()) from exc

        if grade_needs_cpu_materialize(effect_settings):
            from orga_drone.studio_grade_model import read_grade
            from orga_drone.studio_managed_spatial_export import (
                materialize_spatial_managed_media,
            )

            digest = managed_grade_digest(effect_settings, data_dir=data_dir or settings.data_dir)
            model = read_grade(effect_settings)
            if digest is None or model.grade is None:
                raise StudioExportError("Managed grade is incomplete.")
            work = (data_dir or settings.data_dir) / "export-work" / "managed-grades"
            work.mkdir(parents=True, exist_ok=True)
            try:
                graded = materialize_spatial_managed_media(
                    source,
                    model.grade,
                    work,
                    kind="photo",
                    grade_digest=digest,
                )
            except ManagedApplyError as exc:
                raise StudioExportError(str(exc), code=exc.code.lower()) from exc
            if on_progress is not None:
                on_progress(1.0)
            return graded

        if not grade_is_managed_pointwise(effect_settings):
            raise StudioExportError(
                "This managed grade needs a creative LUT resolver before still export.",
                code="unsupported_grade",
            )

    digest = managed_grade_digest(
        effect_settings, data_dir=data_dir or settings.data_dir
    )
    if digest is None:
        digest = hashlib.sha256((effect_settings or "").encode("utf-8")).hexdigest()
    try:
        st = source.stat()
        source_token = f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        source_token = "missing"
    cache_key = hashlib.sha256(f"{digest}|{source_token}".encode("utf-8")).hexdigest()[:20]
    dest = base / f"graded_{cache_key}.png"
    if dest.is_file() and dest.stat().st_size > 0:
        if on_progress is not None:
            on_progress(1.0)
        return dest
    tmp = dest.with_suffix(".tmp.png")
    if tmp.is_file():
        tmp.unlink(missing_ok=True)
    _ffmpeg_grade_still(source, tmp, effect_settings, cancel_event=cancel_event)
    tmp.replace(dest)
    if on_progress is not None:
        on_progress(1.0)
    return dest


def inspect_studio_photo_clip_still(
    db: Database,
    studio_item_id: int,
    *,
    preset: str = PRESET_BEST,
    still_format: str | None = None,
) -> dict[str, object]:
    """Describe the still that would be written. Does not grade or write."""
    clip, _media, path = _require_photo_clip(db, studio_item_id)
    key = normalize_share_preset(preset, allow_custom=True)
    fmt = normalize_still_format(still_format) if key == PRESET_BEST else None
    # Inspect geometry against the source; grading does not change dimensions.
    spec = inspect_photo_preset(
        path,
        key,
        image=ImageAdjust(),
        still_format=fmt,
    )
    return {
        "ok": True,
        "studio_item_id": clip.id,
        "preset": key,
        "width": spec.width,
        "height": spec.height,
        "suffix": spec.suffix,
        "has_color": effect_settings_has_color(clip.effect_settings),
        "jpeg_quality": spec.jpeg_quality or BEST_JPEG_QUALITY,
    }


def export_studio_photo_clip_still(
    db: Database,
    studio_item_id: int,
    output_path: Path,
    *,
    preset: str = PRESET_BEST,
    still_format: str | None = "jpeg",
    overwrite: bool = False,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressFn | None = None,
) -> Path:
    """Grade one photo clip and publish a still via the shared preset writer."""
    from orga_drone.studio_export import _snapshot_export_destination

    _ = overwrite
    clip, _media, source = _require_photo_clip(db, studio_item_id)
    key = normalize_share_preset(preset, allow_custom=True)
    fmt = normalize_still_format(still_format) if key == PRESET_BEST else None
    if key == PRESET_BEST and fmt is None:
        fmt = "jpeg"

    def _progress(fraction: float) -> None:
        if on_progress is not None:
            on_progress(max(0.0, min(1.0, float(fraction))))

    _progress(0.05)
    graded = materialize_studio_photo_grade_source(
        source,
        clip.effect_settings,
        data_dir=settings.data_dir,
        cancel_event=cancel_event,
        on_progress=lambda f: _progress(0.05 + 0.7 * float(f)),
    )
    _check_cancel(cancel_event)

    # Graded media is already color-correct; avoid a second grade pass.
    spec = inspect_photo_preset(
        graded,
        key,
        image=ImageAdjust(),
        still_format=fmt,
    )
    dest, identities, protected = _snapshot_export_destination(
        db,
        Path(output_path),
        overwrite=False,
        suffix=spec.suffix,
    )
    _progress(0.8)
    result = export_photo_file(
        graded,
        dest,
        key,
        protected=protected,
        protected_identities=identities,
        cancel_event=cancel_event,
        image=ImageAdjust(),
        still_format=fmt,
    )
    # Source integrity: never write the library path.
    if Path(source).resolve() == Path(result).resolve():
        raise StudioExportError("Still export refused to overwrite the library file.")
    _progress(1.0)
    return result
