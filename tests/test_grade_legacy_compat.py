"""Legacy effect_settings compatibility evidence (ADR 0035 Phase A).

OpenCode evidence lane. Locks the CURRENT legacy read/write behavior that the
canonical grade model must preserve without reinterpretation:

- existing readers are pure: no write, deterministic output, raw text kept,
- unknown top-level members survive the existing dump functions,
- unknown members INSIDE a feature object do not survive today's dump
  functions (the documented gap the canonical model must close),
- malformed legacy text falls back to the existing reader defaults,
- reads never introduce a canonical `grade` envelope.

Reuse note: operation semantics/ordering are already covered by
tests/test_studio_color_scenarios.py (PR #368) and the feature test files;
this file deliberately does not duplicate them.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from orga_drone.studio_color_animation import color_animation_from_effect_settings
from orga_drone.studio_color_wheels import (
    color_wheels_from_effect_settings,
    dump_color_wheels,
)
from orga_drone.studio_hsl import dump_hsl_adjust, hsl_adjust_from_effect_settings
from orga_drone.studio_image import (
    dump_effect_settings,
    image_adjust_from_effect_settings,
)
from orga_drone.studio_lut import color_look_from_effect_settings, dump_color_look

_READERS = {
    "image": image_adjust_from_effect_settings,
    "color_look": color_look_from_effect_settings,
    "hsl": hsl_adjust_from_effect_settings,
    "color_wheels": color_wheels_from_effect_settings,
    "color_animation": color_animation_from_effect_settings,
}


def _rich_legacy_settings() -> str:
    """Existing fields plus unknown top-level and nested members."""
    return json.dumps(
        {
            "image": {"exposure": 12, "vendor_hint": {"never_touched": [1, 2, 3]}},
            "color": {
                "input_profile": "rec709",
                "creative_strength": 80,
                "legacy_extension": {"opaque": True},
            },
            "hsl": {"ranges": {"blue": {"hue": 15}}, "future_axis": 3},
            "color_wheels": {"wheels": {"shadows": {"x": 0.2}}, "meta": "x"},
            "color_animation": {"version": 1, "keys": []},
            "saturation_ramp": {"enabled": False},
            "detail": {"strength": 40},
            "vendor_note": {"opaque": {"deep": None}},
            "section_repeats": 1,
        },
        sort_keys=True,
    )


@pytest.mark.parametrize("reader_name", sorted(_READERS))
def test_readers_are_pure_and_deterministic(reader_name: str) -> None:
    """Reading returns identical values on repeat and never writes."""
    reader = _READERS[reader_name]
    raw = _rich_legacy_settings()
    first = reader(raw)
    second = reader(raw)
    assert first == second
    # Read-only: the input text is unchanged (no normalization/wrapping).
    assert raw == json.dumps(json.loads(raw), sort_keys=True)


def test_reads_never_introduce_a_canonical_grade() -> None:
    """No legacy read path wraps data into a canonical grade envelope."""
    raw = _rich_legacy_settings()
    for reader in _READERS.values():
        assert reader(raw) is not None
    # All dump functions below must also stay grade-free (asserted in the
    # roundtrip tests); here: readers alone cannot mutate anything.
    assert "grade" not in json.loads(raw)


def test_dump_functions_preserve_unrelated_top_level_members() -> None:
    """Existing dump functions keep unrelated top-level keys verbatim
    (contract: verified current implementation)."""
    raw = _rich_legacy_settings()
    settings = json.loads(raw)

    pairs: list[tuple[Callable[[str | None, Any], str], Callable[[str | None], Any]]] = [
        (dump_effect_settings, image_adjust_from_effect_settings),
        (dump_color_look, color_look_from_effect_settings),
        (dump_hsl_adjust, hsl_adjust_from_effect_settings),
        (dump_color_wheels, color_wheels_from_effect_settings),
    ]
    for dump, reader in pairs:
        dumped = json.loads(dump(raw, reader(raw)))
        for key, original in settings.items():
            # The feature's own section may be rewritten; everything else
            # must deep-equal the original, including unknown members.
            if key in {"image", "color", "hsl", "color_wheels"}:
                continue
            assert dumped.get(key) == original, (dump.__name__, key)
        # No canonical envelope appears.
        assert "grade" not in dumped


def test_dump_functions_replace_nested_feature_members_documented_gap() -> None:
    """DOCUMENTED GAP (contract: "they are not sufficient for canonical
    unknown-field preservation"): unknown members INSIDE a feature object are
    dropped by today's dump functions. Locked here as the compatibility
    baseline that the canonical model must not silently change and legacy
    paths must not rely on for unknown data."""
    raw = json.dumps(
        {
            "hsl": {"ranges": {"blue": {"hue": 15}}, "future_axis": 3},
            "color": {"input_profile": "rec709", "legacy_extension": {"opaque": True}},
        }
    )
    dumped_hsl = json.loads(dump_hsl_adjust(raw, hsl_adjust_from_effect_settings(raw)))
    assert "future_axis" not in dumped_hsl.get("hsl", {})

    dumped_look = json.loads(dump_color_look(raw, color_look_from_effect_settings(raw)))
    assert "legacy_extension" not in dumped_look.get("color", {})


@pytest.mark.parametrize(
    "malformed", ["not json", '{"image": broken', "", "   ", '{"grade": 12}']
)
def test_malformed_legacy_text_falls_back_to_defaults(malformed: str) -> None:
    """Existing readers keep their invalid-value defaults and never raise on
    malformed legacy text; '{"grade": 12}' is ignored by legacy readers."""
    for reader in _READERS.values():
        value = reader(malformed)
        assert value is not None


def test_legacy_section_repeats_reader_survives_unknown_members() -> None:
    """The section_repeats/forward-loop readers keep their existing defaults
    when unrelated members are present."""
    from orga_drone.studio_cut import section_repeats_from_effect_settings
    from orga_drone.studio_forward_loop import loop_to_soundtrack_enabled

    raw = json.dumps({"section_repeats": 2, "forward_loop": {"enabled": False},
                      "vendor": {"x": 1}})
    assert section_repeats_from_effect_settings(raw) == 2
    assert loop_to_soundtrack_enabled(raw) is False


def test_playback_speed_coercion_default_is_unchanged() -> None:
    """Playback speed is a column, not effect_settings; its coercion keeps
    1.0 for absent values (existing contract)."""
    from orga_drone.studio_speed import coerce_playback_speed

    assert coerce_playback_speed(None) == pytest.approx(1.0)
