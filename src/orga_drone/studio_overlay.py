"""Clip-attached text, shape, and image overlays (Issue #78).

Overlays live in ``studio_clips.effect_settings`` under ``overlays``. They belong
to one Story clip instance. Times are seconds from the start of that clip's
visible duration (photo duration, or the trimmed video range). Coordinates are
fractions of the fitted picture, so letterboxing does not move them.

Export draws each overlay onto a transparent PNG and composites it in the
existing segment graph, after scale/pad and before fades. The stitch graph is
unchanged: a crossfade blends finished segments, so an overlay cannot continue
onto the next clip. Video filter time follows the source timestamp because
``-ss`` stays an output option; enable windows are shifted by ``source_start``.

User text and colors never become FFmpeg expressions. Filter text is built only
from formatted numbers.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_OVERLAYS = 8
KINDS = ("text", "arrow", "circle", "rectangle", "image")
ANIMATIONS = ("none", "fade_in", "fade_out", "slide_in")
SLIDE_FROMS = ("left", "right", "up", "down")
MIN_ANIMATION_S = 0.1
MAX_ANIMATION_S = 2.0
DEFAULT_ANIMATION_S = 0.4
MIN_SPAN_S = 0.1
TIME_STEP_S = 0.1
MAX_TEXT_CHARS = 80
MIN_FONT_SIZE = 0.03
MAX_FONT_SIZE = 0.20
DEFAULT_FONT_SIZE = 0.06
MIN_BOX = 0.04
MAX_ROTATION = 180.0
MIN_STROKE = 0.002
MAX_STROKE = 0.04
DEFAULT_STROKE_WIDTH = 0.012
DEFAULT_STROKE_COLOR = "#ffffff"
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_ASSET_EDGE = 2048
ASSET_NAME_RE = re.compile(r"^[a-f0-9]{32}\.(?:png|jpg)$")
OVERLAY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
COLOR_RE = re.compile(r"^#[0-9a-f]{6}(?:[0-9a-f]{2})?$")

DEFAULT_COLOR = "#ffffff"
DEFAULT_FILL = "#00000066"
TRANSPARENT = "#00000000"


class OverlayAssetMissing(Exception):
    """A stored overlay image is no longer on disk."""

    def __init__(self, asset_name: str) -> None:
        super().__init__(asset_name)
        self.asset_name = asset_name


class OverlayFontMissing(Exception):
    """Text export needs the same system sans font as Title Cards."""


@dataclass(frozen=True)
class Overlay:
    id: str
    kind: str
    start_s: float
    end_s: float
    x: float
    y: float
    w: float
    h: float
    rotation: float = 0.0
    text: str = ""
    font_size: float = DEFAULT_FONT_SIZE
    color: str = DEFAULT_COLOR
    fill: str = DEFAULT_FILL
    stroke: str = DEFAULT_STROKE_COLOR
    stroke_width: float = DEFAULT_STROKE_WIDTH
    asset_name: str = ""
    animation: str = "none"
    animation_s: float = DEFAULT_ANIMATION_S
    slide_from: str = "left"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "rotation": self.rotation,
            "text": self.text,
            "font_size": self.font_size,
            "color": self.color,
            "fill": self.fill,
            "stroke": self.stroke,
            "stroke_width": self.stroke_width,
            "asset_name": self.asset_name,
            "animation": self.animation,
            "animation_s": self.animation_s,
            "slide_from": self.slide_from,
        }


@dataclass(frozen=True)
class OverlayWindow:
    """One overlay's filter-clock interval and optional entrance or exit."""

    start_s: float
    end_s: float
    animation: str = "none"
    animation_s: float = 0.0
    slide_from: str = "left"
    frame_w: int = 0
    frame_h: int = 0
    px: int = 0
    py: int = 0
    pw: int = 0
    ph: int = 0
    ox: int = 0
    oy: int = 0
    cw: int = 0
    ch: int = 0


