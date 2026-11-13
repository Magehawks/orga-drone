"""Pure grade plan construction, not an FFmpeg/GPU renderer or a cache writer."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping

from orga_drone.studio_color_animation import (
    apply_keyed_image,
    apply_keyed_look,
    color_animation_from_effect_settings,
)
from orga_drone.studio_color_wheels import color_wheels_from_effect_settings
from orga_drone.studio_detail import detail_from_effect_settings
from orga_drone.studio_grade_contract import (
    LEGACY_KEYS,
    fail,
    identifier,
    integer,
    snapshot,
)
from orga_drone.studio_grade_model import GradeModel, read_grade
from orga_drone.studio_hsl import hsl_adjust_from_effect_settings
from orga_drone.studio_image import (
    image_adjust_from_effect_settings,
    saturation_multiplier,
    saturation_ramp_from_effect_settings,
)
from orga_drone.studio_lut import color_look_from_effect_settings


@dataclass(frozen=True)
class RenderContext:
    """Caller-supplied clock mapping; this module never computes a playback clock."""

    source_id: str
    source_pts: Fraction = Fraction(0)
    source_frame: int = 0
    source_in: Fraction = Fraction(0)
    source_out: Fraction | None = None
    source_local: Fraction = Fraction(0)
    story_time: Fraction = Fraction(0)
    speed: Fraction = Fraction(1)
    repeat_pass: int = 0
    transition_side: str = "single"
    width: int = 1920
    height: int = 1080
    orientation: int = 1

    def to_dict(self) -> dict[str, Any]:
        identifier(self.source_id, "context.source_id")
        result: dict[str, Any] = {"source_id": self.source_id}
        for field in (
            "source_pts",
            "source_in",
            "source_out",
            "source_local",
            "story_time",
            "speed",
        ):
            value = getattr(self, field)
            if field == "source_out" and value is None:
                result[field] = None
                continue
            if (
                not isinstance(value, Fraction)
                or value < 0
                or (field == "speed" and value == 0)
            ):
                fail(
                    "context." + field,
                    "Expected a nonnegative rational (positive speed)",
                )
            integer(value.numerator, "context." + field + ".numerator")
            integer(value.denominator, "context." + field + ".denominator", 1)
            result[field] = [value.numerator, value.denominator]
        if self.source_pts < self.source_in or (
            self.source_out is not None and self.source_out <= self.source_in
        ):
            fail("context", "Invalid source interval")
        if self.source_out is not None and self.source_pts > self.source_out:
            fail("context.source_pts", "Outside source interval")
        if self.source_local != self.source_pts - self.source_in:
            fail("context.source_local", "Must match caller's clip-local source time")
        for field in ("source_frame", "repeat_pass", "width", "height", "orientation"):
            result[field] = integer(
                getattr(self, field),
                "context." + field,
                1 if field in ("width", "height", "orientation") else 0,
            )
        if self.orientation > 8:
            fail("context.orientation", "Expected EXIF orientation 1..8")
        if self.transition_side not in ("single", "incoming", "outgoing"):
            fail("context.transition_side", "Unknown transition side")
        result["transition_side"] = self.transition_side
        return result


@dataclass(frozen=True)
class RenderPlan:
    """Immutable snapshot. Digest is a planning digest, not a published render cache key."""

    _json: str
    semantic_digest: str
    grade_identity: bool
    assets_resolved: bool

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._json)


def _legacy_payload(model: GradeModel) -> str | None:
    grade = model.grade
    if grade is None:
        return model.original_effect_settings()
    step = grade["steps"][0]
    if not step["enabled"]:
        return None
    return snapshot(
        {key: value for key, value in step["params"].items() if key in LEGACY_KEYS}
    )


def evaluate_grade(
    model: GradeModel,
    context: RenderContext,
    *,
    asset_digests: Mapping[str, str] | None = None,
) -> RenderPlan:
    """Evaluate data only; no LUT access, renderer calls, or mutation of inputs.

    Asset digests must come from the later confined resolver (#352). Missing
    digests yield explicit unresolved requirements, never a render-cache hit.
    No existing production adapter consumes this new contract yet.
    """
    # Revalidate public snapshots at the pure evaluator boundary.
    model = (
        read_grade(model.to_dict())
        if model.authority == "canonical"
        else read_grade(model.original_effect_settings())
    )
    timing = context.to_dict()
    assets: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    supplied = dict(asset_digests or {})
    for asset_id, digest in supplied.items():
        if (
            not isinstance(asset_id, str)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            fail("asset_digests", "Expected asset ID to lowercase SHA-256 mapping")

    def asset(asset_id: str, role: str) -> None:
        assets.append(
            {
                "asset_id": asset_id,
                "sha256": supplied.get(asset_id),
                "role": role,
                "resolution": "provided" if asset_id in supplied else "required",
            }
        )

    def operation(
        kind: str, params: dict[str, Any], domain: str, *, pointwise: bool = True
    ) -> None:
        operations.append(
            {
                "type": kind,
                "input_domain": domain,
                "output_domain": domain,
                "params": params,
                "pointwise": pointwise,
                "selection_id": None,
                "mix": 1,
                "capability": "legacy-reference-only",
            }
        )

    input_stage: dict[str, Any]
    output_stage: dict[str, Any]
    if model.evaluator == "legacy-v1":
        raw = _legacy_payload(model)
        animation = color_animation_from_effect_settings(raw)
        local = float(context.source_local)
        image = apply_keyed_image(
            image_adjust_from_effect_settings(raw), animation, local
        )
        look = apply_keyed_look(color_look_from_effect_settings(raw), animation, local)
        hsl = hsl_adjust_from_effect_settings(raw)
        wheels = color_wheels_from_effect_settings(raw)
        detail = detail_from_effect_settings(raw)
        ramp = saturation_multiplier(saturation_ramp_from_effect_settings(raw), local)
        if not image.is_neutral:
            operation("legacy-image-v1", image.as_dict(), "legacy-ffmpeg-auto")
        if look.conversion_lut and look.conversion_confirmed:
            asset(look.conversion_lut, "technical")
            operation(
                "legacy-technical-lut-v1",
                {"asset_id": look.conversion_lut, "interpolation": "tetrahedral"},
                "legacy-encoded-rgb",
            )
        if look.creative_lut and look.creative_strength > 0:
            asset(look.creative_lut, "creative")
            operation(
                "legacy-creative-lut-v1",
                {
                    "asset_id": look.creative_lut,
                    "strength_percent": look.creative_strength,
                    "interpolation": "tetrahedral",
                },
                "legacy-encoded-rgb",
            )
        if not hsl.is_neutral:
            operation("legacy-hsl-v1", hsl.as_dict(), "legacy-encoded-rgb")
        if not wheels.is_neutral:
            operation("legacy-wheels-v1", wheels.as_dict(), "legacy-encoded-rgb")
        if not detail.is_neutral:
            operation(
                "legacy-detail-v1",
                detail.as_dict(),
                "legacy-ffmpeg-auto",
                pointwise=False,
            )
        if ramp != 1:
            operation("legacy-saturation-ramp-v1", {"multiplier": ramp}, "legacy-yuv")
        input_stage = {
            "profile": "legacy-native",
            "policy": "existing-adapter-negotiation",
        }
        output_stage = {
            "profile": "legacy-native",
            "policy": "existing-adapter-negotiation",
        }
        requirements = ["legacy-animation-segmentation"] if animation.is_active else []
    else:
        grade = model.grade
        assert grade is not None  # Validated model, not caller-provided arbitrary JSON.
        input_stage = {
            "profile": grade["input"]["profile"],
            "output_domain": "linear-bt709",
            "technical_lut": None,
            "policy": "explicit-transfer-decode",
            "source_domain": grade["input"]["profile"],
            "transfer": {
                "srgb": "inverse-srgb",
                "bt709-sdr": "inverse-bt709",
                "linear-bt709": "identity",
            }[grade["input"]["profile"]],
            "decoded_rgb_range": "full",
        }
        output_stage = {
            "profile": grade["output"]["profile"],
            "input_domain": "linear-bt709",
            "gamut": "clip",
            "preview_transfer": "srgb",
            "export_transfer": "bt709",
            "comparison_gate": "M709-SRGB8-v1",
            "export_matrix": "bt709",
            "export_range": "limited",
            "export_format": "yuv420p",
            "alpha": "straight-before-composite",
        }
        # Emit enabled managed steps in serial order. Pixel adapters remain
        # not-integrated until #359/#360 consume the plan.
        from orga_drone.studio_grade_model import OPERATION_DESCRIPTORS

        for step in grade["steps"]:
            if not step["enabled"]:
                continue
            descriptor = OPERATION_DESCRIPTORS.get(step["type"])
            assert descriptor is not None  # Validated by read_grade for enabled steps.
            domain = descriptor["domain"]
            if domain == "declared":
                domain = str(step["params"].get("domain") or "linear-bt709")
            operations.append(
                {
                    "type": step["type"],
                    "input_domain": domain,
                    "output_domain": domain,
                    "params": dict(step["params"]),
                    "pointwise": bool(descriptor["pointwise"]),
                    "selection_id": step.get("selection_id"),
                    "mix": step.get("mix", 1),
                    "capability": "managed-reference-plan",
                    "lut_bakeable": bool(descriptor["lut_bakeable"]),
                }
            )
            if step["type"] == "creative-lut-v1":
                asset_id = step["params"].get("asset_id")
                if isinstance(asset_id, str) and asset_id:
                    asset(asset_id, "creative")
        requirements = ["managed-sdr-adapter"]
    resolved = all(entry["sha256"] is not None for entry in assets)
    content = {
        "plan_version": 1,
        "schema_version": 1,
        "evaluator": model.evaluator,
        "timing": timing,
        "input": input_stage,
        "operations": operations,
        "output": output_stage,
        "assets": assets,
        "capabilities": {
            "planning": True,
            "pixel_execution": False,
            "ffmpeg": "not-integrated",
            "gpu": "not-integrated",
            "requirements": requirements,
            "assets_resolved": resolved,
        },
    }
    encoded = snapshot(content)
    return RenderPlan(
        encoded,
        hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        not operations,
        resolved,
    )
