"""Opaque-preserving, read-only canonical grade model. Never persists or migrates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from orga_drone.studio_grade_contract import (
    LEGACY_KEYS,
    MAX_BRUSH_POINTS,
    MAX_BYTES,
    MAX_CURVE_POINTS,
    MAX_SELECTIONS,
    MAX_STEPS,
    array_value,
    fail,
    identifier,
    integer,
    number,
    object_value,
    snapshot,
    unique_object,
)

EVALUATORS = ("legacy-v1", "managed-sdr-v1")
# Metadata registry for plan construction. Pixel adapters remain separate.
def _animatable_descriptor(op_type: str) -> dict[str, Any] | str:
    """Advertise exact interpolation/outside policy per supported parameter."""
    from orga_drone.studio_grade_animation import ANIMATABLE_PARAMETERS

    params = ANIMATABLE_PARAMETERS.get(op_type)
    if not params:
        return "none"
    return {
        name: {
            "interpolation": policy["interpolation"],
            "outside": list(policy["outside"]),
            "min": policy["min"],
            "max": policy["max"],
        }
        for name, policy in params.items()
    }


OPERATION_DESCRIPTORS = {
    "legacy-stack-v1": {
        "evaluator": "legacy-v1",
        "domain": "legacy-native",
        "pointwise": False,
        "lut_bakeable": False,
        "parameters": list(LEGACY_KEYS),
        "animation": "legacy-source-local",
    },
    "primaries-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "linear-bt709",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": [
            "exposure",
            "gains",
            "kelvin",
            "tint",
            "contrast",
            "pivot",
            "tone",
            "blacks",
            "shadows",
            "highlights",
            "whites",
            "saturation",
        ],
        "animation": _animatable_descriptor("primaries-v1"),
    },
    "rgb-curves-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "declared",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": ["domain", "master", "red", "green", "blue"],
        "animation": "none",
    },
    "luma-curve-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "linear-bt709",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": ["curve"],
        "animation": "none",
    },
    "hue-vs-hue-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "encoded-bt709",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": ["curve"],
        "animation": "none",
    },
    "hue-vs-saturation-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "encoded-bt709",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": ["curve"],
        "animation": "none",
    },
    "hue-vs-luma-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "encoded-bt709",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": ["curve"],
        "animation": "none",
    },
    "luma-vs-saturation-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "encoded-bt709",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": ["curve"],
        "animation": "none",
    },
    "saturation-vs-saturation-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "encoded-bt709",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": ["curve"],
        "animation": "none",
    },
    "wheels-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "linear-bt709",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": ["lift", "gamma", "gain", "offset"],
        "animation": "none",
    },
    "managed-hsl-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "encoded-bt709",
        "pointwise": True,
        "lut_bakeable": True,
        "parameters": ["hue", "saturation", "lightness"],
        "animation": "none",
    },
    "creative-lut-v1": {
        "evaluator": "managed-sdr-v1",
        "domain": "declared",
        "pointwise": True,
        # Bakeable once a confined asset resolver supplies the cube at bake time.
        "lut_bakeable": True,
        "parameters": [
            "asset_id",
            "strength",
            "sha256",
            "interpolation",
            "domain",
            "input_profile",
            "output_profile",
        ],
        "animation": _animatable_descriptor("creative-lut-v1"),
    },
}


@dataclass(frozen=True)
class GradeModel:
    """The serialized snapshot prevents callers mutating nested state behind a digest."""

    authority: str
    evaluator: str
    revision: int
    _document: str
    _original: str | None
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Fresh JSON-compatible copy, including opaque unrelated/nested members."""
        return json.loads(self._document)

    def original_effect_settings(self) -> str | None:
        """Original stored bytes/text, even malformed legacy JSON; not a DB writer."""
        return self._original

    @property
    def grade(self) -> dict[str, Any] | None:
        return self.to_dict().get("grade") if self.authority == "canonical" else None

    @property
    def schema_version(self) -> int | None:
        grade = self.grade
        return grade["schema_version"] if grade is not None else None

    @property
    def steps(self) -> tuple[dict[str, Any], ...]:
        grade = self.grade
        return tuple(grade["steps"]) if grade is not None else ()

    @property
    def selections(self) -> tuple[dict[str, Any], ...]:
        grade = self.grade
        return tuple(grade["selections"]) if grade is not None else ()

    @property
    def animation(self) -> tuple[dict[str, Any], ...]:
        grade = self.grade
        return tuple(grade["animation"]) if grade is not None else ()

    @property
    def output(self) -> dict[str, Any] | None:
        grade = self.grade
        return grade["output"] if grade is not None else None

    @property
    def descriptors(self) -> dict[str, Any]:
        return json.loads(snapshot(OPERATION_DESCRIPTORS))


