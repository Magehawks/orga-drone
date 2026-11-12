"""Shared audio/overlay clip actions (issue #281, clip-scoped slice).

``clip.audio.edit`` (video clips) and ``clip.overlays.edit`` (photos and
videos) run through the same apply_action path as the color actions: same
validation, same effect_settings storage, same undo story. No duplicated
persistence or rendering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orga_drone.studio_actions import (
    ActionValidationError,
    prepare_action,
    resolve_action_spec,
)
from orga_drone.studio_audio import detached_audio_from_effect_settings
from orga_drone.studio_overlay import overlays_from_effect_settings

_RAW = json.dumps({
    "image": {"exposure": 5},
    "vendor": {"opaque": [1, None]},
})


def test_specs_and_targets() -> None:
    spec_audio = resolve_action_spec("clip.audio.edit", 1)
    spec_overlays = resolve_action_spec("clip.overlays.edit", 1)
    assert spec_audio.target == "video_clip"  # clip audio is video-only
    assert spec_overlays.target == "media_clip"  # photos and videos


def test_audio_action_persists_detached_audio() -> None:
    spec = resolve_action_spec("clip.audio.edit", 1)
    prepared = prepare_action(spec, _RAW, {
        "source_in_s": 0.2, "source_out_s": 1.4, "place_s": 0.0,
    }, set(), None)  # type: ignore[arg-type]
    stored = json.loads(prepared)
    audio = detached_audio_from_effect_settings(prepared)
    assert audio.active is True
    assert audio.source_in_s == pytest.approx(0.2)
    assert audio.source_out_s == pytest.approx(1.4)
    assert audio.place_s == pytest.approx(0.0)
    assert stored["image"] == {"exposure": 5}
    assert stored["vendor"] == {"opaque": [1, None]}


def test_audio_action_clamps_to_clip_duration() -> None:
    spec = resolve_action_spec("clip.audio.edit", 1)
    prepared = prepare_action(
        spec, _RAW,
        {"source_in_s": 0.2, "source_out_s": 9.9, "place_s": 1.0},
        set(), None,  # type: ignore[arg-type]
        clip_duration_s=2.0,
    )
    audio = detached_audio_from_effect_settings(prepared)
    assert audio.source_out_s == pytest.approx(2.0)
    assert audio.source_in_s == pytest.approx(0.2)


def test_audio_action_rejects_short_span_and_bad_values() -> None:
    spec = resolve_action_spec("clip.audio.edit", 1)
    with pytest.raises(ActionValidationError):
        prepare_action(spec, _RAW, {"source_in_s": 0.0, "source_out_s": 0.01,
                                    "place_s": 0.0}, set(), None)  # type: ignore[arg-type]
    with pytest.raises(ActionValidationError):
        prepare_action(spec, _RAW, {"source_in_s": -1, "source_out_s": 1.0,
                                    "place_s": 0.0}, set(), None)  # type: ignore[arg-type]
    with pytest.raises(ActionValidationError):
        prepare_action(spec, _RAW, {"source_in_s": 0.0, "source_out_s": 1.0},
                       set(), None)  # type: ignore[arg-type]  # place missing
    with pytest.raises(ActionValidationError):
        prepare_action(spec, _RAW, {"source_in_s": 0.0, "source_out_s": 1.0,
                                    "place_s": 0.0, "extra": True}, set(), None)  # type: ignore[arg-type]


def test_overlay_action_persists_full_list(tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    spec = resolve_action_spec("clip.overlays.edit", 1)
    overlays_payload = [
        {
            "id": "ovtext0001",
            "kind": "text",
            "start_s": 0.2,
            "end_s": 1.0,
            "x": 0.1,
            "y": 0.2,
            "w": 0.4,
            "h": 0.16,
            "rotation": 0,
            "text": "Ridge",
            "font_size": 0.06,
            "color": "#ffffff",
            "fill": "#00000000",
            "stroke": "#ffffff",
            "stroke_width": 0.012,
            "asset_name": "",
        }
    ]
    prepared = prepare_action(
        spec, _RAW, {"overlays": overlays_payload}, set(), None,  # type: ignore[arg-type]
        clip_duration_s=2.0,
    )
    overlays = overlays_from_effect_settings(prepared, duration_s=2.0)
    assert len(overlays) == 1
    assert overlays[0].text == "Ridge"
    stored = json.loads(prepared)
    assert stored["image"] == {"exposure": 5}


def test_overlay_action_requires_duration_context() -> None:
    """Without the clip duration context the action refuses (clamping needs
    it) — never silently unclamped."""
    spec = resolve_action_spec("clip.overlays.edit", 1)
    with pytest.raises(ActionValidationError):
        prepare_action(spec, _RAW, {"overlays": []}, set(), None)  # type: ignore[arg-type]


def test_overlay_action_rejects_bad_payload() -> None:
    spec = resolve_action_spec("clip.overlays.edit", 1)
    # parse_overlays materializes defaults and clamps times (documented UI
    # behavior); only structurally bad values raise.
    with pytest.raises(ActionValidationError):
        prepare_action(spec, _RAW, {"overlays": [{"kind": "text", "color": "not-a-color"}]},
                       set(), None, clip_duration_s=2.0)  # type: ignore[arg-type]
    with pytest.raises(ActionValidationError):
        prepare_action(spec, _RAW, {"overlays": "not-a-list"}, set(), None,  # type: ignore[arg-type]
                       clip_duration_s=2.0)


def test_audio_and_overlay_actions_are_idempotent() -> None:
    audio_spec = resolve_action_spec("clip.audio.edit", 1)
    once = prepare_action(audio_spec, _RAW, {
        "source_in_s": 0.2, "source_out_s": 1.4, "place_s": 0.5,
    }, set(), None)  # type: ignore[arg-type]
    twice = prepare_action(audio_spec, once, {
        "source_in_s": 0.2, "source_out_s": 1.4, "place_s": 0.5,
    }, set(), None)  # type: ignore[arg-type]
    assert json.loads(once) == json.loads(twice)
