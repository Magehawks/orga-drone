"""Schema, opacity and legacy compatibility regressions for issue #350."""

from __future__ import annotations

import builtins
import copy
import sqlite3
import subprocess
from fractions import Fraction
import json
from pathlib import Path

import pytest

from orga_drone.studio_grade_commands import validate_patch
from orga_drone.studio_grade_plan import RenderContext, evaluate_grade
from orga_drone.studio_grade_contract import GradeError
from orga_drone.studio_grade_model import read_grade


def managed() -> dict:
    return {
        "grade": {
            "schema_version": 1,
            "evaluator": "managed-sdr-v1",
            "revision": 7,
            "input": {"profile": "srgb", "technical_lut": None},
            "working": "linear-bt709",
            "steps": [],
            "selections": [],
            "animation": [],
            "output": {"profile": "bt709-sdr", "gamut": "clip"},
            "extensions": {},
        }
    }


def future_step(step_id: str = "future") -> dict:
    return {
        "id": step_id,
        "type": "future-curve-v9",
        "enabled": False,
        "mix": 1,
        "params": {"opaque": {"future": [None, True, 1.23456789]}},
        "selection_id": None,
        "future_field": {"precision": "unmodified"},
    }


@pytest.mark.parametrize(
    "raw", [None, "", "  ", "{}", "[]", "null", "bad JSON", '{"image":']
)
def test_legacy_read_preserves_original_without_wrapping(raw: str | None) -> None:
    result = read_grade(raw)
    assert result.authority == "legacy" and result.evaluator == "legacy-v1"
    assert result.revision == 0 and result.grade is None
    assert result.original_effect_settings() == raw


def test_all_legacy_sections_and_unknown_data_roundtrip() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/grade_model_v1.json").read_text()
    )
    result = read_grade(fixture["legacy"])
    assert result.to_dict() == fixture["legacy"]
    assert "grade" not in result.to_dict()
    assert set(fixture["legacy"]) >= {
        "image",
        "color",
        "hsl",
        "color_wheels",
        "detail",
        "saturation_ramp",
        "color_animation",
    }


def test_disabled_unknowns_and_unrelated_members_survive_without_aliasing() -> None:
    source = managed()
    source["grade"]["steps"] = [future_step()]
    source["grade"]["output"]["future_profile_data"] = {"items": [1, None, {"x": "y"}]}
    source["private_effect"] = {"v": 123}
    original = copy.deepcopy(source)
    model = read_grade(source)
    source["grade"]["steps"][0]["params"].clear()
    model.to_dict()["grade"]["output"].clear()
    model.grade["steps"].clear()
    assert model.to_dict() == original
    assert read_grade(model.to_dict()).to_dict() == original
    descriptors = model.descriptors
    descriptors.clear()
    assert model.descriptors["legacy-stack-v1"]["lut_bakeable"] is False


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("schema_version", None, "INVALID_GRADE"),
        ("schema_version", True, "INVALID_GRADE"),
        ("schema_version", 2, "UNSUPPORTED_GRADE"),
        ("schema_version", 0, "INVALID_GRADE"),
        ("evaluator", "future-v2", "UNSUPPORTED_GRADE"),
        ("evaluator", None, "UNSUPPORTED_GRADE"),
        ("revision", -1, "INVALID_GRADE"),
        ("revision", 1.5, "INVALID_GRADE"),
        ("revision", True, "INVALID_GRADE"),
        ("revision", 2**53, "INVALID_GRADE"),
        ("steps", None, "INVALID_GRADE"),
        ("selections", {}, "INVALID_GRADE"),
        ("animation", None, "INVALID_GRADE"),
        ("input", None, "INVALID_GRADE"),
        ("output", None, "INVALID_GRADE"),
        ("working", "srgb", "INVALID_GRADE"),
        ("extensions", None, "INVALID_GRADE"),
    ],
)
def test_envelope_validation(field, value, code) -> None:
    source = managed()
    source["grade"][field] = value
    with pytest.raises(GradeError) as error:
        read_grade(source)
    assert error.value.code == code
    assert error.value.as_dict()["path"].startswith("grade")


