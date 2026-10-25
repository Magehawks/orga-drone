"""Per-clip Studio privacy masks (Issue #81).

A mask is a normalized region on one photo or video Story clip, plus a blur or
pixelate effect. The region is fractions of the fitted picture so a later slice
can add a time range without a new coordinate system. This slice covers the
whole clip. Source files are never modified.

Values live in ``studio_clips.effect_settings`` under ``masks``. The box is a
fraction of the visible picture after zoom and pan, so preview and export
cover the same pixels. Filter text contains only formatted numbers. Preview
approximates the export.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from orga_drone.studio_frame import FrameTransform, sample_frame, source_window

MAX_MASKS = 8
MIN_BOX = 0.04
STRENGTH_MIN = 1
STRENGTH_MAX = 100
DEFAULT_STRENGTH = 50
# Full strength as a fraction of the shorter fitted side.
BLUR_FRACTION = 0.05
PIXEL_FRACTION = 0.06
EFFECTS = ("blur", "pixelate")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class MaskRenderError(Exception):
    """A configured mask cannot be placed on the frame."""


@dataclass(frozen=True)
class Mask:
    """One rectangular privacy region on a single Story clip."""

    id: str
    effect: str
    strength: int
    x: float
    y: float
    w: float
    h: float

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "effect": self.effect,
            "strength": self.strength,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
        }


@dataclass(frozen=True)
class MaskWindow:
    """Pixel box of one mask inside the export frame."""

    effect: str
    x: int
    y: int
    w: int
    h: int
    radius: int
    block: int


def mask_preview_model() -> dict[str, object]:
    """Numeric ranges the Studio page passes to the preview script."""
    return {
        "maxMasks": MAX_MASKS,
        "minBox": MIN_BOX,
        "strengthMin": STRENGTH_MIN,
        "strengthMax": STRENGTH_MAX,
        "defaultStrength": DEFAULT_STRENGTH,
        "blurFraction": BLUR_FRACTION,
        "pixelFraction": PIXEL_FRACTION,
        "effects": list(EFFECTS),
    }


def _finite(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{key} must be a number")
    return number


def _strength(value: object) -> int:
    number = _finite(value, "strength")
    if number < STRENGTH_MIN or number > STRENGTH_MAX:
        raise ValueError("strength must be from 1 to 100")
    return int(round(number))


def _fraction(value: object, key: str) -> float:
    return round(_finite(value, key), 4)


def _clamp_box(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    width = min(1.0, max(MIN_BOX, w))
    height = min(1.0, max(MIN_BOX, h))
    left = min(1.0 - width, max(0.0, x))
    top = min(1.0 - height, max(0.0, y))
    return (round(left, 4), round(top, 4), round(width, 4), round(height, 4))


def _new_id(used: set[str]) -> str:
    from uuid import uuid4

    for _ in range(8):
        candidate = "m" + uuid4().hex[:10]
        if candidate not in used:
            return candidate
    raise ValueError("could not assign a mask id")


def _mask_from_mapping(raw: Mapping[str, object], used: set[str]) -> Mask:
    effect = raw.get("effect")
    if effect not in EFFECTS:
        raise ValueError("effect must be blur or pixelate")
    raw_id = raw.get("id")
    if isinstance(raw_id, str) and _ID_RE.fullmatch(raw_id) and raw_id not in used:
        mask_id = raw_id
    else:
        mask_id = _new_id(used)
    used.add(mask_id)
    left, top, width, height = _clamp_box(
        _fraction(raw.get("x", 0.2), "x"),
        _fraction(raw.get("y", 0.2), "y"),
        _fraction(raw.get("w", 0.28), "w"),
        _fraction(raw.get("h", 0.22), "h"),
    )
    return Mask(
        id=mask_id,
        effect=str(effect),
        strength=_strength(raw.get("strength", DEFAULT_STRENGTH)),
        x=left,
        y=top,
        w=width,
        h=height,
    )


def _stored_mask(raw: object, used: set[str]) -> Mask | None:
    if not isinstance(raw, dict):
        return None
    try:
        return _mask_from_mapping(raw, used)
    except ValueError:
        return None


def masks_from_effect_settings(raw: str | None) -> tuple[Mask, ...]:
    """Missing or invalid entries are dropped so older rows still open."""
    if raw is None or not str(raw).strip():
        return ()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(data, dict):
        return ()
    items = data.get("masks", [])
    if not isinstance(items, list):
        return ()
    used: set[str] = set()
    found: list[Mask] = []
    for item in items:
        mask = _stored_mask(item, used)
        if mask is None:
            continue
        found.append(mask)
        if len(found) >= MAX_MASKS:
            break
    return tuple(found)


def parse_masks_payload(payload: Mapping[str, object]) -> tuple[Mask, ...]:
    """Replace the clip mask list. Bad values raise. Positions are clamped."""
    if "masks" not in payload:
        raise ValueError("JSON body must include masks")
    items = payload.get("masks")
    if not isinstance(items, list):
        raise ValueError("masks must be a list")
    if len(items) > MAX_MASKS:
        raise ValueError(f"a clip can have at most {MAX_MASKS} privacy masks")
    used: set[str] = set()
    parsed: list[Mask] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each mask must be an object")
        parsed.append(_mask_from_mapping(item, used))
    return tuple(parsed)


def dump_masks(existing: str | None, masks: Sequence[Mask]) -> str:
    """Write masks and keep unrelated effect_settings keys, including image."""
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data["masks"] = [mask.as_dict() for mask in masks]
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


def _even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


def blur_radius_px(
    strength: int,
    content_w: int,
    content_h: int,
    box_w: int,
    box_h: int,
) -> int:
    span = max(1, min(int(content_w), int(content_h)))
    radius = int(round((int(strength) / 100.0) * span * BLUR_FRACTION))
    limit = max(1, min(int(box_w), int(box_h)) // 2 - 1)
    return max(1, min(max(1, radius), limit))


def pixel_block_px(
    strength: int,
    content_w: int,
    content_h: int,
    box_w: int,
    box_h: int,
) -> int:
    span = max(1, min(int(content_w), int(content_h)))
    block = int(round((int(strength) / 100.0) * span * PIXEL_FRACTION))
    limit = max(2, min(int(box_w), int(box_h)) // 2)
    return max(2, min(max(2, block), limit))


def mask_box_pixels(
    mask: Mask,
    rect: tuple[int, int, int, int],
    *,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    """Even pixel box. Raises when the region cannot cover at least 2×2."""
    origin_x, origin_y, content_w, content_h = rect
    width = max(2, int(round(mask.w * content_w)))
    height = max(2, int(round(mask.h * content_h)))
    left = origin_x + int(round(mask.x * content_w))
    top = origin_y + int(round(mask.y * content_h))
    frame_w = int(frame_width)
    frame_h = int(frame_height)
    if left < 0:
        width += left
        left = 0
    if top < 0:
        height += top
        top = 0
    if left + width > frame_w:
        width = frame_w - left
    if top + height > frame_h:
        height = frame_h - top
    left = _even(max(0, left))
    top = _even(max(0, top))
    width = _even(max(0, width))
    height = _even(max(0, height))
    if width < 2 or height < 2 or left + width > frame_w or top + height > frame_h:
        raise MaskRenderError("privacy mask is too small for this frame")
    return left, top, width, height


def visible_picture_rect(
    *,
    frame_width: int,
    frame_height: int,
    source_width: int,
    source_height: int,
    frame: FrameTransform | None = None,
) -> tuple[int, int, int, int]:
    """Picture the mask sits on in the export frame.

    Zoom and pan already crop that picture before the mask runs. The overlay
    therefore uses the full frame, the same space the preview window shows.
    """
    if frame is not None and not frame.is_neutral:
        return 0, 0, int(frame_width), int(frame_height)
    return content_rect(frame_width, frame_height, source_width, source_height)


def preview_source_rect(
    mask: Mask,
    *,
    source_width: int,
    source_height: int,
    frame: FrameTransform | None = None,
    progress: float = 0.0,
) -> tuple[float, float, float, float]:
    """Source crop that the preview must sample for one mask.

    Without zoom this is the mask on the full picture. With zoom it is the
    same region of the visible window that export shows after the crop.
    """
    src_w = max(1.0, float(source_width))
    src_h = max(1.0, float(source_height))
    if frame is None or frame.is_neutral:
        return mask.x * src_w, mask.y * src_h, mask.w * src_w, mask.h * src_h
    zoom, focal_x, focal_y = sample_frame(frame, progress)
    left, top, view_w, view_h = source_window(
        zoom,
        focal_x,
        focal_y,
        source_width=int(source_width),
        source_height=int(source_height),
    )
    return left + mask.x * view_w, top + mask.y * view_h, mask.w * view_w, mask.h * view_h


def mask_windows(
    masks: Sequence[Mask],
    *,
    frame_width: int,
    frame_height: int,
    source_width: int,
    source_height: int,
    frame: FrameTransform | None = None,
) -> tuple[MaskWindow, ...]:
    """Place every mask. One failure aborts so export cannot drop a mask."""
    if not masks:
        raise MaskRenderError("no privacy masks")
    fitted = visible_picture_rect(
        frame_width=frame_width,
        frame_height=frame_height,
        source_width=source_width,
        source_height=source_height,
        frame=frame,
    )
    _origin_x, _origin_y, content_w, content_h = fitted
    windows: list[MaskWindow] = []
    for mask in masks:
        left, top, width, height = mask_box_pixels(
            mask,
            fitted,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        windows.append(
            MaskWindow(
                effect=mask.effect,
                x=left,
                y=top,
                w=width,
                h=height,
                radius=blur_radius_px(mask.strength, content_w, content_h, width, height),
                block=pixel_block_px(mask.strength, content_w, content_h, width, height),
            )
        )
    return tuple(windows)


def ffmpeg_mask_graph(
    *,
    base_chain: str,
    fades: Sequence[str],
    windows: Sequence[MaskWindow],
    include_tail: bool = True,
) -> str:
    """Composite each mask after ``base_chain`` and before fades.

    The graph interpolates integers only. User text is never included.
    ``include_tail=False`` stops on ``mbase{n}`` so a later overlay graph can
    continue from that label. The default graph is unchanged.
    """
    if not windows:
        raise MaskRenderError("no privacy masks")
    steps = [f"[0:v]{base_chain}[mbase0]"]
    for index, window in enumerate(windows):
        src = f"mbase{index}"
        nxt = f"mbase{index + 1}"
        if window.effect == "pixelate":
            small_w = max(1, int(window.w) // int(window.block))
            small_h = max(1, int(window.h) // int(window.block))
            effect = (
                f"scale={small_w}:{small_h}:flags=neighbor,"
                f"scale={window.w}:{window.h}:flags=neighbor"
            )
        else:
            radius = int(window.radius)
            effect = f"boxblur=lr={radius}:lp=1:cr={radius}:cp=1"
        steps.append(f"[{src}]split[mb{index}][mc{index}]")
        steps.append(
            f"[mc{index}]crop={window.w}:{window.h}:{window.x}:{window.y},{effect}[mm{index}]"
        )
        steps.append(f"[mb{index}][mm{index}]overlay={window.x}:{window.y}[{nxt}]")
    if not include_tail:
        return ";".join(steps)
    tail_parts = [part for part in fades if part]
    tail_parts.append("format=yuv420p")
    steps.append(f"[mbase{len(windows)}]{','.join(tail_parts)}[vout]")
    return ";".join(steps)
