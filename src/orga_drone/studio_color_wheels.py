"""Per-clip Studio colour wheels (Issues #232 follow-up).

Three tonal colour wheels: shadows, midtones, and highlights. Each wheel stores
a point in the unit disc. The angle is the hue direction and the distance from
the centre is the tint intensity. The centre is neutral. Values live in
``studio_clips.effect_settings`` under ``color_wheels`` and apply to that Story
clip only. Source files are never modified.

Processing order (pause/scrub stills, playback proxy, and MP4 export share it):

    grade -> conversion/creative LUTs -> HSL mixer -> colour wheels
          -> detail -> saturation ramp

Like the HSL mixer, the wheels are compiled into a generated 3D ``.cube`` LUT
and applied through the existing ``lut3d`` path. That keeps stills, the optional
playback proxy, and MP4 export on one deterministic implementation.

Tonal weighting crossfades with smoothstep between shadow (luma 0), midtone
(luma 0.5), and highlight (luma 1) centres. The three weights always sum to 1.
A wheel tint is a zero-luma RGB direction, so it changes colour without adding a
separate brightness shift. Full radius adds at most ``WHEEL_TINT_AT_FULL``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from orga_drone.studio_lut import escape_ffmpeg_lut_path

COLOR_WHEELS_KEY = "color_wheels"
WHEEL_IDS = ("shadows", "midtones", "highlights")
POINT_MIN = -1.0
POINT_MAX = 1.0
WHEEL_TINT_AT_FULL = 0.20
WHEEL_LUT_SIZE = 33
WHEEL_LUT_VERSION = 1
WHEEL_LUT_DIR = "color-wheel-luts"
WHEEL_LUT_CACHE_MAX_BYTES = 64 * 1024 * 1024

_wheel_lock = threading.Lock()


@dataclass(frozen=True)
class ColorWheelPoint:
    """Point in the unit disc. x/y are screen-like: y grows downward."""

    x: float = 0.0
    y: float = 0.0

    @property
    def is_neutral(self) -> bool:
        return self.x == 0.0 and self.y == 0.0

    @property
    def radius(self) -> float:
        return min(1.0, math.hypot(self.x, self.y))

    @property
    def hue_deg(self) -> float:
        if self.is_neutral:
            return 0.0
        return (math.degrees(math.atan2(self.y, self.x)) + 360.0) % 360.0

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


_NEUTRAL_POINT = ColorWheelPoint()


@dataclass(frozen=True)
class ColorWheels:
    """Three independent tonal wheels. Missing wheels are neutral."""

    shadows: ColorWheelPoint = _NEUTRAL_POINT
    midtones: ColorWheelPoint = _NEUTRAL_POINT
    highlights: ColorWheelPoint = _NEUTRAL_POINT

    @property
    def is_neutral(self) -> bool:
        return all(getattr(self, key).is_neutral for key in WHEEL_IDS)

    def get(self, wheel_id: str) -> ColorWheelPoint:
        return getattr(self, wheel_id)

    def with_wheel(self, wheel_id: str, point: ColorWheelPoint) -> "ColorWheels":
        return replace(self, **{wheel_id: point})

    def as_dict(self) -> dict[str, object]:
        return {"wheels": {key: getattr(self, key).as_dict() for key in WHEEL_IDS}}

    def wheels_dict(self) -> dict[str, dict[str, float]]:
        return {key: getattr(self, key).as_dict() for key in WHEEL_IDS}


def color_wheels_preview_model() -> dict[str, object]:
    return {
        "wheels": list(WHEEL_IDS),
        "pointMin": POINT_MIN,
        "pointMax": POINT_MAX,
        "tintAtFull": WHEEL_TINT_AT_FULL,
        "lutSize": WHEEL_LUT_SIZE,
    }


def _clamp_point(x: object, y: object) -> ColorWheelPoint:
    """Clamp a point to the unit disc. Bad numbers become the centre."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return _NEUTRAL_POINT
    if isinstance(y, bool) or not isinstance(y, (int, float)):
        return _NEUTRAL_POINT
    px = float(x)
    py = float(y)
    if not math.isfinite(px) or not math.isfinite(py):
        return _NEUTRAL_POINT
    px = min(POINT_MAX, max(POINT_MIN, px))
    py = min(POINT_MAX, max(POINT_MIN, py))
    radius = math.hypot(px, py)
    if radius > 1.0 and radius > 0.0:
        px /= radius
        py /= radius
    return ColorWheelPoint(x=round(px, 4), y=round(py, 4))