@pytest.mark.parametrize("value", [None, [], "bad", 1, False])
def test_present_grade_is_never_legacy_fallback(value) -> None:
    with pytest.raises(GradeError):
        read_grade({"grade": value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", None),
        ("enabled", 1),
        ("mix", -0.01),
        ("mix", 1.01),
        ("mix", True),
        ("mix", None),
        ("params", None),
        ("id", ""),
        ("id", "x" * 129),
        ("type", None),
        ("selection_id", "absent"),
    ],
)
def test_step_structure_is_strict_even_when_disabled(field, value) -> None:
    source = managed()
    step = future_step()
    step[field] = value
    source["grade"]["steps"] = [step]
    with pytest.raises(GradeError):
        read_grade(source)


def test_active_unknown_fails_even_with_zero_mix() -> None:
    source = managed()
    source["grade"]["steps"] = [dict(future_step(), enabled=True, mix=0)]
    with pytest.raises(GradeError, match="UNSUPPORTED_GRADE"):
        read_grade(source)


@pytest.mark.parametrize("profile", ["pq", "hlg", "dlog_m", "guess", None])
def test_unknown_input_transform_is_never_guessed(profile) -> None:
    source = managed()
    source["grade"]["input"]["profile"] = profile
    with pytest.raises(GradeError):
        read_grade(source)


def test_lut_transform_not_implemented_is_explicit() -> None:
    source = managed()
    source["grade"]["input"]["technical_lut"] = {"id": "future"}
    with pytest.raises(GradeError, match="UNSUPPORTED_GRADE"):
        read_grade(source)


def test_duplicate_ids_and_cross_resource_collisions() -> None:
    source = managed()
    source["grade"]["steps"] = [future_step("x"), future_step("x")]
    with pytest.raises(GradeError, match="Duplicate ID"):
        read_grade(source)
    source["grade"]["steps"] = [future_step("x")]
    source["grade"]["selections"] = [
        {"id": "x", "mask": {}, "qualifier": {}, "invert": False}
    ]
    with pytest.raises(GradeError, match="Duplicate ID"):
        read_grade(source)


def test_selection_resources_preserved_but_cannot_be_executed_implicitly() -> None:
    source = managed()
    selection = {
        "id": "mask",
        "mask": {},
        "qualifier": {},
        "invert": False,
        "opaque": [None],
    }
    source["grade"]["selections"] = [selection]
    source["grade"]["steps"] = [dict(future_step(), selection_id="mask")]
    assert read_grade(source).to_dict() == source


@pytest.mark.parametrize(
    "clock,step",
    [("source-local", "absent"), ("guess", "future"), ("story-local", "future")],
)
def test_animation_references_clocks_and_unimplemented_execution(clock, step) -> None:
    source = managed()
    source["grade"]["steps"] = [future_step()]
    source["grade"]["animation"] = [
        {"id": "a", "step_id": step, "clock": clock, "parameter": "exposure"}
    ]
    with pytest.raises(GradeError):
        read_grade(source)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), object()])
def test_nonjson_values_rejected_recursively(bad) -> None:
    source = managed()
    source["grade"]["extensions"] = {"nested": [bad]}
    with pytest.raises(GradeError):
        read_grade(source)


def test_duplicate_json_members_and_nonstring_keys_rejected() -> None:
    raw = json.dumps(managed()).replace('"revision": 7', '"revision": 7, "revision": 8')
    with pytest.raises(GradeError, match="Duplicate JSON"):
        read_grade(raw)
    source = managed()
    source["grade"]["extensions"] = {1: "must not coerce to string"}
    with pytest.raises(GradeError):
        read_grade(source)


def test_structural_limits_and_exact_boundaries() -> None:
    source = managed()
    source["grade"]["steps"] = [future_step(str(i)) for i in range(32)]
    read_grade(source)
    source["grade"]["steps"].append(future_step("overflow"))
    with pytest.raises(GradeError):
        read_grade(source)
    source = managed()
    source["grade"]["selections"] = [
        {"id": str(i), "mask": {}, "qualifier": {}, "invert": False} for i in range(33)
    ]
    with pytest.raises(GradeError):
        read_grade(source)


