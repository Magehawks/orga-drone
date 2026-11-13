"""Canonical grade animation clocks (#358)."""

from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path

import pytest

from orga_drone.studio_grade_animation import (
    materialize_grade_at,
    sample_animation_value,
)
from orga_drone.studio_grade_clock import (
    ClipTimingInputs,
    build_render_context,
    map_repeat_pass,
)
from orga_drone.studio_grade_commands import validate_patch
from orga_drone.studio_grade_contract import GradeError
from orga_drone.studio_grade_model import read_grade
from orga_drone.studio_grade_plan import RenderContext, evaluate_grade
from orga_drone.studio_managed_apply import grade_is_managed_pointwise
from orga_drone.studio_speed_ramp import Point, SpeedRamp


def _primaries_grade(**overrides: object) -> dict:
    grade = {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 3,
        "input": {"profile": "srgb", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "step-1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "params": {"exposure": 0.0, "saturation": 1.0},
                "selection_id": None,
            }
        ],
        "selections": [],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }
    grade.update(overrides)
    return {"grade": grade}


def _animation(
    *,
    clock: str = "source-local",
    parameter: str = "exposure",
    outside: str = "hold",
    keys: list[dict] | None = None,
) -> dict:
    return {
        "id": "anim-1",
        "step_id": "step-1",
        "clock": clock,
        "parameter": parameter,
        "interpolation": "linear",
        "outside": outside,
        "keys": keys
        or [
            {"t": [0, 1], "value": 0.0},
            {"t": [2, 1], "value": 2.0},
        ],
    }


def _context(**overrides: object) -> RenderContext:
    values = {
        "source_id": "clip-1",
        "source_pts": Fraction(1),
        "source_frame": 30,
        "source_in": Fraction(0),
        "source_out": Fraction(10),
        "source_local": Fraction(1),
        "story_time": Fraction(5),
        "speed": Fraction(1),
        "repeat_pass": 0,
        "transition_side": "single",
        "width": 1920,
        "height": 1080,
        "orientation": 1,
    }
    values.update(overrides)
    return RenderContext(**values)  # type: ignore[arg-type]


def test_supported_animation_reads_and_advertises_policy() -> None:
    source = _primaries_grade(animation=[_animation()])
    model = read_grade(source)
    policy = model.descriptors["primaries-v1"]["animation"]
    assert policy["exposure"]["interpolation"] == "linear"
    assert set(policy["exposure"]["outside"]) == {"hold", "base"}
    assert len(model.animation) == 1


def test_unsupported_parameter_rejects_without_flattening() -> None:
    source = _primaries_grade(animation=[_animation(parameter="gains")])
    with pytest.raises(GradeError) as excinfo:
        read_grade(source)
    assert excinfo.value.code == "UNSUPPORTED_GRADE"
    assert "animatable" in excinfo.value.message or "gains" in excinfo.value.message


def test_spatial_step_animation_rejected() -> None:
    source = _primaries_grade(
        selections=[
            {"id": "mask", "mask": {"type": "linear"}, "qualifier": {}, "invert": False}
        ],
        steps=[
            {
                "id": "step-1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "params": {"exposure": 0.0},
                "selection_id": "mask",
            }
        ],
        animation=[_animation()],
    )
    with pytest.raises(GradeError) as excinfo:
        read_grade(source)
    assert excinfo.value.code == "UNSUPPORTED_GRADE"


def test_legacy_stack_canonical_animation_rejected() -> None:
    source = {
        "grade": {
            "schema_version": 1,
            "evaluator": "legacy-v1",
            "revision": 1,
            "input": {"profile": "legacy-native", "technical_lut": None},
            "working": "legacy-native",
            "steps": [
                {
                    "id": "step-1",
                    "type": "legacy-stack-v1",
                    "enabled": True,
                    "mix": 1,
                    "params": {"image": {"exposure": 0}},
                    "selection_id": None,
                }
            ],
            "selections": [],
            "animation": [_animation()],
            "output": {"profile": "legacy-native", "gamut": "legacy"},
        }
    }
    with pytest.raises(GradeError) as excinfo:
        read_grade(source)
    assert excinfo.value.code == "UNSUPPORTED_GRADE"


