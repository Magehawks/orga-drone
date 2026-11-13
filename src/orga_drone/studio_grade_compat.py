"""Compatibility views so legacy color readers honor wrapped grades.

After ``wrap_legacy_to_canonical``, color keys live inside ``legacy-stack-v1``.
Existing ``*_from_effect_settings`` helpers still expect top-level keys. This
module expands the stack for those readers without inventing a second grade
store. Managed-sdr grades intentionally expose no legacy color keys: the
managed applicator / bake path owns pixels.
"""

from __future__ import annotations

import json
from typing import Any

from orga_drone.studio_grade_contract import GradeError, LEGACY_KEYS, snapshot
from orga_drone.studio_grade_model import read_grade


def color_effect_settings_view(raw: str | None) -> str | None:
    """JSON text for legacy color readers, or the original raw for non-canonical."""
    if raw is None or not str(raw).strip():
        return raw
    try:
        model = read_grade(raw)
    except GradeError:
        return raw
    if model.authority != "canonical" or model.grade is None:
        return raw
    if model.evaluator == "managed-sdr-v1":
        # Preserve non-color root keys; omit legacy color sections so readers
        # stay neutral while the managed bake path applies the grade.
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return "{}"
        if not isinstance(data, dict):
            return "{}"
        cleaned = {
            key: value for key, value in data.items() if key not in LEGACY_KEYS and key != "grade"
        }
        return snapshot(cleaned)
    if model.evaluator != "legacy-v1":
        return raw
    steps = model.grade.get("steps") or []
    if not steps:
        return "{}"
    step = steps[0]
    if not isinstance(step, dict) or not step.get("enabled", True):
        return "{}"
    if step.get("type") != "legacy-stack-v1":
        return raw
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    payload: dict[str, Any] = {
        key: params[key] for key in LEGACY_KEYS if key in params
    }
    return snapshot(payload)
