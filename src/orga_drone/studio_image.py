"""Per-clip Studio image adjustment (Issue #76).

Four sliders, each an integer from -100 to 100. Neutral is 0. Values live in
``studio_clips.effect_settings`` under the ``image`` object and apply to that
Story clip only, for photos and videos. Source files are never modified.

Export mapping (ffmpeg 7.1 filters, numbers only — never raw user text):

- Brightness: ``exposure=exposure=EV`` with EV = slider/100 (±1.0 stop).
  Measured on this ffmpeg: encoded RGB is multiplied by ``2^EV``.
- Contrast: ``eq=contrast=`` where factor = 1 + slider/200 (0.5 … 1.5).
- Saturation: ``eq=saturation=`` where factor = 1 + slider/100 (0 … 2).
- Warmth: ``colortemperature=temperature=K``. Positive warmth lowers Kelvin
  (warmer). K comes from a ±60 mired shift around 6500 K. The filter is omitted
  at 0 because 6500 K blackbody is not an identity multiply.

Neutral clips add no filters, so the existing scale/fade chain stays unchanged.
Grade filters run before scale and before fades, so a fade still goes to black
and a crossfade blends already graded segment frames.

Preview is a browser approximation, not a pixel match:

- CSS ``brightness(2^EV)`` matches the measured ``exposure`` multiply.
- CSS ``contrast()`` uses the same pivot-0.5 factor, but per sRGB channel.
  ffmpeg ``eq`` applies contrast in YUV, so color (not the direction) differs.
- CSS ``saturate()`` follows the same 0…2 factor; luma coefficients differ.
- Warmth uses an SVG ``feColorMatrix`` in sRGB with the same peak-normalized
  blackbody gains as ``colortemperature`` (Tanner Helland). On ffmpeg 7.1,
  rgb(127, 95, 63) at 4800 K becomes (127, 83, 49); the matrix matches that.
  CSS applies filters right-to-left, so the matrix URL is last (applied first),
  then brightness, contrast, and saturation.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from orga_drone.studio_hud import sibling_srt

_COLOR_MD_RE = re.compile(r"\[color_md:\s*([^\]]+)\]", re.IGNORECASE)

SLIDER_MIN = -100
SLIDER_MAX = 100

# Full-scale slider (±100) distances. Kept small enough for overcast footage.
EXPOSURE_EV_AT_FULL = 1.0
CONTRAST_DELTA_AT_FULL = 0.5
SATURATION_DELTA_AT_FULL = 1.0
WARMTH_MIRED_AT_FULL = 60.0
NEUTRAL_KELVIN = 6500.0

IMAGE_KEYS = (
    "exposure",
    "contrast",
    "saturation",
    "warmth",
    "highlights",
    "shadows",
    "blacks",
)

# Restrained colorlevels travel at full slider (±100). Does not recover clipped data.
HIGHLIGHTS_MAX_DELTA = 0.12
SHADOWS_MIN_DELTA = 0.10
BLACKS_MIN_DELTA = 0.08


@dataclass(frozen=True)
class ImageAdjust:
    """Validated slider positions. 0 is the current ungraded picture."""

    exposure: int = 0
    contrast: int = 0
    saturation: int = 0
    warmth: int = 0
    highlights: int = 0
    shadows: int = 0
    blacks: int = 0

    @property
    def is_neutral(self) -> bool:
        return (
            self.exposure == 0
            and self.contrast == 0
            and self.saturation == 0
            and self.warmth == 0
            and self.highlights == 0
            and self.shadows == 0
            and self.blacks == 0
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "exposure": self.exposure,
            "contrast": self.contrast,
            "saturation": self.saturation,
            "warmth": self.warmth,
            "highlights": self.highlights,
            "shadows": self.shadows,
            "blacks": self.blacks,
        }


def image_adjust_preview_model() -> dict[str, float]:
    """Numeric ranges the Studio page passes to the preview script."""
    return {
        "exposureEvAtFull": EXPOSURE_EV_AT_FULL,
        "contrastDeltaAtFull": CONTRAST_DELTA_AT_FULL,
        "saturationDeltaAtFull": SATURATION_DELTA_AT_FULL,
        "warmthMiredAtFull": WARMTH_MIRED_AT_FULL,
        "neutralKelvin": NEUTRAL_KELVIN,
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


def _read_stored_slider(value: object) -> int:
    """Corrupt or out-of-range stored data renders as neutral."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    number = float(value)
    if not math.isfinite(number) or number < SLIDER_MIN or number > SLIDER_MAX:
        return 0
    return _round_half_away_from_zero(number)


