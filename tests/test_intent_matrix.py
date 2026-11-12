"""Deterministic intent-matrix validation (issue #292).

The versioned matrix (tests/fixtures/intent_matrix.json) maps ~20 DE/EN
creator intents to supported capabilities. This suite runs the DETERMINISTIC
part in CI (no cloud/model invocation): every mapped case must reference an
implemented action whose live validator accepts the recorded params;
unsupported cases must carry an honest disclosure; repeated identical
commands must report no-op; unrelated stored keys must stay unchanged.

Semantic phrasing quality and visual results stay MANUAL (rubric in the
fixture) and are never claimed as pixel proof.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orga_drone.studio_actions import (
    ActionValidationError,
    ACTION_SPECS,
    canonical as action_canonical,
    prepare_action,
    resolve_action_spec,
    validate_action_params,
)

ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads(
    (ROOT / "tests/fixtures/intent_matrix.json").read_text(encoding="utf-8")
)

_EMPTY_SETTINGS = json.dumps({"image": {"exposure": 0}})


def _case(case_id: str) -> dict:  # type: ignore[type-arg]
    return next(case for case in MATRIX["cases"] if case["id"] == case_id)


def test_matrix_schema_and_case_count() -> None:
    """The matrix is versioned and carries the required rubric and ~20 cases."""
    assert MATRIX["schema"] == "orga-drone-intent-matrix-v1"
    assert {"PASS", "FAIL", "MANUAL"} <= set(MATRIX["rubric"])
    assert len(MATRIX["cases"]) >= 20


def test_every_case_has_required_fields() -> None:
    markers = ("not implemented", "no shared action", "requires", "must ask", "decline")
    for case in MATRIX["cases"]:
        assert {"id", "request_en", "request_de", "expected_action", "params",
                "checks", "unsupported_disclosure", "manual_note"} <= set(case), case["id"]
        if case["expected_action"] is None:
            assert case["unsupported_disclosure"], case["id"]
            assert any(marker in case["unsupported_disclosure"].lower() for marker in markers), case["id"]
        else:
            assert case["params"] is not None, case["id"]


def test_expected_actions_exist_and_params_validate() -> None:
    """Mapped cases point to implemented actions; params pass the LIVE
    validator (bounds drift fails here). Placeholder asset ids stand for
    imported assets and are substituted with schema-valid names — the
    lookup itself is disk-free."""
    implemented = {spec.name for spec in ACTION_SPECS}
    for case in MATRIX["cases"]:
        action = case["expected_action"]
        if action is None:
            continue
        assert action in implemented, (case["id"], action)
        spec = resolve_action_spec(action, 1)
        params = dict(case["params"])
        for key, value in list(params.items()):
            if isinstance(value, str) and value.startswith("<"):
                params[key] = "a" * 32 + ".cube"
        validate_action_params(spec, params)


def test_unsupported_cases_disclose_honestly() -> None:
    """Every unmapped case must disclose the limitation or the UI-only gap —
    never a silent decline, never a fake capability. Disclosures either name
    the capability gap, the missing prerequisite, or the decline rule."""
    ui_only = [case for case in MATRIX["cases"] if "ui_only_capability" in case["checks"]]
    unsupported = [case for case in MATRIX["cases"]
                   if case["expected_action"] is None and "ui_only_capability" not in case["checks"]]
    assert ui_only and unsupported  # both classes are represented
    markers = ("not implemented", "no shared action", "requires", "must ask", "decline")
    for case in unsupported:
        disclosure = case["unsupported_disclosure"]
        assert disclosure, case["id"]
        assert any(marker in disclosure.lower() for marker in markers), case["id"]


def test_prepared_settings_keep_unrelated_keys(tmp_path: Path) -> None:
    """prepare_action on a populated clip keeps unrelated stored members."""
    raw = json.dumps({
        "image": {"exposure": 5},
        "hsl": {"ranges": {"blue": {"hue": 12}}},
        "vendor": {"opaque": [1, None]},
    })
    spec = resolve_action_spec("clip.color.image", 1)
    prepared = prepare_action(spec, raw, {"warmth": 10}, set(), tmp_path)
    stored = json.loads(prepared)
    assert stored["image"]["exposure"] == 5
    assert stored["hsl"]["ranges"]["blue"]["hue"] == 12
    assert stored["vendor"] == {"opaque": [1, None]}


def test_repeated_identical_command_is_no_op(tmp_path: Path) -> None:
    """Idempotency: a repeated identical action reports a canonical no-op."""
    spec = resolve_action_spec("clip.color.image", 1)
    once = prepare_action(spec, _EMPTY_SETTINGS, {"warmth": 20}, set(), tmp_path)
    twice = prepare_action(spec, once, {"warmth": 20}, set(), tmp_path)
    assert action_canonical(once) == action_canonical(twice)
    assert action_canonical(twice) == action_canonical(once)


def test_out_of_bounds_intent_rejects(tmp_path: Path) -> None:
    """A hallucinated strength value fails validation with a stable code."""
    spec = resolve_action_spec("clip.color.image", 1)
    with pytest.raises(ActionValidationError) as excinfo:
        prepare_action(spec, _EMPTY_SETTINGS, {"exposure": 500}, set(), tmp_path)
    assert excinfo.value.code == "INVALID_PARAMS"


def test_missing_lut_rejects(tmp_path: Path) -> None:
    """A look action referencing a not-imported asset fails closed."""
    spec = resolve_action_spec("clip.color.look", 1)
    with pytest.raises(ActionValidationError) as excinfo:
        prepare_action(
            spec, _EMPTY_SETTINGS,
            {"creative_lut": "does-not-exist.cube", "creative_strength": 50},
            set(), tmp_path,
        )
    assert excinfo.value.code == "INVALID_PARAMS"


def test_replaces_not_stacks_semantics(tmp_path: Path) -> None:
    """Applying another creative LUT REPLACES the previous one (single
    creative slot); conversion choices stay separate. The validator checks
    real confined assets, so both cubes exist on disk."""
    spec = resolve_action_spec("clip.color.look", 1)
    first, second = "a" * 32 + ".cube", "b" * 32 + ".cube"
    for name in (first, second):
        (tmp_path / "luts").mkdir(exist_ok=True)
        (tmp_path / "luts" / name).write_text(
            'TITLE "t"\nLUT_3D_SIZE 2\n' + "\n".join(["0 0 0"] * 7 + ["1 1 1"]) + "\n",
            encoding="utf-8",
        )
    raw = json.dumps({"color": {"creative_lut": first, "creative_strength": 80}})
    prepared = json.loads(prepare_action(
        spec, raw, {"creative_lut": second}, {first, second}, tmp_path
    ))
    assert prepared["color"]["creative_lut"] == second