def test_curve_brush_byte_and_depth_limits() -> None:
    source = managed()
    step = future_step()
    step["params"] = {"points": [[0, 0]] * 4096}
    source["grade"]["steps"] = [step]
    read_grade(source)
    step["params"]["points"].append([1, 1])
    with pytest.raises(GradeError):
        read_grade(source)
    step["params"] = {
        "type": "brush",
        "strokes": [{"points": [[0, 0]] * 50000}, {"points": [[0, 0]] * 50000}],
    }
    read_grade(source)
    step["params"]["strokes"][1]["points"].append([0, 0])
    with pytest.raises(GradeError, match="Brush points"):
        read_grade(source)
    step["params"] = {"opaque": "x" * (4 * 1024 * 1024)}
    with pytest.raises(GradeError, match="4 MiB"):
        read_grade(source)
    nested = {}
    source = managed()
    source["grade"]["extensions"] = nested
    for _ in range(70):
        nested["child"] = {}
        nested = nested["child"]
    with pytest.raises(GradeError, match="nesting"):
        read_grade(source)


def wrapped_legacy(payload: dict) -> dict:
    return {
        "grade": {
            "schema_version": 1,
            "evaluator": "legacy-v1",
            "revision": 3,
            "input": {"profile": "legacy-native", "technical_lut": None},
            "working": "legacy-native",
            "steps": [
                {
                    "id": "old",
                    "type": "legacy-stack-v1",
                    "enabled": True,
                    "mix": 1,
                    "selection_id": None,
                    "params": payload,
                }
            ],
            "selections": [],
            "animation": [],
            "output": {"profile": "legacy-native", "gamut": "legacy"},
        }
    }


def golden() -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures/grade_model_v1.json").read_text()
    )


def test_golden_order_timing_domains_and_legacy_wrapping_parity() -> None:
    fixture = golden()
    raw = read_grade(fixture["legacy"])
    wrapper = read_grade(wrapped_legacy(fixture["legacy"]))
    context = RenderContext(
        "synthetic-video",
        source_pts=Fraction(12),
        source_in=Fraction(10),
        source_out=Fraction(20),
        source_local=Fraction(2),
        source_frame=360,
        story_time=Fraction(15, 2),
        speed=Fraction(1, 2),
        repeat_pass=2,
        transition_side="outgoing",
    )
    plan = evaluate_grade(raw, context)
    reference = fixture["at_source_local_2"]
    data = plan.to_dict()
    ops = data["operations"]
    assert [op["type"] for op in ops] == reference["operation_types"]
    assert ops[0]["params"] == reference["image"]
    assert ops[2]["params"]["strength_percent"] == reference["creative_strength"]
    assert ops[-1]["params"]["multiplier"] == reference["ramp_multiplier"]
    assert [entry["asset_id"] for entry in data["assets"]] == reference["asset_ids"]
    assert not plan.assets_resolved and not plan.grade_identity
    assert data["timing"]["source_local"] == [2, 1]
    assert data["timing"]["story_time"] == [15, 2]
    assert data["timing"]["speed"] == [1, 2]
    assert data["timing"]["repeat_pass"] == 2
    assert ops[0]["input_domain"] == "legacy-ffmpeg-auto"
    assert ops[3]["output_domain"] == "legacy-encoded-rgb"
    assert ops[-2]["pointwise"] is False
    assert plan.to_dict() == evaluate_grade(wrapper, context).to_dict()
    assert plan.semantic_digest == evaluate_grade(wrapper, context).semantic_digest
    assert data["capabilities"]["pixel_execution"] is False
    assert data["capabilities"]["requirements"] == ["legacy-animation-segmentation"]
    plan.to_dict()["operations"].clear()
    assert len(plan.to_dict()["operations"]) == 7


def test_neutral_identity_is_distinct_from_transfer_identity() -> None:
    legacy = evaluate_grade(read_grade(None), RenderContext("photo"))
    canonical = evaluate_grade(read_grade(managed()), RenderContext("photo"))
    assert legacy.grade_identity and canonical.grade_identity
    assert legacy.to_dict()["operations"] == canonical.to_dict()["operations"] == []
    assert canonical.to_dict()["input"]["profile"] == "srgb"
    assert canonical.to_dict()["input"]["output_domain"] == "linear-bt709"
    assert canonical.to_dict()["output"]["preview_transfer"] == "srgb"
    assert canonical.to_dict()["output"]["export_transfer"] == "bt709"
    assert canonical.to_dict()["output"]["comparison_gate"] == "M709-SRGB8-v1"
    assert legacy.semantic_digest != canonical.semantic_digest


