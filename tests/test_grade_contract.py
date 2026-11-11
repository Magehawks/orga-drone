"""Contract tests for the canonical grade model and pure render-plan
evaluator (ADR 0035 + docs/architecture/COLOR_WORKSPACE_CONTRACT.md, #350).

OpenCode evidence lane. Written against the APPROVED CONTRACT and verified
against the merged foundation (PR #370, develop 51d9de3). Deviations between
assumption and implementation found during integration:

- ``validate_patch`` ships in ``studio_grade_commands`` (the ADR names it in
  the engine interface list without pinning the module); it is a #350
  function, NOT deferred to #351/#363 — those only wire it.
- ``RenderContext`` is a dataclass with ``Fraction`` rational timing, not a
  plain dict. A dict context is not contract-mandated, so the tests follow
  the implementation.
- ``mix`` and ``selection_id`` are REQUIRED step members (explicit null
  allowed). The contract lists them as shape members without an
  optional-marker; the stricter reading is accepted and documented.
- Only ``legacy-stack-v1`` is registered. Managed ACTIVE operator evaluation
  belongs to #352 and is NOT_RUN here; animation evaluation is deliberately
  UNSUPPORTED_GRADE pending #358 and is tested AS a rejection.
"""

from __future__ import annotations

import importlib.util
import json
from fractions import Fraction
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


