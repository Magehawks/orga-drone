"""Reusable Studio action contract shared by the UI routes and Control API.

Transport concerns stay outside this module: HTTP admission, editor leases,
state tokens, command IDs, and preview acknowledgement belong to ``control.py``
and ``control_routes.py``. This module owns the transport-neutral action names,
capability metadata, validation, canonical values, and effect-settings merge
rules available to both Studio editing paths.

The contract is additive. Existing Control API v1 command types keep their
payload and meaning; new actions get a name and version instead of silently
changing an existing command.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from orga_drone.project_actions import PROJECT_PARAMETERS, ProjectActionError, validate_project_params
from orga_drone.timeline_actions import TIMELINE_PARAMETERS, TimelineActionError, validate_timeline_params
from orga_drone.db import Database
from orga_drone.library_actions import LIST_PARAMETERS, LibraryActionError, validate_params
from orga_drone.lut_library import list_catalog
from orga_drone.studio_color_wheels import (
    POINT_MAX,
    POINT_MIN,
    WHEEL_IDS,
    color_wheels_from_effect_settings,
    dump_color_wheels,
    parse_color_wheels_payload,
)
from orga_drone.studio_detail import (
    SLIDER_MAX as DETAIL_MAX,
    SLIDER_MIN as DETAIL_MIN,
    detail_from_effect_settings,
    dump_detail,
    parse_detail_patch,
)
from orga_drone.studio_hsl import (
    RANGE_IDS,
    SLIDER_MAX as HSL_MAX,
    SLIDER_MIN as HSL_MIN,
    dump_hsl_adjust,
    hsl_adjust_from_effect_settings,
    parse_hsl_payload,
)
from orga_drone.studio_image import (
    IMAGE_KEYS,
    SLIDER_MAX as IMAGE_MAX,
    SLIDER_MIN as IMAGE_MIN,
    dump_effect_settings,
    image_adjust_from_effect_settings,
    parse_image_adjust_patch,
)
from orga_drone.studio_overlay import (
    dump_overlays,
    parse_overlays,
)
from orga_drone.studio_audio import (
    dump_detached_audio,
)
from orga_drone.studio_lut import (
    INPUT_PROFILES,
    color_look_from_effect_settings,
    dump_color_look,
    parse_color_look_payload,
    require_lut_asset,
)

CONTRACT_VERSION = 1
MAX_SAFE_INTEGER = 2**53 - 1
LUT_ID_RE = re.compile(r"^[a-f0-9]{32}\.cube$")
LIMITS = {
    "contrast": (-100, 100),
    "saturation_percent": (0, 200),
    "creative_lut_strength_percent": (0, 100),
}
IMAGE_PARAMETERS: dict[str, dict[str, Any]] = {
    key: {
        "type": "integer",
        "minimum": IMAGE_MIN,
        "maximum": IMAGE_MAX,
    }
    for key in IMAGE_KEYS
}
LOOK_PARAMETERS: dict[str, dict[str, Any]] = {
    "input_profile": {"type": "string", "enum": list(INPUT_PROFILES)},
    "conversion_lut": {"type": "string"},
    "creative_lut": {"type": "string"},
    "creative_strength": {"type": "integer", "minimum": 0, "maximum": 100},
    "conversion_confirmed": {"type": "boolean"},
}
HSL_PARAMETERS: dict[str, dict[str, Any]] = {
    "ranges": {
        "type": "object",
        "ranges": list(RANGE_IDS),
        "sliders": ["hue", "saturation", "luminance"],
        "minimum": HSL_MIN,
        "maximum": HSL_MAX,
    }
}
WHEEL_PARAMETERS: dict[str, dict[str, Any]] = {
    "wheels": {
        "type": "object",
        "wheels": list(WHEEL_IDS),
        "minimum": POINT_MIN,
        "maximum": POINT_MAX,
    }
}
DETAIL_PARAMETERS: dict[str, dict[str, Any]] = {
    "sharpen": {"type": "integer", "minimum": DETAIL_MIN, "maximum": DETAIL_MAX},
    "denoise": {"type": "integer", "minimum": DETAIL_MIN, "maximum": DETAIL_MAX},
}
AUDIO_PARAMETERS: dict[str, dict[str, Any]] = {
    "source_in_s": {"type": "number", "minimum": 0.0},
    "source_out_s": {"type": "number", "minimum": 0.0},
    "place_s": {"type": "number", "minimum": 0.0},
}
OVERLAY_PARAMETERS: dict[str, dict[str, Any]] = {
    "overlays": {"type": "array"},
}


class ActionValidationError(ValueError):
    """A transport-neutral action validation failure with a stable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ActionSpec:
    """Capability metadata for one implemented action version."""

    name: str
    version: int
    scope: str
    target: str
    reversible: bool
    description: str
    parameters: Mapping[str, Mapping[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "scope": self.scope,
            "target": self.target,
            "reversible": self.reversible,
            "description": self.description,
            "parameters": {
                key: dict(value) for key, value in self.parameters.items()
            },
        }


ACTION_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        name="clip.color.properties",
        version=1,
        scope="clip",
        target="video_clip",
        reversible=True,
        description=(
            "Set the supported basic color properties on the selected video clip."
        ),
        parameters={
            "contrast": {
                "type": "integer",
                "minimum": LIMITS["contrast"][0],
                "maximum": LIMITS["contrast"][1],
            },
            "saturation_percent": {
                "type": "integer",
                "minimum": LIMITS["saturation_percent"][0],
                "maximum": LIMITS["saturation_percent"][1],
            },
            "creative_lut_id": {"type": "string_or_null"},
            "creative_lut_strength_percent": {
                "type": "integer",
                "minimum": LIMITS["creative_lut_strength_percent"][0],
                "maximum": LIMITS["creative_lut_strength_percent"][1],
            },
        },
    ),
    ActionSpec(
        name="clip.color.image",
        version=1,
        scope="clip",
        target="media_clip",
        reversible=True,
        description="Set one or more existing image-adjust sliders on the selected clip.",
        parameters=IMAGE_PARAMETERS,
    ),
    ActionSpec(
        name="clip.grade.command",
        version=1,
        scope="clip",
        target="media_clip",
        reversible=True,
        description=(
            "Apply one bounded canonical grade command (enable/mix/reorder/"
            "animation) through the shared #363 bridge."
        ),
        parameters={
            "type": {"type": "string"},
            "expected_revision": {"type": "integer", "minimum": 0},
            "params": {"type": "object"},
            "project_id": {"type": "integer", "minimum": 1},
            "clip_id": {"type": "integer", "minimum": 1},
        },
    ),
    ActionSpec(
        name="clip.color.look",
        version=1,
        scope="clip",
        target="media_clip",
        reversible=True,
        description=(
            "Set the existing input profile, conversion LUT, creative LUT, and strength."
        ),
        parameters=LOOK_PARAMETERS,
    ),
    ActionSpec(
        name="clip.color.hsl",
        version=1,
        scope="clip",
        target="media_clip",
        reversible=True,
        description="Update the existing eight-range HSL mixer.",
        parameters=HSL_PARAMETERS,
    ),
    ActionSpec(
        name="clip.color.wheels",
        version=1,
        scope="clip",
        target="media_clip",
        reversible=True,
        description="Update the existing shadow, midtone, and highlight colour wheels.",
        parameters=WHEEL_PARAMETERS,
    ),
    ActionSpec(
        name="clip.effects.detail",
        version=1,
        scope="clip",
        target="media_clip",
        reversible=True,
        description="Update the existing sharpen and denoise effect.",
        parameters=DETAIL_PARAMETERS,
    ),
    ActionSpec(
        name="clip.audio.edit",
        version=1,
        scope="clip",
        target="video_clip",
        reversible=True,
        description=(
            "Set the clip's own detached audio bar (source range and story "
            "placement). The picture range and the source file stay unchanged."
        ),
        parameters=AUDIO_PARAMETERS,
    ),
    ActionSpec(
        name="clip.overlays.edit",
        version=1,
        scope="clip",
        target="media_clip",
        reversible=True,
        description=(
            "Replace the clip's timed text/shape/image overlays (full list)."
        ),
        parameters=OVERLAY_PARAMETERS,
    ),
    *(ActionSpec(
        name=f"library.media.{operation}", version=1, scope="library",
        target="media" if operation == "get" else "library", reversible=False,
        description="Read imported media metadata without filesystem paths.",
        parameters={} if operation == "get" else LIST_PARAMETERS,
    ) for operation in ("list", "search", "get")),
    *(ActionSpec(name=name, version=1, scope="timeline", target="story_clip" if name in {"timeline.remove", "timeline.trim"} else "story",
                 reversible=True, description="Edit the existing Story timeline.", parameters=params)
      for name, params in TIMELINE_PARAMETERS.items()),
)