@pytest.mark.parametrize(
    "instant,outside,expected",
    [
        (Fraction(-1), "hold", 0.0),
        (Fraction(-1), "base", 0.5),
        (Fraction(0), "hold", 0.0),
        (Fraction(1), "hold", 1.0),
        (Fraction(2), "hold", 2.0),
        (Fraction(3), "hold", 2.0),
        (Fraction(3), "base", 0.5),
    ],
)
def test_linear_interpolation_and_outside_policy(
    instant: Fraction, outside: str, expected: float
) -> None:
    anim = _animation(outside=outside)
    assert sample_animation_value(anim, instant, base=0.5) == pytest.approx(expected)


def test_evaluate_grade_applies_source_local_clock() -> None:
    source = _primaries_grade(animation=[_animation()])
    model = read_grade(source)
    plan = evaluate_grade(model, _context(source_local=Fraction(1), source_pts=Fraction(1)))
    data = plan.to_dict()
    assert data["operations"][0]["params"]["exposure"] == pytest.approx(1.0)
    assert data["evaluated_animation"][0]["value"] == pytest.approx(1.0)
    assert "managed-animation-segmentation" in data["capabilities"]["requirements"]


def test_story_local_clock_uses_story_time() -> None:
    source = _primaries_grade(
        animation=[_animation(clock="story-local", keys=[
            {"t": [0, 1], "value": 0.0},
            {"t": [10, 1], "value": 5.0},
        ])]
    )
    model = read_grade(source)
    plan = evaluate_grade(
        model,
        _context(
            source_local=Fraction(0),
            source_pts=Fraction(0),
            story_time=Fraction(5),
        ),
    )
    assert plan.to_dict()["operations"][0]["params"]["exposure"] == pytest.approx(2.5)


def test_materialize_and_pointwise_bake_disabled() -> None:
    source = _primaries_grade(animation=[_animation()])
    assert grade_is_managed_pointwise(source) is False
    resolved = materialize_grade_at(
        source["grade"],
        _context(source_local=Fraction(1), source_pts=Fraction(1)),
    )
    assert resolved["steps"][0]["params"]["exposure"] == pytest.approx(1.0)
    # Static grade without animation remains bakeable.
    assert grade_is_managed_pointwise(_primaries_grade()) is True


def test_bypass_skips_animation_on_disabled_step() -> None:
    source = _primaries_grade(
        steps=[
            {
                "id": "step-1",
                "type": "primaries-v1",
                "enabled": False,
                "mix": 1,
                "params": {"exposure": 0.0},
                "selection_id": None,
            }
        ],
        animation=[_animation()],
    )
    model = read_grade(source)
    plan = evaluate_grade(model, _context(source_local=Fraction(1), source_pts=Fraction(1)))
    assert plan.to_dict()["operations"] == []
    assert plan.grade_identity is True


def test_upsert_remove_reorder_animation_commands() -> None:
    source = _primaries_grade()
    model = read_grade(source)
    proposed = validate_patch(
        model,
        {
            "type": "upsert_animation",
            "project_id": 1,
            "clip_id": 2,
            "expected_revision": 3,
            "params": {"animation": _animation()},
        },
        expected_revision=3,
    )
    assert proposed.changed is True
    assert len(proposed.proposed.animation) == 1
    removed = validate_patch(
        proposed.proposed,
        {
            "type": "remove_animation",
            "project_id": 1,
            "clip_id": 2,
            "expected_revision": 3,
            "params": {"animation_id": "anim-1"},
        },
        expected_revision=3,
    )
    assert removed.proposed.animation == ()
    with_two = _primaries_grade(
        animation=[
            _animation(),
            {
                **_animation(parameter="saturation"),
                "id": "anim-2",
                "keys": [{"t": [0, 1], "value": 1.0}, {"t": [1, 1], "value": 2.0}],
            },
        ]
    )
    model = read_grade(with_two)
    reordered = validate_patch(
        model,
        {
            "type": "reorder_animation",
            "project_id": 1,
            "clip_id": 2,
            "expected_revision": 3,
            "params": {"ids": ["anim-2", "anim-1"]},
        },
        expected_revision=3,
    )
    assert [entry["id"] for entry in reordered.proposed.animation] == ["anim-2", "anim-1"]