def _point_limits(value: Any, path: str = "grade", brush: bool = False) -> int:
    total = 0
    if isinstance(value, dict):
        brush = brush or value.get("type") == "brush"
        for key, item in value.items():
            if key == "points" and isinstance(item, list):
                limit = MAX_BRUSH_POINTS if brush else MAX_CURVE_POINTS
                array_value(item, f"{path}.points", limit)
                if brush:
                    total += len(item)
            total += _point_limits(item, f"{path}.{key}", brush)
    elif isinstance(value, list):
        total += sum(_point_limits(v, path, brush) for v in value)
    return total


def _validate_grade(grade: dict[str, Any]) -> None:
    if len(snapshot(grade).encode("utf-8")) > MAX_BYTES:
        fail("grade", "Grade exceeds 4 MiB")
    if integer(grade.get("schema_version"), "grade.schema_version", 1) != 1:
        fail("grade.schema_version", "Unsupported schema version", "UNSUPPORTED_GRADE")
    evaluator = grade.get("evaluator")
    if evaluator not in EVALUATORS:
        fail("grade.evaluator", "Unsupported evaluator", "UNSUPPORTED_GRADE")
    integer(grade.get("revision"), "grade.revision")
    source = object_value(grade.get("input"), "grade.input")
    profile = identifier(source.get("profile"), "grade.input.profile")
    if "technical_lut" not in source:
        fail("grade.input.technical_lut", "Explicit null or asset metadata required")
    technical = source["technical_lut"]
    if technical is not None:
        object_value(technical, "grade.input.technical_lut")
        # Technical asset/domain validation belongs to #352; never guess a transform.
        fail(
            "grade.input.technical_lut",
            "Technical LUT metadata not supported yet",
            "UNSUPPORTED_GRADE",
        )
    if evaluator == "managed-sdr-v1":
        if profile not in ("srgb", "bt709-sdr", "linear-bt709"):
            fail(
                "grade.input.profile",
                "Unsupported input profile",
                "UNSUPPORTED_INPUT_PROFILE",
            )
        if grade.get("working") != "linear-bt709":
            fail("grade.working", "Expected linear-bt709")
    else:
        if profile != "legacy-native" or grade.get("working") != "legacy-native":
            fail("grade.input", "Legacy adapter requires legacy-native domains")
    output = object_value(grade.get("output"), "grade.output")
    expected_profile = "bt709-sdr" if evaluator == "managed-sdr-v1" else "legacy-native"
    if output.get("profile") != expected_profile or output.get("gamut") != (
        "clip" if evaluator == "managed-sdr-v1" else "legacy"
    ):
        fail(
            "grade.output",
            "Unsupported output profile or gamut policy",
            "UNSUPPORTED_GRADE",
        )
    object_value(grade.get("extensions", {}), "grade.extensions")
    steps = array_value(grade.get("steps"), "grade.steps", MAX_STEPS)
    selections = array_value(
        grade.get("selections"), "grade.selections", MAX_SELECTIONS
    )
    animations = array_value(grade.get("animation"), "grade.animation", MAX_STEPS)
    ids: set[str] = set()
    selection_ids: set[str] = set()
    for kind, values in (
        ("selections", selections),
        ("steps", steps),
        ("animation", animations),
    ):
        for index, entry in enumerate(values):
            path = f"grade.{kind}[{index}]"
            item = object_value(entry, path)
            item_id = identifier(item.get("id"), path + ".id")
            if item_id in ids:
                fail(path + ".id", "Duplicate ID")
            ids.add(item_id)
            if kind == "selections":
                selection_ids.add(item_id)
                object_value(item.get("mask"), path + ".mask")
                object_value(item.get("qualifier"), path + ".qualifier")
                if type(item.get("invert")) is not bool:
                    fail(path + ".invert", "Expected a boolean")
    for index, step in enumerate(steps):
        path = f"grade.steps[{index}]"
        op = identifier(step.get("type"), path + ".type")
        if type(step.get("enabled")) is not bool:
            fail(path + ".enabled", "Expected a boolean")
        mix = number(step.get("mix"), path + ".mix", 0, 1)
        object_value(step.get("params"), path + ".params")
        if "selection_id" not in step:
            fail(path + ".selection_id", "Explicit null or selection ID required")
        selection = step["selection_id"]
        if (
            selection is not None
            and identifier(selection, path + ".selection_id") not in selection_ids
        ):
            fail(path + ".selection_id", "Dangling selection reference")
        descriptor = OPERATION_DESCRIPTORS.get(op)
        if step["enabled"]:
            if descriptor is None or descriptor["evaluator"] != evaluator:
                fail(
                    path + ".type", "Unsupported active operation", "UNSUPPORTED_GRADE"
                )
            if op == "legacy-stack-v1" and (mix != 1 or selection is not None):
                fail(
                    path,
                    "Legacy stack cannot be mixed or spatially selected",
                    "UNSUPPORTED_GRADE",
                )
    if evaluator == "legacy-v1" and (
        len(steps) != 1 or steps[0]["type"] != "legacy-stack-v1"
    ):
        fail("grade.steps", "Legacy wrapper requires exactly one legacy-stack-v1")
    from orga_drone.studio_grade_animation import validate_grade_animations

    # #358: validate clocks/targets/keys; unsupported combinations reject.
    validate_grade_animations(animations, steps)
    if _point_limits(grade) > MAX_BRUSH_POINTS:
        fail("grade", "Brush points exceed per-clip limit")


