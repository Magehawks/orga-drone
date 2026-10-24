"""Optional Studio flight-map overlay (Issue #108).

The overlay is a picture-in-picture on one photo or video Story clip. It draws
the GPS track already stored for that clip onto a plain background, plus a
marker that follows the clip clock. Placement uses the same fractions of the
fitted picture as timed overlays, so letterboxing does not move it and the box
cannot sit outside the export frame.

This slice does not download, request, or bundle third-party map tiles. A clip
with no usable GPS still keeps the box and shows an empty panel. Source files
are never modified. The marker is not a tracker and does not invent positions
across a GPS gap longer than ``GAP_S``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

from orga_drone.studio_overlay import content_rect

MIN_BOX = 0.12
MAX_BOX = 0.72
DEFAULT_W = 0.28
DEFAULT_H = 0.28
DEFAULT_MARGIN = 0.04
DEFAULT_X = round(1.0 - DEFAULT_W - DEFAULT_MARGIN, 4)
DEFAULT_Y = round(1.0 - DEFAULT_H - DEFAULT_MARGIN, 4)
PAD = 0.08
GAP_S = 2.0
MAX_MARKER_SAMPLES = 32
MAP_BG = "#14181d"
MAP_ROUTE = "#7eb6ff"
MAP_MARKER = "#ff9f0a"
MAP_BORDER = "#c5d0dc"
_BG_RGBA = (20, 24, 29, 255)
_ROUTE_RGBA = (126, 182, 255, 255)
_MARKER_RGBA = (255, 159, 10, 255)
_BORDER_RGBA = (197, 208, 220, 255)


class MapRenderError(Exception):
    """The flight map could not be drawn for export."""


@dataclass(frozen=True)
class GpsSample:
    """One stored GPS fix. ``t`` is seconds from the source start when known."""

    lat: float
    lon: float
    t: float | None = None


@dataclass(frozen=True)
class RoutePoint:
    """A fix projected into the map panel. ``x`` and ``y`` are 0..1, north up."""

    x: float
    y: float
    t: float

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "t": self.t}


@dataclass(frozen=True)
class MapPlacement:
    """Enabled flag and box in fractions of the fitted picture."""

    enabled: bool = False
    x: float = DEFAULT_X
    y: float = DEFAULT_Y
    w: float = DEFAULT_W
    h: float = DEFAULT_H

    def __post_init__(self) -> None:
        x, y, w, h = _clamp_box(self.x, self.y, self.w, self.h)
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)
        object.__setattr__(self, "w", w)
        object.__setattr__(self, "h", h)

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
        }


def map_preview_model() -> dict[str, object]:
    """Bounds and colors the Studio page uses so it cannot drift from export."""
    return {
        "minBox": MIN_BOX,
        "maxBox": MAX_BOX,
        "gapS": GAP_S,
        "pad": PAD,
        "defaultX": DEFAULT_X,
        "defaultY": DEFAULT_Y,
        "defaultW": DEFAULT_W,
        "defaultH": DEFAULT_H,
        "bg": MAP_BG,
        "route": MAP_ROUTE,
        "marker": MAP_MARKER,
        "border": MAP_BORDER,
    }


def gps_from_stored(
    track: Sequence[Mapping[str, Any]] | None,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> tuple[GpsSample, ...]:
    """Read a stored track, or one still fix when the track is empty."""
    samples: list[GpsSample] = []
    for item in track or ():
        if not isinstance(item, Mapping):
            continue
        lat = _coord(item.get("lat"))
        lon = _coord(item.get("lon"))
        if lat is None or lon is None or _null_island(lat, lon):
            continue
        if abs(lat) > 90 or abs(lon) > 180:
            continue
        raw_t = item.get("t")
        t = _coord(raw_t) if raw_t is not None else None
        samples.append(GpsSample(lat, lon, t))
    if samples:
        return tuple(samples)
    if (
        latitude is not None
        and longitude is not None
        and not _null_island(latitude, longitude)
        and abs(latitude) <= 90
        and abs(longitude) <= 180
        and math.isfinite(latitude)
        and math.isfinite(longitude)
    ):
        return (GpsSample(float(latitude), float(longitude), 0.0),)
    return ()


def project_route(
    samples: Sequence[GpsSample],
    *,
    media_duration_s: float | None,
) -> tuple[RoutePoint, ...]:
    """Project lat/lon into the panel and attach a source time to every fix."""
    if not samples:
        return ()
    timed = all(sample.t is not None for sample in samples)
    duration = float(media_duration_s) if media_duration_s is not None else 0.0
    if not math.isfinite(duration) or duration < 0:
        duration = 0.0
    norms = _project_norm(samples)
    points: list[RoutePoint] = []
    last = len(samples) - 1
    for index, sample in enumerate(samples):
        if timed:
            moment = float(sample.t if sample.t is not None else 0.0)
        elif last == 0 or duration <= 0:
            moment = 0.0
        else:
            moment = duration * index / last
        nx, ny = norms[index]
        points.append(
            RoutePoint(x=round(nx, 4), y=round(ny, 4), t=round(moment, 4))
        )
    return tuple(points)


def downsample_route(
    points: Sequence[RoutePoint],
    limit: int = MAX_MARKER_SAMPLES,
) -> tuple[RoutePoint, ...]:
    """Keep the marker expression short. The first and last fixes stay."""
    if len(points) <= limit:
        return tuple(points)
    if limit < 2:
        return (points[0], points[-1])
    step = (len(points) - 1) / (limit - 1)
    chosen = [points[min(len(points) - 1, int(round(i * step)))] for i in range(limit)]
    chosen[-1] = points[-1]
    return tuple(chosen)


def route_preview(
    samples: Sequence[GpsSample],
    *,
    media_duration_s: float | None,
) -> dict[str, object]:
    """Payload for the Studio preview. Marker samples match the export clock."""
    line = project_route(samples, media_duration_s=media_duration_s)
    marker = downsample_route(line)
    return {
        "line": [point.as_dict() for point in line],
        "marker": [point.as_dict() for point in marker],
    }


def marker_xy(points: Sequence[RoutePoint], time_s: float) -> tuple[float, float] | None:
    """Panel position at ``time_s``. A gap longer than ``GAP_S`` holds the last fix."""
    if not points:
        return None
    moment = float(time_s)
    first = points[0]
    if len(points) == 1 or moment <= first.t:
        return first.x, first.y
    last = points[-1]
    if moment >= last.t:
        return last.x, last.y
    for index in range(len(points) - 1):
        left = points[index]
        right = points[index + 1]
        if moment >= right.t:
            continue
        span = right.t - left.t
        if span <= 0 or span > GAP_S:
            return left.x, left.y
        mix = (moment - left.t) / span
        return (
            left.x + (right.x - left.x) * mix,
            left.y + (right.y - left.y) * mix,
        )
    return last.x, last.y


def map_from_effect_settings(raw: str | None) -> MapPlacement:
    """Missing or invalid JSON stays off, in the lower-right default box."""
    if raw is None or not str(raw).strip():
        return MapPlacement()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return MapPlacement()
    if not isinstance(data, dict):
        return MapPlacement()
    item = data.get("map", {})
    if not isinstance(item, dict):
        return MapPlacement()
    return MapPlacement(
        enabled=item.get("enabled") is True,
        x=_read_unit(item.get("x"), DEFAULT_X),
        y=_read_unit(item.get("y"), DEFAULT_Y),
        w=_read_unit(item.get("w"), DEFAULT_W),
        h=_read_unit(item.get("h"), DEFAULT_H),
    )


def parse_map_payload(payload: Mapping[str, object]) -> MapPlacement:
    """Replace the clip map. Bad numbers raise. The box is clamped inside the frame."""
    raw = payload.get("map", payload)
    if not isinstance(raw, dict) or "enabled" not in raw:
        raise ValueError("JSON body must include map")
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    return MapPlacement(
        enabled=enabled,
        x=_require_unit(raw.get("x", DEFAULT_X), "x"),
        y=_require_unit(raw.get("y", DEFAULT_Y), "y"),
        w=_require_unit(raw.get("w", DEFAULT_W), "w"),
        h=_require_unit(raw.get("h", DEFAULT_H), "h"),
    )


def dump_map(existing: str | None, placement: MapPlacement) -> str:
    """Write the map object and keep unrelated effect_settings keys."""
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data["map"] = placement.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def box_pixels(
    placement: MapPlacement,
    rect: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Pixel box of the map inside the fitted picture. Stays inside that picture."""
    origin_x, origin_y, content_w, content_h = rect
    width = max(1, int(round(placement.w * content_w)))
    height = max(1, int(round(placement.h * content_h)))
    width = min(width, content_w)
    height = min(height, content_h)
    left = origin_x + int(round(placement.x * content_w))
    top = origin_y + int(round(placement.y * content_h))
    left = min(max(origin_x, left), origin_x + content_w - width)
    top = min(max(origin_y, top), origin_y + content_h - height)
    return left, top, width, height


