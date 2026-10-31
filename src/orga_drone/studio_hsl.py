"""Per-clip HSL colour mixer (Issue #232).

Eight colour ranges (red, orange, yellow, green, aqua, blue, purple, magenta)
each carry independent Hue, Saturation, and Luminance sliders from -100 to
100. Neutral is 0. Values live in ``studio_clips.effect_settings`` under the
``hsl`` object and apply to that Story clip only, for photos and videos.
Source files are never modified.

Processing order (preview stills, playback proxy, and MP4 export share it):

    grade -> conversion/creative LUTs -> HSL mixer -> detail -> saturation ramp

The mixer is a generated 3D ``.cube`` LUT. That keeps one deterministic colour
implementation for pause/scrub stills, the optional playback proxy, and MP4
export instead of a second grading engine.

Hue weighting is deterministic and smooth. The eight range centres are 0, 30,
60, 120, 180, 240, 270, and 300 degrees. A pixel between two centres gets a
smoothstep crossfade of its neighbours' weights (50/50 exactly between them);
the two weights always sum to 1. Near-neutral pixels fade out by chroma so a
gray sky is not tinted by an undefined hue. Internal mappings:

- Hue: +/-45 degrees at the slider extremes (not UI degrees).
- Saturation: multiplies the pixel's HSL saturation by 0.0x ... 2.0x.
- Luminance: adds up to +/-0.30 in HSL lightness.

LUT interpolation is tetrahedral, matching the existing user LUT path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from orga_drone.studio_lut import escape_ffmpeg_lut_path

HSL_KEY = "hsl"
RANGE_IDS = (
    "red",
    "orange",
    "yellow",
    "green",
    "aqua",
    "blue",
    "purple",
    "magenta",
)
RANGE_CENTERS_DEG = (0.0, 30.0, 60.0, 120.0, 180.0, 240.0, 270.0, 300.0)
SLIDER_MIN = -100
SLIDER_MAX = 100
HUE_DEG_AT_FULL = 45.0
SATURATION_SCALE_AT_FULL = 1.0
LUMINANCE_DELTA_AT_FULL = 0.30
CHROMA_GATE = 0.045
HSL_LUT_SIZE = 33
HSL_LUT_VERSION = 1
HSL_LUT_DIR = "hsl-luts"
HSL_LUT_CACHE_MAX_BYTES = 64 * 1024 * 1024

_hsl_lock = threading.Lock()


@dataclass(frozen=True)
class HslRange:
    """Three sliders for one colour range. 0 is the ungraded picture."""

    hue: int = 0
    saturation: int = 0
    luminance: int = 0

    @property
    def is_neutral(self) -> bool:
        return self.hue == 0 and self.saturation == 0 and self.luminance == 0

    def as_dict(self) -> dict[str, int]:
        return {
            "hue": self.hue,
            "saturation": self.saturation,
            "luminance": self.luminance,
        }


_NEUTRAL_RANGE = HslRange()


@dataclass(frozen=True)
class HslAdjust:
    """Eight independent ranges. Missing ranges are neutral."""

    red: HslRange = _NEUTRAL_RANGE
    orange: HslRange = _NEUTRAL_RANGE
    yellow: HslRange = _NEUTRAL_RANGE
    green: HslRange = _NEUTRAL_RANGE
    aqua: HslRange = _NEUTRAL_RANGE
    blue: HslRange = _NEUTRAL_RANGE
    purple: HslRange = _NEUTRAL_RANGE
    magenta: HslRange = _NEUTRAL_RANGE

    @property
    def is_neutral(self) -> bool:
        return all(getattr(self, key).is_neutral for key in RANGE_IDS)

    def get(self, range_id: str) -> HslRange:
        return getattr(self, range_id)

    def with_range(self, range_id: str, value: HslRange) -> "HslAdjust":
        return replace(self, **{range_id: value})

    def as_dict(self) -> dict[str, object]:
        return {
            "ranges": {key: getattr(self, key).as_dict() for key in RANGE_IDS},
        }

    def ranges_dict(self) -> dict[str, dict[str, int]]:
        return {key: getattr(self, key).as_dict() for key in RANGE_IDS}


def hsl_preview_model() -> dict[str, object]:
    """Ranges and numbers the Studio page may surface to the UI."""
    return {
        "ranges": list(RANGE_IDS),
        "hueDegAtFull": HUE_DEG_AT_FULL,
        "saturationScaleAtFull": SATURATION_SCALE_AT_FULL,
        "luminanceDeltaAtFull": LUMINANCE_DELTA_AT_FULL,
        "lutSize": HSL_LUT_SIZE,
    }


def _round_half_away_from_zero(value: float) -> int:
    if value >= 0:
        return int(value + 0.5)
    return int(value - 0.5)


def _parse_slider(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number from -100 to 100")
    number = float(value)
    if not math.isfinite(number) or number < SLIDER_MIN or number > SLIDER_MAX:
        raise ValueError(f"{key} must be a number from -100 to 100")
    return _round_half_away_from_zero(number)


def _read_slider(value: object) -> int:
    """Corrupt or out-of-range stored data renders as neutral."""
    try:
        return _parse_slider(value, "hsl")
    except ValueError:
        return 0


def _read_range(value: object) -> HslRange:
    if not isinstance(value, dict):
        return HslRange()
    return HslRange(
        hue=_read_slider(value.get("hue")),
        saturation=_read_slider(value.get("saturation")),
        luminance=_read_slider(value.get("luminance")),
    )


def hsl_adjust_from_effect_settings(raw: str | None) -> HslAdjust:
    """Missing, empty, or invalid JSON is the neutral mixer."""
    if raw is None or not str(raw).strip():
        return HslAdjust()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return HslAdjust()
    if not isinstance(data, dict):
        return HslAdjust()
    nested = data.get(HSL_KEY, {})
    if not isinstance(nested, dict):
        return HslAdjust()
    ranges = nested.get("ranges", {})
    if not isinstance(ranges, dict):
        return HslAdjust()
    return HslAdjust(
        **{key: _read_range(ranges.get(key)) for key in RANGE_IDS}  # type: ignore[arg-type]
    )


def _range_from_payload(
    range_id: str,
    payload: Mapping[str, object],
    current: HslRange,
) -> HslRange:
    updates: dict[str, int] = {}
    for key in ("hue", "saturation", "luminance"):
        if key in payload:
            updates[key] = _parse_slider(payload[key], f"{range_id}.{key}")
    return replace(current, **updates)


def parse_hsl_payload(payload: Mapping[str, object], current: HslAdjust) -> HslAdjust:
    """Merge a partial update. Unknown keys are ignored. Bad values raise.

    Accepts either ``{"ranges": {"blue": {"hue": 20}}}`` or the compact
    ``{"range": "blue", "hue": 20}`` used by the selected-colour sliders.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("JSON body must include HSL settings")
    source = payload.get(HSL_KEY, payload)
    if not isinstance(source, Mapping):
        raise ValueError("JSON body must include HSL settings")
    ranges = source.get("ranges")
    if ranges is None:
        range_id = source.get("range")
        if not isinstance(range_id, str) or range_id not in RANGE_IDS:
            raise ValueError("JSON body must include an HSL colour range")
        if not any(key in source for key in ("hue", "saturation", "luminance")):
            raise ValueError("JSON body must include an HSL adjustment")
        updated = _range_from_payload(range_id, source, current.get(range_id))
        return current.with_range(range_id, updated)
    if not isinstance(ranges, Mapping) or not ranges:
        raise ValueError("JSON body must include HSL ranges")
    result = current
    found = False
    for range_id, values in ranges.items():
        if range_id not in RANGE_IDS:
            continue
        if not isinstance(values, Mapping):
            raise ValueError(f"{range_id} must include HSL sliders")
        found = True
        result = result.with_range(
            str(range_id),
            _range_from_payload(str(range_id), values, result.get(str(range_id))),
        )
    if not found:
        raise ValueError("JSON body must include an HSL colour range")
    return result


