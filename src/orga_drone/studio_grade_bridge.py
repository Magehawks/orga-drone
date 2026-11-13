"""Shared grade command bridge for UI HTTP and Control API (#363).

One validation + publish path. Transports must not invent a second editor.
"""

from __future__ import annotations

from typing import Any, Mapping

from orga_drone.studio_grade_commands import (
    COMMAND_CAPABILITIES,
    GradeCommandResult,
    validate_patch,
)
from orga_drone.studio_grade_model import OPERATION_DESCRIPTORS, GradeModel, read_grade
from orga_drone.studio_grade_persistence import publish_grade_document


def grade_capability_report(model: GradeModel) -> dict[str, Any]:
    """Report actual supported grade operations for discovery (#363 / #296)."""
    operations: dict[str, Any] = {}
    for name, descriptor in OPERATION_DESCRIPTORS.items():
        evaluator = descriptor.get("evaluator")
        if model.authority == "canonical" and evaluator != model.evaluator:
            continue
        if model.authority != "canonical" and name != "legacy-stack-v1":
            # Unwrapped legacy clips stay on the existing color routes until wrap.
            continue
        raw_params = descriptor.get("parameters") or []
        param_names = (
            list(raw_params) if isinstance(raw_params, (list, tuple)) else []
        )
        operations[name] = {
            "evaluator": evaluator,
            "pointwise": bool(descriptor.get("pointwise")),
            "lut_bakeable": bool(descriptor.get("lut_bakeable")),
            "animation": descriptor.get("animation"),
            "parameters": param_names,
        }
    return {
        "authority": model.authority,
        "evaluator": model.evaluator,
        "revision": int(model.revision),
        "commands": list(COMMAND_CAPABILITIES),
        "operations": operations,
        "writes": model.authority == "canonical",
    }


def propose_grade_command(
    effect_settings: str | None,
    command: Mapping[str, Any],
    *,
    expected_revision: int,
) -> GradeCommandResult:
    """Validate one bounded grade command against the current clip grade."""
    model = read_grade(effect_settings)
    return validate_patch(model, command, expected_revision=expected_revision)


def apply_grade_command_text(
    effect_settings: str | None,
    command: Mapping[str, Any],
    *,
    expected_revision: int,
) -> str:
    """Return published effect_settings JSON for one shared grade command."""
    current = read_grade(effect_settings)
    result = validate_patch(current, command, expected_revision=expected_revision)
    return publish_grade_document(
        current,
        result.proposed.to_dict(),
        expected_revision=expected_revision,
    )
