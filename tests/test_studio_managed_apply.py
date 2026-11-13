"""CPU managed-sdr applicator and bake path (#359)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orga_drone.studio_managed_apply import (
    ADAPTER_VERSION,
    ManagedApplyError,
    apply_managed_grade_rgb,
    bake_managed_grade_cube,
    ffmpeg_managed_grade_chain,
    grade_is_managed_pointwise,
)
from orga_drone.studio_managed_primaries import apply_primaries
from orga_drone.studio_managed_lut import encode_bt709, decode_bt709


def _managed_grade(*, steps: list[dict] | None = None) -> dict:
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": steps or [],
        "selections": [],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def test_identity_managed_grade_roundtrips_mid_gray() -> None:
    sample = (0.5, 0.5, 0.5)
    out = apply_managed_grade_rgb(sample, _managed_grade())
    assert out == pytest.approx(sample, abs=1e-6)


def test_primaries_exposure_matches_published_linear_math() -> None:
    encoded = (0.4, 0.35, 0.3)
    linear = tuple(decode_bt709(c) for c in encoded)
    expected_linear = apply_primaries(linear, exposure=1.0, kelvin=6500.0)
    expected = tuple(encode_bt709(min(1.0, max(0.0, c))) for c in expected_linear)
    grade = _managed_grade(
        steps=[
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": None,
                "params": {
                    "exposure": 1.0,
                    "kelvin": 6500,
                    "tint": 0,
                    "contrast": 1,
                    "pivot": 0.18,
                    "saturation": 1,
                    "blacks": 0,
                    "shadows": 0,
                    "highlights": 0,
                    "whites": 0,
                },
            }
        ]
    )
    out = apply_managed_grade_rgb(encoded, grade)
    assert out == pytest.approx(expected, abs=1e-6)


def test_masked_step_is_not_silently_omitted() -> None:
    grade = _managed_grade(
        steps=[
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": "sel-1",
                "params": {"exposure": 0.5},
            }
        ]
    )
    with pytest.raises(ManagedApplyError) as exc:
        apply_managed_grade_rgb((0.5, 0.5, 0.5), grade)
    assert exc.value.code == "UNSUPPORTED_GRADE"


def test_bake_cube_and_ffmpeg_chain(tmp_path: Path) -> None:
    grade = _managed_grade(
        steps=[
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": None,
                "params": {"exposure": 0.25, "kelvin": 6500, "contrast": 1, "pivot": 0.18, "saturation": 1},
            }
        ]
    )
    effect = json.dumps({"grade": grade})
    assert grade_is_managed_pointwise(effect)
    cube = tmp_path / "managed.cube"
    bake_managed_grade_cube(grade, cube, size=5)
    text = cube.read_text(encoding="utf-8")
    assert ADAPTER_VERSION in text
    assert "LUT_3D_SIZE 5" in text
    chain = ffmpeg_managed_grade_chain(effect, work_dir=tmp_path / "work")
    assert chain.startswith("lut3d=file=")
    assert "tetrahedral" in chain


def test_wheels_gain_zero_and_hsl_saturation_zero_are_preserved() -> None:
    grade = _managed_grade(
        steps=[
            {
                "id": "w1",
                "type": "wheels-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": None,
                "params": {"lift": 0, "gamma": 1, "gain": 0, "offset": 0},
            },
            {
                "id": "h1",
                "type": "managed-hsl-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": None,
                "params": {"hue": 0, "saturation": 0, "lightness": 0},
            },
        ]
    )
    # Encoded mid gray → linear → gain 0 → black → encoded black; then HSL sat 0 keeps gray.
    out = apply_managed_grade_rgb((0.5, 0.4, 0.3), grade)
    assert out[0] == pytest.approx(0.0, abs=1e-5)
    assert out[1] == pytest.approx(0.0, abs=1e-5)
    assert out[2] == pytest.approx(0.0, abs=1e-5)


def test_legacy_effect_settings_skip_managed_chain() -> None:
    assert grade_is_managed_pointwise('{"image":{"exposure":10}}') is False
    assert ffmpeg_managed_grade_chain('{"image":{"exposure":10}}', work_dir=Path(".")) == ""


def test_creative_lut_managed_grade_is_rejected_before_bake() -> None:
    from orga_drone.studio_managed_apply import require_managed_pointwise

    grade = _managed_grade(
        steps=[
            {
                "id": "lut1",
                "type": "creative-lut-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": None,
                "params": {
                    "asset_id": "abc.cube",
                    "strength": 1,
                    "sha256": "a" * 64,
                    "interpolation": "tetrahedral",
                },
            }
        ]
    )
    effect = json.dumps({"grade": grade})
    with pytest.raises(ManagedApplyError) as exc:
        require_managed_pointwise(effect)
    assert exc.value.code == "UNSUPPORTED_GRADE"
    assert grade_is_managed_pointwise(effect) is False
    assert ffmpeg_managed_grade_chain(effect, work_dir=Path(".")) == ""