def overlay_preview_model() -> dict[str, Any]:
    """Bounds the page script uses so it cannot drift from the server."""
    return {
        "max_overlays": MAX_OVERLAYS,
        "min_span_s": MIN_SPAN_S,
        "time_step_s": TIME_STEP_S,
        "max_text_chars": MAX_TEXT_CHARS,
        "min_font_size": MIN_FONT_SIZE,
        "max_font_size": MAX_FONT_SIZE,
        "min_box": MIN_BOX,
        "max_rotation": MAX_ROTATION,
        "kinds": list(KINDS),
        "animations": list(ANIMATIONS),
        "slide_from": list(SLIDE_FROMS),
        "min_animation_s": MIN_ANIMATION_S,
        "max_animation_s": MAX_ANIMATION_S,
    }


def new_overlay_id() -> str:
    return "ov" + uuid.uuid4().hex[:10]


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def _round_time(value: float) -> float:
    stepped = round(value / TIME_STEP_S) * TIME_STEP_S
    return round(stepped, 1)


def _round_unit(value: float) -> float:
    return round(value, 4)


def _color(value: object, name: str, *, default: str) -> str:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a hex color")
    color = value.strip().lower()
    if not COLOR_RE.fullmatch(color):
        raise ValueError(f"{name} must be a hex color")
    return color


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("overlay text must be a string")
    cleaned = "".join(ch for ch in value if ch >= " " and ch != "\x7f")
    cleaned = " ".join(cleaned.split())
    return cleaned[:MAX_TEXT_CHARS]


def _asset_name(value: object, *, required: bool) -> str:
    if value is None or value == "":
        if required:
            raise ValueError("image overlay needs a stored image")
        return ""
    if not isinstance(value, str) or not ASSET_NAME_RE.fullmatch(value):
        raise ValueError("overlay image reference is invalid")
    return value


def clamp_overlay_timing(
    start_s: float,
    end_s: float,
    duration_s: float,
) -> tuple[float, float, bool]:
    """Fit an interval into the clip. Returns start, end, and whether it changed."""
    duration = _round_time(max(0.0, float(duration_s)))
    if duration < MIN_SPAN_S:
        raise ValueError("clip is too short for an overlay")
    start = _round_time(start_s)
    end = _round_time(end_s)
    original = (start, end)
    start = _clamp(start, 0.0, duration - MIN_SPAN_S)
    end = _clamp(end, start + MIN_SPAN_S, duration)
    start = _round_time(start)
    end = _round_time(end)
    if end - start < MIN_SPAN_S:
        end = _round_time(min(duration, start + MIN_SPAN_S))
        start = _round_time(max(0.0, end - MIN_SPAN_S))
    changed = (start, end) != original
    return start, end, changed