def image_adjust_from_effect_settings(raw: str | None) -> ImageAdjust:
    """Missing, empty, or invalid JSON is the neutral grade."""
    if raw is None or not str(raw).strip():
        return ImageAdjust()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ImageAdjust()
    if not isinstance(data, dict):
        return ImageAdjust()
    image = data.get("image", {})
    if not isinstance(image, dict):
        return ImageAdjust()
    return ImageAdjust(
        exposure=_read_stored_slider(image.get("exposure")),
        contrast=_read_stored_slider(image.get("contrast")),
        saturation=_read_stored_slider(image.get("saturation")),
        warmth=_read_stored_slider(image.get("warmth")),
        highlights=_read_stored_slider(image.get("highlights")),
        shadows=_read_stored_slider(image.get("shadows")),
        blacks=_read_stored_slider(image.get("blacks")),
    )


def parse_image_adjust_patch(
    payload: Mapping[str, object],
    current: ImageAdjust,
) -> ImageAdjust:
    """Merge a partial update. Unknown keys are ignored. Bad values raise."""
    if not any(key in payload for key in IMAGE_KEYS):
        raise ValueError("JSON body must include an image adjustment")
    updates: dict[str, int] = {}
    for key in IMAGE_KEYS:
        if key not in payload:
            continue
        updates[key] = _parse_slider(payload[key], key)
    return replace(current, **updates)


def image_adjust_from_export_payload(payload: Mapping[str, object] | None) -> ImageAdjust:
    """Sliders for one photo export. Omitted keys stay at 0.

    A missing adjustment is neutral, so older clients keep today's file.
    A present key that is not a number from -100 to 100 raises ValueError.
    """
    if not isinstance(payload, Mapping):
        return ImageAdjust()
    nested = payload.get("image")
    source: Mapping[str, object] = nested if isinstance(nested, Mapping) else payload
    if not any(key in source for key in IMAGE_KEYS):
        return ImageAdjust()
    values: dict[str, int] = {}
    for key in IMAGE_KEYS:
        if key not in source:
            values[key] = 0
            continue
        values[key] = _parse_slider(source[key], key)
    return ImageAdjust(**values)


def export_payload_sets_adjust(payload: Mapping[str, object] | None) -> bool:
    """True when the export body includes at least one slider."""
    if not isinstance(payload, Mapping):
        return False
    nested = payload.get("image")
    source: Mapping[str, object] = nested if isinstance(nested, Mapping) else payload
    return any(key in source for key in IMAGE_KEYS)


def image_adjust_from_stored(raw: str | None) -> ImageAdjust:
    """Read a saved photo grade. Missing or corrupt JSON is neutral."""
    if raw is None or not str(raw).strip():
        return ImageAdjust()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ImageAdjust()
    if not isinstance(data, dict):
        return ImageAdjust()
    nested = data.get("image")
    source = nested if isinstance(nested, dict) else data
    return ImageAdjust(
        exposure=_read_stored_slider(source.get("exposure")),
        contrast=_read_stored_slider(source.get("contrast")),
        saturation=_read_stored_slider(source.get("saturation")),
        warmth=_read_stored_slider(source.get("warmth")),
        highlights=_read_stored_slider(source.get("highlights")),
        shadows=_read_stored_slider(source.get("shadows")),
        blacks=_read_stored_slider(source.get("blacks")),
    )


def dump_effect_settings(existing: str | None, image: ImageAdjust) -> str:
    """Write the image object and keep unrelated effect_settings keys."""
    data: dict[str, object]
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data["image"] = image.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _fmt(value: float) -> str:
    return f"{value:.4f}"


def kelvin_for_warmth(warmth: int) -> int:
    """Map a warmth slider to Kelvin. Positive is warmer (lower Kelvin)."""
    neutral_mired = 1_000_000.0 / NEUTRAL_KELVIN
    mired = neutral_mired + (float(warmth) / 100.0) * WARMTH_MIRED_AT_FULL
    kelvin = 1_000_000.0 / mired
    clamped = min(40_000.0, max(1_000.0, kelvin))
    return int(round(clamped))


