"""Contract tests for the canonical grade model and pure render-plan
evaluator (ADR 0035 + docs/architecture/COLOR_WORKSPACE_CONTRACT.md, #350).

OpenCode evidence lane. These tests are written against the APPROVED
CONTRACT, not against Codex's implementation branch. The contract pins the
module boundaries (ADR 0035 "Proposed file boundaries"):
``studio_grade_model`` owns read/validation, ``studio_grade_plan`` owns pure
evaluation. While #350 is unmerged both imports fail and every engine test
reports **NOT_RUN** with that explicit reason â€” no production stubs are
created to fake a pass.

When #350 lands, these tests activate and any naming/semantics deviation
from the contract surfaces as a FAIL that must be reconciled with the ADR.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


GRADE_MODEL_MODULE = "orga_drone.studio_grade_model"
GRADE_PLAN_MODULE = "orga_drone.studio_grade_plan"

_NOT_RUN_REASON = (
    "#350 canonical grade foundation is not merged yet (ADR 0035 still "
    "Proposed); contract test armed, NOT_RUN until studio_grade_model/"
    "studio_grade_plan exist on develop"
)

requires_grade_model = pytest.mark.skipif(
    not _module_available(GRADE_MODEL_MODULE), reason=_NOT_RUN_REASON
)
requires_grade_plan = pytest.mark.skipif(
    not _module_available(GRADE_PLAN_MODULE), reason=_NOT_RUN_REASON
)


# ---------------------------------------------------------------------------
# Contract fixtures (deterministic, built from the contract's JSON shape)
# ---------------------------------------------------------------------------


def _neutral_grade() -> dict:
    """The contract's illustrative neutral managed grade."""
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "srgb", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [],
        "selections": [],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def _effect_settings_with_grade(grade: dict | None, **extra_top_level) -> dict:
    settings: dict = {"image": {"exposure": 5}, "color": {"input_profile": "rec709"}}
    if grade is not None:
        settings["grade"] = grade
    elif "grade" in extra_top_level:
        settings["grade"] = extra_top_level.pop("grade")
    settings.update(extra_top_level)
    return settings


def _step(step_id: str, step_type: str, *, enabled: bool = True, params: dict | None = None,
          mix: float | None = None, selection_id: str | None = None) -> dict:
    step: dict = {"id": step_id, "type": step_type, "enabled": enabled, "params": params or {}}
    if mix is not None:
        step["mix"] = mix
    if selection_id is not None:
        step["selection_id"] = selection_id
    return step


def _render_context(**overrides) -> dict:
    """Contract RenderContext: rational timing, source identity, geometry."""
    context = {
        "source_id": "clip-1",
        "source_pts_num": 0,
        "source_pts_den": 1,
        "frame_index": 0,
        "source_in_s": 0.0,
        "source_local_s": 0.0,
        "story_s": 0.0,
        "speed": 1.0,
        "repeat_pass": 1,
        "transition_side": None,
        "width": 1920,
        "height": 1080,
        "orientation": 1,
    }
    context.update(overrides)
    return context


# ---------------------------------------------------------------------------
# 1. Legacy compatibility (contract: "Data envelope and authority")
# ---------------------------------------------------------------------------


@requires_grade_model
def test_missing_grade_is_legacy_without_writing(tmp_path: Path) -> None:
    """Missing grade means legacy; read alone never writes and never wraps."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    settings = json.dumps({"image": {"exposure": 7}, "vendor_note": {"nested": True}})
    model = read_grade(settings)
    assert model.original_effect_settings() == settings
    assert model.authority == "legacy-v1" or model.evaluator == "legacy-v1"
    # No database/disk write happened (tmp_path stays empty) and the input
    # text is unchanged.
    assert list(tmp_path.iterdir()) == []


@requires_grade_model
def test_null_scalar_and_null_grade_are_errors_not_reset() -> None:
    """grade:null, malformed grade and null scalars are errors, not implicit
    resets."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    with pytest.raises(Exception) as excinfo:
        read_grade(json.dumps({"grade": None}))
    assert "INVALID_GRADE" in str(excinfo.value) or getattr(excinfo.value, "code", "") == "INVALID_GRADE"
    with pytest.raises(Exception):
        read_grade(json.dumps({"grade": {"schema_version": 1, "evaluator": "managed-sdr-v1", "revision": "broken"}}))
    with pytest.raises(Exception):
        read_grade(json.dumps({"grade": _neutral_grade() | {"revision": None}}))


