"""Pure proposed grade commands for future shared actions (#351/#363).

No database writes, revision assignment, authorization, history or HTTP endpoints.
The caller must verify target identity/local authorization and publish atomically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping  # Any used by upsert_animation list typing

from orga_drone.studio_grade_contract import (
    fail,
    identifier,
    integer,
    number,
    object_value,
    snapshot,
)
from orga_drone.studio_grade_model import OPERATION_DESCRIPTORS, GradeModel, read_grade

COMMAND_CAPABILITIES = (
    "set_step_enabled",
    "set_step_mix",
    "reorder_steps",
    "upsert_step_params",
    "remove_step",
    "upsert_selection",
    "bind_step_selection",
    "apply_preset",
    "upsert_animation",
    "remove_animation",
    "reorder_animation",
)


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
    animations = list(grade.get("animation") or [])
    if kind == "reorder_steps":
        if set(params) != {"ids"} or not isinstance(params["ids"], list):
            fail("command.params", "Expected ids array only")
        ids = [identifier(item, "command.params.ids") for item in params["ids"]]
        lookup = {step["id"]: step for step in steps}
        if len(ids) != len(set(ids)) or set(ids) != set(lookup):
            fail("command.params.ids", "Expected an exact permutation of step IDs")
        grade["steps"] = [lookup[item] for item in ids]
    elif kind == "reorder_animation":
        if set(params) != {"ids"} or not isinstance(params["ids"], list):
            fail("command.params", "Expected ids array only")
        ids = [identifier(item, "command.params.ids") for item in params["ids"]]
        lookup = {entry["id"]: entry for entry in animations}
        if len(ids) != len(set(ids)) or set(ids) != set(lookup):
            fail("command.params.ids", "Expected an exact permutation of animation IDs")
        grade["animation"] = [lookup[item] for item in ids]
    elif kind == "remove_animation":
        if set(params) != {"animation_id"}:
            fail("command.params", "Expected animation_id only")
        animation_id = identifier(params["animation_id"], "command.params.animation_id")
        kept = [entry for entry in animations if entry.get("id") != animation_id]
        if len(kept) == len(animations):
            fail("command.params.animation_id", "Unknown animation ID")
        grade["animation"] = kept
    elif kind == "upsert_animation":
        if set(params) != {"animation"}:
            fail("command.params", "Expected animation object only")
        entry = object_value(params["animation"], "command.params.animation")
        animation_id = identifier(entry.get("id"), "command.params.animation.id")
        replaced = False
        next_animations: list[Any] = []
        for existing in animations:
            if existing.get("id") == animation_id:
                next_animations.append(dict(entry))
                replaced = True
            else:
                next_animations.append(existing)
        if not replaced:
            next_animations.append(dict(entry))
        grade["animation"] = next_animations
    elif kind == "upsert_step_params":
        allowed_keys = {"step_id", "type", "params", "enabled", "mix", "selection_id"}
        if not {"step_id", "type", "params"}.issubset(params) or set(params) - allowed_keys:
            fail(
                "command.params",
                "Expected step_id, type, params and optional enabled/mix/selection_id",
            )
        step_id = identifier(params["step_id"], "command.params.step_id")
        step_type = identifier(params["type"], "command.params.type")
        body = object_value(params["params"], "command.params.params")
        descriptor = OPERATION_DESCRIPTORS.get(step_type)
        if descriptor is None:
            fail(
                "command.params.type",
                "Unsupported step type for upsert_step_params",
                "UNSUPPORTED_GRADE",
            )
        raw_params = descriptor["parameters"]
        allowed_params = {
            str(item) for item in (raw_params if isinstance(raw_params, list) else [])
        }
        unknown = set(body) - allowed_params
        if unknown:
            fail(
                "command.params.params",
                "Unknown parameter keys for "
                + step_type
                + ": "
                + ", ".join(sorted(unknown)),
            )
        if "enabled" in params and type(params["enabled"]) is not bool:
            fail("command.params.enabled", "Expected a boolean")
        if "mix" in params:
            number(params["mix"], "command.params.mix", 0, 1)
        selection_value = params.get("selection_id", None)
        if "selection_id" in params and selection_value is not None:
            identifier(selection_value, "command.params.selection_id")
        step = next((entry for entry in steps if entry["id"] == step_id), None)
        if step is None:
            grade["steps"] = list(steps) + [
                {
                    "id": step_id,
                    "type": step_type,
                    "enabled": bool(params["enabled"]) if "enabled" in params else True,
                    "mix": float(params["mix"]) if "mix" in params else 1.0,
                    "params": dict(body),
                    "selection_id": selection_value if "selection_id" in params else None,
                }
            ]
        else:
            if step["type"] != step_type:
                fail("command.params.type", "Cannot change step type via upsert_step_params")
            merged = dict(step.get("params") or {})
            merged.update(body)
            step["params"] = merged
            if "enabled" in params:
                step["enabled"] = bool(params["enabled"])
            if "mix" in params:
                step["mix"] = float(params["mix"])
            if "selection_id" in params:
                step["selection_id"] = selection_value
    elif kind == "remove_step":
        if set(params) != {"step_id"}:
            fail("command.params", "Expected step_id only")
        step_id = identifier(params["step_id"], "command.params.step_id")
        kept = [entry for entry in steps if entry["id"] != step_id]
        if len(kept) == len(steps):
            fail("command.params.step_id", "Unknown step ID")
        used = {
            entry.get("selection_id")
            for entry in kept
            if entry.get("selection_id") is not None
        }
        grade["steps"] = kept
        grade["selections"] = [
            entry for entry in grade.get("selections") or [] if entry.get("id") in used
        ]
    elif kind == "upsert_selection":
        if set(params) != {"selection"}:
            fail("command.params", "Expected selection object only")
        entry = object_value(params["selection"], "command.params.selection")
        selection_id = identifier(entry.get("id"), "command.params.selection.id")
        selections = list(grade.get("selections") or [])
        replaced = False
        next_selections: list[Any] = []
        for existing in selections:
            if existing.get("id") == selection_id:
                next_selections.append(dict(entry))
                replaced = True
            else:
                next_selections.append(existing)
        if not replaced:
            next_selections.append(dict(entry))
        grade["selections"] = next_selections
    elif kind == "bind_step_selection":
        if set(params) != {"step_id", "selection_id"}:
            fail("command.params", "Expected step_id and selection_id only")
        step_id = identifier(params["step_id"], "command.params.step_id")
        selection_value = params["selection_id"]
        if selection_value is not None:
            identifier(selection_value, "command.params.selection_id")
        step = next((entry for entry in steps if entry["id"] == step_id), None)
        if step is None:
            fail("command.params.step_id", "Unknown step ID")
        step["selection_id"] = selection_value
        if selection_value is None:
            used = {
                entry.get("selection_id")
                for entry in steps
                if entry.get("selection_id") is not None
            }
            grade["selections"] = [
                entry
                for entry in grade.get("selections") or []
                if entry.get("id") in used
            ]
    elif kind == "apply_preset":
        if set(params) != {"preset_id"}:
            fail("command.params", "Expected preset_id only")
        from orga_drone.studio_grade_presets import (
            compile_quick_look_to_primaries,
            neutral_primaries_params,
        )

        preset_raw = params["preset_id"]
        if preset_raw in ("", None):
            body = neutral_primaries_params()
            extensions = object_value(grade.get("extensions") or {}, "grade.extensions")
            extensions.pop("creative_preset", None)
            grade["extensions"] = extensions
            step = next((entry for entry in steps if entry["type"] == "primaries-v1"), None)
            if step is not None:
                step["enabled"] = True
                step["params"] = dict(body)
        else:
            try:
                compiled = compile_quick_look_to_primaries(str(preset_raw))
            except ValueError as exc:
                fail("command.params.preset_id", str(exc))
            body = object_value(compiled["params"], "command.params.compiled.params")
            step = next((entry for entry in steps if entry["type"] == "primaries-v1"), None)
            if step is None:
                grade["steps"] = list(steps) + [
                    {
                        "id": "primaries-preset",
                        "type": "primaries-v1",
                        "enabled": True,
                        "mix": 1.0,
                        "params": dict(body),
                        "selection_id": None,
                    }
                ]
            else:
                step["enabled"] = True
                step["params"] = dict(body)
            extensions = object_value(grade.get("extensions") or {}, "grade.extensions")
            extensions["creative_preset"] = {
                "id": compiled["preset_id"],
                "source": compiled["source"],
                "compiled_type": compiled["type"],
            }
            grade["extensions"] = extensions
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
    # read_grade revalidates animation references and unsupported targets.
    proposed = read_grade(document)
    changed = snapshot(proposed.to_dict()) != snapshot(current.to_dict())
    return GradeCommandResult(proposed, project, clip, revision, changed)