ACTION_SPECS += tuple(
    ActionSpec(name=name, version=1, scope="project_read" if name in {"project.list", "project.get"} else "project",
               target="project", reversible=name.startswith("sfx."),
               description=(
                   "Place, move, trim, or remove one local sound effect on the Story."
                   if name.startswith("sfx.")
                   else "Use existing persisted Studio project lifecycle."
               ), parameters=params)
    for name, params in PROJECT_PARAMETERS.items()
)

_ACTION_SPECS_BY_KEY = {(spec.name, spec.version): spec for spec in ACTION_SPECS}


def action_catalog() -> dict[str, Any]:
    """Versioned capability discovery without paths, credentials, or media URLs."""
    from orga_drone.studio_action_semantics import attach_semantics

    return attach_semantics(
        {
            "contract_version": CONTRACT_VERSION,
            "actions": [spec.as_dict() for spec in ACTION_SPECS],
        }
    )


def resolve_action_spec(name: Any, version: Any) -> ActionSpec:
    """Return one implemented action or raise a stable action error."""
    if not isinstance(name, str) or type(version) is not int:
        raise ActionValidationError("INVALID_ACTION")
    spec = _ACTION_SPECS_BY_KEY.get((name, version))
    if spec is None:
        raise ActionValidationError("UNKNOWN_ACTION")
    return spec


