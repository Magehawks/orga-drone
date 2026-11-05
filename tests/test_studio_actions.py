"""Shared Studio action contract tests for the Control API foundation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orga_drone.studio_actions import (
    CONTRACT_VERSION,
    ActionValidationError,
    action_catalog,
    canonical,
    merge_properties,
    parse_properties_patch,
    properties,
    validate_clip_effect_settings,
)


def test_catalog_is_versioned_and_path_free() -> None:
    catalog = action_catalog()
    assert catalog["contract_version"] == CONTRACT_VERSION == 1
    actions = catalog["actions"]
    assert [entry["name"] for entry in actions] == ["clip.color.properties"]
    action = actions[0]
    assert action["version"] == 1
    assert action["scope"] == "clip"
    assert action["target"] == "video_clip"
    assert action["reversible"] is True
    assert action["parameters"]["contrast"]["minimum"] == -100
    serialized = json.dumps(catalog)
    assert "data_dir" not in serialized and "C:\\" not in serialized


def test_properties_and_canonical_use_existing_domain_models() -> None:
    raw = json.dumps(
        {
            "image": {"contrast": 15, "saturation": 20, "future": "keep"},
            "color": {
                "creative_lut": "a" * 32 + ".cube",
                "creative_strength": 70,
                "future": "keep",
            },
        }
    )
    assert properties(raw) == {
        "contrast": 15,
        "saturation_percent": 120,
        "creative_lut_id": "a" * 32 + ".cube",
        "creative_lut_strength_percent": 70,
    }
    view = canonical(raw)
    assert view["properties"] == properties(raw)
    assert view["image"]["saturation"] == 20
    assert view["color_look"]["creative_strength"] == 70


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"unknown": 1},
        {"contrast": True},
        {"contrast": 1.5},
        {"contrast": 101},
        {"saturation_percent": -1},
        {"creative_lut_strength_percent": 101},
        {"creative_lut_id": "../../x.cube"},
    ],
)
def test_invalid_property_patch_is_stable(payload: object) -> None:
    with pytest.raises(ActionValidationError) as exc:
        parse_properties_patch(payload)
    assert exc.value.code == "INVALID_PROPERTIES"


def test_merge_preserves_unrelated_settings_and_uses_one_merge_path(
    tmp_path: Path,
) -> None:
    lut = "b" * 32 + ".cube"
    lut_dir = tmp_path / "luts"
    lut_dir.mkdir()
    (lut_dir / lut).write_text(
        "LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n",
        encoding="utf-8",
    )
    raw = json.dumps(
        {
            "frame": {"zoom": 1.2},
            "image": {"exposure": 8, "future": "keep"},
            "color": {"input_profile": "rec709", "future": "keep"},
        }
    )
    merged = merge_properties(
        raw,
        {
            "contrast": 15,
            "saturation_percent": 120,
            "creative_lut_id": lut,
            "creative_lut_strength_percent": 100,
        },
        {lut},
        tmp_path,
    )
    stored = json.loads(merged)
    assert stored["frame"] == {"zoom": 1.2}
    assert stored["image"]["exposure"] == 8
    assert stored["image"]["future"] == "keep"
    assert stored["image"]["contrast"] == 15
    assert stored["image"]["saturation"] == 20
    assert stored["color"]["future"] == "keep"
    assert stored["color"]["creative_lut"] == lut
    assert stored["color"]["creative_strength"] == 100


def test_merge_requires_an_imported_lut(tmp_path: Path) -> None:
    with pytest.raises(ActionValidationError) as exc:
        merge_properties(
            "{}",
            {"contrast": 10, "creative_lut_id": "c" * 32 + ".cube"},
            set(),
            tmp_path,
        )
    assert exc.value.code == "LUT_UNAVAILABLE"


@pytest.mark.parametrize(
    "raw,code",
    [
        ('{"saturation_ramp": {"enabled": true}}', "ANIMATED_SETTINGS_UNSUPPORTED"),
        ('{"color_animation": {"keys": []}}', "ANIMATED_SETTINGS_UNSUPPORTED"),
        ('{"image": {"contrast": 101}}', "INVALID_CLIP_SETTINGS"),
        ('{"image": "bad"}', "INVALID_CLIP_SETTINGS"),
        ('{"color": {"input_profile": "bad"}}', "INVALID_CLIP_SETTINGS"),
    ],
)
def test_validate_clip_effect_settings_rejects_unsafe_state(
    raw: str, code: str
) -> None:
    with pytest.raises(ActionValidationError) as exc:
        validate_clip_effect_settings(raw)
    assert exc.value.code == code