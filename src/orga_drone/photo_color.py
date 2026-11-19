"""Library-photo color state on ``media_meta.image_adjust_json`` (#491).

Extends the existing flat ImageAdjust + Quick Look blob with Studio-compatible
``hsl``, ``color_wheels``, ``color`` (cube LUT), and optional canonical ``grade``
keys. No new SQLite column. Builders consume an effect_settings-shaped view
without requiring a Studio clip.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from orga_drone.studio_color_wheels import (
    COLOR_WHEELS_KEY,
    ColorWheels,
    color_wheels_from_effect_settings,
)
from orga_drone.studio_hsl import HSL_KEY, HslAdjust, hsl_adjust_from_effect_settings
from orga_drone.studio_image import ImageAdjust, image_adjust_from_stored
from orga_drone.studio_looks import LOOK_KEY, look_id_from_stored
from orga_drone.studio_lut import COLOR_KEY, ColorLook, color_look_from_effect_settings
from orga_drone.studio_managed_apply import grade_is_managed_sdr

PHOTO_COLOR_HISTORY_MAX = 40

_history_lock = threading.Lock()
_undo: dict[str, list[str]] = {}
_redo: dict[str, list[str]] = {}


def _parse_object(raw: str | None) -> dict[str, object]:
    if raw is None or not str(raw).strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def dumps_photo_color(data: Mapping[str, object]) -> str:
    return json.dumps(dict(data), separators=(",", ":"), sort_keys=True)


def merge_photo_image_adjust(
    existing: str | None,
    image: ImageAdjust,
    *,
    look_id: str = "",
) -> str:
    """Write flat ImageAdjust (+ optional Quick Look) and keep advanced keys."""
    from orga_drone.studio_looks import LOOK_IDS

    data = _parse_object(existing)
    for key, value in image.as_dict().items():
        data[key] = value
    # Drop nested Studio-style image mirror if present so flat keys stay SoT.
    data.pop("image", None)
    key = str(look_id or "").strip().lower()
    if key:
        if key not in LOOK_IDS:
            raise ValueError("unknown quick look")
        data[LOOK_KEY] = {"id": key}
    else:
        data.pop(LOOK_KEY, None)
    return dumps_photo_color(data)


def merge_photo_hsl(existing: str | None, hsl: HslAdjust) -> str:
    data = _parse_object(existing)
    data[HSL_KEY] = hsl.as_dict()
    return dumps_photo_color(data)


def merge_photo_color_wheels(existing: str | None, wheels: ColorWheels) -> str:
    data = _parse_object(existing)
    data[COLOR_WHEELS_KEY] = wheels.as_dict()
    return dumps_photo_color(data)


def merge_photo_color_look(existing: str | None, look: ColorLook) -> str:
    data = _parse_object(existing)
    data[COLOR_KEY] = look.as_dict()
    return dumps_photo_color(data)


def merge_photo_grade_blob(existing: str | None, grade_blob: str) -> str:
    """Merge a Studio effect_settings-shaped grade string into photo JSON."""
    data = _parse_object(existing)
    incoming = _parse_object(grade_blob)
    for key, value in incoming.items():
        data[key] = value
    # Keep flat ImageAdjust SoT when incoming nests image.
    nested = incoming.get("image")
    if isinstance(nested, dict):
        for key, value in nested.items():
            data[key] = value
        data.pop("image", None)
    return dumps_photo_color(data)


def effect_settings_from_photo_raw(raw: str | None) -> str:
    """Normalize photo meta JSON into effect_settings shape for shared builders."""
    data = _parse_object(raw)
    image = image_adjust_from_stored(raw)
    out: dict[str, object] = {"image": image.as_dict()}
    look_id = look_id_from_stored(raw)
    if look_id:
        out[LOOK_KEY] = {"id": look_id}
    if HSL_KEY in data:
        out[HSL_KEY] = data[HSL_KEY]
    if COLOR_WHEELS_KEY in data:
        out[COLOR_WHEELS_KEY] = data[COLOR_WHEELS_KEY]
    if COLOR_KEY in data:
        out[COLOR_KEY] = data[COLOR_KEY]
    if "grade" in data:
        out["grade"] = data["grade"]
    if "evaluator" in data:
        out["evaluator"] = data["evaluator"]
    if "authority" in data:
        out["authority"] = data["authority"]
    return dumps_photo_color(out)


@dataclass(frozen=True)
class PhotoColorParts:
    image: ImageAdjust
    look_id: str
    color_look: ColorLook
    hsl: HslAdjust
    color_wheels: ColorWheels
    effect_settings: str
    managed: bool


def photo_color_parts(raw: str | None) -> PhotoColorParts:
    effect = effect_settings_from_photo_raw(raw)
    return PhotoColorParts(
        image=image_adjust_from_stored(raw),
        look_id=look_id_from_stored(raw),
        color_look=color_look_from_effect_settings(effect),
        hsl=hsl_adjust_from_effect_settings(effect),
        color_wheels=color_wheels_from_effect_settings(effect),
        effect_settings=effect,
        managed=grade_is_managed_sdr(effect),
    )


def photo_color_is_active(raw: str | None) -> bool:
    parts = photo_color_parts(raw)
    if not parts.image.is_neutral:
        return True
    if parts.look_id:
        return True
    if not parts.color_look.is_neutral:
        return True
    if not parts.hsl.is_neutral:
        return True
    if not parts.color_wheels.is_neutral:
        return True
    if parts.managed:
        return True
    return False


def photo_color_needs_server_preview(raw: str | None) -> bool:
    """CSS cannot express HSL/LUT/wheels/managed — those need a server still."""
    parts = photo_color_parts(raw)
    if not parts.color_look.is_neutral:
        return True
    if not parts.hsl.is_neutral:
        return True
    if not parts.color_wheels.is_neutral:
        return True
    if parts.managed:
        return True
    return False


def clear_photo_color_history(media_path: str | Path | None = None) -> None:
    key = str(media_path) if media_path is not None else None
    with _history_lock:
        if key is None:
            _undo.clear()
            _redo.clear()
            return
        _undo.pop(key, None)
        _redo.pop(key, None)


def photo_color_history_flags(media_path: str | Path) -> dict[str, bool]:
    key = str(media_path)
    with _history_lock:
        return {
            "can_undo": bool(_undo.get(key)),
            "can_redo": bool(_redo.get(key)),
        }


def push_photo_color_undo(media_path: str | Path, previous_raw: str | None) -> None:
    key = str(media_path)
    snapshot = previous_raw if previous_raw is not None else ""
    with _history_lock:
        stack = _undo.setdefault(key, [])
        if stack and stack[-1] == snapshot:
            return
        stack.append(snapshot)
        extra = len(stack) - PHOTO_COLOR_HISTORY_MAX
        if extra > 0:
            del stack[:extra]
        _redo[key] = []


def undo_photo_color(media_path: str | Path, current_raw: str | None) -> str | None:
    """Pop undo → return raw to restore. None if empty."""
    key = str(media_path)
    with _history_lock:
        stack = _undo.get(key) or []
        if not stack:
            return None
        previous = stack.pop()
        redo = _redo.setdefault(key, [])
        redo.append(current_raw if current_raw is not None else "")
        return previous


def redo_photo_color(media_path: str | Path, current_raw: str | None) -> str | None:
    key = str(media_path)
    with _history_lock:
        stack = _redo.get(key) or []
        if not stack:
            return None
        nxt = stack.pop()
        undo = _undo.setdefault(key, [])
        undo.append(current_raw if current_raw is not None else "")
        return nxt