def render_route_image(
    points: Sequence[RoutePoint],
    *,
    width: int,
    height: int,
) -> Image.Image:
    """Plain panel and, when at least two fixes exist, the route. No marker."""
    panel_w = max(8, int(width))
    panel_h = max(8, int(height))
    image = Image.new("RGBA", (panel_w, panel_h), _BG_RGBA)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, panel_w - 1, panel_h - 1), outline=_BORDER_RGBA)
    if len(points) >= 2:
        pad_x = max(1, int(round(panel_w * PAD)))
        pad_y = max(1, int(round(panel_h * PAD)))
        inner_w = max(1, panel_w - 2 * pad_x)
        inner_h = max(1, panel_h - 2 * pad_y)
        coords = [
            (
                pad_x + int(round(point.x * (inner_w - 1))),
                pad_y + int(round(point.y * (inner_h - 1))),
            )
            for point in points
        ]
        width_px = max(2, min(panel_w, panel_h) // 28)
        draw.line(coords, fill=_ROUTE_RGBA, width=width_px, joint="curve")
    return image


def axis_expr(samples: Sequence[tuple[float, float]]) -> str:
    """FFmpeg ``t`` expression for one axis. Commas are escaped for filtergraphs."""
    if not samples:
        return "0"
    if len(samples) == 1:
        return f"{samples[0][1]:.5f}"
    expr = f"{samples[-1][1]:.5f}"
    for index in range(len(samples) - 2, -1, -1):
        left_t, left_v = samples[index]
        right_t, right_v = samples[index + 1]
        span = right_t - left_t
        if span <= 0 or span > GAP_S:
            piece = f"{left_v:.5f}"
        else:
            piece = f"{left_v:.5f}+({(right_v - left_v):.5f})*(t-{left_t:.4f})/{span:.4f}"
        expr = f"if(lt(t,{right_t:.4f}),{piece},{expr})"
    first_t, first_v = samples[0]
    expr = f"if(lt(t,{first_t:.4f}),{first_v:.5f},{expr})"
    return expr.replace(",", r"\,")


def flight_map_overlay(
    *,
    placement: MapPlacement,
    track: Sequence[GpsSample],
    media_duration_s: float | None,
    frame_width: int,
    frame_height: int,
    source_width: int,
    source_height: int,
    dest_dir: Path,
    first_input: int,
    picture_label: str,
    fps: int,
) -> tuple[list[str], str, str]:
    """Write the panel PNG and return ffmpeg inputs, a filter fragment, and its label.

    The marker is a second input whose ``x`` and ``y`` follow the source clock.
    Video filter ``t`` is that source clock because ``-ss`` stays an output option.
    Photos start at 0. No network URL is included.
    """
    if not placement.enabled:
        raise MapRenderError("flight map is disabled")
    rect = content_rect(frame_width, frame_height, source_width, source_height)
    left, top, box_w, box_h = box_pixels(placement, rect)
    dest_dir.mkdir(parents=True, exist_ok=True)
    route_path = dest_dir / "flight-map-route.png"
    line = project_route(track, media_duration_s=media_duration_s)
    try:
        render_route_image(line, width=box_w, height=box_h).save(route_path, "PNG")
    except OSError as exc:
        raise MapRenderError("flight map could not be drawn") from exc
    args = ["-loop", "1", "-framerate", str(int(fps)), "-i", str(route_path)]
    parts = [
        f"[{int(first_input)}:v]format=rgba[mapbg]",
        f"[{picture_label}][mapbg]overlay={left}:{top}:format=auto[mapon]",
    ]
    label = "mapon"
    marker_points = downsample_route(line)
    if marker_points:
        pad_x = max(1, int(round(box_w * PAD)))
        pad_y = max(1, int(round(box_h * PAD)))
        inner_w = max(1, box_w - 2 * pad_x)
        inner_h = max(1, box_h - 2 * pad_y)
        diameter = max(7, int(round(min(box_w, box_h) * 0.07)))
        if diameter % 2 == 0:
            diameter += 1
        diameter = min(diameter, max(1, min(inner_w, inner_h)))
        half = diameter // 2
        marker = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
        draw = ImageDraw.Draw(marker)
        draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=_MARKER_RGBA)
        marker_path = dest_dir / "flight-map-marker.png"
        try:
            marker.save(marker_path, "PNG")
        except OSError as exc:
            raise MapRenderError("flight map could not be drawn") from exc
        args.extend(["-loop", "1", "-framerate", str(int(fps)), "-i", str(marker_path)])
        nx = axis_expr([(point.t, point.x) for point in marker_points])
        ny = axis_expr([(point.t, point.y) for point in marker_points])
        x_expr = f"{(left + pad_x):.2f}+{inner_w:.2f}*({nx})-{half}"
        y_expr = f"{(top + pad_y):.2f}+{inner_h:.2f}*({ny})-{half}"
        dot = int(first_input) + 1
        parts.append(f"[{dot}:v]format=rgba[mapdot]")
        parts.append(
            f"[mapon][mapdot]overlay=x='{x_expr}':y='{y_expr}':format=auto[mapout]"
        )
        label = "mapout"
    return args, ";".join(parts), label


