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
    prepare_action,
    properties,
    resolve_action_spec,
    validate_action_params,
    validate_clip_effect_settings,
)


def test_catalog_is_versioned_and_path_free() -> None:
    catalog = action_catalog()
    assert catalog["contract_version"] == CONTRACT_VERSION == 1
    actions = catalog["actions"]
    assert actions[0]["name"] == "clip.color.properties"
    assert {a["name"] for a in actions if a["scope"] == "library"} == {
        "library.media.list", "library.media.search", "library.media.get",
    }
    assert {a["name"] for a in actions if a["scope"] == "project"} == {
        "project.create", "project.open", "project.rename", "project.delete",
        "music.append", "music.update", "music.remove", "music.reorder",
        "music.set_start",
        "sfx.append", "sfx.update", "sfx.remove",
    }
    assert {a["name"] for a in actions if a["scope"] == "project_read"} == {
        "project.list", "project.get",
    }
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
def test_catalog_lists_only_implemented_color_and_effect_actions() -> None:
    actions = action_catalog()["actions"]
    # Issue #281 adds the clip-scoped audio/overlay actions.
    assert [entry["name"] for entry in actions if entry["scope"] == "clip"] == [
        "clip.color.properties",
        "clip.color.image",
        "clip.color.look",
        "clip.color.hsl",
        "clip.color.wheels",
        "clip.effects.detail",
        "clip.audio.edit",
        "clip.overlays.edit",
    ]
    assert all(entry["version"] == 1 for entry in actions)


def test_prepare_image_action_merges_sliders_and_preserves_other_settings() -> None:
    spec = resolve_action_spec("clip.color.image", 1)
    raw = json.dumps({"image": {"warmth": 4}, "frame": {"zoom": 1.1}})
    prepared = prepare_action(
        spec,
        raw,
        {"contrast": 15, "exposure": -10},
        set(),
        Path(),
    )
    stored = json.loads(prepared)
    assert stored["image"]["contrast"] == 15
    assert stored["image"]["exposure"] == -10
    assert stored["image"]["warmth"] == 4
    assert stored["frame"] == {"zoom": 1.1}


def test_prepare_hsl_wheels_and_detail_share_existing_validators() -> None:
    hsl_spec = resolve_action_spec("clip.color.hsl", 1)
    wheels_spec = resolve_action_spec("clip.color.wheels", 1)
    detail_spec = resolve_action_spec("clip.effects.detail", 1)
    raw = json.dumps({"frame": {"zoom": 1.2}})
    hsl = prepare_action(
        hsl_spec,
        raw,
        {"ranges": {"blue": {"hue": 20, "saturation": -10}}},
        set(),
        Path(),
    )
    wheels = prepare_action(
        wheels_spec,
        hsl,
        {"wheels": {"shadows": {"x": 0.2, "y": -0.1}}},
        set(),
        Path(),
    )
    prepared = prepare_action(
        detail_spec,
        wheels,
        {"sharpen": 12, "denoise": 4},
        set(),
        Path(),
    )
    stored = json.loads(prepared)
    assert stored["hsl"]["ranges"]["blue"]["hue"] == 20
    assert stored["hsl"]["ranges"]["blue"]["saturation"] == -10
    assert stored["color_wheels"]["wheels"]["shadows"] == {"x": 0.2, "y": -0.1}
    assert stored["detail"] == {"sharpen": 12, "denoise": 4}
    assert stored["frame"] == {"zoom": 1.2}
    view = canonical(prepared)
    assert view["hsl"] == stored["hsl"]
    assert view["color_wheels"] == stored["color_wheels"]
    assert view["detail"] == stored["detail"]


def test_prepare_look_action_requires_imported_luts(tmp_path: Path) -> None:
    spec = resolve_action_spec("clip.color.look", 1)
    lut = "d" * 32 + ".cube"
    with pytest.raises(ActionValidationError) as exc:
        prepare_action(
            spec,
            "{}",
            {"creative_lut": lut, "creative_strength": 70},
            set(),
            tmp_path,
        )
    assert exc.value.code == "LUT_UNAVAILABLE"
    lut_dir = tmp_path / "luts"
    lut_dir.mkdir()
    (lut_dir / lut).write_text(
        "LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n",
        encoding="utf-8",
    )
    prepared = prepare_action(
        spec,
        "{}",
        {"creative_lut": lut, "creative_strength": 70},
        {lut},
        tmp_path,
    )
    stored = json.loads(prepared)
    assert stored["color"]["creative_lut"] == lut
    assert stored["color"]["creative_strength"] == 70