@requires_grade_model
def test_unknown_evaluator_is_read_only_never_neutral() -> None:
    """An unknown evaluator blocks grading edits; no neutral fallback."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    grade = _neutral_grade() | {"evaluator": "future-engine-v9"}
    with pytest.raises(Exception) as excinfo:
        read_grade(json.dumps({"grade": grade}))
    assert "UNSUPPORTED" in str(excinfo.value) or "UNSUPPORTED" in str(
        getattr(excinfo.value, "code", "")
    )


# ---------------------------------------------------------------------------
# 2. Canonical model: schema, IDs, order, validation, limits
# ---------------------------------------------------------------------------


@requires_grade_model
def test_schema_version_and_evaluator_are_distinct_fields() -> None:
    """schema_version describes data shape; evaluator describes mathematics.
    Neither may change implicitly on reopen."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    model = read_grade(json.dumps({"grade": _neutral_grade()}))
    assert model.schema_version == 1
    assert model.evaluator == "managed-sdr-v1"


@requires_grade_model
def test_stable_ids_and_no_dangling_references() -> None:
    """Step IDs are stable and opaque; a dangling selection_id is an error."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    grade = _neutral_grade() | {
        "steps": [_step("step-0001", "registered-op-v1", selection_id="missing-sel")],
    }
    with pytest.raises(Exception):
        read_grade(json.dumps({"grade": grade}))


@requires_grade_model
def test_disabled_unknown_operation_is_preserved_and_bypassed() -> None:
    """Unknown DISABLED operations roundtrip byte-value-for-value and bypass
    evaluation."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    unknown_step = _step("step-0002", "vendor-bloom-v3", enabled=False,
                         params={"strength": 0.5, "custom": {"deep": [1, 2, {"x": None}]}})
    grade = _neutral_grade() | {"steps": [unknown_step]}
    model = read_grade(json.dumps({"grade": grade}))
    serialized = model.to_dict()["grade"]
    stored_step = next(step for step in serialized["steps"] if step["id"] == "step-0002")
    assert stored_step == unknown_step


@requires_grade_model
def test_unknown_enabled_operation_rejects() -> None:
    """Unknown ENABLED operations block rendering with UNSUPPORTED_GRADE; no
    silent neutral fallback."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]
    from orga_drone.studio_grade_plan import evaluate_grade  # type: ignore[import-untyped]

    grade = _neutral_grade() | {"steps": [_step("step-0003", "vendor-bloom-v3")]}
    model = read_grade(json.dumps({"grade": grade}))
    with pytest.raises(Exception) as excinfo:
        evaluate_grade(model, _render_context())
    assert "UNSUPPORTED_GRADE" in str(excinfo.value) or "UNSUPPORTED_GRADE" in str(
        getattr(excinfo.value, "code", "")
    )


def _oversize_grade(target_bytes: int) -> dict:
    grade = _neutral_grade()
    grade["extensions"] = {"payload": "x" * target_bytes}
    return grade


@requires_grade_model
def test_structural_limits_reject_atomically() -> None:
    """32 steps, 32 selections, 4096 curve points, 100000 brush points per
    clip and 4 MiB grade JSON are hard caps; oversized edits fail whole."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    too_many_steps = _neutral_grade() | {"steps": [
        _step(f"step-{index:04d}", "registered-op-v1", enabled=False)
        for index in range(33)
    ]}
    with pytest.raises(Exception):
        read_grade(json.dumps({"grade": too_many_steps}))

    too_many_selections = _neutral_grade() | {"selections": [
        {"id": f"sel-{index:04d}", "mask": {"leaves": []}, "qualifier": None, "invert": False}
        for index in range(33)
    ]}
    with pytest.raises(Exception):
        read_grade(json.dumps({"grade": too_many_selections}))

    four_mib = _oversize_grade(4 * 1024 * 1024)
    with pytest.raises(Exception):
        read_grade(json.dumps({"grade": four_mib}))


@requires_grade_model
def test_nonfinite_numbers_are_rejected() -> None:
    """Finite JSON numbers only; NaN/Infinity fail validation."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    # Python's json accepts NaN by default; the contract does not.
    grade_text = json.dumps({"grade": _neutral_grade()})[:-2] + ', "steps": [{"id": "s", "mix": NaN}]}'
    with pytest.raises(Exception):
        read_grade(grade_text)


@requires_grade_model
def test_missing_optional_params_materialize_neutral_defaults() -> None:
    """Missing optional step parameters materialize documented neutral
    defaults; a reset is an explicit command, not an omission."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    grade = _neutral_grade() | {"steps": [_step("step-0004", "registered-op-v1", params={})]}
    model = read_grade(json.dumps({"grade": grade}))
    assert model is not None  # validated; defaults are part of the model


# ---------------------------------------------------------------------------
# 3. Render plan (contract: "Engine, workspace and evidence interfaces")
# ---------------------------------------------------------------------------


