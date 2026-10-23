"""Per-clip Studio zoom and pan (Issue #86).

The framing lives in ``studio_clips.effect_settings`` under ``frame``. It is a
start and an end zoom plus a focal point in the source picture. Equal values
are a static crop. Different values move smoothly across the trimmed clip.
Zoom 1.0 keeps the existing fit and letterbox. Source files are never modified.

The crop runs after grade and after scale/pad, and before fades. Overlays and
privacy masks composite after this crop so they stay on the output frame
instead of riding the zoom.

Video filter time follows the source timestamp because ``-ss`` stays an output
option. Photo time starts at 0.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Mapping

ZOOM_MIN = 1.0
ZOOM_MAX = 3.0
ZOOM_STEP = 0.05


@dataclass(frozen=True)
class FrameTransform:
    """Zoom and focal point at the start and end of one Story clip."""

    zoom_start: float = 1.0
    zoom_end: float = 1.0
    x_start: float = 0.5
    y_start: float = 0.5
    x_end: float = 0.5
    y_end: float = 0.5

    @property
    def is_neutral(self) -> bool:
        """Zoom 1 shows the fitted picture. Pan has no room yet."""
        return (
            self.zoom_start <= ZOOM_MIN + 0.0001 and self.zoom_end <= ZOOM_MIN + 0.0001
        )

    @property
    def is_animated(self) -> bool:
        if self.is_neutral:
            return False
        return (
            abs(self.zoom_start - self.zoom_end) > 0.001
            or abs(self.x_start - self.x_end) > 0.001
            or abs(self.y_start - self.y_end) > 0.001
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "zoom_start": self.zoom_start,
            "zoom_end": self.zoom_end,
            "x_start": self.x_start,
            "y_start": self.y_start,
            "x_end": self.x_end,
            "y_end": self.y_end,
        }


def frame_preview_model() -> dict[str, float]:
    """Numeric ranges the Studio page passes to the preview script."""
    return {
        "zoomMin": ZOOM_MIN,
        "zoomMax": ZOOM_MAX,
        "zoomStep": ZOOM_STEP,
    }


def _finite(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{key} must be a number")
    return number


def _zoom(value: object, key: str) -> float:
    number = _finite(value, key)
    if number < ZOOM_MIN or number > ZOOM_MAX:
        raise ValueError("zoom must be from 1 to 3")
    return round(number, 2)


def _focal(value: object, key: str) -> float:
    number = _finite(value, key)
    clamped = min(1.0, max(0.0, number))
    return round(clamped, 4)


def _read_zoom(value: object) -> float:
    try:
        return _zoom(value, "zoom")
    except ValueError:
        return 1.0


def _read_focal(value: object, default: float) -> float:
    try:
        return _focal(value, "focus")
    except ValueError:
        return default


def frame_from_effect_settings(raw: str | None) -> FrameTransform:
    """Missing or invalid JSON is the fitted picture."""
    if raw is None or not str(raw).strip():
        return FrameTransform()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return FrameTransform()
    if not isinstance(data, dict):
        return FrameTransform()
    frame = data.get("frame", {})
    if not isinstance(frame, dict):
        return FrameTransform()
    return FrameTransform(
        zoom_start=_read_zoom(frame.get("zoom_start", 1)),
        zoom_end=_read_zoom(frame.get("zoom_end", 1)),
        x_start=_read_focal(frame.get("x_start", 0.5), 0.5),
        y_start=_read_focal(frame.get("y_start", 0.5), 0.5),
        x_end=_read_focal(frame.get("x_end", 0.5), 0.5),
        y_end=_read_focal(frame.get("y_end", 0.5), 0.5),
    )


def parse_frame_payload(payload: Mapping[str, object]) -> FrameTransform:
    """Replace the clip framing. Bad numbers raise. Focal points are clamped."""
    frame = payload.get("frame", payload)
    if not isinstance(frame, dict):
        raise ValueError("JSON body must include frame")
    if "zoom_start" not in frame and "zoom" not in frame:
        raise ValueError("JSON body must include frame")
    zoom_start = _zoom(frame.get("zoom_start", frame.get("zoom", 1)), "zoom_start")
    zoom_end = _zoom(frame.get("zoom_end", zoom_start), "zoom_end")
    x_start = _focal(frame.get("x_start", frame.get("x", 0.5)), "x_start")
    y_start = _focal(frame.get("y_start", frame.get("y", 0.5)), "y_start")
    x_end = _focal(frame.get("x_end", x_start), "x_end")
    y_end = _focal(frame.get("y_end", y_start), "y_end")
    return FrameTransform(
        zoom_start=zoom_start,
        zoom_end=zoom_end,
        x_start=x_start,
        y_start=y_start,
        x_end=x_end,
        y_end=y_end,
    )


def dump_frame(existing: str | None, frame: FrameTransform) -> str:
    """Write the frame object and keep unrelated effect_settings keys."""
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data["frame"] = frame.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def content_rect(
    frame_width: int,
    frame_height: int,
    source_width: int,
    source_height: int,
) -> tuple[int, int, int, int]:
    """Return x, y, width, height of the fitted picture inside the frame."""
    frame_w = max(1, int(frame_width))
    frame_h = max(1, int(frame_height))
    src_w = int(source_width)
    src_h = int(source_height)
    if src_w <= 0 or src_h <= 0:
        return 0, 0, frame_w, frame_h
    scale = min(frame_w / src_w, frame_h / src_h)
    content_w = max(1, min(frame_w, int(round(src_w * scale))))
    content_h = max(1, min(frame_h, int(round(src_h * scale))))
    origin_x = (frame_w - content_w) // 2
    origin_y = (frame_h - content_h) // 2
    return origin_x, origin_y, content_w, content_h


def sample_frame(frame: FrameTransform, progress: float) -> tuple[float, float, float]:
    """Return zoom, focal x, focal y at a 0..1 position in the clip."""
    span = min(1.0, max(0.0, float(progress)))
    zoom = frame.zoom_start + (frame.zoom_end - frame.zoom_start) * span
    focal_x = frame.x_start + (frame.x_end - frame.x_start) * span
    focal_y = frame.y_start + (frame.y_end - frame.y_start) * span
    return zoom, focal_x, focal_y


def window_for(
    zoom: float,
    focal_x: float,
    focal_y: float,
    *,
    frame_width: int,
    frame_height: int,
    source_width: int,
    source_height: int,
) -> tuple[int, int, int, int]:
    """Crop window inside the fitted picture. Letterbox pixels stay outside it."""
    frame_w = max(1, int(frame_width))
    frame_h = max(1, int(frame_height))
    zoom_value = min(ZOOM_MAX, max(ZOOM_MIN, float(zoom)))
    fx = min(1.0, max(0.0, float(focal_x)))
    fy = min(1.0, max(0.0, float(focal_y)))
    origin_x, origin_y, content_w, content_h = content_rect(
        frame_w, frame_h, source_width, source_height
    )
    view_w = max(1, min(content_w, int(round(content_w / zoom_value))))
    view_h = max(1, min(content_h, int(round(content_h / zoom_value))))
    center_x = origin_x + fx * content_w
    center_y = origin_y + fy * content_h
    left = int(round(center_x - view_w / 2.0))
    top = int(round(center_y - view_h / 2.0))
    left = max(origin_x, min(origin_x + content_w - view_w, left))
    top = max(origin_y, min(origin_y + content_h - view_h, top))
    return left, top, view_w, view_h


def _progress_expr(origin_s: float, duration_s: float) -> str:
    duration = max(0.001, float(duration_s))
    return f"min(1\\,max(0\\,(time-{origin_s:.4f})/{duration:.4f}))"


def _lerp_expr(start: float, end: float, progress: str) -> str:
    if abs(start - end) <= 0.0005:
        return f"{start:.4f}"
    delta = end - start
    return f"({start:.4f}+({delta:.4f})*({progress}))"


def ffmpeg_frame_prefix(
    frame: FrameTransform,
    *,
    source_width: int,
    source_height: int,
    kind: str,
    source_start_s: float,
    duration_s: float,
) -> str:
    """Animated zoompan before the fit, or an empty string.

    ``zoompan`` keeps the source aspect. The existing scale/pad then
    letterboxes that picture. Only formatted numbers are interpolated.
    Video progress uses ``time`` minus the trim start because ``-ss`` is an
    output option. A static crop uses :func:`ffmpeg_frame_suffix` instead.
    """
    if not frame.is_animated or kind not in {"photo", "video"}:
        return ""
    source_w = int(source_width)
    source_h = int(source_height)
    if source_w <= 0 or source_h <= 0:
        return ""
    origin = max(0.0, float(source_start_s)) if kind == "video" else 0.0
    progress = _progress_expr(origin, duration_s)
    zoom = _lerp_expr(frame.zoom_start, frame.zoom_end, progress)
    focal_x = _lerp_expr(frame.x_start, frame.x_end, progress)
    focal_y = _lerp_expr(frame.y_start, frame.y_end, progress)
    x_expr = f"max(0\\,min(iw-iw/zoom\\,({focal_x})*iw-iw/(zoom*2)))"
    y_expr = f"max(0\\,min(ih-ih/zoom\\,({focal_y})*ih-ih/(zoom*2)))"
    return (
        f"zoompan=z='{zoom}':x='{x_expr}':y='{y_expr}':"
        f"d=1:s={source_w}x{source_h}:fps=30"
    )


def ffmpeg_frame_suffix(
    frame: FrameTransform,
    *,
    frame_width: int,
    frame_height: int,
    source_width: int,
    source_height: int,
    kind: str,
    source_start_s: float,
    duration_s: float,
) -> str:
    """Crop and scale after the fit chain, or an empty string at zoom 1.

    Only formatted numbers are interpolated. A neutral clip adds nothing.
    The crop stays inside the fitted picture, then that window is fitted again
    so the existing letterbox is preserved. Motion uses zoompan instead, so
    this returns an empty string when the clip is animated.
    """
    if frame.is_neutral or frame.is_animated or kind not in {"photo", "video"}:
        return ""
    frame_w = max(1, int(frame_width))
    frame_h = max(1, int(frame_height))
    _, _, content_w, content_h = content_rect(
        frame_w, frame_h, source_width, source_height
    )
    tail = (
        f"scale={frame_w}:{frame_h}:force_original_aspect_ratio=decrease,"
        f"pad={frame_w}:{frame_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
    )
    zoom, focal_x, focal_y = sample_frame(frame, 0.0)
    left, top, view_w, view_h = window_for(
        zoom,
        focal_x,
        focal_y,
        frame_width=frame_w,
        frame_height=frame_h,
        source_width=source_width,
        source_height=source_height,
    )
    if view_w >= content_w and view_h >= content_h:
        return ""
    return f"format=yuv444p,crop={view_w}:{view_h}:{left}:{top},{tail}"