@pytest.mark.parametrize(
    "name,params,code",
    [
        ("clip.color.image", {"contrast": True}, "INVALID_PARAMS"),
        ("clip.color.image", {"contrast": 101}, "INVALID_PARAMS"),
        ("clip.color.image", {"unknown": 1}, "INVALID_PARAMS"),
        ("clip.color.hsl", {"ranges": {}}, "INVALID_PARAMS"),
        ("clip.color.hsl", {"ranges": {"blue": {"hue": 101}}}, "INVALID_PARAMS"),
        ("clip.color.wheels", {"wheels": {}}, "INVALID_PARAMS"),
        ("clip.effects.detail", {"sharpen": 101}, "INVALID_PARAMS"),
        ("clip.color.look", {"unknown": 1}, "INVALID_PARAMS"),
    ],
)
def test_action_parameter_validation_is_stable(
    name: str, params: dict[str, object], code: str
) -> None:
    spec = resolve_action_spec(name, 1)
    with pytest.raises(ActionValidationError) as exc:
        validate_action_params(spec, params)
    assert exc.value.code == code


def test_unknown_action_and_version_are_rejected() -> None:
    with pytest.raises(ActionValidationError) as exc:
        resolve_action_spec("clip.nope", 1)
    assert exc.value.code == "UNKNOWN_ACTION"
    with pytest.raises(ActionValidationError) as exc:
        resolve_action_spec("clip.color.image", 2)
    assert exc.value.code == "UNKNOWN_ACTION"
    with pytest.raises(ActionValidationError) as exc:
        resolve_action_spec("clip.color.image", "1")
    assert exc.value.code == "INVALID_ACTION"

def test_properties_action_is_validated_by_the_shared_registry() -> None:
    spec = resolve_action_spec("clip.color.properties", 1)
    params = validate_action_params(
        spec, {"contrast": 15, "saturation_percent": 120}
    )
    assert params == {"contrast": 15, "saturation_percent": 120}
    prepared = prepare_action(
        spec,
        "{}",
        params,
        set(),
        Path(),
    )
    stored = json.loads(prepared)
    assert stored["image"] == {
        "exposure": 0,
        "contrast": 15,
        "saturation": 20,
        "warmth": 0,
        "highlights": 0,
        "shadows": 0,
        "blacks": 0,
    }


@pytest.mark.parametrize(
    "name,params,code",
    [
        ("clip.color.hsl", {"ranges": {"bogus": {"hue": 1}}}, "INVALID_PARAMS"),
        ("clip.color.hsl", {"ranges": {"blue": {"hue": 1.5}}}, "INVALID_PARAMS"),
        ("clip.color.hsl", {"ranges": {"blue": {"hue": 1, "x": 2}}}, "INVALID_PARAMS"),
        ("clip.color.wheels", {"wheels": {"bogus": {"x": 0}}}, "INVALID_PARAMS"),
        ("clip.color.wheels", {"wheels": {"shadows": {"x": 2}}}, "INVALID_PARAMS"),
        ("clip.color.wheels", {"wheels": {"shadows": {"x": True}}}, "INVALID_PARAMS"),
        ("clip.color.wheels", {"wheels": {"shadows": {"x": 10**400}}}, "INVALID_PARAMS"),
        ("clip.effects.detail", {"sharpen": 1.5}, "INVALID_PARAMS"),
        ("clip.effects.detail", {"sharpen": 1, "unknown": 2}, "INVALID_PARAMS"),
        ("clip.color.look", {"conversion_confirmed": "yes"}, "INVALID_PARAMS"),
        ("clip.color.look", {"creative_strength": 1.5}, "INVALID_PARAMS"),
    ],
)
def test_strict_action_parameter_validation(
    name: str, params: dict[str, object], code: str
) -> None:
    spec = resolve_action_spec(name, 1)
    with pytest.raises(ActionValidationError) as exc:
        validate_action_params(spec, params)
    assert exc.value.code == code


def test_look_action_reports_merged_current_conflict_as_invalid_params() -> None:
    spec = resolve_action_spec("clip.color.look", 1)
    raw = json.dumps(
        {
            "color": {
                "input_profile": "dlog_m",
                "conversion_lut": "e" * 32 + ".cube",
                "conversion_confirmed": True,
            }
        }
    )
    with pytest.raises(ActionValidationError) as exc:
        prepare_action(
            spec,
            raw,
            {"conversion_confirmed": False},
            set(),
            Path(),
        )
    assert exc.value.code == "INVALID_PARAMS"