def _parse_one(raw: object, *, duration_s: float) -> tuple[Overlay, bool]:
    if not isinstance(raw, dict):
        raise ValueError("overlay must be an object")
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("overlay kind is invalid")
    ident = raw.get("id")
    if not isinstance(ident, str) or not OVERLAY_ID_RE.fullmatch(ident):
        ident = new_overlay_id()
    start, end, timed = clamp_overlay_timing(
        _finite_number(raw.get("start_s", 0), "start_s"),
        _finite_number(raw.get("end_s", duration_s), "end_s"),
        duration_s,
    )
    x = _clamp(_finite_number(raw.get("x", 0.1), "x"), 0.0, 1.0 - MIN_BOX)
    y = _clamp(_finite_number(raw.get("y", 0.1), "y"), 0.0, 1.0 - MIN_BOX)
    w = _clamp(_finite_number(raw.get("w", 0.4), "w"), MIN_BOX, 1.0)
    h = _clamp(_finite_number(raw.get("h", 0.16), "h"), MIN_BOX, 1.0)
    if x + w > 1.0:
        w = 1.0 - x
        timed = True
    if y + h > 1.0:
        h = 1.0 - y
        timed = True
    rotation = _clamp(_finite_number(raw.get("rotation", 0), "rotation"), -MAX_ROTATION, MAX_ROTATION)
    font_size = _clamp(
        _finite_number(raw.get("font_size", DEFAULT_FONT_SIZE), "font_size"),
        MIN_FONT_SIZE,
        MAX_FONT_SIZE,
    )
    stroke_width = _clamp(
        _finite_number(raw.get("stroke_width", DEFAULT_STROKE_WIDTH), "stroke_width"),
        MIN_STROKE,
        MAX_STROKE,
    )
    fill_default = TRANSPARENT if kind in {"text", "arrow"} else DEFAULT_FILL
    animation = raw.get("animation", "none")
    if not isinstance(animation, str) or animation not in ANIMATIONS:
        raise ValueError("overlay animation is invalid")
    slide_from = raw.get("slide_from", "left")
    if not isinstance(slide_from, str) or slide_from not in SLIDE_FROMS:
        raise ValueError("overlay slide direction is invalid")
    span = max(MIN_SPAN_S, end - start)
    animation_s = _clamp(
        _finite_number(raw.get("animation_s", DEFAULT_ANIMATION_S), "animation_s"),
        MIN_ANIMATION_S,
        min(MAX_ANIMATION_S, span),
    )
    rounded_animation = min(span, _round_time(animation_s))
    if animation != "none" and abs(rounded_animation - _finite_number(raw.get("animation_s", DEFAULT_ANIMATION_S), "animation_s")) > 0.001:
        timed = True
    overlay = Overlay(
        id=ident,
        kind=kind,
        start_s=start,
        end_s=end,
        x=_round_unit(x),
        y=_round_unit(y),
        w=_round_unit(w),
        h=_round_unit(h),
        rotation=_round_unit(rotation),
        text=_clean_text(raw.get("text", "")),
        font_size=_round_unit(font_size),
        color=_color(raw.get("color"), "color", default=DEFAULT_COLOR),
        fill=_color(raw.get("fill"), "fill", default=fill_default),
        stroke=_color(raw.get("stroke"), "stroke", default=DEFAULT_STROKE_COLOR),
        stroke_width=_round_unit(stroke_width),
        asset_name=_asset_name(raw.get("asset_name", ""), required=kind == "image"),
        animation=animation,
        animation_s=rounded_animation,
        slide_from=slide_from,
    )
    return overlay, timed


def parse_overlays(payload: object, *, duration_s: float) -> tuple[tuple[Overlay, ...], bool]:
    """Validate a replacement list. Unknown keys are ignored. Bad values raise."""
    raw_list = payload
    if isinstance(payload, dict):
        raw_list = payload.get("overlays")
    if not isinstance(raw_list, list):
        raise ValueError("JSON body must include overlays")
    if len(raw_list) > MAX_OVERLAYS:
        raise ValueError(f"a clip can have at most {MAX_OVERLAYS} overlays")
    parsed: list[Overlay] = []
    clamped = False
    seen: set[str] = set()
    for item in raw_list:
        overlay, changed = _parse_one(item, duration_s=duration_s)
        if overlay.id in seen:
            overlay = Overlay(**{**overlay.as_dict(), "id": new_overlay_id()})
        seen.add(overlay.id)
        parsed.append(overlay)
        clamped = clamped or changed
    return tuple(parsed), clamped