def blackbody_channel_gains(kelvin: float) -> tuple[float, float, float]:
    """Peak-normalized blackbody RGB. Matches ffmpeg ``colortemperature``.

    Coefficients are Tanner Helland's approximation, then divided by the peak
    channel so a neutral gray keeps its brightest channel. That is what
    ffmpeg 7.1 does with ``pl=0``.
    """
    temp = float(kelvin) / 100.0
    if temp <= 66.0:
        red = 255.0
        green = 99.4708025861 * math.log(temp) - 161.1195681661
        if temp <= 19.0:
            blue = 0.0
        else:
            blue = 138.5177312231 * math.log(temp - 10.0) - 305.0447927307
    else:
        red = 329.698727446 * (temp - 60.0) ** -0.1332047592
        green = 288.1221695283 * (temp - 60.0) ** -0.0755148492
        blue = 255.0
    red = min(255.0, max(0.0, red))
    green = min(255.0, max(0.0, green))
    blue = min(255.0, max(0.0, blue))
    peak = max(red, green, blue) or 1.0
    return (red / peak, green / peak, blue / peak)


def exposure_ev(image: ImageAdjust) -> float:
    return (image.exposure / 100.0) * EXPOSURE_EV_AT_FULL


def contrast_factor(image: ImageAdjust) -> float:
    return 1.0 + (image.contrast / 100.0) * CONTRAST_DELTA_AT_FULL


def saturation_factor(image: ImageAdjust) -> float:
    return 1.0 + (image.saturation / 100.0) * SATURATION_DELTA_AT_FULL


def _colorlevels_chain(image: ImageAdjust) -> str:
    """Restrained shadows / highlights / blacks via ``colorlevels``.

    Positive highlights lower the upper bound (compress bright areas). Positive
    shadows raise the lower bound (lift dark areas). Positive blacks raise the
    floor further. Negative values move in the opposite direction. Values stay
    inside a safe range so clipped data is not claimed to be recovered.
    """
    if image.highlights == 0 and image.shadows == 0 and image.blacks == 0:
        return ""
    # Lower input bound: shadows + blacks contribute; clamp away from collapse.
    imin = 0.0
    imin += (image.shadows / 100.0) * SHADOWS_MIN_DELTA
    imin += (image.blacks / 100.0) * BLACKS_MIN_DELTA
    imin = min(0.35, max(0.0, imin))
    # Upper input bound: positive highlights pull max down.
    imax = 1.0 - (image.highlights / 100.0) * HIGHLIGHTS_MAX_DELTA
    imax = min(1.0, max(imin + 0.2, imax))
    level = (
        f"rimin={_fmt(imin)}:gimin={_fmt(imin)}:bimin={_fmt(imin)}:"
        f"rimax={_fmt(imax)}:gimax={_fmt(imax)}:bimax={_fmt(imax)}"
    )
    return f"colorlevels={level}"


def ffmpeg_grade_chain(image: ImageAdjust) -> str:
    """ffmpeg filter fragment, or an empty string when the clip stays ungraded.

    Only formatted numbers from the validated sliders are interpolated.
    Order: warmth → exposure → eq contrast/saturation → colorlevels tonal.
    """
    if image.is_neutral:
        return ""
    parts: list[str] = []
    if image.warmth != 0:
        parts.append(f"colortemperature=temperature={kelvin_for_warmth(image.warmth)}")
    if image.exposure != 0:
        parts.append(f"exposure=exposure={_fmt(exposure_ev(image))}")
    eq_bits: list[str] = []
    if image.contrast != 0:
        eq_bits.append(f"contrast={_fmt(contrast_factor(image))}")
    if image.saturation != 0:
        eq_bits.append(f"saturation={_fmt(saturation_factor(image))}")
    if eq_bits:
        parts.append("eq=" + ":".join(eq_bits))
    tonal = _colorlevels_chain(image)
    if tonal:
        parts.append(tonal)
    return ",".join(parts)