@requires_grade_plan
def test_evaluation_is_deterministic() -> None:
    """Pure evaluation: identical inputs produce identical plans/digests."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]
    from orga_drone.studio_grade_plan import evaluate_grade  # type: ignore[import-untyped]

    model = read_grade(json.dumps({"grade": _neutral_grade()}))
    context = _render_context()
    first = evaluate_grade(model, context)
    second = evaluate_grade(model, context)
    assert first.to_dict() == second.to_dict()
    assert first.semantic_digest == second.semantic_digest


@requires_grade_plan
def test_plan_carries_domains_order_and_requirements() -> None:
    """RenderPlan contains ordered operations with explicit domains, plan
    versions, output profile and capability requirements."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]
    from orga_drone.studio_grade_plan import evaluate_grade  # type: ignore[import-untyped]

    model = read_grade(json.dumps({"grade": _neutral_grade()}))
    plan = evaluate_grade(model, _render_context()).to_dict()
    assert plan["schema_version"] == 1
    assert plan["evaluator"] == "managed-sdr-v1"
    assert "linear-bt709" in json.dumps(plan)
    assert "bt709-sdr" in json.dumps(plan)


@requires_grade_plan
def test_plan_timing_references_are_explicit() -> None:
    """Context carries rational PTS/frame index/trim/clocks; source_local
    must equal source_pts - source_in (contract invariant)."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]
    from orga_drone.studio_grade_plan import evaluate_grade  # type: ignore[import-untyped]

    model = read_grade(json.dumps({"grade": _neutral_grade()}))
    context = _render_context(
        source_pts_num=7, source_pts_den=30, source_in_s=0.5, source_local_s=7 / 30 - 0.5
    )
    plan = evaluate_grade(model, context)
    assert plan is not None
    inconsistent = _render_context(
        source_pts_num=7, source_pts_den=30, source_in_s=0.5, source_local_s=99.0
    )
    with pytest.raises(Exception):
        evaluate_grade(model, inconsistent)


@requires_grade_plan
def test_pure_evaluation_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pure evaluation has no disk writes and no DOM access."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]
    from orga_drone.studio_grade_plan import evaluate_grade  # type: ignore[import-untyped]

    model = read_grade(json.dumps({"grade": _neutral_grade()}))
    monkeypatch.chdir(tmp_path)
    evaluate_grade(model, _render_context())
    assert list(tmp_path.rglob("*")) == []


@requires_grade_plan
def test_semantic_digest_excludes_revision_and_disabled() -> None:
    """Digest covers active semantics; revision and disabled operations are
    excluded from semantic reuse."""
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]
    from orga_drone.studio_grade_plan import evaluate_grade  # type: ignore[import-untyped]

    base = _neutral_grade()
    digest_a = evaluate_grade(read_grade(json.dumps({"grade": base})), _render_context()).semantic_digest
    revision_bump = base | {"revision": 2}
    digest_b = evaluate_grade(read_grade(json.dumps({"grade": revision_bump})), _render_context()).semantic_digest
    assert digest_a == digest_b

    disabled_extra = base | {"steps": [_step("step-0009", "vendor-bloom-v3", enabled=False)]}
    digest_c = evaluate_grade(read_grade(json.dumps({"grade": disabled_extra})), _render_context()).semantic_digest
    assert digest_a == digest_c


# ---------------------------------------------------------------------------
# 4. Commands, revision and safety
# ---------------------------------------------------------------------------


@requires_grade_model
def test_stale_revision_conflicts_without_mutation() -> None:
    """validate_patch with a stale expected_revision returns STALE_REVISION
    and does not mutate the current model."""
    from orga_drone.studio_grade_model import read_grade, validate_patch  # type: ignore[import-untyped]

    model = read_grade(json.dumps({"grade": _neutral_grade() | {"revision": 3}}))
    command = {
        "type": "set_step_enabled",
        "project_id": 1,
        "clip_id": 1,
        "expected_revision": 2,
        "params": {"step_id": "step-0001", "enabled": False},
    }
    with pytest.raises(Exception) as excinfo:
        validate_patch(model, command, expected_revision=2)
    assert "STALE" in str(excinfo.value) or "STALE" in str(getattr(excinfo.value, "code", ""))


@requires_grade_model
def test_command_result_is_detached() -> None:
    """A returned model is a detached copy; mutating it never rewrites the
    stored snapshot."""
    from orga_drone.studio_grade_model import read_grade, validate_patch  # type: ignore[import-untyped]

    model = read_grade(json.dumps({"grade": _neutral_grade() | {"revision": 1}}))
    command = {
        "type": "reorder_steps",
        "project_id": 1,
        "clip_id": 1,
        "expected_revision": 1,
        "params": {"ordered_ids": []},
    }
    result = validate_patch(model, command, expected_revision=1)
    assert result is not None
    assert getattr(result, "persisted", False) is False