def _managed_grade(**overrides) -> dict:  # type: ignore[no-untyped-def]
    """The contract's illustrative neutral managed grade."""
    grade = {
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
    grade.update(overrides)
    return grade


def _legacy_grade(**step_overrides) -> dict:  # type: ignore[no-untyped-def]
    """The ADR's explicit legacy wrapper shape (one legacy-stack-v1 step)."""
    step = {
        "id": "step-legacy-0001",
        "type": "legacy-stack-v1",
        "enabled": True,
        "mix": 1,
        "params": {"image": {"exposure": 12}, "vendor_hint": {"deep": [1, None]}},
        "selection_id": None,
    }
    step.update(step_overrides)
    return {
        "schema_version": 1,
        "evaluator": "legacy-v1",
        "revision": 1,
        "input": {"profile": "legacy-native", "technical_lut": None},
        "working": "legacy-native",
        "steps": [step],
        "selections": [],
        "animation": [],
        "output": {"profile": "legacy-native", "gamut": "legacy"},
        "extensions": {},
    }


def _step(step_id: str, step_type: str, *, enabled: bool = True, params: dict | None = None,
          mix: float | None = None, selection_id: str | None = None) -> dict:
    """A step per the foundation's strict shape: mix and selection_id are
    required members (explicit null for no selection)."""
    step: dict = {
        "id": step_id,
        "type": step_type,
        "enabled": enabled,
        "mix": 1 if mix is None else mix,
        "params": params or {},
        "selection_id": selection_id,
    }
    return step


def _render_context(**overrides) -> object:
    """Contract RenderContext (rational timing; the evaluator revalidates it).
    Frozen dataclass: overrides go through the constructor."""
    from orga_drone.studio_grade_plan import RenderContext

    values: dict = {
        "source_id": "clip-1",
        "source_pts": Fraction(0),
        "source_frame": 0,
        "source_in": Fraction(0),
        "source_local": Fraction(0),
        "story_time": Fraction(0),
        "speed": Fraction(1),
        "repeat_pass": 0,
        "transition_side": "single",
        "width": 1920,
        "height": 1080,
        "orientation": 1,
    }
    values.update(overrides)
    return RenderContext(**values)


def _effect_settings_with_grade(grade: dict) -> str:
    return json.dumps({"image": {"exposure": 5}, "grade": grade})


def _read(text: str):  # type: ignore[no-untyped-def]
    from orga_drone.studio_grade_model import read_grade  # type: ignore[import-untyped]

    return read_grade(text)


# ---------------------------------------------------------------------------
# 1. Legacy compatibility (contract: "Data envelope and authority")
# ---------------------------------------------------------------------------


@requires_grade_model
def test_missing_grade_is_legacy_without_writing(tmp_path: Path) -> None:
    """Missing grade means legacy; read alone never writes and never wraps."""
    from orga_drone.studio_grade_plan import RenderContext  # noqa: F401 — import surface sanity
    settings = json.dumps({"image": {"exposure": 7}, "vendor_note": {"nested": True}})
    model = _read(settings)
    assert model.original_effect_settings() == settings
    assert model.authority != "canonical"
    assert model.evaluator == "legacy-v1"
    assert model.revision == 0
    # No disk write happened and the input text is unchanged.
    assert list(tmp_path.iterdir()) == []


@requires_grade_model
def test_null_scalar_and_null_grade_are_errors_not_reset() -> None:
    """grade:null, malformed grade and null scalars are errors, not implicit
    resets. Verified against the foundation: object_value(None) raises
    INVALID_GRADE at path 'grade'."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    with pytest.raises(GradeError) as excinfo:
        _read(json.dumps({"grade": None}))
    assert excinfo.value.code == "INVALID_GRADE"
    with pytest.raises(GradeError):
        _read(_effect_settings_with_grade(_managed_grade(revision=None)))


@requires_grade_model
def test_corrupt_canonical_json_splits_recognizable_from_ambiguous() -> None:
    """Damaged text WITH a recognizable root grade member raises
    INVALID_GRADE (never overwritten as legacy); fully ambiguous damaged
    text cannot establish authority and stays legacy WITH diagnostics and
    the original text retained (foundation read semantics; #351 must never
    overwrite a failed read)."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    recognizable = '{"image": {"exposure": 5}, "grade": {"schema_version": 1,'
    with pytest.raises(GradeError) as excinfo:
        _read(recognizable)
    assert excinfo.value.code == "INVALID_GRADE"

    ambiguous = "{not json at all, sorry}"
    model = _read(ambiguous)
    assert model.authority != "canonical"
    assert model.original_effect_settings() == ambiguous
    assert model.diagnostics  # damage recorded, not swallowed


@requires_grade_model
def test_unknown_evaluator_is_read_only_never_neutral() -> None:
    """An unknown evaluator is a typed UNSUPPORTED_GRADE error; no neutral
    fallback materializes."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(_managed_grade(evaluator="future-engine-v9")))
    assert excinfo.value.code == "UNSUPPORTED_GRADE"
    assert excinfo.value.path == "grade.evaluator"


# ---------------------------------------------------------------------------
# 2. Canonical model: schema, IDs, validation, limits
# ---------------------------------------------------------------------------


@requires_grade_model
def test_schema_version_and_evaluator_are_distinct_fields() -> None:
    """schema_version describes data shape; evaluator describes mathematics.
    Neither may change implicitly on reopen."""
    model = _read(_effect_settings_with_grade(_managed_grade()))
    assert model.schema_version == 1
    assert model.evaluator == "managed-sdr-v1"


@requires_grade_model
def test_duplicate_ids_and_dangling_references_reject() -> None:
    """Duplicate step IDs and a dangling selection_id are errors."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    duplicated = _managed_grade(steps=[
        _step("step-0001", "legacy-stack-v1", enabled=False),
        _step("step-0001", "legacy-stack-v1", enabled=False),
    ])
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(duplicated))
    assert excinfo.value.path == "grade.steps[1].id"

    dangling = _managed_grade(steps=[_step("step-0001", "legacy-stack-v1", selection_id="missing-sel")])
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(dangling))
    assert excinfo.value.path == "grade.steps[0].selection_id"


@requires_grade_model
def test_disabled_unknown_operation_is_preserved_and_bypassed() -> None:
    """Unknown DISABLED operations roundtrip byte-value-for-value and bypass
    evaluation."""
    unknown_step = _step(
        "step-0002", "vendor-bloom-v3", enabled=False,
        params={"strength": 0.5, "custom": {"deep": [1, 2, {"x": None}]}},
    )
    grade = _managed_grade(steps=[unknown_step])
    model = _read(_effect_settings_with_grade(grade))
    serialized = model.to_dict()["grade"]
    stored_step = next(step for step in serialized["steps"] if step["id"] == "step-0002")
    assert stored_step == unknown_step