def _has_canonical_member(raw: str) -> bool:
    """Find lexically identifiable root keys even after invalid string escapes.

    This is a corruption guard, not a recovering JSON parser. Quoted spans are
    scanned with escape parity even when their contents cannot be decoded. Only
    a decodable key in root member position establishes canonical authority;
    values, nested keys, trailing documents and unterminated spans do not.
    A root grade key alone is enough: its colon/value may themselves be damaged.
    """
    index = len(raw) - len(raw.lstrip())
    if index == len(raw) or raw[index] != "{":
        return False
    stack = ["{"]
    root_key = True
    index += 1
    while index < len(raw):
        char = raw[index]
        if char == '"':
            start = index
            index += 1
            while index < len(raw) and raw[index] != '"':
                # Invalid escapes still escape the next lexical character. In
                # particular, do not treat quoted commas/braces as structure.
                index += 2 if raw[index] == "\\" else 1
            if index >= len(raw):
                return False
            index += 1
            if len(stack) == 1 and root_key:
                try:
                    key = json.loads(raw[start:index])
                except ValueError:
                    key = None
                if key == "grade":
                    return True
                root_key = False
            continue
        if char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack or stack[-1] != ("{" if char == "}" else "["):
                return False
            stack.pop()
            if not stack:
                return False
        elif len(stack) == 1:
            if char == ",":
                root_key = True
            elif char == ":":
                root_key = False
        index += 1
    return False


def read_grade(raw: str | Mapping[str, Any] | None) -> GradeModel:
    """Read without persistence or automatic wrapping; old malformed data stays legacy."""
    if raw is not None and not isinstance(raw, (str, Mapping)):
        fail("$", "Expected stored JSON text, object, or absent legacy data")
    original = raw if isinstance(raw, str) or raw is None else snapshot(dict(raw))
    try:
        data = json.loads(original) if original else {}
    except (ValueError, RecursionError):
        if original and _has_canonical_member(original):
            fail("grade", "Corrupt canonical JSON; original input was not modified")
        return GradeModel(
            "legacy", "legacy-v1", 0, "{}", original, ("legacy-invalid-json",)
        )
    if not isinstance(data, dict):
        return GradeModel(
            "legacy", "legacy-v1", 0, "{}", original, ("legacy-nonobject-json",)
        )
    if "grade" not in data:
        # Keep exact original for compatibility readers, even legacy NaN defaults.
        return GradeModel("legacy", "legacy-v1", 0, json.dumps(data), original)
    try:
        data = json.loads(original or "{}", object_pairs_hook=unique_object)
        document = snapshot(data)
        grade = object_value(data["grade"], "grade")
        _validate_grade(grade)
    except (RecursionError, OverflowError, UnicodeError) as exc:
        fail("grade", f"Invalid JSON representation: {type(exc).__name__}")
    return GradeModel(
        "canonical", grade["evaluator"], grade["revision"], document, original
    )