def preview_css_functions(image: ImageAdjust) -> str:
    """CSS filter functions, excluding the warmth matrix URL.

    Order is right-to-left in the browser: brightness, then contrast, then
    saturation. Callers append ``url(#...)`` last so warmth is applied first.
    Highlights / shadows / blacks are a coarse brightness+contrast approx of
    the export ``colorlevels`` stage — not pixel-identical.
    """
    if image.is_neutral:
        return ""
    parts: list[str] = []
    if image.saturation != 0:
        parts.append(f"saturate({_fmt(saturation_factor(image))})")
    contrast = contrast_factor(image)
    # Lifted shadows / blacks read slightly softer; crushed highlights slightly harder.
    contrast += (image.highlights / 100.0) * 0.08
    contrast -= (image.shadows / 100.0) * 0.05
    contrast -= (image.blacks / 100.0) * 0.04
    contrast = min(1.6, max(0.4, contrast))
    if abs(contrast - 1.0) > 0.0005:
        parts.append(f"contrast({_fmt(contrast)})")
    brightness = 2.0 ** exposure_ev(image)
    brightness += (image.shadows / 100.0) * 0.06
    brightness += (image.blacks / 100.0) * 0.04
    brightness -= (image.highlights / 100.0) * 0.05
    brightness = min(2.2, max(0.5, brightness))
    if abs(brightness - 1.0) > 0.0005:
        parts.append(f"brightness({_fmt(brightness)})")
    return " ".join(parts)


def preview_matrix_values(image: ImageAdjust) -> str:
    """``feColorMatrix`` values for warmth. Identity when warmth is 0."""
    if image.warmth == 0:
        red, green, blue = 1.0, 1.0, 1.0
    else:
        red, green, blue = blackbody_channel_gains(kelvin_for_warmth(image.warmth))
    return (
        f"{red:.6f} 0 0 0 0 "
        f"0 {green:.6f} 0 0 0 "
        f"0 0 {blue:.6f} 0 0 "
        "0 0 0 1 0"
    )


# Issue #109. One linear saturation ramp per video clip, stored beside the
# grade. 100% keeps that grade's saturation; 0% is black and white. Times are
# seconds into the trimmed clip. Missing JSON leaves the grade unchanged.
PERCENT_MIN = 0
PERCENT_MAX = 100
TIME_MIN_S = -86_400.0
TIME_MAX_S = 86_400.0
MIN_RAMP_SPAN_S = 0.001
RAMP_KEY = "saturation_ramp"


@dataclass(frozen=True)
class SaturationRamp:
    """Clip-relative saturation multiplier. Disabled leaves the grade alone."""

    enabled: bool = False
    start_s: float = 0.0
    end_s: float = 0.0
    start_saturation: int = 100
    end_saturation: int = 0

    @property
    def is_active(self) -> bool:
        """True when export and preview should move saturation over time."""
        return self.enabled and (self.end_s - self.start_s) > MIN_RAMP_SPAN_S

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "start_saturation": self.start_saturation,
            "end_saturation": self.end_saturation,
        }


