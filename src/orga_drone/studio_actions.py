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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from orga_drone.db import Database
from orga_drone.lut_library import list_catalog
from orga_drone.studio_image import (
    image_adjust_from_effect_settings,
    parse_image_adjust_patch,
)
from orga_drone.studio_lut import (
    color_look_from_effect_settings,
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
)


def action_catalog() -> dict[str, Any]:
    """Versioned capability discovery without paths, credentials, or media URLs."""
    return {
        "contract_version": CONTRACT_VERSION,
        "actions": [spec.as_dict() for spec in ACTION_SPECS],
    }


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
    }


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
    for name in (color.creative_lut, color.conversion_lut):
        if name:
            try:
                if name not in available_luts:
                    raise ValueError
                require_lut_asset(data_dir, name)
            except Exception:
                raise ActionValidationError("LUT_UNAVAILABLE") from None
    if image_patch:
        data["image"] = dict(data.get("image", {}), **image.as_dict())
    if "creative_lut_id" in patch or "creative_lut_strength_percent" in patch:
        data["color"] = dict(data.get("color", {}), **color.as_dict())
    return json.dumps(data, separators=(",", ":"), sort_keys=True)