def properties(raw: str | None) -> dict[str, Any]:
    """The Control API v1 property view of a clip's effect settings."""
    image = image_adjust_from_effect_settings(raw)
    color = color_look_from_effect_settings(raw)
    return {
        "contrast": image.contrast,
        "saturation_percent": image.saturation + 100,
        "creative_lut_id": color.creative_lut or None,
        "creative_lut_strength_percent": color.creative_strength,
    }


def canonical(raw: str | None) -> dict[str, Any]:
    """Canonical values used by the Studio bridge after a committed action."""
    return {
        "properties": properties(raw),
        "image": image_adjust_from_effect_settings(raw).as_dict(),
        "color_look": color_look_from_effect_settings(raw).as_dict(),
        "hsl": hsl_adjust_from_effect_settings(raw).as_dict(),
        "color_wheels": color_wheels_from_effect_settings(raw).as_dict(),
        "detail": detail_from_effect_settings(raw).as_dict(),
    }


def _validate_properties_params(params: Any) -> dict[str, Any]:
    try:
        return parse_properties_patch(params)
    except ActionValidationError:
        raise ActionValidationError("INVALID_PARAMS") from None


def parse_properties_patch(payload: Any) -> dict[str, Any]:
    """Validate one partial basic-color patch. Unknown keys are rejected."""
    if not isinstance(payload, Mapping):
        raise ActionValidationError("INVALID_PROPERTIES")
    patch = dict(payload)
    if not patch or set(patch) - (set(LIMITS) | {"creative_lut_id"}):
        raise ActionValidationError("INVALID_PROPERTIES")
    for key, value in patch.items():
        if key in LIMITS:
            low, high = LIMITS[key]
            if type(value) is not int or not low <= value <= high:
                raise ActionValidationError("INVALID_PROPERTIES")
        elif value is not None and (
            not isinstance(value, str) or not LUT_ID_RE.fullmatch(value)
        ):
            raise ActionValidationError("INVALID_PROPERTIES")
    return patch


def _validate_slider_map(
    params: Any, allowed: set[str], minimum: int, maximum: int
) -> dict[str, int]:
    if not isinstance(params, Mapping) or not params:
        raise ActionValidationError("INVALID_PARAMS")
    patch = dict(params)
    if set(patch) - allowed:
        raise ActionValidationError("INVALID_PARAMS")
    for value in patch.values():
        if type(value) is not int or not minimum <= value <= maximum:
            raise ActionValidationError("INVALID_PARAMS")
    return patch


def _validate_image_params(params: Any) -> dict[str, int]:
    return _validate_slider_map(params, set(IMAGE_KEYS), IMAGE_MIN, IMAGE_MAX)


def _validate_detail_params(params: Any) -> dict[str, int]:
    return _validate_slider_map(
        params, {"sharpen", "denoise"}, DETAIL_MIN, DETAIL_MAX
    )


