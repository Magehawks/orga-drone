"""Limited color points on a Studio video clip (Issue #211 PR2).

Versioned ``color_animation`` in ``effect_settings``. Outside the color bar the
static ``image`` grade applies. Inside, absolute keyed exposure / contrast /
saturation / warmth replace those four fields (linear). Missing JSON is
neutral. Presets generate points; switching to Manual keeps them. Not a
general NLE keyframe editor — max 8 points, video only, no Bézier.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import Mapping

from orga_drone.studio_image import (
    SLIDER_MAX,
    SLIDER_MIN,
    ImageAdjust,
    image_adjust_from_effect_settings,
)

COLOR_ANIM_KEY = "color_animation"
COLOR_BAR_KIND = "color"
MAX_KEYS = 8
MIN_KEY_GAP_S = 0.1
MIN_BAR_SPAN_S = 0.05
SCHEMA_VERSION = 1

PRESET_IDS = (
    "warm_up",
    "cool_down",
    "color_boost",
    "calm_down",
    "brighten",
    "dim",
)

# Absolute end values for presets (start is always 0 on all four).
_PRESET_ENDS: dict[str, dict[str, int]] = {
    "warm_up": {"exposure": 8, "contrast": 0, "saturation": 0, "warmth": 35},
    "cool_down": {"exposure": 0, "contrast": 0, "saturation": 0, "warmth": -35},
    "color_boost": {"exposure": 0, "contrast": 10, "saturation": 30, "warmth": 0},
    "calm_down": {"exposure": 0, "contrast": 0, "saturation": -25, "warmth": 0},
    "brighten": {"exposure": 25, "contrast": 0, "saturation": 0, "warmth": 0},
    "dim": {"exposure": -25, "contrast": 10, "saturation": 0, "warmth": 0},
}


@dataclass(frozen=True)
class ColorKey:
    t: float
    exposure: int = 0
    contrast: int = 0
    saturation: int = 0
    warmth: int = 0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "t": self.t,
            "exposure": self.exposure,
            "contrast": self.contrast,
            "saturation": self.saturation,
            "warmth": self.warmth,
        }


@dataclass(frozen=True)
class ColorAnimation:
    """Clip-relative color bar + points. Empty / inactive = no animation."""

    v: int = SCHEMA_VERSION
    mode: str = "manual"  # preset | manual
    preset_id: str | None = None
    interp: str = "linear"
    bar_start_s: float = 0.0
    bar_end_s: float = 0.0
    keys: tuple[ColorKey, ...] = ()

    @property
    def is_active(self) -> bool:
        return (
            len(self.keys) >= 2
            and (self.bar_end_s - self.bar_start_s) >= MIN_BAR_SPAN_S
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "v": self.v,
            "mode": self.mode,
            "preset_id": self.preset_id,
            "interp": self.interp,
            "bar": {"start_s": self.bar_start_s, "end_s": self.bar_end_s},
            "keys": [key.as_dict() for key in self.keys],
        }


def _clamp_slider(value: int) -> int:
    return max(SLIDER_MIN, min(SLIDER_MAX, int(value)))


def _read_slider(value: object, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    if not math.isfinite(number):
        return default
    return _clamp_slider(round(number))


def _read_time(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    if not math.isfinite(number):
        return default
    return round(number, 4)


def _parse_key(raw: object) -> ColorKey | None:
    if not isinstance(raw, dict):
        return None
    return ColorKey(
        t=_read_time(raw.get("t", 0)),
        exposure=_read_slider(raw.get("exposure", 0)),
        contrast=_read_slider(raw.get("contrast", 0)),
        saturation=_read_slider(raw.get("saturation", 0)),
        warmth=_read_slider(raw.get("warmth", 0)),
    )


def color_animation_from_effect_settings(raw: str | None) -> ColorAnimation:
    """Missing or invalid → inactive (compat with older projects)."""
    if raw is None or not str(raw).strip():
        return ColorAnimation()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ColorAnimation()
    if not isinstance(data, dict):
        return ColorAnimation()
    blob = data.get(COLOR_ANIM_KEY)
    if not isinstance(blob, dict):
        return ColorAnimation()
    bar = blob.get("bar")
    if not isinstance(bar, dict):
        bar = {}
    start = _read_time(bar.get("start_s", 0))
    end = _read_time(bar.get("end_s", 0))
    if end < start:
        start, end = end, start
    keys: list[ColorKey] = []
    raw_keys = blob.get("keys")
    if isinstance(raw_keys, list):
        for item in raw_keys[:MAX_KEYS]:
            key = _parse_key(item)
            if key is not None:
                keys.append(key)
    keys.sort(key=lambda item: item.t)
    mode = str(blob.get("mode") or "manual")
    if mode not in {"preset", "manual"}:
        mode = "manual"
    preset = blob.get("preset_id")
    preset_id = str(preset) if isinstance(preset, str) and preset in PRESET_IDS else None
    interp = str(blob.get("interp") or "linear")
    if interp not in {"linear", "ease_in_out"}:
        interp = "linear"
    try:
        version = int(blob.get("v", SCHEMA_VERSION))
    except (TypeError, ValueError):
        version = SCHEMA_VERSION
    return ColorAnimation(
        v=version if version > 0 else SCHEMA_VERSION,
        mode=mode,
        preset_id=preset_id,
        interp=interp,
        bar_start_s=start,
        bar_end_s=end,
        keys=tuple(keys),
    )


def dump_color_animation(existing: str | None, anim: ColorAnimation) -> str:
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    if not anim.is_active and not anim.keys:
        data.pop(COLOR_ANIM_KEY, None)
    else:
        data[COLOR_ANIM_KEY] = anim.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def build_preset(
    preset_id: str,
    *,
    bar_start_s: float,
    bar_end_s: float,
) -> ColorAnimation:
    """Deterministic two-point preset. Not AI."""
    if preset_id not in _PRESET_ENDS:
        raise ValueError("unknown color preset")
    start = round(float(bar_start_s), 4)
    end = round(float(bar_end_s), 4)
    if end < start:
        start, end = end, start
    if end - start < MIN_BAR_SPAN_S:
        raise ValueError("color change needs a longer range")
    ends = _PRESET_ENDS[preset_id]
    keys = (
        ColorKey(t=start),
        ColorKey(
            t=end,
            exposure=ends["exposure"],
            contrast=ends["contrast"],
            saturation=ends["saturation"],
            warmth=ends["warmth"],
        ),
    )
    return ColorAnimation(
        mode="preset",
        preset_id=preset_id,
        bar_start_s=start,
        bar_end_s=end,
        keys=keys,
    )


def parse_color_animation_payload(payload: Mapping[str, object]) -> ColorAnimation:
    """Validate a client payload. Raises ValueError on bad input."""
    body = payload.get(COLOR_ANIM_KEY, payload)
    if not isinstance(body, dict):
        raise ValueError("JSON body must include a color animation")
    if body.get("clear") is True:
        return ColorAnimation()
    preset = body.get("preset_id")
    bar = body.get("bar")
    if not isinstance(bar, dict):
        raise ValueError("bar with start_s and end_s is required")
    start = _read_time(bar.get("start_s", 0))
    end = _read_time(bar.get("end_s", 0))
    if end < start:
        start, end = end, start
    if end - start < MIN_BAR_SPAN_S:
        raise ValueError("color change needs a longer range")
    if isinstance(preset, str) and preset in PRESET_IDS and "keys" not in body:
        return build_preset(preset, bar_start_s=start, bar_end_s=end)
    raw_keys = body.get("keys")
    if not isinstance(raw_keys, list) or len(raw_keys) < 2:
        raise ValueError("at least two color points are required")
    if len(raw_keys) > MAX_KEYS:
        raise ValueError(f"at most {MAX_KEYS} color points")
    keys: list[ColorKey] = []
    for item in raw_keys:
        key = _parse_key(item)
        if key is None:
            raise ValueError("invalid color point")
        if key.t < start - 1e-3 or key.t > end + 1e-3:
            raise ValueError("color points must lie inside the bar")
        keys.append(key)
    keys.sort(key=lambda item: item.t)
    for left, right in zip(keys, keys[1:]):
        if right.t - left.t < MIN_KEY_GAP_S - 1e-6 and right.t != left.t:
            # Allow exact duplicates only if collapsed; otherwise enforce gap.
            if abs(right.t - left.t) > 1e-6:
                raise ValueError(f"color points need at least {MIN_KEY_GAP_S}s gap")
    # Deduplicate exact times by keeping the later definition.
    dedup: dict[float, ColorKey] = {}
    for key in keys:
        dedup[key.t] = key
    ordered = tuple(sorted(dedup.values(), key=lambda item: item.t))
    if len(ordered) < 2:
        raise ValueError("at least two color points are required")
    mode = str(body.get("mode") or "manual")
    if mode not in {"preset", "manual"}:
        mode = "manual"
    preset_id = (
        str(preset) if isinstance(preset, str) and preset in PRESET_IDS else None
    )
    if mode == "manual":
        preset_id = None
    interp = str(body.get("interp") or "linear")
    if interp not in {"linear", "ease_in_out"}:
        interp = "linear"
    return ColorAnimation(
        mode=mode,
        preset_id=preset_id,
        interp=interp,
        bar_start_s=start,
        bar_end_s=end,
        keys=ordered,
    )


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def _ease(u: float, interp: str) -> float:
    t = max(0.0, min(1.0, float(u)))
    if interp == "ease_in_out":
        return t * t * (3.0 - 2.0 * t)
    return t


def _interp_key(a: ColorKey, b: ColorKey, u: float, interp: str) -> ColorKey:
    w = _ease(u, interp)
    return ColorKey(
        t=_lerp(a.t, b.t, w),
        exposure=_clamp_slider(round(_lerp(a.exposure, b.exposure, w))),
        contrast=_clamp_slider(round(_lerp(a.contrast, b.contrast, w))),
        saturation=_clamp_slider(round(_lerp(a.saturation, b.saturation, w))),
        warmth=_clamp_slider(round(_lerp(a.warmth, b.warmth, w))),
    )


def keyed_sliders_at(anim: ColorAnimation, local_s: float) -> ColorKey | None:
    """Absolute four-slider values inside the bar, else None (use static image)."""
    if not anim.is_active:
        return None
    t = float(local_s)
    if t < anim.bar_start_s - 1e-3 or t > anim.bar_end_s + 1e-3:
        return None
    keys = list(anim.keys)
    if t <= keys[0].t:
        return keys[0]
    if t >= keys[-1].t:
        return keys[-1]
    for left, right in zip(keys, keys[1:]):
        if left.t <= t <= right.t:
            span = right.t - left.t
            if span <= 1e-9:
                return right
            u = (t - left.t) / span
            return _interp_key(left, right, u, anim.interp)
    return keys[-1]


def image_adjust_at(raw: str | None, local_s: float) -> ImageAdjust:
    """Static image, overridden by keyed exposure/contrast/saturation/warmth."""
    base = image_adjust_from_effect_settings(raw)
    anim = color_animation_from_effect_settings(raw)
    keyed = keyed_sliders_at(anim, local_s)
    if keyed is None:
        return base
    return replace(
        base,
        exposure=keyed.exposure,
        contrast=keyed.contrast,
        saturation=keyed.saturation,
        warmth=keyed.warmth,
    )


def shift_color_animation_settings(raw: str | None, delta_s: float) -> str:
    """Shift bar and keys by ``-delta_s`` (same pattern as saturation ramp)."""
    text = raw if raw else "{}"
    try:
        parsed = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return text
    if not isinstance(parsed, dict) or COLOR_ANIM_KEY not in parsed:
        return text
    anim = color_animation_from_effect_settings(text)
    if not anim.keys and not anim.is_active:
        return text
    delta = float(delta_s)
    shifted_keys = tuple(
        replace(key, t=round(key.t - delta, 4)) for key in anim.keys
    )
    shifted = replace(
        anim,
        bar_start_s=round(anim.bar_start_s - delta, 4),
        bar_end_s=round(anim.bar_end_s - delta, 4),
        keys=shifted_keys,
    )
    return dump_color_animation(text, shifted)


def color_bar(raw: str | None) -> tuple[float, float] | None:
    anim = color_animation_from_effect_settings(raw)
    if not anim.is_active:
        return None
    return anim.bar_start_s, anim.bar_end_s


def segment_boundaries(anim: ColorAnimation) -> list[float]:
    """Clip-relative times where the grade becomes piecewise constant."""
    if not anim.is_active:
        return []
    points = {anim.bar_start_s, anim.bar_end_s}
    for key in anim.keys:
        if anim.bar_start_s - 1e-3 <= key.t <= anim.bar_end_s + 1e-3:
            points.add(key.t)
    return sorted(points)


def color_animation_preview_model() -> dict[str, object]:
    return {
        "maxKeys": MAX_KEYS,
        "minKeyGapS": MIN_KEY_GAP_S,
        "presets": [
            {"id": "warm_up", "label_en": "Warm up", "label_de": "Aufwärmen"},
            {"id": "cool_down", "label_en": "Cool down", "label_de": "Abkühlen"},
            {"id": "color_boost", "label_en": "Color boost", "label_de": "Farbschub"},
            {"id": "calm_down", "label_en": "Calm down", "label_de": "Beruhigen"},
            {"id": "brighten", "label_en": "Brighten", "label_de": "Aufhellen"},
            {"id": "dim", "label_en": "Dim", "label_de": "Abdunkeln"},
        ],
    }


def apply_keyed_image(base: ImageAdjust, anim: ColorAnimation | None, local_s: float) -> ImageAdjust:
    """Static grade with keyed overrides inside the color bar."""
    if anim is None or not anim.is_active:
        return base
    keyed = keyed_sliders_at(anim, local_s)
    if keyed is None:
        return base
    return replace(
        base,
        exposure=keyed.exposure,
        contrast=keyed.contrast,
        saturation=keyed.saturation,
        warmth=keyed.warmth,
    )


def expand_export_clip_for_color(clip: object) -> list[object]:
    """Split a video export clip into piecewise-constant grade pieces.

    ``clip`` is a ``StudioExportClip``. Import is deferred to avoid cycles.
    """
    from orga_drone.export.studio_config import StudioExportClip

    if not isinstance(clip, StudioExportClip):
        return [clip]
    anim = clip.color_animation
    if (
        anim is None
        or not anim.is_active
        or clip.kind != "video"
        or clip.source_end_s is None
        or clip.section_repeats > 1
        or clip.forward_loop
    ):
        return [clip]
    origin = float(clip.source_start_s)
    total = float(clip.source_end_s) - origin
    if total < MIN_BAR_SPAN_S:
        return [clip]
    cuts = [0.0]
    for boundary in segment_boundaries(anim):
        if 0.0 < boundary < total:
            cuts.append(boundary)
    cuts.append(total)
    cuts = sorted(set(round(value, 4) for value in cuts))
    pieces: list[StudioExportClip] = []
    speed = float(clip.playback_speed) or 1.0
    for begin, finish in zip(cuts, cuts[1:]):
        if finish - begin < 0.05:
            continue
        # Midpoint holds a constant grade that tracks the linear curve.
        sample_t = (begin + finish) * 0.5
        image = apply_keyed_image(clip.image, anim, sample_t)
        pieces.append(
            replace(
                clip,
                source_start_s=origin + begin,
                source_end_s=origin + finish,
                duration_s=(finish - begin) / speed,
                image=image,
                color_animation=None,
            )
        )
    return pieces or [clip]