def test_repeat_pass_and_trim_mapping() -> None:
    within, pass_index = map_repeat_pass(2.5, 1.0, 3)
    assert pass_index == 2
    assert within == pytest.approx(0.5)
    context = build_render_context(
        ClipTimingInputs(
            source_id="c1",
            source_in_s=1.0,
            source_out_s=3.0,
            story_time_s=10.5,
            clip_story_start_s=10.0,
            cycle_story_s=2.0,
            section_repeats=2,
            transition_side="outgoing",
        )
    )
    assert context.repeat_pass == 0
    assert context.source_in == Fraction(1)
    assert context.source_local == context.source_pts - context.source_in
    assert context.transition_side == "outgoing"
    # Second cycle of a 2s play within a 2-repeat clip.
    context2 = build_render_context(
        ClipTimingInputs(
            source_id="c1",
            source_in_s=1.0,
            source_out_s=3.0,
            story_time_s=12.5,
            clip_story_start_s=10.0,
            cycle_story_s=2.0,
            section_repeats=2,
        )
    )
    assert context2.repeat_pass == 1


def test_story_local_export_path_rejects_before_bake(tmp_path: Path) -> None:
    from orga_drone.studio_managed_apply import ManagedApplyError
    from orga_drone.studio_managed_spatial_export import materialize_spatial_managed_media

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not-a-real-mp4-but-present")
    source = _primaries_grade(animation=[_animation(clock="story-local")])
    with pytest.raises(ManagedApplyError) as excinfo:
        materialize_spatial_managed_media(
            media,
            source["grade"],
            tmp_path / "work",
            kind="video",
        )
    assert excinfo.value.code == "UNSUPPORTED_GRADE"
    assert "Story-local" in str(excinfo.value)


def test_render_context_honors_trim_for_source_local() -> None:
    from orga_drone.studio_grade_animation import render_context_for_source_sample

    ctx = render_context_for_source_sample(
        source_id="c",
        source_pts_s=3.0,
        source_in_s=1.0,
        source_out_s=5.0,
        story_time_s=12.0,
        transition_side="incoming",
        repeat_pass=2,
    )
    assert float(ctx.source_local) == pytest.approx(2.0)
    assert float(ctx.story_time) == pytest.approx(12.0)
    assert ctx.transition_side == "incoming"
    assert ctx.repeat_pass == 2


def test_transition_side_partner_is_incoming() -> None:
    from types import SimpleNamespace

    from orga_drone.studio_grade_clock import transition_side_for_hit

    hit = SimpleNamespace(overlap_index=1, crossfade_progress=0.4)
    assert transition_side_for_hit(hit, role="primary") == "outgoing"
    assert transition_side_for_hit(hit, role="partner") == "incoming"
    assert transition_side_for_hit(SimpleNamespace(overlap_index=None, crossfade_progress=None)) == "single"


def test_speed_ramp_mapping_uses_existing_ramp() -> None:
    ramp = SpeedRamp(
        points=(
            Point(source_s=0.0, speed=1.0),
            Point(source_s=2.0, speed=2.0),
        )
    )
    context = build_render_context(
        ClipTimingInputs(
            source_id="c1",
            source_in_s=0.0,
            source_out_s=2.0,
            story_time_s=0.5,
            clip_story_start_s=0.0,
            cycle_story_s=ramp.duration(0.0, 2.0),
            speed_ramp=ramp,
        )
    )
    assert float(context.source_pts) >= 0.0
    assert float(context.speed) > 0.0


def test_mix_and_reorder_steps_still_work_with_animation() -> None:
    source = _primaries_grade(
        steps=[
            {
                "id": "a",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "params": {"exposure": 0.0},
                "selection_id": None,
            },
            {
                "id": "b",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "params": {"exposure": 1.0},
                "selection_id": None,
            },
        ],
        animation=[
            {
                **_animation(),
                "step_id": "a",
            }
        ],
    )
    model = read_grade(source)
    mixed = validate_patch(
        model,
        {
            "type": "set_step_mix",
            "project_id": 1,
            "clip_id": 2,
            "expected_revision": 3,
            "params": {"step_id": "a", "mix": 0.25},
        },
        expected_revision=3,
    )
    assert mixed.proposed.steps[0]["mix"] == 0.25
    reordered = validate_patch(
        mixed.proposed,
        {
            "type": "reorder_steps",
            "project_id": 1,
            "clip_id": 2,
            "expected_revision": 3,
            "params": {"ids": ["b", "a"]},
        },
        expected_revision=3,
    )
    assert [step["id"] for step in reordered.proposed.steps] == ["b", "a"]
    # Persistence roundtrip via JSON snapshot keeps animation.
    text = json.dumps(reordered.proposed.to_dict())
    assert len(read_grade(text).animation) == 1
