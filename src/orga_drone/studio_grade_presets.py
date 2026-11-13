"""Compile Creative Quick Looks into inspectable managed grade operations (#361).

Named Quick Looks remain the product presets. For managed-sdr-v1 grades they
compile to explicit ``primaries-v1`` parameters (same grade Creative and Pro
edit). Legacy clips keep the existing slider-replacement path.
"""

from __future__ import annotations

from typing import Any, Mapping

from orga_drone.studio_image import ImageAdjust, kelvin_for_warmth
from orga_drone.studio_looks import LOOK_IDS, look_image_adjust


def image_adjust_to_primaries_params(image: ImageAdjust) -> dict[str, float | int]:
    """Map legacy Quick Look slider units onto managed primaries-v1 neutrals."""
    exposure_ev = float(image.exposure) / 100.0
    contrast = 1.0 + float(image.contrast) / 200.0
    saturation = 1.0 + float(image.saturation) / 100.0
    kelvin = int(kelvin_for_warmth(int(image.warmth)))
    return {
        "exposure": exposure_ev,
        "kelvin": kelvin,
        "tint": 0,
        "contrast": contrast,
        "pivot": 0.18,
        "saturation": saturation,
        "blacks": 0,
        "shadows": 0,
        "highlights": 0,
        "whites": 0,
    }


def compile_quick_look_to_primaries(look_id: str) -> dict[str, Any]:
    """Return an inspectable primaries-v1 step body for one Quick Look id."""
    key = str(look_id or "").strip().lower()
    if key not in LOOK_IDS:
        raise ValueError("unknown quick look")
    params = image_adjust_to_primaries_params(look_image_adjust(key))
    return {
        "preset_id": key,
        "type": "primaries-v1",
        "params": params,
        "source": "quick-look-v1",
    }


def neutral_primaries_params() -> dict[str, float | int]:
    """Documented managed primaries neutrals used when clearing a Creative preset."""
    return image_adjust_to_primaries_params(ImageAdjust())


def apply_preset_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate ``apply_preset`` command params and return the compile payload.

    Empty ``preset_id`` clears the Creative preset label and returns neutrals.
    """
    if set(params) != {"preset_id"}:
        raise ValueError("Expected preset_id only")
    raw = params["preset_id"]
    if raw in ("", None):
        return {
            "preset_id": "",
            "type": "primaries-v1",
            "params": neutral_primaries_params(),
            "source": "quick-look-v1",
        }
    return compile_quick_look_to_primaries(str(raw))
