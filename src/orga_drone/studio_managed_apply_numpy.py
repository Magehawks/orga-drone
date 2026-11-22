"""NumPy-accelerated managed grade apply with Python-oracle semantics (#553)."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from typing import Any

Rgb = tuple[float, float, float]

# Soft feather + primaries/HSL near clipped whites can differ slightly; mean stays tiny.
NUMPY_APPLY_PARITY_MAX_ABS = 1.5e-1
NUMPY_APPLY_PARITY_MEAN_ABS = 1e-4
_SUPPORTED_STEPS = frozenset({"primaries-v1", "managed-hsl-v1", "wheels-v1"})


def numpy_apply_enabled() -> bool:
    raw = os.getenv("ORGA_MANAGED_APPLY_BACKEND", "auto").strip().lower()
    if raw in {"python", "oracle", "ref", "reference"}:
        return False
    if raw in {"numpy", "auto", ""}:
        try:
            import numpy as np  # noqa: F401
        except ImportError:
            return False
        return True
    return False


def _decode_bt709_np(encoded: Any) -> Any:
    import numpy as np

    x = np.asarray(encoded, dtype=np.float64)
    return np.where(x < 0.081, x / 4.5, ((x + 0.099) / 1.099) ** (1.0 / 0.45))


def _encode_bt709_np(linear: Any) -> Any:
    import numpy as np

    x = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0)
    return np.where(x < 0.018, 4.5 * x, 1.099 * np.power(x, 0.45) - 0.099)


def _decode_srgb_np(encoded: Any) -> Any:
    import numpy as np

    x = np.asarray(encoded, dtype=np.float64)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _encode_srgb_np(linear: Any) -> Any:
    import numpy as np

    x = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def _to_domain_np(rgb: Any, *, current: str, target: str) -> Any:
    if current == target:
        return rgb
    if current == "linear-bt709":
        linear = rgb
    elif current in {"bt709-sdr", "encoded-bt709", "bt709"}:
        linear = _decode_bt709_np(rgb)
    elif current == "srgb":
        linear = _decode_srgb_np(rgb)
    else:
        raise ValueError(f"unsupported current domain {current}")
    if target == "linear-bt709":
        return linear
    if target in {"bt709-sdr", "encoded-bt709", "bt709"}:
        return _encode_bt709_np(linear)
    if target == "srgb":
        return _encode_srgb_np(linear)
    raise ValueError(f"unsupported target domain {target}")


def _blend_np(base: Any, processed: Any, factor: Any) -> Any:
    f = factor[..., None] if factor.ndim == 2 else factor
    return base + f * (processed - base)


def _managed_hsl_np(
    rgb: Any,
    *,
    hue_offset_deg: float,
    saturation_mult: float,
    lightness_offset: float,
) -> Any:
    import numpy as np

    # Fast path matching studio_managed_wheels.managed_hsl desaturate shortcut.
    if saturation_mult == 0.0 and hue_offset_deg == 0.0:
        lo = rgb.min(axis=-1)
        hi = rgb.max(axis=-1)
        lightness = np.clip(0.5 * (lo + hi) + lightness_offset, 0.0, 1.0)
        return np.stack([lightness, lightness, lightness], axis=-1)

    red = rgb[..., 0]
    green = rgb[..., 1]
    blue = rgb[..., 2]
    maximum = rgb.max(axis=-1)
    minimum = rgb.min(axis=-1)
    lightness = 0.5 * (maximum + minimum)
    delta = maximum - minimum
    saturation = np.zeros_like(lightness)
    denom = 1.0 - np.abs(2.0 * lightness - 1.0)
    valid = (delta > 1e-12) & (denom > 1e-12)
    saturation = np.where(valid, delta / np.maximum(denom, 1e-30), 0.0)

    hue = np.zeros_like(lightness)
    safe = np.maximum(delta, 1e-30)
    is_r = (maximum == red) & (delta > 1e-12)
    is_g = (maximum == green) & (delta > 1e-12) & ~is_r
    is_b = (delta > 1e-12) & ~is_r & ~is_g
    hue = np.where(is_r, ((green - blue) / safe) % 6.0, hue)
    hue = np.where(is_g, (blue - red) / safe + 2.0, hue)
    hue = np.where(is_b, (red - green) / safe + 4.0, hue)
    hue = hue * 60.0

    hue = (hue + hue_offset_deg) % 360.0
    saturation = np.clip(saturation * saturation_mult, 0.0, 1.0)
    lightness = np.clip(lightness + lightness_offset, 0.0, 1.0)
    return _hsl_to_rgb_np(hue, saturation, lightness)


def _hsl_to_rgb_np(hue: Any, saturation: Any, lightness: Any) -> Any:
    import numpy as np

    gray = saturation <= 1e-12
    channel2 = np.where(
        lightness < 0.5,
        lightness * (1.0 + saturation),
        lightness + saturation - lightness * saturation,
    )
    channel1 = 2.0 * lightness - channel2
    hue_norm = (hue % 360.0) / 360.0

    def channel(offset: float) -> Any:
        value = (hue_norm + offset) % 1.0
        # Piecewise like hsl_to_rgb.channel
        m1 = value < 1.0 / 6.0
        m2 = (value >= 1.0 / 6.0) & (value < 0.5)
        m3 = (value >= 0.5) & (value < 2.0 / 3.0)
        out = np.where(m1, channel1 + (channel2 - channel1) * 6.0 * value, channel1)
        out = np.where(m2, channel2, out)
        out = np.where(
            m3, channel1 + (channel2 - channel1) * 6.0 * (2.0 / 3.0 - value), out
        )
        return out

    rgb = np.stack(
        [channel(1.0 / 3.0), channel(0.0), channel(-1.0 / 3.0)],
        axis=-1,
    )
    lightness_clip = np.clip(lightness, 0.0, 1.0)
    gray_rgb = np.stack([lightness_clip, lightness_clip, lightness_clip], axis=-1)
    return np.where(gray[..., None], gray_rgb, rgb)


def _primaries_np(
    rgb: Any,
    *,
    exposure: float,
    kelvin: float,
    tint: float,
    contrast: float,
    pivot: float,
    saturation: float,
    blacks: float,
    shadows: float,
    highlights: float,
    whites: float,
) -> Any:
    import numpy as np

    from orga_drone.studio_managed_primaries import (
        kelvin_tint_to_gains,
        tone_controls_to_curve,
    )

    factor = 2.0**exposure
    exposed = rgb * factor
    gains = kelvin_tint_to_gains(kelvin, tint)
    weighted = 0.2126 * gains[0] + 0.7152 * gains[1] + 0.0722 * gains[2]
    scale = 1.0 / weighted
    balanced = exposed * np.array(
        [gains[0] * scale, gains[1] * scale, gains[2] * scale], dtype=np.float64
    )

    # Contrast: pivot * sign(ratio)*abs(ratio)**amount
    if contrast == 0.0:
        contrasted = np.copysign(pivot, balanced)
        contrasted = np.where(balanced == 0.0, 0.0, contrasted)
    else:
        ratio = balanced / pivot
        contrasted = pivot * np.copysign(np.abs(ratio) ** contrast, ratio)

    curve = tone_controls_to_curve(
        blacks=blacks, shadows=shadows, highlights=highlights, whites=whites
    )
    xs = np.array([p[0] for p in curve], dtype=np.float64)
    ys = np.array([p[1] for p in curve], dtype=np.float64)
    luma = (
        0.2126 * contrasted[..., 0]
        + 0.7152 * contrasted[..., 1]
        + 0.0722 * contrasted[..., 2]
    )
    mapped = np.interp(luma, xs, ys)
    delta = mapped - luma
    toned = contrasted + delta[..., None]

    luma2 = (
        0.2126 * toned[..., 0] + 0.7152 * toned[..., 1] + 0.0722 * toned[..., 2]
    )
    return luma2[..., None] + saturation * (toned - luma2[..., None])


def _wheels_np(
    rgb: Any, *, lift: float, gamma: float, gain: float, offset: float
) -> Any:
    import numpy as np

    scaled = (rgb + lift) * gain
    return np.copysign(np.abs(scaled) ** (1.0 / gamma), scaled) + offset


def _param_float(params: Mapping[str, Any], key: str, default: float) -> float:
    if key not in params or params[key] is None:
        return float(default)
    value = float(params[key])
    if not math.isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value


def _param_float_any(
    params: Mapping[str, Any], keys: Sequence[str], default: float
) -> float:
    for key in keys:
        if key in params and params[key] is not None:
            return _param_float(params, key, default)
    return float(default)


def apply_managed_grade_array(
    pixels: Sequence[Sequence[Rgb]] | Any,
    *,
    compiled: Sequence[tuple[Mapping[str, Any], str | None, str]],
    coverage_maps: Mapping[str, Sequence[float]],
    lattice: str,
    input_profile: str,
    output_profile: str,
    return_numpy: bool = False,
) -> list[list[Rgb]] | Any | None:
    """Return graded rows (or ndarray), or None outside the NumPy fast path."""
    if not numpy_apply_enabled():
        return None

    import numpy as np

    if pixels is None:
        return [] if not return_numpy else np.zeros((0, 0, 3), dtype=np.float64)

    for step, _sid, _target in compiled:
        kind = step.get("type")
        if kind not in _SUPPORTED_STEPS:
            return None
        # Qualifier / missing coverage → Python path.
        sid = _sid
        if sid is not None and sid not in coverage_maps:
            return None

    arr = np.asarray(pixels, dtype=np.float64)
    if arr.ndim != 3 or arr.shape[2] != 3:
        return None
    height, width = int(arr.shape[0]), int(arr.shape[1])
    if width <= 0 or height <= 0:
        return arr if return_numpy else []

    cov_np: dict[str, Any] = {
        key: np.asarray(weights, dtype=np.float64).reshape(height, width)
        for key, weights in coverage_maps.items()
    }

    if lattice in {"encoded-bt709", "bt709-sdr", "bt709"}:
        working = arr.copy()
        domain = "bt709-sdr"
    elif lattice == "srgb":
        working = arr.copy()
        domain = "srgb"
    elif lattice == "linear-bt709":
        working = arr.copy()
        domain = "linear-bt709"
    else:
        working = _to_domain_np(arr, current=input_profile, target="linear-bt709")
        domain = "linear-bt709"

    touched = np.zeros((height, width), dtype=bool)
    # Pixels that saw a non-encoded-domain step with coverage>0 lose encoded_only.
    left_encoded_lattice = lattice in {"encoded-bt709", "bt709-sdr", "bt709"}
    encoded_only = (
        np.ones((height, width), dtype=bool)
        if left_encoded_lattice
        else np.zeros((height, width), dtype=bool)
    )
    for step, sid, target in compiled:
        if sid is None:
            factor = np.ones((height, width), dtype=np.float64)
        else:
            factor = cov_np[sid]
        mix = 1.0 if step.get("mix") is None else float(step["mix"])
        factor = factor * mix
        active = factor > 0.0
        if not bool(np.any(active)):
            continue
        touched |= active
        if target != "bt709-sdr":
            encoded_only &= ~active
        working = _to_domain_np(working, current=domain, target=target)
        domain = target
        params_raw = step.get("params")
        params: Mapping[str, Any] = params_raw if isinstance(params_raw, Mapping) else {}
        kind = str(step.get("type"))
        if kind == "managed-hsl-v1":
            processed = _managed_hsl_np(
                working,
                hue_offset_deg=_param_float_any(params, ("hue", "hue_offset_deg"), 0.0),
                saturation_mult=_param_float_any(
                    params, ("saturation", "saturation_mult"), 1.0
                ),
                lightness_offset=_param_float_any(
                    params, ("lightness", "lightness_offset"), 0.0
                ),
            )
        elif kind == "primaries-v1":
            processed = _primaries_np(
                working,
                exposure=_param_float(params, "exposure", 0.0),
                kelvin=_param_float(params, "kelvin", 6500.0),
                tint=_param_float(params, "tint", 0.0),
                contrast=_param_float(params, "contrast", 1.0),
                pivot=_param_float(params, "pivot", 0.18),
                saturation=_param_float(params, "saturation", 1.0),
                blacks=_param_float(params, "blacks", 0.0),
                shadows=_param_float(params, "shadows", 0.0),
                highlights=_param_float(params, "highlights", 0.0),
                whites=_param_float(params, "whites", 0.0),
            )
        elif kind == "wheels-v1":
            processed = _wheels_np(
                working,
                lift=_param_float(params, "lift", 0.0),
                gamma=_param_float(params, "gamma", 1.0),
                gain=_param_float(params, "gain", 1.0),
                offset=_param_float(params, "offset", 0.0),
            )
        else:
            return None
        working = _blend_np(working, processed, factor)

    # Match serial applicator output staging (#532 encoded_only + #524 identity).
    out_profile = "bt709-sdr" if output_profile == "bt709" else output_profile
    stay_encoded = touched & encoded_only & (domain == "bt709-sdr")
    need_roundtrip = touched & ~stay_encoded
    linearized = _to_domain_np(working, current=domain, target="linear-bt709")
    if out_profile in {"bt709-sdr", "encoded-bt709", "bt709"}:
        encoded = _encode_bt709_np(linearized)
    elif out_profile == "srgb":
        encoded = _encode_srgb_np(linearized)
    elif out_profile == "linear-bt709":
        encoded = linearized
    else:
        return None
    result = arr.copy()
    result = np.where(stay_encoded[..., None], working, result)
    result = np.where(need_roundtrip[..., None], encoded, result)
    working = np.clip(result, 0.0, 1.0)
    if return_numpy:
        return working
    # Nested Python rows; tuples match the oracle return type.
    return [
        [(float(px[0]), float(px[1]), float(px[2])) for px in row]
        for row in working.tolist()
    ]


__all__ = [
    "NUMPY_APPLY_PARITY_MAX_ABS",
    "apply_managed_grade_array",
    "numpy_apply_enabled",
]
