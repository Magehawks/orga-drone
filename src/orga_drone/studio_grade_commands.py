"""Pure proposed grade commands for future shared actions (#351/#363).

No database writes, revision assignment, authorization, history or HTTP endpoints.
The caller must verify target identity/local authorization and publish atomically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from orga_drone.studio_grade_contract import (
    fail,
    identifier,
    integer,
    number,
    object_value,
    snapshot,
)
from orga_drone.studio_grade_model import GradeModel, read_grade

COMMAND_CAPABILITIES = ("set_step_enabled", "set_step_mix", "reorder_steps")


@dataclass(frozen=True)
class GradeCommandResult:
    proposed: GradeModel
    project_id: int
    clip_id: int
    expected_revision: int
    changed: bool
    persisted: bool = False


def validate_patch(
    current: GradeModel,
    command: Mapping[str, Any],
    expected_revision: int,
) -> GradeCommandResult:
    """Validate a bounded command and return a detached proposal, not a saved grade.

    No public setter is wired. Revision remains unchanged until #351 allocates it
    in the same transaction as history/persistence. Unknown fields cannot be edited.
    """
    current = (
        read_grade(current.to_dict())
        if current.authority == "canonical"
        else read_grade(current.original_effect_settings())
    )
    integer(expected_revision, "expected_revision")
    payload = object_value(dict(command), "command")
    if set(payload) != {"type", "project_id", "clip_id", "expected_revision", "params"}:
        fail(
            "command",
            "Expected type, project_id, clip_id, expected_revision and params only",
        )
    project = integer(payload["project_id"], "command.project_id", 1)
    clip = integer(payload["clip_id"], "command.clip_id", 1)
    revision = integer(payload["expected_revision"], "command.expected_revision")
    if revision != expected_revision or revision != current.revision:
        fail("command.expected_revision", "Grade revision conflict", "STALE_REVISION")
    grade = current.grade
    if grade is None:
        fail(
            "command",
            "Legacy clips cannot be implicitly wrapped by a grade command",
            "UNSUPPORTED_GRADE",
        )
    params = object_value(payload["params"], "command.params")
    kind = payload["type"]
    if kind not in COMMAND_CAPABILITIES:
        fail(
            "command.type",
            "Command is not supported by this foundation",
            "UNSUPPORTED_GRADE",
        )
    steps = grade["steps"]
    if kind == "reorder_steps":
        if set(params) != {"ids"} or not isinstance(params["ids"], list):
            fail("command.params", "Expected ids array only")
        ids = [identifier(item, "command.params.ids") for item in params["ids"]]
        lookup = {step["id"]: step for step in steps}
        if len(ids) != len(set(ids)) or set(ids) != set(lookup):
            fail("command.params.ids", "Expected an exact permutation of step IDs")
        grade["steps"] = [lookup[item] for item in ids]
    else:
        field = "enabled" if kind == "set_step_enabled" else "mix"
        if set(params) != {"step_id", field}:
            fail("command.params", "Expected step_id and " + field + " only")
        step_id = identifier(params["step_id"], "command.params.step_id")
        step = next((entry for entry in steps if entry["id"] == step_id), None)
        if step is None:
            fail("command.params.step_id", "Unknown step ID")
        if field == "enabled" and type(params[field]) is not bool:
            fail("command.params.enabled", "Expected a boolean")
        if field == "mix":
            number(params[field], "command.params.mix", 0, 1)
        step[field] = params[field]
    document = current.to_dict()
    document["grade"] = grade
    proposed = read_grade(document)
    changed = snapshot(proposed.to_dict()) != snapshot(current.to_dict())
    return GradeCommandResult(proposed, project, clip, revision, changed)