def dump_hsl_adjust(existing: str | None, hsl: HslAdjust) -> str:
    """Write the hsl object and keep unrelated effect_settings keys."""
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data[HSL_KEY] = hsl.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _smoothstep(value: float) -> float:
    t = min(1.0, max(0.0, value))
    return t * t * (3.0 - 2.0 * t)


def _wrap_hue(hue_deg: float) -> float:
    value = hue_deg % 360.0
    return value + 360.0 if value < 0 else value


def hue_weights(hue_deg: float) -> tuple[float, ...]:
    """Smooth weights for the eight ranges. They always sum to 1.

    The hue is crossfaded between the two nearest range centres with a
    smoothstep curve. At a centre one range has full weight; halfway between
    two centres both have half weight. This avoids hard colour boundaries and
    keeps the transition derivative zero at each centre.
    """
    hue = _wrap_hue(float(hue_deg)) if math.isfinite(float(hue_deg)) else 0.0
    weights = [0.0] * len(RANGE_CENTERS_DEG)
    for index, start in enumerate(RANGE_CENTERS_DEG):
        end = (
            RANGE_CENTERS_DEG[index + 1]
            if index + 1 < len(RANGE_CENTERS_DEG)
            else 360.0
        )
        span = end - start
        if span <= 0:
            continue
        if start <= hue < end or (index == len(RANGE_CENTERS_DEG) - 1 and hue >= 360.0):
            position = (hue - start) / span
            blend = _smoothstep(position)
            weights[index] += 1.0 - blend
            next_index = (index + 1) % len(RANGE_CENTERS_DEG)
            weights[next_index] += blend
            return tuple(weights)
    # Hue is exactly 360 after wrapping only when the modulo produced 0.0.
    weights[0] = 1.0
    return tuple(weights)


