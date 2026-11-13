"""Wrapped legacy grades must keep feeding legacy color readers."""

from __future__ import annotations

import json

from orga_drone.studio_color_animation import (
    build_preset,
    color_animation_from_effect_settings,
    dump_color_animation,
)
from orga_drone.studio_grade_compat import color_effect_settings_view
from orga_drone.studio_grade_persistence import wrap_legacy_to_canonical
from orga_drone.studio_image import image_adjust_from_effect_settings
from orga_drone.studio_lut import color_look_from_effect_settings


def test_wrapped_legacy_stack_still_feeds_image_and_lut_readers() -> None:
    base = {
        "image": {"exposure": 20, "contrast": 0, "saturation": 0, "warmth": -10},
        "color": {
            "input_profile": "rec709",
            "conversion_lut": "",
            "creative_lut": "",
            "creative_strength": 100,
            "conversion_confirmed": False,
        },
        "masks": [{"id": "privacy"}],
    }
    raw = dump_color_animation(
        json.dumps(base),
        build_preset("brighten", bar_start_s=0.0, bar_end_s=2.0),
    )
    wrapped = wrap_legacy_to_canonical(raw)
    text = json.dumps(wrapped)
    assert "grade" in wrapped
    assert "image" not in wrapped
    view = json.loads(color_effect_settings_view(text) or "{}")
    assert view["image"]["exposure"] == 20
    image = image_adjust_from_effect_settings(text)
    assert image.exposure == 20
    assert image.warmth == -10
    look = color_look_from_effect_settings(text)
    assert look.input_profile == "rec709"
    anim = color_animation_from_effect_settings(text)
    assert anim.is_active
    assert len(anim.keys) >= 2


def test_managed_grade_view_hides_legacy_color_keys() -> None:
    raw = json.dumps(
        {
            "grade": {
                "schema_version": 1,
                "evaluator": "managed-sdr-v1",
                "revision": 2,
                "input": {"profile": "srgb", "technical_lut": None},
                "working": "linear-bt709",
                "steps": [],
                "selections": [],
                "animation": [],
                "output": {"profile": "bt709-sdr", "gamut": "clip"},
                "extensions": {
                    "legacy_recovery": {"image": {"exposure": 40}},
                },
            },
            "image": {"exposure": 40},
        }
    )
    view = json.loads(color_effect_settings_view(raw) or "{}")
    assert "image" not in view
    assert image_adjust_from_effect_settings(raw).exposure == 0
