"""Studio pause/scrub stills that reuse the export grade+LUT filter builders.

When a clip has a non-neutral color look, the WebView2 preview cannot apply
``.cube`` files in CSS. This module renders one JPEG via FFmpeg using the same
``ffmpeg_grade_chain`` and ``ffmpeg_lut_chain`` builders as MP4 export
(ADR 0028). Playback may still approximate without the LUT; pause and scrub
are the honesty gate. Source media is never modified.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_below_normal_kwargs
from orga_drone.studio_color_wheels import ColorWheels, ffmpeg_color_wheels_chain
from orga_drone.studio_hsl import HslAdjust, ffmpeg_hsl_chain
from orga_drone.studio_image import ImageAdjust, ffmpeg_grade_chain
from orga_drone.studio_lut import ColorLook, LutMissingError, ffmpeg_lut_chain, require_lut_asset
from orga_drone.studio_grade_model import read_grade
from orga_drone.studio_managed_apply import (
    apply_managed_grade_image,
    ffmpeg_managed_grade_chain,
    grade_needs_cpu_materialize,
    managed_grade_digest,
)

logger = logging.getLogger(__name__)

PREVIEW_STILLS_DIR = "preview-stills"
PREVIEW_MAX_EDGE = 1080
PREVIEW_QUANTIZE_S = 0.1
PREVIEW_JPEG_Q = 3
PREVIEW_CACHE_MAX_BYTES = 400 * 1024 * 1024
PREVIEW_FFMPEG_TIMEOUT_S = 45.0
PREVIEW_COLD_LATENCY_WARN_S = 1.0
JPEG_COLOR_CHAIN = (
    # RGB is an explicit boundary: direct YUV→YUV matrix conversion differs
    # between bundled FFmpeg builds. Decode the exported interpretation first.
    "scale=in_color_matrix=bt709:in_range=tv,format=rgb24,"
    "scale=out_color_matrix=bt601:out_range=pc,"
    "format=yuvj420p,setparams=colorspace=bt470bg:range=pc"
)

_lock = threading.Lock()
_inflight: dict[str, threading.Event] = {}


@dataclass(frozen=True)
class PreviewFrameRequest:
    """Inputs for one graded+LUT still."""

    media_path: Path
    kind: str
    source_time_s: float
    image: ImageAdjust
    look: ColorLook
    hsl: HslAdjust = HslAdjust()
    color_wheels: ColorWheels = ColorWheels()
    detail: bool = False
    max_edge: int = PREVIEW_MAX_EDGE
    saturation: float = 1.0
    # When set and managed-pointwise, preview uses the #359 baked grade LUT.
    effect_settings: str | None = None
    # Clip trim in-point and optional Story time for #358 animation clocks.
    source_in_s: float = 0.0
    source_out_s: float | None = None
    story_time_s: float | None = None
    transition_side: str = "single"
    repeat_pass: int = 0


def before_color_request(req: PreviewFrameRequest) -> PreviewFrameRequest:
    """Temporary comparison inputs; preserve only configured technical conversion.

    Reuse the existing effective-input cache identity. Never write clip settings
    or change the normal still/proxy/export builders. Clear managed
    ``effect_settings`` so before-compare does not keep the managed bake.
    """
    look = ColorLook(
        input_profile=req.look.input_profile,
        conversion_lut=req.look.conversion_lut if req.look.conversion_confirmed else "",
        conversion_confirmed=req.look.conversion_confirmed,
    )
    return replace(
        req,
        image=ImageAdjust(),
        look=look,
        hsl=HslAdjust(),
        color_wheels=ColorWheels(),
        saturation=1.0,
        detail=False,
        effect_settings=None,
    )


class PreviewFrameError(Exception):
    """Still generation failed for a recoverable reason."""

    def __init__(self, message: str, *, code: str = "preview_failed") -> None:
        super().__init__(message)
        self.code = code


def preview_stills_dir(data_dir: Path) -> Path:
    path = data_dir / PREVIEW_STILLS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def look_needs_preview_still(look: ColorLook) -> bool:
    """Keep an assigned look on the export color path, including 0% strength."""
    if look.conversion_lut and look.conversion_confirmed:
        return True
    if look.creative_lut:
        return True
    return False


def hsl_needs_preview_still(hsl: HslAdjust) -> bool:
    """A non-neutral HSL mixer needs the same rendered path as a LUT."""
    return not hsl.is_neutral


def color_wheels_need_preview_still(color_wheels: ColorWheels) -> bool:
    """Non-neutral colour wheels need the same rendered path as a LUT."""
    return not color_wheels.is_neutral


def color_needs_preview_still(
    look: ColorLook,
    hsl: HslAdjust,
    color_wheels: ColorWheels | None = None,
) -> bool:
    wheels = color_wheels if color_wheels is not None else ColorWheels()
    return (
        look_needs_preview_still(look)
        or hsl_needs_preview_still(hsl)
        or color_wheels_need_preview_still(wheels)
    )


def _apply_spatial_managed_jpeg(
    path: Path,
    effect_settings: str | None,
    *,
    source_time_s: float = 0.0,
    source_in_s: float = 0.0,
    source_out_s: float | None = None,
    story_time_s: float | None = None,
    transition_side: str = "single",
    repeat_pass: int = 0,
) -> None:
    """CPU-apply a spatial/animated managed grade onto a decoded preview JPEG."""
    from PIL import Image

    from orga_drone.studio_grade_animation import (
        grade_has_animation,
        grade_uses_story_local_animation,
        materialize_grade_at,
        render_context_for_source_sample,
    )
    from orga_drone.studio_grade_contract import GradeError

    model = read_grade(effect_settings)
    if model.grade is None:
        return
    grade = model.grade
    if grade_has_animation(grade):
        if grade_uses_story_local_animation(grade) and story_time_s is None:
            raise PreviewFrameError(
                "Story-local grade animation needs an explicit Story time",
                code="unsupported",
            )
        try:
            grade = materialize_grade_at(
                grade,
                render_context_for_source_sample(
                    source_id="preview",
                    source_pts_s=float(source_time_s),
                    source_in_s=float(source_in_s),
                    source_out_s=source_out_s,
                    story_time_s=story_time_s,
                    transition_side=transition_side,
                    repeat_pass=repeat_pass,
                ),
            )
        except GradeError as exc:
            raise PreviewFrameError(str(exc), code="unsupported") from exc
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        raw = list(rgb.getdata())
        rows = [
            [
                (raw[y * width + x][0] / 255.0, raw[y * width + x][1] / 255.0, raw[y * width + x][2] / 255.0)
                for x in range(width)
            ]
            for y in range(height)
        ]
        graded = apply_managed_grade_image(rows, grade, lattice_domain="srgb")
        out = Image.new("RGB", (width, height))
        out.putdata(
            [
                (
                    int(min(255, max(0, round(sample[0] * 255)))),
                    int(min(255, max(0, round(sample[1] * 255)))),
                    int(min(255, max(0, round(sample[2] * 255)))),
                )
                for row in graded
                for sample in row
            ]
        )
        out.save(path, format="JPEG", quality=92, optimize=True)


def quantize_preview_time(t_s: float, *, step: float = PREVIEW_QUANTIZE_S) -> float:
    if not isinstance(t_s, (int, float)) or t_s != t_s:  # NaN
        return 0.0
    value = max(0.0, float(t_s))
    if step <= 0:
        return value
    return round(value / step) * step


def preview_filter_chain(
    image: ImageAdjust,
    look: ColorLook,
    *,
    data_dir: Path,
    work_dir: Path,
    max_edge: int = PREVIEW_MAX_EDGE,
    even_dimensions: bool = False,
    saturation: float = 1.0,
    hsl: HslAdjust | None = None,
    color_wheels: ColorWheels | None = None,
    effect_settings: str | None = None,
) -> str:
    """Same grade→LUT→HSL→wheels order as export; scale for preview."""
    parts: list[str] = []
    managed = ffmpeg_managed_grade_chain(
        effect_settings,
        work_dir=work_dir / "managed-grades",
        data_dir=data_dir,
    )
    if managed:
        parts.append(managed)
    else:
        grade = ffmpeg_grade_chain(image)
        if grade:
            parts.append(grade)
        if not look.is_neutral:
            lut = ffmpeg_lut_chain(look, data_dir=data_dir, work_dir=work_dir)
            if lut:
                parts.append(lut)
        if hsl is not None and not hsl.is_neutral:
            parts.append(ffmpeg_hsl_chain(hsl, data_dir=data_dir))
        if color_wheels is not None and not color_wheels.is_neutral:
            parts.append(ffmpeg_color_wheels_chain(color_wheels, data_dir=data_dir))
    if saturation != 1.0:
        parts.append(f"eq=saturation={max(0.0, min(1.0, saturation)):.6f}")
    edge = max(64, min(2160, int(max_edge)))
    # Same scale pattern as export framing: no filter quotes (Windows argv-safe).
    # FFmpeg 7.1 can crash encoding odd-height JPEG inputs on the photo/no-LUT
    # path. Round photos inside this existing scale, leaving video unchanged.
    divisible = "force_divisible_by=2:" if even_dimensions else ""
    parts.append(
        f"scale={edge}:{edge}:force_original_aspect_ratio=decrease:{divisible}"
        "out_color_matrix=bt709:out_range=tv,"
        # Match export's limited-range BT.709 output before converting to the
        # full-range JPEG/BT.601 representation decoded by the browser.
        "format=yuv420p,"
        "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
    )
    parts.append(JPEG_COLOR_CHAIN)
    return ",".join(parts)


def cache_key_for(
    req: PreviewFrameRequest,
    *,
    media_mtime_ns: int,
    media_size: int,
    data_dir: Path | None = None,
) -> str:
    payload = {
        "path": str(req.media_path.resolve()),
        "mtime_ns": media_mtime_ns,
        "size": media_size,
        "kind": req.kind,
        "t": quantize_preview_time(req.source_time_s),
        # #358 animation clocks: same absolute PTS can sample different
        # source-local / Story values after trim or Story placement changes.
        "source_in": round(float(req.source_in_s), 4),
        "source_out": (
            None
            if req.source_out_s is None
            else round(float(req.source_out_s), 4)
        ),
        "story_t": (
            None
            if req.story_time_s is None
            else quantize_preview_time(float(req.story_time_s))
        ),
        "transition_side": str(req.transition_side or "single"),
        "repeat_pass": int(req.repeat_pass or 0),
        "image": req.image.as_dict(),
        "look": req.look.as_dict(),
        "hsl": req.hsl.as_dict(),
        "color_wheels": req.color_wheels.as_dict(),
        "detail": bool(req.detail),
        "edge": int(req.max_edge),
        "saturation": req.saturation,
        "managed": managed_grade_digest(req.effect_settings, data_dir=data_dir),
        "v": 9,
    }
    if req.kind == "photo":
        payload["photo_even_dimensions"] = True
        payload["photo_export_source"] = 1
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evict_if_needed(cache_dir: Path, *, max_bytes: int = PREVIEW_CACHE_MAX_BYTES) -> None:
    files = [p for p in cache_dir.glob("*.jpg") if p.is_file()]
    total = 0
    stamped: list[tuple[float, int, Path]] = []
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        total += st.st_size
        stamped.append((st.st_mtime, st.st_size, path))
    if total <= max_bytes:
        return
    stamped.sort(key=lambda item: item[0])
    for _mtime, size, path in stamped:
        if total <= max_bytes:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            continue


def render_preview_frame(
    req: PreviewFrameRequest,
    *,
    data_dir: Path,
    cache_dir: Path | None = None,
) -> Path:
    """Return a JPEG path (cached). Raises PreviewFrameError / LutMissingError."""
    if req.kind not in {"photo", "video"}:
        raise PreviewFrameError("Preview stills are only for photos and videos.", code="unsupported")
    media = req.media_path
    if not media.is_file():
        raise PreviewFrameError("This media file is missing.", code="media_missing")
    try:
        st = media.stat()
    except OSError as exc:
        raise PreviewFrameError("Could not read this media file.", code="media_missing") from exc

    folder = cache_dir if cache_dir is not None else preview_stills_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    # A cached JPEG must not conceal a LUT removed since it was rendered.
    if req.look.conversion_lut and req.look.conversion_confirmed:
        require_lut_asset(data_dir, req.look.conversion_lut)
    if req.look.creative_lut and req.look.creative_strength > 0:
        require_lut_asset(data_dir, req.look.creative_lut)
    key = cache_key_for(
        req,
        media_mtime_ns=st.st_mtime_ns,
        media_size=st.st_size,
        data_dir=data_dir,
    )
    dest = folder / f"{key}.jpg"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    with _lock:
        waiter = _inflight.get(key)
        if waiter is None:
            waiter = threading.Event()
            _inflight[key] = waiter
            owner = True
        else:
            owner = False

    if not owner:
        waiter.wait(timeout=PREVIEW_FFMPEG_TIMEOUT_S + 5.0)
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        raise PreviewFrameError("Could not build the preview still.", code="preview_failed")

    work: Path | None = None
    try:
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise PreviewFrameError(
                "Install ffmpeg or: pip install imageio-ffmpeg",
                code="ffmpeg_missing",
            )
        work = folder / "work" / key[:16]
        work.mkdir(parents=True, exist_ok=True)
        if req.kind == "photo":
            # Export grades a normalized JPEG rather than the original photo.
            # Reuse that exact read-only preparation so PNG/JPEG input color
            # conversion agrees before the shared grade/LUT filters run.
            from orga_drone.export.studio_encoder import _materialize_photo_still

            try:
                media = _materialize_photo_still(media, work / "source.jpg")
            except Exception as exc:  # noqa: BLE001 — surface as preview error
                raise PreviewFrameError("Could not prepare the photo preview.", code="preview_failed") from exc
        try:
            vf = preview_filter_chain(
                req.image,
                req.look,
                data_dir=data_dir,
                work_dir=work,
                max_edge=req.max_edge,
                even_dimensions=req.kind == "photo",
                saturation=req.saturation,
                hsl=req.hsl,
                color_wheels=req.color_wheels,
                effect_settings=req.effect_settings,
            )
        except LutMissingError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as preview error
            raise PreviewFrameError(str(exc) or "Invalid color look.", code="lut_invalid") from exc

        abs_t = max(0.0, float(req.source_time_s))
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        if req.kind == "video":
            cmd.extend(["-ss", f"{abs_t:.3f}"])
        cmd.extend(
            [
                "-i",
                str(media),
                "-frames:v",
                "1",
                "-vf",
                vf,
                "-q:v", str(PREVIEW_JPEG_Q), str(work / "frame.jpg"),
            ]
        )
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=PREVIEW_FFMPEG_TIMEOUT_S,
                **subprocess_below_normal_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise PreviewFrameError(
                "Building the preview still took too long.",
                code="preview_timeout",
            ) from exc
        except OSError as exc:
            raise PreviewFrameError(
                "Could not run ffmpeg for the preview still.",
                code="preview_failed",
            ) from exc
        elapsed = time.perf_counter() - started
        if elapsed >= PREVIEW_COLD_LATENCY_WARN_S:
            logger.warning(
                "preview still cold latency %.2fs (budget %.1fs) for %s",
                elapsed,
                PREVIEW_COLD_LATENCY_WARN_S,
                media.name,
            )
        completed = work / "frame.jpg"
        if proc.returncode != 0 or not completed.is_file() or completed.stat().st_size <= 0:
            detail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise PreviewFrameError(
                detail or "Could not build the preview still.",
                code="preview_failed",
            )
        if req.effect_settings and grade_needs_cpu_materialize(req.effect_settings):
            _apply_spatial_managed_jpeg(
                completed,
                req.effect_settings,
                source_time_s=float(req.source_time_s),
                source_in_s=float(req.source_in_s),
                source_out_s=req.source_out_s,
                story_time_s=req.story_time_s,
                transition_side=str(req.transition_side or "single"),
                repeat_pass=int(req.repeat_pass or 0),
            )
        completed.replace(dest)
        _evict_if_needed(folder)
        return dest
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
        with _lock:
            event = _inflight.pop(key, None)
            if event is not None:
                event.set()