def test_managed_serial_primaries_emit_plan_operations() -> None:
    source = managed()
    source["grade"]["steps"] = [
        {
            "id": "p1",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1,
            "selection_id": None,
            "params": {"exposure": 0.5, "contrast": 1.1, "pivot": 0.18},
        },
        {
            "id": "c1",
            "type": "rgb-curves-v1",
            "enabled": True,
            "mix": 0.5,
            "selection_id": None,
            "params": {"domain": "linear-bt709", "master": [[0, 0], [1, 1]]},
        },
    ]
    plan = evaluate_grade(read_grade(source), RenderContext("photo"))
    ops = plan.to_dict()["operations"]
    assert [item["type"] for item in ops] == ["primaries-v1", "rgb-curves-v1"]
    assert ops[0]["input_domain"] == "linear-bt709"
    assert ops[1]["mix"] == 0.5
    assert plan.grade_identity is False
    caps = plan.to_dict()["capabilities"]
    assert caps["pixel_execution"] is True
    assert caps["ffmpeg"] == "managed-lut-bake-v1"
    assert caps["adapter"] == "managed-sdr-cpu-v1"


def test_revision_opaque_fields_and_disabled_ops_do_not_change_semantic_digest() -> (
    None
):
    source = managed()
    a = evaluate_grade(read_grade(source), RenderContext("photo"))
    source["grade"]["revision"] = 99
    source["grade"]["extensions"] = {"future": 1}
    source["grade"]["steps"] = [future_step()]
    source["unrelated"] = "keep"
    b = evaluate_grade(read_grade(source), RenderContext("photo"))
    assert a.semantic_digest == b.semantic_digest
    assert b.to_dict()["capabilities"]["gpu"] == "not-integrated"


def test_asset_resolution_is_explicit_content_sensitive_and_never_reads_lut() -> None:
    fixture = golden()
    model = read_grade(fixture["legacy"])
    context = RenderContext("synthetic")
    requirements = evaluate_grade(model, context)
    digests = {key: "a" * 64 for key in fixture["at_source_local_2"]["asset_ids"]}
    resolved = evaluate_grade(model, context, asset_digests=digests)
    assert resolved.assets_resolved
    assert resolved.semantic_digest != requirements.semantic_digest
    digests[next(iter(digests))] = "b" * 64
    assert (
        evaluate_grade(model, context, asset_digests=digests).semantic_digest
        != resolved.semantic_digest
    )
    with pytest.raises(GradeError):
        evaluate_grade(model, context, asset_digests={"bad": "not-sha256"})


def test_digest_is_deterministic_across_json_key_order_and_context_changes() -> None:
    raw = golden()["legacy"]
    a = read_grade(json.dumps(raw, sort_keys=True))
    b = read_grade(json.dumps(raw, indent=4))
    context = RenderContext("source")
    assert evaluate_grade(a, context) == evaluate_grade(b, context)
    assert (
        evaluate_grade(a, context).semantic_digest
        != evaluate_grade(a, RenderContext("other-source")).semantic_digest
    )
    assert (
        evaluate_grade(a, context).semantic_digest
        != evaluate_grade(
            a, RenderContext("source", width=1280, height=720)
        ).semantic_digest
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_pts", 0.0),
        ("source_local", Fraction(1)),
        ("source_frame", True),
        ("repeat_pass", -1),
        ("speed", Fraction(0)),
        ("width", 0),
        ("height", None),
        ("orientation", 9),
        ("transition_side", "guess"),
        ("source_out", Fraction(0)),
        ("story_time", Fraction(-1)),
        ("source_id", ""),
        ("source_pts", Fraction(10**400)),
    ],
)
def test_context_strictness(field, value) -> None:
    values = {"source_id": "source", field: value}
    with pytest.raises(GradeError):
        evaluate_grade(read_grade(None), RenderContext(**values))


def test_legacy_invalid_nested_values_keep_existing_reader_defaults() -> None:
    raw = {
        "image": {"exposure": "bad", "warmth": True},
        "hsl": [],
        "color_wheels": None,
        "color": {},
        "detail": "bad",
        "saturation_ramp": False,
        "color_animation": None,
    }
    plan = evaluate_grade(read_grade(raw), RenderContext("source"))
    assert plan.grade_identity and plan.to_dict()["operations"] == []