def _clamp_box(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    if not all(math.isfinite(value) for value in (x, y, w, h)):
        raise ValueError("map position must be a finite number")
    width = round(min(MAX_BOX, max(MIN_BOX, float(w))), 4)
    height = round(min(MAX_BOX, max(MIN_BOX, float(h))), 4)
    width = min(width, 1.0)
    height = min(height, 1.0)
    left = round(min(max(0.0, float(x)), 1.0 - width), 4)
    top = round(min(max(0.0, float(y)), 1.0 - height), 4)
    if left + width > 1:
        left = round(1.0 - width, 4)
    if top + height > 1:
        top = round(1.0 - height, 4)
    return left, top, width, height


def _coord(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _null_island(lat: float, lon: float) -> bool:
    return abs(lat) < 0.0001 and abs(lon) < 0.0001


def _project_norm(samples: Sequence[GpsSample]) -> list[tuple[float, float]]:
    if len(samples) == 1:
        return [(0.5, 0.5)]
    lats = [sample.lat for sample in samples]
    mid = math.radians(sum(lats) / len(lats))
    cos = max(0.2, math.cos(mid))
    xs = [sample.lon * cos for sample in samples]
    ys = lats
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span = max(max_x - min_x, max_y - min_y, 1e-9)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    projected: list[tuple[float, float]] = []
    for x_value, y_value in zip(xs, ys, strict=True):
        nx = min(1.0, max(0.0, 0.5 + (x_value - center_x) / span))
        ny = min(1.0, max(0.0, 0.5 - (y_value - center_y) / span))
        projected.append((nx, ny))
    return projected


def _read_unit(value: object, default: float) -> float:
    number = _coord(value)
    if number is None:
        return default
    return number


def _require_unit(value: object, name: str) -> float:
    number = _coord(value)
    if number is None:
        raise ValueError(f"{name} must be a number")
    return number
