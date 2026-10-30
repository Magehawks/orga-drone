"""Deterministic Studio Quick Looks (Issue #175).

Looks are named presets of the existing image sliders. Applying a look
**replaces** the four basic correction values for that Story clip. It does not
touch technical LUT conversion, creative LUTs, overlays, or source files.
A missing or unknown look id means the clip stays on its stored sliders
(custom). Before/after comparison is a preview-only toggle and does not change
saved edits.
"""

from __future__ import annotations

import json
from typing import Mapping

from orga_drone.studio_image import ImageAdjust

LOOK_KEY = "look"
LOOK_IDS = (
    "natural",
    "cinematic",
    "golden_hour",
    "vibrant",
    "cool",
    "black_and_white",
)

# Tuned as starting points for drone footage; users can edit sliders afterward.
_LOOK_VALUES: dict[str, ImageAdjust] = {
    "natural": ImageAdjust(),
    "cinematic": ImageAdjust(exposure=-8, contrast=18, saturation=-12, warmth=8),
    "golden_hour": ImageAdjust(exposure=6, contrast=8, saturation=12, warmth=42),
    "vibrant": ImageAdjust(exposure=2, contrast=16, saturation=38, warmth=4),
    "cool": ImageAdjust(exposure=0, contrast=10, saturation=6, warmth=-36),
    "black_and_white": ImageAdjust(exposure=0, contrast=12, saturation=-100, warmth=0),
}


def quick_looks_preview_model() -> dict[str, object]:
    return {
        "ids": list(LOOK_IDS),
        "values": {key: value.as_dict() for key, value in _LOOK_VALUES.items()},
    }


def look_image_adjust(look_id: str) -> ImageAdjust:
    key = str(look_id or "").strip().lower()
    if key not in _LOOK_VALUES:
        raise ValueError("unknown quick look")
    return _LOOK_VALUES[key]


def look_id_from_effect_settings(raw: str | None) -> str:
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    nested = parsed.get(LOOK_KEY)
    if not isinstance(nested, dict):
        return ""
    value = nested.get("id")
    if not isinstance(value, str):
        return ""
    key = value.strip().lower()
    return key if key in _LOOK_VALUES else ""


def dump_look_id(existing: str | None, look_id: str) -> str:
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    key = str(look_id or "").strip().lower()
    if not key:
        data.pop(LOOK_KEY, None)
    elif key not in _LOOK_VALUES:
        raise ValueError("unknown quick look")
    else:
        data[LOOK_KEY] = {"id": key}
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def parse_look_payload(payload: Mapping[str, object]) -> str:
    value = payload.get("id", payload.get("look_id", ""))
    if value in ("", None):
        return ""
    if not isinstance(value, str):
        raise ValueError("look id must be a string")
    key = value.strip().lower()
    if key and key not in _LOOK_VALUES:
        raise ValueError("unknown quick look")
    return key


def dump_photo_adjust(image: ImageAdjust, look_id: str = "") -> str:
    """Persist a library-photo grade. Flat ImageAdjust fields; optional look id.

    Older rows store only the four basic sliders. Extra tonal keys and an
    optional ``look`` object are additive and stay compatible with
    ``image_adjust_from_stored``.
    """
    data: dict[str, object] = dict(image.as_dict())
    key = str(look_id or "").strip().lower()
    if key:
        if key not in _LOOK_VALUES:
            raise ValueError("unknown quick look")
        data[LOOK_KEY] = {"id": key}
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def look_id_from_stored(raw: str | None) -> str:
    """Look id saved on a photo meta row. Missing → custom (empty)."""
    return look_id_from_effect_settings(raw)