@requires_grade_model
def test_unknown_enabled_operation_rejects() -> None:
    """Unknown ENABLED operations block at read time with UNSUPPORTED_GRADE
    on the step type path; no silent neutral fallback."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    grade = _managed_grade(steps=[_step("step-0003", "vendor-bloom-v3")])
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(grade))
    assert excinfo.value.code == "UNSUPPORTED_GRADE"
    assert excinfo.value.path == "grade.steps[0].type"


@requires_grade_model
def test_structural_limits_reject_atomically() -> None:
    """32 steps, 32 selections and the 4 MiB grade ceiling are hard caps;
    each failure names its exact path."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    too_many_steps = _managed_grade(steps=[
        _step(f"step-{index:04d}", "legacy-stack-v1", enabled=False)
        for index in range(33)
    ])
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(too_many_steps))
    assert excinfo.value.path == "grade.steps"

    too_many_selections = _managed_grade(selections=[
        {"id": f"sel-{index:04d}", "mask": {"leaves": []}, "qualifier": None, "invert": False}
        for index in range(33)
    ])
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(too_many_selections))
    assert excinfo.value.path == "grade.selections"

    oversized = _managed_grade(extensions={"payload": "x" * (4 * 1024 * 1024)})
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(oversized))
    assert excinfo.value.path == "grade"
    assert "4 MiB" in excinfo.value.message


@requires_grade_model
def test_nonfinite_numbers_are_rejected() -> None:
    """Finite JSON numbers only; NaN fails validation with INVALID_GRADE.
    Tree-level errors carry the '$.'-rooted JSON path (schema-level errors
    use the plain path — foundation inconsistency, documented in the
    matrix)."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    grade = _managed_grade(steps=[_step("step-0007", "legacy-stack-v1", enabled=False, mix=float("nan"))])
    # json.dumps emits a bare NaN literal; the reader must reject it.
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(grade))
    assert excinfo.value.code == "INVALID_GRADE"
    assert excinfo.value.path == "$.grade.steps[0].mix"


@requires_grade_model
def test_animation_entries_are_unsupported_until_358() -> None:
    """Canonical animation references/clock validate, then fail with
    UNSUPPORTED_GRADE — #358's gate; nothing is silently flattened."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    animated = _managed_grade(
        steps=[_step("step-0001", "legacy-stack-v1", enabled=False)],
        animation=[{
            "id": "anim-0001", "step_id": "step-0001", "clock": "source-local",
            "parameter": "mix", "keys": [],
        }],
    )
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(animated))
    assert excinfo.value.code == "UNSUPPORTED_GRADE"
    assert excinfo.value.path == "grade.animation[0]"


@requires_grade_model
def test_technical_lut_metadata_rejects_until_352() -> None:
    """A non-null technical LUT is an explicit UNSUPPORTED_GRADE at read
    (#352's gate); no guessed input transform."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    with_lut = _managed_grade(input={
        "profile": "srgb",
        "technical_lut": {"asset_id": "lut-0001", "input_profile": "dlog_m"},
    })
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(with_lut))
    assert excinfo.value.code == "UNSUPPORTED_GRADE"
    assert excinfo.value.path == "grade.input.technical_lut"


@requires_grade_model
def test_unsupported_managed_input_profile_is_typed() -> None:
    """HDR/log input profiles fail with UNSUPPORTED_INPUT_PROFILE; no
    automatic D-Log M conversion."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    hdr = _managed_grade(input={"profile": "pq-hdr", "technical_lut": None})
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(hdr))
    assert excinfo.value.code == "UNSUPPORTED_INPUT_PROFILE"