def _load_effect_object(existing: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def overlays_from_effect_settings(
    raw: str | None,
    *,
    duration_s: float,
) -> tuple[Overlay, ...]:
    """Read stored overlays. Invalid entries are dropped so old rows stay usable."""
    data = _load_effect_object(raw)
    items = data.get("overlays")
    if not isinstance(items, list):
        return ()
    kept: list[Overlay] = []
    for item in items:
        if len(kept) >= MAX_OVERLAYS:
            break
        try:
            overlay, _changed = _parse_one(item, duration_s=duration_s)
        except ValueError:
            continue
        kept.append(overlay)
    return tuple(kept)


def dump_overlays(existing: str | None, overlays: tuple[Overlay, ...] | list[Overlay]) -> str:
    """Write overlays and keep unrelated effect_settings keys, including image."""
    data = _load_effect_object(existing)
    data["overlays"] = [item.as_dict() for item in overlays]
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def overlay_asset_dir(data_dir: Path) -> Path:
    path = data_dir / "overlay-assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_overlay_asset(data_dir: Path, asset_name: str) -> Path:
    if not isinstance(asset_name, str) or not ASSET_NAME_RE.fullmatch(asset_name):
        raise ValueError("overlay image reference is invalid")
    root = overlay_asset_dir(data_dir).resolve()
    path = (root / asset_name).resolve()
    if path.parent != root:
        raise ValueError("overlay image reference is invalid")
    return path


def store_overlay_asset(data_dir: Path, data: bytes) -> str:
    """Re-encode a PNG or JPEG into the data directory. The original path is not kept."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("overlay image is empty")
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError("overlay image is too large")
    from PIL import Image, UnidentifiedImageError

    try:
        from io import BytesIO

        with Image.open(BytesIO(data)) as incoming:
            incoming.load()
            fmt = (incoming.format or "").upper()
            if fmt not in {"PNG", "JPEG"}:
                raise ValueError("overlay image must be a PNG or JPEG")
            image = incoming.convert("RGBA" if fmt == "PNG" else "RGB")
    except UnidentifiedImageError as exc:
        raise ValueError("overlay image must be a PNG or JPEG") from exc
    except OSError as exc:
        raise ValueError("overlay image must be a PNG or JPEG") from exc
    image.thumbnail((MAX_ASSET_EDGE, MAX_ASSET_EDGE))
    ext = "png" if image.mode == "RGBA" else "jpg"
    name = uuid.uuid4().hex + "." + ext
    dest = resolve_overlay_asset(data_dir, name)
    if ext == "png":
        image.save(dest, "PNG")
    else:
        image.save(dest, "JPEG", quality=90)
    return name


def content_rect(
    frame_width: int,
    frame_height: int,
    source_width: int,
    source_height: int,
) -> tuple[int, int, int, int]:
    """Return x, y, width, height of the fitted picture inside the frame.

    A missing source size uses the full frame. Centering matches integer pad.
    """
    frame_w = max(1, int(frame_width))
    frame_h = max(1, int(frame_height))
    src_w = int(source_width)
    src_h = int(source_height)
    if src_w <= 0 or src_h <= 0:
        return 0, 0, frame_w, frame_h
    scale = min(frame_w / src_w, frame_h / src_h)
    content_w = max(1, int(round(src_w * scale)))
    content_h = max(1, int(round(src_h * scale)))
    content_w = min(content_w, frame_w)
    content_h = min(content_h, frame_h)
    origin_x = (frame_w - content_w) // 2
    origin_y = (frame_h - content_h) // 2
    return origin_x, origin_y, content_w, content_h


def overlay_box_pixels(
    overlay: Overlay,
    rect: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    origin_x, origin_y, content_w, content_h = rect
    width = max(1, int(round(overlay.w * content_w)))
    height = max(1, int(round(overlay.h * content_h)))
    left = origin_x + int(round(overlay.x * content_w))
    top = origin_y + int(round(overlay.y * content_h))
    return left, top, width, height


def overlay_is_active(overlay: Overlay, local_s: float, *, duration_s: float) -> bool:
    """True when ``local_s`` is inside the clip-relative interval, clamped to the clip."""
    end = min(float(overlay.end_s), max(0.0, float(duration_s)))
    if end - float(overlay.start_s) < MIN_SPAN_S:
        return False
    local = float(local_s)
    return float(overlay.start_s) <= local <= end


def filter_time_origin(*, kind: str, source_start_s: float) -> float:
    """Map clip-relative overlay time onto the segment filter clock.

    Photos are generated from t=0. Videos keep output ``-ss``, so filter ``t``
    is the source timestamp and the window shifts by the trim in-point.
    """
    if kind == "video":
        return max(0.0, float(source_start_s))
    return 0.0


def _window(item: OverlayWindow | tuple[float, float]) -> OverlayWindow:
    if isinstance(item, OverlayWindow):
        return item
    start, end = item
    return OverlayWindow(start_s=float(start), end_s=float(end))


def _slide_xy(window: OverlayWindow) -> tuple[str, str]:
    """Return overlay x/y expressions. Commas inside ``if`` are escaped."""
    start = float(window.start_s)
    duration = max(MIN_ANIMATION_S, float(window.animation_s))
    until = start + duration
    remain = f"(1-(t-{start:.4f})/{duration:.4f})"
    if window.slide_from == "right":
        distance = (window.ox + window.cw) - window.px
        axis = "x"
    elif window.slide_from == "up":
        distance = window.oy - window.py - window.ph
        axis = "y"
    elif window.slide_from == "down":
        distance = (window.oy + window.ch) - window.py
        axis = "y"
    else:
        distance = window.ox - window.px - window.pw
        axis = "x"
    expr = f"if(lt(t\\,{until:.4f})\\,{distance:.4f}*{remain}\\,0)"
    if axis == "x":
        return expr, "0"
    return "0", expr


def ffmpeg_overlay_graph(
    *,
    base_chain: str,
    fades: list[str],
    windows: Sequence[OverlayWindow | tuple[float, float]],
    first_input: int,
) -> str:
    """Composite full-frame PNGs onto the scaled segment, then run fades.

    ``windows`` are filter-clock seconds. Fade in/out uses the overlay input's
    clock, which starts with the main input because ``-ss`` is an output option.
    Slide in moves the finished PNG. The graph contains only formatted numbers.
    """
    parsed = [_window(item) for item in windows]
    if not parsed:
        raise ValueError("overlay graph needs at least one overlay")
    if any(
        not math.isfinite(item.start_s) or not math.isfinite(item.end_s) or item.end_s < item.start_s
        for item in parsed
    ):
        raise ValueError("overlay timing is invalid")
    parts = [f"[0:v]{base_chain}[base]"]
    prev = "base"
    for index, window in enumerate(parsed):
        src = first_input + index
        prep = f"[{src}:v]format=rgba"
        duration = max(MIN_ANIMATION_S, float(window.animation_s or 0))
        if window.animation == "fade_in":
            prep += f",fade=t=in:st={window.start_s:.4f}:d={duration:.4f}:alpha=1"
        elif window.animation == "fade_out":
            out_at = max(window.start_s, window.end_s - duration)
            prep += f",fade=t=out:st={out_at:.4f}:d={duration:.4f}:alpha=1"
        prep += f"[ov{index}]"
        parts.append(prep)
        labelled = f"ovl{index}"
        enable = f"between(t\\,{window.start_s:.4f}\\,{window.end_s:.4f})"
        if window.animation == "slide_in":
            slide_x, slide_y = _slide_xy(window)
            parts.append(
                f"[{prev}][ov{index}]overlay=x='{slide_x}':y='{slide_y}':enable='{enable}':format=auto[{labelled}]"
            )
        else:
            parts.append(
                f"[{prev}][ov{index}]overlay=0:0:enable='{enable}':format=auto[{labelled}]"
            )
        prev = labelled
    if not fades:
        parts.append(f"[{prev}]format=yuv420p[vout]")
        return ";".join(parts)
    parts.append(f"[{prev}]format=yuv420p[fmt]")
    prev = "fmt"
    for index, fade in enumerate(fades):
        label = "vout" if index == len(fades) - 1 else f"fd{index}"
        parts.append(f"[{prev}]{fade}[{label}]")
        prev = label
    return ";".join(parts)


def _parse_hex(color: str) -> tuple[int, int, int, int]:
    raw = color[1:]
    red = int(raw[0:2], 16)
    green = int(raw[2:4], 16)
    blue = int(raw[4:6], 16)
    alpha = int(raw[6:8], 16) if len(raw) == 8 else 255
    return red, green, blue, alpha


def render_overlay_png(
    overlay: Overlay,
    *,
    frame_width: int,
    frame_height: int,
    source_width: int,
    source_height: int,
    asset_path: Path | None,
    dest: Path,
) -> None:
    """Draw one overlay on a transparent frame. ``dest`` is a PNG path."""
    from PIL import Image, ImageDraw

    rect = content_rect(frame_width, frame_height, source_width, source_height)
    left, top, width, height = overlay_box_pixels(overlay, rect)
    _content_x, _content_y, content_w, content_h = rect
    sprite = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    stroke_px = max(1, int(round(overlay.stroke_width * min(content_w, content_h))))
    stroke = _parse_hex(overlay.stroke)
    fill = _parse_hex(overlay.fill)
    color = _parse_hex(overlay.color)
    if overlay.kind == "text":
        font_px = max(8, int(round(overlay.font_size * content_h)))
        _draw_text(sprite, overlay, color, fill, font_px)
    elif overlay.kind == "rectangle":
        inset = stroke_px // 2
        draw.rectangle(
            [inset, inset, max(inset, width - 1 - inset), max(inset, height - 1 - inset)],
            fill=fill if fill[3] else None,
            outline=stroke,
            width=stroke_px,
        )
    elif overlay.kind == "circle":
        inset = stroke_px // 2
        draw.ellipse(
            [inset, inset, max(inset, width - 1 - inset), max(inset, height - 1 - inset)],
            fill=fill if fill[3] else None,
            outline=stroke,
            width=stroke_px,
        )
    elif overlay.kind == "arrow":
        _draw_arrow(draw, width, height, stroke, stroke_px)
    elif overlay.kind == "image":
        if asset_path is None or not asset_path.is_file():
            raise OverlayAssetMissing(overlay.asset_name)
        _paste_image(sprite, asset_path)
    else:
        raise ValueError("overlay kind is invalid")
    if abs(overlay.rotation) > 0.01:
        sprite = sprite.rotate(-overlay.rotation, expand=True, resample=Image.Resampling.BICUBIC)
    frame = Image.new("RGBA", (int(frame_width), int(frame_height)), (0, 0, 0, 0))
    paste_x = left + (width - sprite.width) // 2
    paste_y = top + (height - sprite.height) // 2
    _composite_at(frame, sprite, paste_x, paste_y)
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.save(dest, "PNG")


def _draw_text(
    sprite: Any,
    overlay: Overlay,
    color: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    font_px: int,
) -> None:
    from PIL import ImageDraw, ImageFont

    from orga_drone.studio_title_card import TitleCardFontError, resolve_title_card_font

    draw = ImageDraw.Draw(sprite)
    if fill[3]:
        draw.rectangle([0, 0, sprite.width - 1, sprite.height - 1], fill=fill)
    text = overlay.text.strip()
    if not text:
        return
    try:
        font_path = resolve_title_card_font()
    except TitleCardFontError as exc:
        raise OverlayFontMissing("Text overlay export needs a system sans font.") from exc
    font = ImageFont.truetype(str(font_path), max(8, int(font_px)))
    draw.text((sprite.width / 2, sprite.height / 2), text, font=font, fill=color, anchor="mm")


def _composite_at(frame: Any, sprite: Any, left: int, top: int) -> None:
    """Paste ``sprite`` even when rotation makes it hang outside the frame."""
    if sprite.width <= 0 or sprite.height <= 0:
        return
    src_x = 0 if left >= 0 else -left
    src_y = 0 if top >= 0 else -top
    dest_x = max(0, left)
    dest_y = max(0, top)
    if dest_x >= frame.width or dest_y >= frame.height or src_x >= sprite.width or src_y >= sprite.height:
        return
    crop_w = min(sprite.width - src_x, frame.width - dest_x)
    crop_h = min(sprite.height - src_y, frame.height - dest_y)
    if crop_w <= 0 or crop_h <= 0:
        return
    crop = sprite.crop((src_x, src_y, src_x + crop_w, src_y + crop_h))
    frame.alpha_composite(crop, (dest_x, dest_y))


def _draw_arrow(draw: Any, width: int, height: int, color: tuple[int, int, int, int], stroke_px: int) -> None:
    mid = height / 2
    head = max(stroke_px * 3, int(width * 0.22))
    shaft_end = max(stroke_px, width - head)
    draw.line([(stroke_px, mid), (shaft_end, mid)], fill=color, width=stroke_px)
    draw.polygon(
        [(shaft_end - stroke_px, mid - head * 0.55), (width - 1, mid), (shaft_end - stroke_px, mid + head * 0.55)],
        fill=color,
    )


def _paste_image(sprite: Any, asset_path: Path) -> None:
    from PIL import Image

    with Image.open(asset_path) as incoming:
        image = incoming.convert("RGBA")
    image.thumbnail((sprite.width, sprite.height))
    left = (sprite.width - image.width) // 2
    top = (sprite.height - image.height) // 2
    sprite.alpha_composite(image, (left, top))