def _point_from_mapping(value: object) -> ColorWheelPoint:
    if not isinstance(value, Mapping):
        return _NEUTRAL_POINT
    return _clamp_point(value.get("x", 0.0), value.get("y", 0.0))


def color_wheels_from_effect_settings(raw: str | None) -> ColorWheels:
    """Missing, empty, or invalid JSON is the neutral wheels."""
    if raw is None or not str(raw).strip():
        return ColorWheels()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ColorWheels()
    if not isinstance(data, dict):
        return ColorWheels()
    nested = data.get(COLOR_WHEELS_KEY, {})
    if not isinstance(nested, dict):
        return ColorWheels()
    wheels = nested.get("wheels", {})
    if not isinstance(wheels, dict):
        return ColorWheels()
    return ColorWheels(
        **{key: _point_from_mapping(wheels.get(key)) for key in WHEEL_IDS}  # type: ignore[arg-type]
    )


def parse_color_wheels_payload(
    payload: Mapping[str, object],
    current: ColorWheels,
) -> ColorWheels:
    """Merge a partial wheel update. Unknown wheels are ignored.

    Accepts ``{"wheels": {"shadows": {"x": 0.2, "y": -0.1}}}`` or the compact
    ``{"wheel": "shadows", "x": 0.2, "y": -0.1}`` used by a drag.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("JSON body must include colour wheels")
    source = payload.get(COLOR_WHEELS_KEY, payload)
    if not isinstance(source, Mapping):
        raise ValueError("JSON body must include colour wheels")
    wheels = source.get("wheels")
    if wheels is None:
        wheel_id = source.get("wheel")
        if not isinstance(wheel_id, str) or wheel_id not in WHEEL_IDS:
            raise ValueError("JSON body must include a colour wheel")
        if "x" not in source and "y" not in source:
            raise ValueError("JSON body must include a colour wheel point")
        return current.with_wheel(wheel_id, _clamp_point(source.get("x", 0.0), source.get("y", 0.0)))
    if not isinstance(wheels, Mapping) or not wheels:
        raise ValueError("JSON body must include colour wheels")
    result = current
    found = False
    for wheel_id, value in wheels.items():
        if wheel_id not in WHEEL_IDS:
            continue
        if not isinstance(value, Mapping):
            raise ValueError(f"{wheel_id} must include x and y")
        found = True
        result = result.with_wheel(
            str(wheel_id),
            _clamp_point(value.get("x", 0.0), value.get("y", 0.0)),
        )
    if not found:
        raise ValueError("JSON body must include a colour wheel")
    return result


def dump_color_wheels(existing: str | None, wheels: ColorWheels) -> str:
    """Write the color_wheels object and keep unrelated effect settings."""
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data[COLOR_WHEELS_KEY] = wheels.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _smoothstep(value: float) -> float:
    t = min(1.0, max(0.0, value))
    return t * t * (3.0 - 2.0 * t)


def _luma(red: float, green: float, blue: float) -> float:
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def tonal_weights(luma: float) -> tuple[float, float, float]:
    """Shadow, midtone, and highlight weights. They always sum to 1."""
    value = min(1.0, max(0.0, float(luma)))
    if value <= 0.5:
        blend = _smoothstep(value / 0.5)
        return 1.0 - blend, blend, 0.0
    blend = _smoothstep((value - 0.5) / 0.5)
    return 0.0, 1.0 - blend, blend


def _hue_rgb(hue_deg: float) -> tuple[float, float, float]:
    hue = (float(hue_deg) % 360.0) / 60.0
    sector = int(math.floor(hue)) % 6
    fraction = hue - math.floor(hue)
    if sector == 0:
        return 1.0, fraction, 0.0
    if sector == 1:
        return 1.0 - fraction, 1.0, 0.0
    if sector == 2:
        return 0.0, 1.0, fraction
    if sector == 3:
        return 0.0, 1.0 - fraction, 1.0
    if sector == 4:
        return fraction, 0.0, 1.0
    return 1.0, 0.0, 1.0 - fraction


def hue_tint_vector(hue_deg: float) -> tuple[float, float, float]:
    """Zero-luma RGB direction for a hue. Peak channel magnitude is 1."""
    red, green, blue = _hue_rgb(hue_deg)
    luma = _luma(red, green, blue)
    vector = (red - luma, green - luma, blue - luma)
    peak = max(abs(vector[0]), abs(vector[1]), abs(vector[2]))
    if peak <= 1e-12:
        return 0.0, 0.0, 0.0
    return vector[0] / peak, vector[1] / peak, vector[2] / peak


def apply_color_wheels_rgb(
    red: float,
    green: float,
    blue: float,
    wheels: ColorWheels,
) -> tuple[float, float, float]:
    """Apply the three wheels to one RGB triple. Neutral returns the input."""
    if wheels.is_neutral:
        return red, green, blue
    shadow_weight, mid_weight, highlight_weight = tonal_weights(_luma(red, green, blue))
    tint_red = 0.0
    tint_green = 0.0
    tint_blue = 0.0
    for wheel_id, weight in (
        ("shadows", shadow_weight),
        ("midtones", mid_weight),
        ("highlights", highlight_weight),
    ):
        point = wheels.get(wheel_id)
        if point.is_neutral or weight <= 0.0:
            continue
        amount = point.radius * weight * WHEEL_TINT_AT_FULL
        vec_red, vec_green, vec_blue = hue_tint_vector(point.hue_deg)
        tint_red += vec_red * amount
        tint_green += vec_green * amount
        tint_blue += vec_blue * amount
    if not tint_red and not tint_green and not tint_blue:
        return red, green, blue
    return (
        min(1.0, max(0.0, red + tint_red)),
        min(1.0, max(0.0, green + tint_green)),
        min(1.0, max(0.0, blue + tint_blue)),
    )


def color_wheels_lut_key(wheels: ColorWheels, *, size: int = WHEEL_LUT_SIZE) -> str:
    payload = {
        "wheels": wheels.wheels_dict(),
        "size": int(size),
        "tint": WHEEL_TINT_AT_FULL,
        "v": WHEEL_LUT_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_color_wheels_cube(
    path: Path,
    wheels: ColorWheels,
    *,
    size: int = WHEEL_LUT_SIZE,
) -> Path:
    """Write a deterministic 3D cube for this wheel state."""
    size = max(2, int(size))
    denom = float(size - 1)
    lines = [
        'TITLE "Orga Drone color wheels"',
        f"LUT_3D_SIZE {size}",
    ]
    for blue_index in range(size):
        blue = blue_index / denom
        for green_index in range(size):
            green = green_index / denom
            for red_index in range(size):
                red = red_index / denom
                out_red, out_green, out_blue = apply_color_wheels_rgb(
                    red, green, blue, wheels
                )
                lines.append(
                    f"{out_red:.8f} {out_green:.8f} {out_blue:.8f}"
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass
    return path


def _evict_color_wheel_luts(
    folder: Path, *, max_bytes: int = WHEEL_LUT_CACHE_MAX_BYTES
) -> None:
    files = [path for path in folder.glob("*.cube") if path.is_file()]
    total = 0
    stamped: list[tuple[float, int, Path]] = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        total += stat.st_size
        stamped.append((stat.st_mtime, stat.st_size, path))
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


def color_wheels_lut_path(data_dir: Path, wheels: ColorWheels) -> Path:
    """Return the cached cube path, generating it once. Neutral is not called."""
    folder = Path(data_dir) / WHEEL_LUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{color_wheels_lut_key(wheels)}.cube"
    if path.is_file() and path.stat().st_size > 0:
        return path
    with _wheel_lock:
        if not (path.is_file() and path.stat().st_size > 0):
            write_color_wheels_cube(path, wheels)
            _evict_color_wheel_luts(folder)
    return path


def ffmpeg_color_wheels_chain(wheels: ColorWheels, *, data_dir: Path) -> str:
    """``lut3d`` fragment for the wheels, or empty when all are neutral."""
    if wheels.is_neutral:
        return ""
    path = color_wheels_lut_path(data_dir, wheels)
    return f"lut3d=file={escape_ffmpeg_lut_path(path)}:interp=tetrahedral"