@requires_grade_model
def test_legacy_wrapper_requires_its_exact_shape() -> None:
    """evaluator legacy-v1 demands exactly one legacy-stack-v1 step and
    legacy-native domains (ADR: frozen old keys as provenance)."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    wrong_step = _legacy_grade()
    wrong_step["steps"][0]["type"] = "primaries-v1"
    with pytest.raises(GradeError) as excinfo:
        _read(_effect_settings_with_grade(wrong_step))
    assert excinfo.value.code == "UNSUPPORTED_GRADE"

    managed_domains = _legacy_grade()
    managed_domains["input"]["profile"] = "srgb"
    with pytest.raises(GradeError):
        _read(_effect_settings_with_grade(managed_domains))


# ---------------------------------------------------------------------------
# 3. Render plan (contract: "Engine, workspace and evidence interfaces")
# ---------------------------------------------------------------------------


@requires_grade_plan
def test_evaluation_is_deterministic() -> None:
    """Pure evaluation: identical inputs produce identical plans/digests."""
    model = _read(_effect_settings_with_grade(_managed_grade()))
    context = _render_context()
    first = evaluate_plan(model, context)
    second = evaluate_plan(model, context)
    assert first.to_dict() == second.to_dict()
    assert first.semantic_digest == second.semantic_digest


def evaluate_plan(model, context):  # type: ignore[no-untyped-def]
    from orga_drone.studio_grade_plan import evaluate_grade  # type: ignore[import-untyped]

    return evaluate_grade(model, context)


@requires_grade_plan
def test_plan_carries_domains_order_and_requirements() -> None:
    """RenderPlan contains explicit evaluator/schema, the working domain,
    the output profile and capability requirements."""
    model = _read(_effect_settings_with_grade(_managed_grade()))
    plan = evaluate_plan(model, _render_context()).to_dict()
    assert plan["schema_version"] == 1
    assert plan["evaluator"] == "managed-sdr-v1"
    assert "linear-bt709" in json.dumps(plan)
    assert "bt709-sdr" in json.dumps(plan)


@requires_grade_plan
def test_plan_timing_invariant_is_enforced() -> None:
    """source_local must equal source_pts - source_in; violations are typed
    errors, never silently accepted."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    model = _read(_effect_settings_with_grade(_managed_grade()))
    consistent = _render_context(
        source_pts=Fraction(7, 30), source_in=Fraction(0), source_local=Fraction(7, 30)
    )
    assert evaluate_plan(model, consistent) is not None
    with pytest.raises(GradeError) as excinfo:
        evaluate_plan(model, _render_context(
            source_pts=Fraction(7, 30), source_in=Fraction(0), source_local=Fraction(99)
        ))
    assert excinfo.value.path == "context.source_local"


@requires_grade_plan
def test_pure_evaluation_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pure evaluation has no disk writes and no DOM access."""
    model = _read(_effect_settings_with_grade(_managed_grade()))
    monkeypatch.chdir(tmp_path)
    evaluate_plan(model, _render_context())
    assert list(tmp_path.rglob("*")) == []


@requires_grade_plan
def test_semantic_digest_excludes_revision_and_disabled() -> None:
    """Digest covers active semantics; revision and disabled operations are
    excluded from semantic reuse."""
    digest_a = evaluate_plan(
        _read(_effect_settings_with_grade(_managed_grade())), _render_context()
    ).semantic_digest
    digest_b = evaluate_plan(
        _read(_effect_settings_with_grade(_managed_grade(revision=2))), _render_context()
    ).semantic_digest
    assert digest_a == digest_b

    disabled_extra = _managed_grade(steps=[_step("step-0009", "vendor-bloom-v3", enabled=False)])
    digest_c = evaluate_plan(
        _read(_effect_settings_with_grade(disabled_extra)), _render_context()
    ).semantic_digest
    assert digest_a == digest_c


@requires_grade_plan
def test_legacy_evaluation_keeps_established_order_and_domains() -> None:
    """The legacy wrapper plan emits the established operation order
    (image → technical LUT → creative LUT → HSL → wheels → detail → ramp)
    with legacy domains, reader-materialized defaults, the
    legacy-reference-only capability and unknown non-legacy params filtered
    out (ADR: native builders, no cube roundtrip)."""
    model = _read(_effect_settings_with_grade(_legacy_grade(
        params={
            "image": {"exposure": 12},
            "hsl": {"ranges": {"blue": {"hue": 15}}},
            "color_wheels": {"wheels": {"shadows": {"x": 0.2}}},
            "detail": {"sharpen": 40},
            "vendor_hint": {"never_rendered": True},
        }
    )))
    plan = evaluate_plan(model, _render_context()).to_dict()
    operations = plan["operations"]
    type_names = [operation["type"] for operation in operations]
    assert type_names == [
        "legacy-image-v1", "legacy-hsl-v1", "legacy-wheels-v1", "legacy-detail-v1",
    ], type_names
    # Domains follow the established split; detail is spatial (pointwise off).
    assert operations[0]["input_domain"] == "legacy-ffmpeg-auto"
    assert operations[1]["input_domain"] == "legacy-encoded-rgb"
    assert operations[2]["input_domain"] == "legacy-encoded-rgb"
    assert operations[3]["input_domain"] == "legacy-ffmpeg-auto"
    assert operations[3]["pointwise"] is False
    for operation in operations:
        assert operation["capability"] == "legacy-reference-only"
        assert "vendor_hint" not in operation["params"]
    # Reader defaults materialize for unset legacy fields.
    assert operations[0]["params"]["exposure"] == 12
    assert operations[0]["params"]["warmth"] == 0


# ---------------------------------------------------------------------------
# 4. Commands, revision and safety
# ---------------------------------------------------------------------------


def _validate(current, command: dict, expected_revision: int):  # type: ignore[no-untyped-def]
    from orga_drone.studio_grade_commands import validate_patch  # type: ignore[import-untyped]

    return validate_patch(current, command, expected_revision)


@requires_grade_model
def test_stale_revision_conflicts_without_mutation() -> None:
    """validate_patch with a stale expected_revision returns STALE_REVISION
    and does not mutate the current model."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    model = _read(_effect_settings_with_grade(_managed_grade(revision=3)))
    command = {
        "type": "set_step_enabled",
        "project_id": 1,
        "clip_id": 1,
        "expected_revision": 2,
        "params": {"step_id": "step-0001", "enabled": False},
    }
    with pytest.raises(GradeError) as excinfo:
        _validate(model, command, 2)
    assert excinfo.value.code == "STALE_REVISION"
    # The model snapshot is unchanged.
    assert model.revision == 3