def _rgb_to_hsl(red: float, green: float, blue: float) -> tuple[float, float, float]:
    maximum = max(red, green, blue)
    minimum = min(red, green, blue)
    lightness = (maximum + minimum) / 2.0
    delta = maximum - minimum
    if delta <= 1e-12:
        return 0.0, 0.0, lightness
    denominator = 1.0 - abs(2.0 * lightness - 1.0)
    saturation = 0.0 if denominator <= 1e-12 else delta / denominator
    if maximum == red:
        hue = ((green - blue) / delta) % 6.0
    elif maximum == green:
        hue = (blue - red) / delta + 2.0
    else:
        hue = (red - green) / delta + 4.0
    return hue * 60.0, min(1.0, max(0.0, saturation)), lightness


def _hue_channel(
    channel1: float, channel2: float, hue: float
) -> float:
    value = hue % 1.0
    if value < 1.0 / 6.0:
        return channel1 + (channel2 - channel1) * 6.0 * value
    if value < 0.5:
        return channel2
    if value < 2.0 / 3.0:
        return channel1 + (channel2 - channel1) * (2.0 / 3.0 - value) * 6.0
    return channel1


def _hsl_to_rgb(hue: float, saturation: float, lightness: float) -> tuple[float, float, float]:
    if saturation <= 1e-12:
        value = min(1.0, max(0.0, lightness))
        return value, value, value
    channel2 = (
        lightness * (1.0 + saturation)
        if lightness < 0.5
        else lightness + saturation - lightness * saturation
    )
    channel1 = 2.0 * lightness - channel2
    hue_norm = _wrap_hue(hue) / 360.0
    red = _hue_channel(channel1, channel2, hue_norm + 1.0 / 3.0)
    green = _hue_channel(channel1, channel2, hue_norm)
    blue = _hue_channel(channel1, channel2, hue_norm - 1.0 / 3.0)
    return (
        min(1.0, max(0.0, red)),
        min(1.0, max(0.0, green)),
        min(1.0, max(0.0, blue)),
    )