def _validate_hsl_params(params: Any) -> dict[str, Any]:
    if not isinstance(params, Mapping) or set(params) != {"ranges"}:
        raise ActionValidationError("INVALID_PARAMS")
    ranges = params["ranges"]
    if not isinstance(ranges, Mapping) or not ranges:
        raise ActionValidationError("INVALID_PARAMS")
    for range_id, values in ranges.items():
        if range_id not in RANGE_IDS or not isinstance(values, Mapping):
            raise ActionValidationError("INVALID_PARAMS")
        if not values or set(values) - {"hue", "saturation", "luminance"}:
            raise ActionValidationError("INVALID_PARAMS")
        for value in values.values():
            if type(value) is not int or not HSL_MIN <= value <= HSL_MAX:
                raise ActionValidationError("INVALID_PARAMS")
    return dict(params)


def _validate_wheel_params(params: Any) -> dict[str, Any]:
    if not isinstance(params, Mapping) or set(params) != {"wheels"}:
        raise ActionValidationError("INVALID_PARAMS")
    wheels = params["wheels"]
    if not isinstance(wheels, Mapping) or not wheels:
        raise ActionValidationError("INVALID_PARAMS")
    for wheel_id, value in wheels.items():
        if wheel_id not in WHEEL_IDS or not isinstance(value, Mapping):
            raise ActionValidationError("INVALID_PARAMS")
        if not value or set(value) - {"x", "y"}:
            raise ActionValidationError("INVALID_PARAMS")
        for number in value.values():
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise ActionValidationError("INVALID_PARAMS")
            if isinstance(number, float) and not math.isfinite(number):
                raise ActionValidationError("INVALID_PARAMS")
            if not POINT_MIN <= number <= POINT_MAX:
                raise ActionValidationError("INVALID_PARAMS")
    return dict(params)


def _validate_look_params(params: Any) -> dict[str, Any]:
    if not isinstance(params, Mapping) or not params:
        raise ActionValidationError("INVALID_PARAMS")
    if set(params) - set(LOOK_PARAMETERS):
        raise ActionValidationError("INVALID_PARAMS")
    if "input_profile" in params and not isinstance(params["input_profile"], str):
        raise ActionValidationError("INVALID_PARAMS")
    for key in ("conversion_lut", "creative_lut"):
        if key in params and not isinstance(params[key], str):
            raise ActionValidationError("INVALID_PARAMS")
    if "creative_strength" in params:
        strength = params["creative_strength"]
        if type(strength) is not int or not 0 <= strength <= 100:
            raise ActionValidationError("INVALID_PARAMS")
    if "conversion_confirmed" in params and type(
        params["conversion_confirmed"]
    ) is not bool:
        raise ActionValidationError("INVALID_PARAMS")
    data = color_look_from_effect_settings("{}").as_dict()
    data.update(params)
    try:
        parse_color_look_payload(data)
    except (ValueError, TypeError, AttributeError):
        raise ActionValidationError("INVALID_PARAMS") from None
    return dict(params)


def validate_action_params(spec: ActionSpec, params: Any) -> dict[str, Any]:
    """Validate action parameters without touching the database or disk."""
    if spec.scope == "timeline":
        try:
            return validate_timeline_params(spec.name, params)
        except TimelineActionError as exc:
            raise ActionValidationError(exc.code) from None
    if spec.scope == "library":
        try:
            return validate_params(spec.name, params)
        except LibraryActionError as exc:
            raise ActionValidationError(exc.code) from None
    if spec.name in PROJECT_PARAMETERS:
        try:
            return validate_project_params(spec.name, params)
        except ProjectActionError as exc:
            raise ActionValidationError(exc.code) from None
    validators = {
        "clip.color.properties": _validate_properties_params,
        "clip.color.image": _validate_image_params,
        "clip.color.look": _validate_look_params,
        "clip.color.hsl": _validate_hsl_params,
        "clip.color.wheels": _validate_wheel_params,
        "clip.effects.detail": _validate_detail_params,
        "clip.grade.command": _validate_grade_command_params,
    }
    validator = validators.get(spec.name)
    if validator is None:
        raise ActionValidationError("UNKNOWN_ACTION")
    return dict(validator(params))