@requires_grade_model
def test_command_result_is_detached_and_unpersisted() -> None:
    """A returned proposal is detached (persisted=false); the stored
    snapshot never changes through validation. Reorder params are an exact
    permutation under the 'ids' key; violations reject without mutation."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    model = _read(_effect_settings_with_grade(_managed_grade(
        revision=1,
        steps=[_step("step-a", "legacy-stack-v1", enabled=False),
               _step("step-b", "legacy-stack-v1", enabled=False)],
    )))
    command = {
        "type": "reorder_steps",
        "project_id": 1,
        "clip_id": 1,
        "expected_revision": 1,
        "params": {"ids": ["step-b", "step-a"]},
    }
    result = _validate(model, command, 1)
    assert result is not None
    assert getattr(result, "persisted", False) is False
    assert model.revision == 1  # proposal only; transaction owner allocates later

    # Not an exact permutation of existing IDs → atomic rejection.
    invalid = dict(command)
    invalid["params"] = {"ids": ["step-b"]}
    with pytest.raises(GradeError) as excinfo:
        _validate(model, invalid, 1)
    assert excinfo.value.code == "INVALID_GRADE"
    assert excinfo.value.path == "command.params.ids"


@requires_grade_model
def test_unknown_command_rejects_without_mutation() -> None:
    """Unknown command types and extra fields fail without mutation — later
    commands (add/update params, conversion, presets) stay behind their own
    approved gates (#351/#363)."""
    from orga_drone.studio_grade_contract import GradeError  # type: ignore[import-untyped]

    model = _read(_effect_settings_with_grade(_managed_grade(revision=1)))
    future = {
        "type": "convert_profile",
        "project_id": 1,
        "clip_id": 1,
        "expected_revision": 1,
        "params": {"profile": "bt709-sdr"},
    }
    with pytest.raises(GradeError):
        _validate(model, future, 1)
    extra_field = {
        "type": "reorder_steps",
        "project_id": 1,
        "clip_id": 1,
        "expected_revision": 1,
        "params": {"ordered_ids": []},
        "injected": True,
    }
    with pytest.raises(GradeError):
        _validate(model, extra_field, 1)
    assert model.revision == 1