def test_pure_read_evaluate_and_commands_do_not_access_disk_processes_or_db(
    monkeypatch,
) -> None:
    source = managed()
    source["grade"]["steps"] = [future_step()]
    command = {
        "type": "set_step_mix",
        "project_id": 1,
        "clip_id": 2,
        "expected_revision": 7,
        "params": {"step_id": "future", "mix": 0.5},
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("Pure grade foundation attempted IO")

    with monkeypatch.context() as m:
        m.setattr(builtins, "open", forbidden)
        m.setattr(Path, "open", forbidden)
        m.setattr(sqlite3, "connect", forbidden)
        m.setattr(subprocess, "run", forbidden)
        model = read_grade(source)
        evaluate_grade(model, RenderContext("source"))
        result = validate_patch(model, command, 7)
        assert result.changed and result.persisted is False
    assert source["grade"]["steps"][0]["mix"] == 1


def command(kind="set_step_mix", **params) -> dict:
    return {
        "type": kind,
        "project_id": 10,
        "clip_id": 20,
        "expected_revision": 7,
        "params": params,
    }


def test_commands_are_detached_proposals_preserving_opaque_data_and_revision() -> None:
    source = managed()
    source["grade"]["steps"] = [future_step("a"), future_step("b")]
    source["grade"]["steps"][0]["params"]["opaque"]["future"].append({"keep": True})
    model = read_grade(source)
    result = validate_patch(model, command("reorder_steps", ids=["b", "a"]), 7)
    assert result.changed and result.expected_revision == 7
    assert result.project_id == 10 and result.clip_id == 20 and not result.persisted
    assert result.proposed.revision == 7  # transaction owner assigns new token later
    assert result.proposed.grade["steps"][1] == source["grade"]["steps"][0]
    assert model.to_dict() == source
    unchanged = validate_patch(model, command("reorder_steps", ids=["a", "b"]), 7)
    assert not unchanged.changed


def test_commands_reject_enabling_unknown_edits_to_opaque_fields_and_stale_tokens() -> (
    None
):
    source = managed()
    source["grade"]["steps"] = [future_step()]
    model = read_grade(source)
    with pytest.raises(GradeError, match="UNSUPPORTED_GRADE"):
        validate_patch(
            model, command("set_step_enabled", step_id="future", enabled=True), 7
        )
    with pytest.raises(GradeError):
        validate_patch(model, command(step_id="future", mix=0.5, opaque="replace"), 7)
    with pytest.raises(GradeError, match="STALE_REVISION"):
        validate_patch(model, command(step_id="future", mix=0.5), 8)
    assert model.to_dict() == source


@pytest.mark.parametrize(
    "cmd",
    [
        command("reorder_steps", ids=[]),
        command("reorder_steps", ids=["future", "future"]),
        command("set_step_enabled", step_id="future", enabled=1),
        command(step_id="missing", mix=0.5),
        command(step_id="future", mix=float("nan")),
        command("raw-filter", filter="null"),
        dict(command(step_id="future", mix=0.5), project_id=True),
        dict(command(step_id="future", mix=0.5), clip_id=0),
        dict(command(step_id="future", mix=0.5), extra="bad"),
    ],
)
def test_invalid_command_contracts_reject_without_partial_mutation(cmd) -> None:
    source = managed()
    source["grade"]["steps"] = [future_step()]
    model = read_grade(source)
    with pytest.raises(GradeError):
        validate_patch(model, cmd, 7)
    assert model.to_dict() == source


def test_legacy_command_does_not_implicitly_migrate() -> None:
    with pytest.raises(GradeError, match="implicitly wrapped"):
        validate_patch(
            read_grade(None),
            dict(command("reorder_steps", ids=[]), expected_revision=0),
            0,
        )


@pytest.mark.parametrize(
    "profile,transfer",
    [
        ("srgb", "inverse-srgb"),
        ("bt709-sdr", "inverse-bt709"),
        ("linear-bt709", "identity"),
    ],
)
def test_managed_domain_adapters_are_explicit_with_cpu_pixel_execution(
    profile, transfer
) -> None:
    source = managed()
    source["grade"]["input"]["profile"] = profile
    plan = evaluate_grade(read_grade(source), RenderContext("source")).to_dict()
    assert plan["input"]["transfer"] == transfer
    assert plan["output"]["export_range"] == "limited"
    assert plan["output"]["export_format"] == "yuv420p"
    assert plan["capabilities"]["pixel_execution"] is True
    assert plan["capabilities"]["ffmpeg"] == "managed-lut-bake-v1"
    assert plan["capabilities"]["gpu"] == "not-integrated"


def test_legacy_stack_bypass_and_incompatible_mix_are_explicit() -> None:
    source = wrapped_legacy(golden()["legacy"])
    source["grade"]["steps"][0]["enabled"] = False
    assert evaluate_grade(read_grade(source), RenderContext("source")).grade_identity
    source["grade"]["steps"][0]["enabled"] = True
    source["grade"]["steps"][0]["mix"] = 0.5
    with pytest.raises(GradeError, match="UNSUPPORTED_GRADE"):
        read_grade(source)


def test_unhashable_animation_reference_is_typed_error_not_typeerror() -> None:
    source = managed()
    source["grade"]["animation"] = [{"id": "a", "step_id": []}]
    with pytest.raises(GradeError):
        read_grade(source)


@pytest.mark.parametrize(
    "raw",
    [
        '{"grade":',
        '{"note":"old", "grade":{"schema_version":1,',
        '{"gr\\u0061de": null,',
    ],
)
def test_corrupt_canonical_envelope_never_falls_back_to_legacy(raw) -> None:
    with pytest.raises(GradeError, match="Corrupt canonical"):
        read_grade(raw)


def test_legacy_note_containing_grade_text_is_not_a_canonical_key() -> None:
    raw = '{"note":"\\"grade\\": future", "image":'
    assert read_grade(raw).authority == "legacy"
    assert read_grade(raw).original_effect_settings() == raw


def test_typed_envelope_accessors_are_detached_and_unwrapped_legacy_has_no_version() -> (
    None
):
    source = managed()
    source["grade"]["steps"] = [future_step()]
    model = read_grade(source)
    assert model.schema_version == 1 and model.revision == 7
    assert model.selections == model.animation == ()
    assert model.output == {"profile": "bt709-sdr", "gamut": "clip"}
    model.steps[0]["params"].clear()
    model.output.clear()
    assert model.to_dict() == source
    assert read_grade(None).schema_version is None


def test_missing_optional_legacy_params_materialize_existing_neutral_defaults() -> None:
    model = read_grade(wrapped_legacy({}))
    assert model.steps[0]["params"] == {}
    assert evaluate_grade(model, RenderContext("source")).grade_identity


def test_typed_error_survives_context_manager_unwinding() -> None:
    from contextlib import contextmanager

    @contextmanager
    def boundary():
        yield

    with pytest.raises(GradeError, match="INVALID_GRADE") as caught:
        with boundary():
            read_grade({"grade": None})
    assert caught.value.as_dict()["code"] == "INVALID_GRADE"


@pytest.mark.parametrize(
    "raw",
    [
        r'{"note":"bad\q","grade"}',
        r'{"note":"bad\q","grade":null}',
        r'{"note":"bad\uZZZZ","grade":{',
        r'{"note":"bad\q","gr\u0061de"}',
        r'{"note":"bad\q","\u0067rade":null}',
        r'{"note":"bad\q, } [ \"quoted\"","grade":null}',
        r'{"note":"escaped slash \\","grade"}',
        '{"note":"bad\ncontrol","grade":null}',
        r'{"nested":{"note":"bad\q","grade":12},"grade"}',
        r'{"nested":[{"text":"bad\q"},"grade"],"grade"}',
        r'{"grade":{"note":"bad\q"}}',
        r'{"grade","note":"bad\q"}',
        r'{"gr\u0061de":null,"note":"bad\q"}',
    ],
)
def test_root_grade_remains_canonical_across_damaged_strings(raw) -> None:
    with pytest.raises(GradeError) as error:
        read_grade(raw)
    assert error.value.code == "INVALID_GRADE"
    assert "Corrupt canonical" in error.value.message


@pytest.mark.parametrize(
    "raw",
    [
        r'{"note":"bad\q","label":"grade"}',
        r'{"note":"bad\q","label":"grade: null"}',
        r'{"note":"bad\q \"grade\":null"}',
        r'{"note":"bad\q, \"grade\":null } ["}',
        r'{"note":"bad\q","nested":{"grade":null}}',
        r'{"nested":{"note":"bad\q","grade":null}}',
        r'{"note":"bad\q","nested":["grade",{"grade":null}]}',
        r'{"note":"bad\q","nested":[{"gr\u0061de":null}]}',
        r'{"note":"bad\q","label":"\u0067rade"}',
        r'{"note":"bad\q","gr\\u0061de":null}',
        r'{"note":"bad\q","label":"slash \\","image":',
        r'{"note":"bad\q"} {"grade":null}',
        r'[ {"note":"bad\q","grade":null} ]',
        r'{"note":"unterminated grade: null',
        r'{"note":"bad\q grade',
        r'{"note" "grade":null}',  # no root member separator: ambiguous value position
        r'{"nested":[} ,"grade":null}',  # mismatched brackets: cannot infer root position
        r'{"note":"bad\q","grade_suffix":null}',
    ],
)
def test_damaged_legacy_values_nested_keys_and_ambiguous_text_do_not_claim_grade(
    raw,
) -> None:
    model = read_grade(raw)
    assert model.authority == "legacy"
    assert model.diagnostics == ("legacy-invalid-json",)
    assert model.original_effect_settings() == raw


@pytest.mark.parametrize(
    "raw",
    [
        r'{"label":"grade"}',
        r'{"label":"\"grade\":null"}',
        r'{"nested":{"grade":null}}',
        r'{"nested":[{"grade":null}]}',
        r'{"label":"slash \\ and quote \" and braces {},"}',
    ],
)
def test_valid_legacy_strings_and_nested_grade_keep_original_values(raw) -> None:
    model = read_grade(raw)
    assert model.authority == "legacy" and not model.diagnostics
    assert model.to_dict() == json.loads(raw)
    assert model.original_effect_settings() == raw
def test_upsert_step_params_create_update_and_unknown_keys() -> None:
    source = managed()
    model = read_grade(source)
    created = validate_patch(
        model,
        command(
            "upsert_step_params",
            step_id="p1",
            type="primaries-v1",
            params={"exposure": 0.5, "saturation": 1.1},
            enabled=True,
        ),
        7,
    )
    assert created.changed
    step = created.proposed.grade["steps"][0]
    assert step["id"] == "p1" and step["params"]["exposure"] == 0.5
    updated = validate_patch(
        created.proposed,
        dict(
            command(
                "upsert_step_params",
                step_id="p1",
                type="primaries-v1",
                params={"exposure": 1.0},
            ),
            expected_revision=7,
        ),
        7,
    )
    assert updated.proposed.grade["steps"][0]["params"]["exposure"] == 1.0
    assert updated.proposed.grade["steps"][0]["params"]["saturation"] == 1.1
    with pytest.raises(GradeError):
        validate_patch(
            created.proposed,
            dict(
                command(
                    "upsert_step_params",
                    step_id="p1",
                    type="primaries-v1",
                    params={"not_a_real_param": 1},
                ),
                expected_revision=7,
            ),
            7,
        )
    with pytest.raises(GradeError):
        validate_patch(
            created.proposed,
            dict(
                command(
                    "upsert_step_params",
                    step_id="p1",
                    type="wheels-v1",
                    params={"lift": 0},
                ),
                expected_revision=7,
            ),
            7,
        )


def test_upsert_selection_bind_and_remove_step() -> None:
    source = managed()
    source["grade"]["steps"] = [
        {
            "id": "p1",
            "type": "primaries-v1",
            "enabled": True,
            "mix": 1,
            "params": {"exposure": 0},
            "selection_id": None,
        }
    ]
    model = read_grade(source)
    with_sel = validate_patch(
        model,
        command(
            "upsert_selection",
            selection={
                "id": "s1",
                "mask": {"combine": "union", "leaves": []},
                "qualifier": {},
                "invert": False,
            },
        ),
        7,
    )
    bound = validate_patch(
        with_sel.proposed,
        dict(
            command("bind_step_selection", step_id="p1", selection_id="s1"),
            expected_revision=7,
        ),
        7,
    )
    assert bound.proposed.grade["steps"][0]["selection_id"] == "s1"
    cleared = validate_patch(
        bound.proposed,
        dict(
            command("bind_step_selection", step_id="p1", selection_id=None),
            expected_revision=7,
        ),
        7,
    )
    assert cleared.proposed.grade["steps"][0]["selection_id"] is None
    assert cleared.proposed.grade["selections"] == []
    removed = validate_patch(
        bound.proposed,
        dict(command("remove_step", step_id="p1"), expected_revision=7),
        7,
    )
    assert removed.proposed.grade["steps"] == []
    assert removed.proposed.grade["selections"] == []