def _parse_percent(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number from 0 to 100")
    number = float(value)
    if not math.isfinite(number) or number < PERCENT_MIN or number > PERCENT_MAX:
        raise ValueError(f"{key} must be a number from 0 to 100")
    return _round_half_away_from_zero(number)


def _parse_ramp_time(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a time in seconds")
    number = float(value)
    if not math.isfinite(number) or number < TIME_MIN_S or number > TIME_MAX_S:
        raise ValueError(f"{key} must be a time in seconds")
    return round(number, 4)


def _read_percent(value: object, default: int) -> int:
    try:
        return _parse_percent(value, "saturation")
    except ValueError:
        return default


def _read_ramp_time(value: object) -> float:
    try:
        return _parse_ramp_time(value, "time")
    except ValueError:
        return 0.0


def saturation_ramp_from_effect_settings(raw: str | None) -> SaturationRamp:
    """Missing or invalid JSON is an off ramp. The grade stays as stored."""
    if raw is None or not str(raw).strip():
        return SaturationRamp()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return SaturationRamp()
    if not isinstance(data, dict):
        return SaturationRamp()
    ramp = data.get(RAMP_KEY, {})
    if not isinstance(ramp, dict):
        return SaturationRamp()
    enabled = ramp.get("enabled", False)
    return SaturationRamp(
        enabled=enabled if isinstance(enabled, bool) else False,
        start_s=_read_ramp_time(ramp.get("start_s", 0)),
        end_s=_read_ramp_time(ramp.get("end_s", 0)),
        start_saturation=_read_percent(ramp.get("start_saturation", 100), 100),
        end_saturation=_read_percent(ramp.get("end_saturation", 0), 0),
    )


def parse_saturation_ramp_payload(payload: Mapping[str, object]) -> SaturationRamp:
    """Replace the clip ramp. Bad numbers raise. A zero-length range cannot be on."""
    body = payload.get(RAMP_KEY, payload)
    if not isinstance(body, dict) or "enabled" not in body:
        raise ValueError("JSON body must include a saturation ramp")
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    ramp = SaturationRamp(
        enabled=enabled,
        start_s=_parse_ramp_time(body.get("start_s", 0), "start_s"),
        end_s=_parse_ramp_time(body.get("end_s", 0), "end_s"),
        start_saturation=_parse_percent(
            body.get("start_saturation", 100), "start_saturation"
        ),
        end_saturation=_parse_percent(body.get("end_saturation", 0), "end_saturation"),
    )
    if ramp.enabled and not ramp.is_active:
        raise ValueError("color change needs a longer range")
    return ramp


def dump_saturation_ramp(existing: str | None, ramp: SaturationRamp) -> str:
    """Write the ramp and keep unrelated effect_settings keys, including image."""
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data[RAMP_KEY] = ramp.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def shift_saturation_ramp_settings(raw: str | None, delta_s: float) -> str:
    """Move ramp times by ``-delta_s``. JSON without a ramp is returned unchanged.

    A split keeps the left clip's times. The right clip's local 0 is the cut,
    so its stored times shift by the cut offset and the picture stays continuous.
    """
    text = raw if raw else "{}"
    try:
        parsed = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return text
    if not isinstance(parsed, dict) or RAMP_KEY not in parsed:
        return text
    ramp = saturation_ramp_from_effect_settings(text)
    shifted = replace(
        ramp,
        start_s=round(ramp.start_s - float(delta_s), 4),
        end_s=round(ramp.end_s - float(delta_s), 4),
    )
    return dump_saturation_ramp(text, shifted)


def saturation_multiplier(ramp: SaturationRamp, local_s: float) -> float:
    """1 keeps the graded saturation. 0 is black and white.

    Before the start time the clip holds the start level. After the end time
    it holds the end level. A disabled or zero-length ramp returns 1.
    """
    if not ramp.is_active:
        return 1.0
    start_m = ramp.start_saturation / 100.0
    end_m = ramp.end_saturation / 100.0
    if ramp.start_saturation == ramp.end_saturation:
        return start_m
    local = float(local_s)
    if local <= ramp.start_s:
        return start_m
    if local >= ramp.end_s:
        return end_m
    span = ramp.end_s - ramp.start_s
    progress = (local - ramp.start_s) / span
    return start_m + (end_m - start_m) * progress


def ffmpeg_saturation_ramp(ramp: SaturationRamp, *, origin_s: float) -> str:
    """``hue`` saturation fragment, or empty when the clip stays on its grade.

    The multiplier runs after the grade, so brightness, contrast, warmth, and
    the static saturation slider still apply and then fade toward the target.
    Only formatted numbers are interpolated. Video segments seek with input
    ``-ss``, so clip-relative time is filter ``t`` (origin 0 at the kept in-point).
    """
    if not ramp.is_active:
        return ""
    if ramp.start_saturation == 100 and ramp.end_saturation == 100:
        return ""
    start_m = ramp.start_saturation / 100.0
    end_m = ramp.end_saturation / 100.0
    if ramp.start_saturation == ramp.end_saturation:
        return f"hue=s={_fmt(start_m)}"
    origin = max(0.0, float(origin_s))
    local = f"(t-{_fmt(origin)})"
    start_s = _fmt(ramp.start_s)
    end_s = _fmt(ramp.end_s)
    span = _fmt(ramp.end_s - ramp.start_s)
    delta = _fmt(end_m - start_m)
    expr = (
        f"if(lte({local}\\,{start_s})\\,{_fmt(start_m)}\\,"
        f"if(gte({local}\\,{end_s})\\,{_fmt(end_m)}\\,"
        f"{_fmt(start_m)}+({delta})*({local}-{start_s})/{span}))"
    )
    return f"hue=s='{expr}'"


def color_profile_hint_from_srt(media_path: Path | None) -> str | None:
    """Read ``color_md`` from a sibling DJI SRT when present. Hint only — no grade."""
    if media_path is None:
        return None
    srt = sibling_srt(media_path)
    if srt is None:
        return None
    try:
        sample = srt.read_text(encoding="utf-8", errors="ignore")[:8192]
    except OSError:
        return None
    match = _COLOR_MD_RE.search(sample)
    if not match:
        return None
    token = match.group(1).strip()
    return token or None