def _validate_grade_command_params(params: Mapping[str, Any]) -> dict[str, Any]:
    from orga_drone.studio_grade_commands import COMMAND_CAPABILITIES

    if not isinstance(params, Mapping):
        raise ActionValidationError("INVALID_PARAMS")
    required = {"type", "expected_revision", "params", "project_id", "clip_id"}
    if set(params) != required:
        raise ActionValidationError("INVALID_PARAMS")
    if params["type"] not in COMMAND_CAPABILITIES:
        raise ActionValidationError("INVALID_PARAMS")
    if type(params["expected_revision"]) is not int or params["expected_revision"] < 0:
        raise ActionValidationError("INVALID_PARAMS")
    if type(params["project_id"]) is not int or params["project_id"] < 1:
        raise ActionValidationError("INVALID_PARAMS")
    if type(params["clip_id"]) is not int or params["clip_id"] < 1:
        raise ActionValidationError("INVALID_PARAMS")
    if not isinstance(params["params"], dict):
        raise ActionValidationError("INVALID_PARAMS")
    return {
        "type": params["type"],
        "expected_revision": params["expected_revision"],
        "params": dict(params["params"]),
        "project_id": params["project_id"],
        "clip_id": params["clip_id"],
    }


def validate_clip_effect_settings(raw: str | None) -> None:
    """Reject corrupt, unsupported, or animated settings for static color actions."""
    try:
        stored = json.loads(raw or "{}")
        if not isinstance(stored, dict):
            raise ValueError
        if stored.get("color_animation") or stored.get("saturation_ramp"):
            raise ActionValidationError("ANIMATED_SETTINGS_UNSUPPORTED")
        neutral = image_adjust_from_effect_settings("{}")
        parse_image_adjust_patch(
            dict(neutral.as_dict(), **stored.get("image", {})), neutral
        )
        parse_color_look_payload(stored.get("color", {}))
    except ActionValidationError:
        raise
    except (ValueError, TypeError, AttributeError):
        raise ActionValidationError("INVALID_CLIP_SETTINGS") from None


def lut_catalog(db: Database, data_dir: Path) -> set[str]:
    """Imported LUT asset names that still exist on disk."""
    return {
        entry.asset_name
        for entry in list_catalog(db, data_dir)
        if entry.file_present
    }


def _require_available_luts(
    look: Any, available_luts: set[str], data_dir: Path
) -> None:
    for name in (look.creative_lut, look.conversion_lut):
        if name:
            try:
                if name not in available_luts:
                    raise ValueError
                require_lut_asset(data_dir, name)
            except Exception:
                raise ActionValidationError("LUT_UNAVAILABLE") from None