def apply_hsl_rgb(red: float, green: float, blue: float, hsl: HslAdjust) -> tuple[float, float, float]:
    """Apply the mixer to one RGB triple. Neutral returns the input exactly."""
    if hsl.is_neutral:
        return red, green, blue
    hue, saturation, lightness = _rgb_to_hsl(red, green, blue)
    chroma = max(red, green, blue) - min(red, green, blue)
    chroma_gate = _smoothstep(chroma / CHROMA_GATE) if CHROMA_GATE > 0 else 1.0
    if chroma_gate <= 0.0:
        return red, green, blue
    weights = hue_weights(hue)
    hue_delta = 0.0
    saturation_factor = 1.0
    luminance_delta = 0.0
    for index, range_id in enumerate(RANGE_IDS):
        weight = weights[index] * chroma_gate
        if weight <= 0.0:
            continue
        item = hsl.get(range_id)
        if item.is_neutral:
            continue
        hue_delta += weight * (item.hue / 100.0) * HUE_DEG_AT_FULL
        saturation_factor += weight * (item.saturation / 100.0) * SATURATION_SCALE_AT_FULL
        luminance_delta += weight * (item.luminance / 100.0) * LUMINANCE_DELTA_AT_FULL
    if not hue_delta and saturation_factor == 1.0 and not luminance_delta:
        return red, green, blue
    new_hue = _wrap_hue(hue + hue_delta)
    new_saturation = min(1.0, max(0.0, saturation * max(0.0, saturation_factor)))
    new_lightness = min(1.0, max(0.0, lightness + luminance_delta))
    return _hsl_to_rgb(new_hue, new_saturation, new_lightness)


def hsl_lut_key(hsl: HslAdjust, *, size: int = HSL_LUT_SIZE) -> str:
    payload = {
        "ranges": hsl.ranges_dict(),
        "size": int(size),
        "hue": HUE_DEG_AT_FULL,
        "saturation": SATURATION_SCALE_AT_FULL,
        "luminance": LUMINANCE_DELTA_AT_FULL,
        "chroma": CHROMA_GATE,
        "centers": list(RANGE_CENTERS_DEG),
        "v": HSL_LUT_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_hsl_cube(path: Path, hsl: HslAdjust, *, size: int = HSL_LUT_SIZE) -> Path:
    """Write a deterministic 3D cube for this mixer state."""
    size = max(2, int(size))
    denom = float(size - 1)
    lines = [
        'TITLE "Orga Drone HSL mixer"',
        f"LUT_3D_SIZE {size}",
    ]
    for blue_index in range(size):
        blue = blue_index / denom
        for green_index in range(size):
            green = green_index / denom
            for red_index in range(size):
                red = red_index / denom
                out_red, out_green, out_blue = apply_hsl_rgb(red, green, blue, hsl)
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


def _evict_hsl_luts(folder: Path, *, max_bytes: int = HSL_LUT_CACHE_MAX_BYTES) -> None:
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


def hsl_lut_path(data_dir: Path, hsl: HslAdjust) -> Path:
    """Return the cached cube path, generating it once. Neutral is not called."""
    folder = Path(data_dir) / HSL_LUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{hsl_lut_key(hsl)}.cube"
    if path.is_file() and path.stat().st_size > 0:
        return path
    with _hsl_lock:
        if not (path.is_file() and path.stat().st_size > 0):
            write_hsl_cube(path, hsl)
            _evict_hsl_luts(folder)
    return path


def ffmpeg_hsl_chain(hsl: HslAdjust, *, data_dir: Path) -> str:
    """``lut3d`` fragment for the mixer, or empty when all ranges are neutral."""
    if hsl.is_neutral:
        return ""
    path = hsl_lut_path(data_dir, hsl)
    return f"lut3d=file={escape_ffmpeg_lut_path(path)}:interp=tetrahedral"


def hsl_cache_age_s(path: Path) -> float:
    """Age helper for diagnostics and cache tests."""
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return 0.0