def merge_properties(
    raw: str | None,
    patch: Mapping[str, Any],
    available_luts: set[str],
    data_dir: Path,
) -> str:
    """Merge validated basic-color properties and preserve unrelated keys."""
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ActionValidationError("INVALID_CLIP_SETTINGS")
    image_patch: dict[str, Any] = {}
    if "contrast" in patch:
        image_patch["contrast"] = patch["contrast"]
    if "saturation_percent" in patch:
        image_patch["saturation"] = patch["saturation_percent"] - 100
    current_image = image_adjust_from_effect_settings(raw)
    image = (
        parse_image_adjust_patch(image_patch, current_image)
        if image_patch
        else current_image
    )
    color_data = color_look_from_effect_settings(raw).as_dict()
    if "creative_lut_id" in patch:
        color_data["creative_lut"] = patch["creative_lut_id"] or ""
    if "creative_lut_strength_percent" in patch:
        color_data["creative_strength"] = patch["creative_lut_strength_percent"]
    color = parse_color_look_payload(color_data)
    _require_available_luts(color, available_luts, data_dir)
    if image_patch:
        data["image"] = dict(data.get("image", {}), **image.as_dict())
    if "creative_lut_id" in patch or "creative_lut_strength_percent" in patch:
        data["color"] = dict(data.get("color", {}), **color.as_dict())
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _validate_audio_params(params: Any) -> dict[str, Any]:  # type: ignore[name-defined]
    """Structural validation for the detached audio action. Times must be
    finite nonnegative numbers with an audible span; media-duration clamping
    happens against the clip context in ``prepare_action``."""
    if not isinstance(params, Mapping) or set(params) != set(AUDIO_PARAMETERS):
        raise ActionValidationError("INVALID_PARAMS")
    for key in AUDIO_PARAMETERS:
        value = params[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ActionValidationError("INVALID_PARAMS")
        if not math.isfinite(float(value)) or float(value) < 0.0:
            raise ActionValidationError("INVALID_PARAMS")
    if float(params["source_out_s"]) - float(params["source_in_s"]) < 0.05:
        raise ActionValidationError("INVALID_PARAMS")
    return dict(params)


def prepare_action(
    spec: ActionSpec,
    raw: str | None,
    params: Mapping[str, Any],
    available_luts: set[str],
    data_dir: Path,
    *,
    clip_duration_s: float | None = None,
) -> str:
    """Apply one validated action to effect settings without writing the DB."""
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ActionValidationError("INVALID_CLIP_SETTINGS")
    if spec.name == "clip.grade.command":
        from orga_drone.studio_grade_bridge import apply_grade_command_text
        from orga_drone.studio_grade_contract import GradeError

        required = {"type", "expected_revision", "params", "project_id", "clip_id"}
        if set(params) != required:
            raise ActionValidationError("INVALID_PARAMS")
        try:
            expected = int(params["expected_revision"])
            command = {
                "type": params["type"],
                "project_id": int(params["project_id"]),
                "clip_id": int(params["clip_id"]),
                "expected_revision": expected,
                "params": params["params"],
            }
            return apply_grade_command_text(
                raw,
                command,
                expected_revision=expected,
                data_dir=data_dir,
            )
        except GradeError as exc:
            raise ActionValidationError(exc.code) from None
        except (TypeError, ValueError):
            raise ActionValidationError("INVALID_PARAMS") from None
    if spec.name.startswith("clip.color.") or spec.name == "clip.effects.detail":
        from orga_drone.studio_grade_contract import GradeError
        from orga_drone.studio_grade_persistence import grade_write_guard

        try:
            grade_write_guard(raw)
        except GradeError as exc:
            raise ActionValidationError(exc.code) from None
    if spec.name == "clip.color.properties":
        patch = parse_properties_patch(params)
        return merge_properties(raw, patch, available_luts, data_dir)
    if spec.name == "clip.color.image":
        _validate_image_params(params)
        image = parse_image_adjust_patch(
            params, image_adjust_from_effect_settings(raw)
        )
        return dump_effect_settings(raw, image)
    if spec.name == "clip.color.look":
        _validate_look_params(params)
        look_data = color_look_from_effect_settings(raw).as_dict()
        look_data.update(params)
        try:
            look = parse_color_look_payload(look_data)
        except (ValueError, TypeError, AttributeError):
            raise ActionValidationError("INVALID_PARAMS") from None
        _require_available_luts(look, available_luts, data_dir)
        return dump_color_look(raw, look)
    if spec.name == "clip.color.hsl":
        _validate_hsl_params(params)
        hsl = parse_hsl_payload(params, hsl_adjust_from_effect_settings(raw))
        return dump_hsl_adjust(raw, hsl)
    if spec.name == "clip.color.wheels":
        _validate_wheel_params(params)
        wheels = parse_color_wheels_payload(
            params, color_wheels_from_effect_settings(raw)
        )
        return dump_color_wheels(raw, wheels)
    if spec.name == "clip.effects.detail":
        _validate_detail_params(params)
        detail = parse_detail_patch(params, detail_from_effect_settings(raw))
        return dump_detail(raw, detail)
    if spec.name == "clip.audio.edit":
        audio_params = _validate_audio_params(params)
        start = float(audio_params["source_in_s"])
        end = float(audio_params["source_out_s"])
        place = float(audio_params["place_s"])
        if clip_duration_s is not None:
            limit = float(clip_duration_s)
            start = min(start, limit)
            end = min(end, limit)
        if end - start < 0.05:
            raise ActionValidationError("INVALID_PARAMS")
        from orga_drone.studio_audio import DetachedAudio

        audio = DetachedAudio(
            active=True,
            source_in_s=round(start, 4),
            source_out_s=round(end, 4),
            place_s=round(place, 4),
        )
        return dump_detached_audio(raw, audio)
    if spec.name == "clip.overlays.edit":
        if "overlays" not in params or not isinstance(params["overlays"], list):
            raise ActionValidationError("INVALID_PARAMS")
        if clip_duration_s is None:
            raise ActionValidationError("INVALID_PARAMS")
        try:
            overlays, _clamped = parse_overlays(
                params["overlays"], duration_s=float(clip_duration_s)
            )
        except (ValueError, TypeError, AttributeError):
            raise ActionValidationError("INVALID_PARAMS") from None
        return dump_overlays(raw, list(overlays))
    raise ActionValidationError("UNKNOWN_ACTION")
