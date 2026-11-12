"""Semantic guidance contract tests (issue #291).

The guidance in ``studio_action_semantics.py`` must stay truthful against
the implemented actions: every implemented color action has an entry, no
orphan entries exist, ranges/neutral values match the live validators, and
the required example intents resolve to the correct actions with honest
limitations.
"""

from __future__ import annotations

import pytest

from orga_drone.studio_action_semantics import (
    ACTION_SEMANTICS,
    DISAMBIGUATION,
    SEMANTICS_VERSION,
    action_semantics,
    attach_semantics,
)
from orga_drone.studio_actions import (
    ACTION_SPECS,
    DETAIL_PARAMETERS,
    HSL_PARAMETERS,
    IMAGE_KEYS,
    IMAGE_PARAMETERS,
    LIMITS,
    LOOK_PARAMETERS,
    WHEEL_PARAMETERS,
    action_catalog,
)
from orga_drone.studio_detail import SLIDER_MAX as DETAIL_MAX
from orga_drone.studio_hsl import SLIDER_MAX as HSL_MAX, SLIDER_MIN as HSL_MIN
from orga_drone.studio_image import SLIDER_MAX as IMAGE_MAX, SLIDER_MIN as IMAGE_MIN
from orga_drone.studio_color_wheels import POINT_MAX, POINT_MIN


COLOR_ACTION_NAMES = (
    "clip.color.properties",
    "clip.color.image",
    "clip.color.look",
    "clip.color.hsl",
    "clip.color.wheels",
    "clip.effects.detail",
)


def test_every_implemented_color_action_has_semantics() -> None:
    implemented = {spec.name for spec in ACTION_SPECS}
    for name in COLOR_ACTION_NAMES:
        assert name in implemented, name
        assert name in ACTION_SEMANTICS, name


def test_no_orphan_semantics_entries() -> None:
    """An entry without an implemented action is stale guidance — fail."""
    implemented = {spec.name for spec in ACTION_SPECS}
    orphans = set(ACTION_SEMANTICS) - implemented
    assert orphans == set(), orphans


@pytest.mark.parametrize(
    "name,parameters",
    [
        ("clip.color.image", IMAGE_PARAMETERS),
        ("clip.color.look", LOOK_PARAMETERS),
        ("clip.color.hsl", HSL_PARAMETERS),
        ("clip.color.wheels", WHEEL_PARAMETERS),
        ("clip.effects.detail", DETAIL_PARAMETERS),
    ],
)
def test_semantics_do_not_restate_param_schemas(
    name: str, parameters: dict
) -> None:  # type: ignore[type-arg]
    """Guidance must not restate parameter schemas (single source of truth
    stays the ActionSpec); the catalog carries both side by side."""
    catalog = action_catalog()
    entry = next(action for action in catalog["actions"] if action["name"] == name)
    assert entry["parameters"] == parameters
    assert entry["semantics"]["visual_effect"]


def test_image_range_matches_live_validator() -> None:
    """The image parameter bounds come from the live constants."""
    for key in IMAGE_KEYS:
        assert IMAGE_PARAMETERS[key]["minimum"] == IMAGE_MIN
        assert IMAGE_PARAMETERS[key]["maximum"] == IMAGE_MAX


def test_hsl_and_wheel_and_detail_ranges_match_live_validators() -> None:
    assert HSL_PARAMETERS["ranges"]["minimum"] == HSL_MIN
    assert HSL_PARAMETERS["ranges"]["maximum"] == HSL_MAX
    assert WHEEL_PARAMETERS["wheels"]["minimum"] == POINT_MIN
    assert WHEEL_PARAMETERS["wheels"]["maximum"] == POINT_MAX
    assert DETAIL_PARAMETERS["sharpen"]["maximum"] == DETAIL_MAX
    assert DETAIL_PARAMETERS["denoise"]["maximum"] == DETAIL_MAX


def test_properties_limits_match_catalog() -> None:
    """The properties action documents contrast/saturation/strength limits
    imported from LIMITS."""
    implemented = {spec.name: spec for spec in ACTION_SPECS}
    properties = implemented["clip.color.properties"].parameters
    assert properties["contrast"]["minimum"] == LIMITS["contrast"][0]
    assert properties["contrast"]["maximum"] == LIMITS["contrast"][1]
    assert properties["saturation_percent"]["minimum"] == LIMITS["saturation_percent"][0]
    assert properties["saturation_percent"]["maximum"] == LIMITS["saturation_percent"][1]


def test_more_colorful_intent_points_to_correct_actions() -> None:
    """"Make it more colorful" resolves to uniform saturation (image/
    properties), with HSL as the colour-specific alternative."""
    image = ACTION_SEMANTICS["clip.color.image"]
    properties = ACTION_SEMANTICS["clip.color.properties"]
    assert any("colorful" in intent for intent in properties["intents"]["en"])
    assert any("colorful" in intent or "Farbe" in intent for intent in image["intents"]["en"] + image["intents"]["de"])
    assert any("clip.color.hsl" in alternative for alternative in properties["alternatives"])


def test_desaturate_except_green_intent_is_hsl_and_honest() -> None:
    """"Desaturate everything except green" is an HSL range action and the
    guidance states the hue-not-object limitation."""
    hsl = ACTION_SEMANTICS["clip.color.hsl"]
    intents = " ".join(hsl["intents"]["en"] + hsl["intents"]["de"]).lower()
    assert "except green" in intents or "grün" in intents
    limitations = " ".join(hsl["limitations"]).lower()
    assert "not objects" in limitations or "objects" in limitations


def test_dlog_conversion_intent_requires_confirmation() -> None:
    """"Convert DJI D-Log M" points to clip.color.look with the
    conversion_confirmed prerequisite."""
    look = ACTION_SEMANTICS["clip.color.look"]
    assert any("d-log m" in intent.lower() for intent in look["intents"]["en"])
    assert any("conversion_confirmed" in prerequisite for prerequisite in look["prerequisites"])


def test_required_disambiguations_exist() -> None:
    """The three mandated distinctions are published."""
    for key in (
        "global_saturation_vs_hsl_saturation",
        "conversion_lut_vs_creative_lut",
        "hue_edits_vs_object_masking",
    ):
        assert key in DISAMBIGUATION and DISAMBIGUATION[key]
    # Every color action's limitations reference honesty about masking where
    # hue selection is involved.
    assert "not implemented" in DISAMBIGUATION["hue_edits_vs_object_masking"].lower()


def test_catalog_extension_is_additive_and_versioned() -> None:
    """Existing Control API v1 consumers keep the contract shape: actions
    keep their keys, semantics/semantics_version are additive."""
    catalog = action_catalog()
    assert catalog["contract_version"] == 1
    assert catalog["semantics_version"] == SEMANTICS_VERSION
    for entry in catalog["actions"]:
        assert set(entry) >= {"name", "version", "scope", "target", "reversible", "description", "parameters"}
    # Only color actions carry semantics.
    for entry in catalog["actions"]:
        if entry["name"] in COLOR_ACTION_NAMES:
            assert "semantics" in entry
        else:
            assert "semantics" not in entry


def test_visual_effect_numbers_are_derived_from_live_models() -> None:
    """Prose numbers in visual_effect must come from the live preview models
    — a changed engine constant without a guidance update fails here."""
    from orga_drone.studio_detail import detail_preview_model
    from orga_drone.studio_hsl import hsl_preview_model
    from orga_drone.studio_image import image_adjust_preview_model

    image_effect = ACTION_SEMANTICS["clip.color.image"]["visual_effect"]
    image_model = image_adjust_preview_model()
    assert f"{image_model['exposureEvAtFull']:+g} stop" in image_effect
    assert f"{image_model['warmthMiredAtFull']:+g} mired" in image_effect
    assert f"{image_model['neutralKelvin']:g} K" in image_effect

    hsl_effect = ACTION_SEMANTICS["clip.color.hsl"]["visual_effect"]
    hsl_model = hsl_preview_model()
    assert f"{hsl_model['hueDegAtFull']:+g} degrees" in hsl_effect
    assert f"{hsl_model['lutSize']}-point cube" in hsl_effect

    detail_effect = ACTION_SEMANTICS["clip.effects.detail"]["visual_effect"]
    detail_model = detail_preview_model()
    assert f"{detail_model['sharpenAmountAtFull']:g}" in detail_effect


def test_hsl_intents_do_not_promise_object_or_sky_selectivity() -> None:
    """Example intents must stay colour-range phrased: no 'sky', no object
    isolation promises from hue-based tools."""
    hsl = ACTION_SEMANTICS["clip.color.hsl"]
    all_intents = " ".join(
        hsl["intents"]["en"] + hsl["intents"]["de"]
    ).lower()
    assert "sky" not in all_intents and "himmel" not in all_intents
    assert "objekt" not in all_intents and "subject" not in all_intents


def test_semantics_payload_is_self_contained() -> None:
    """The discoverable payload carries version, disambiguation and actions
    without repository knowledge."""
    payload = action_semantics()
    assert payload["semantics_version"] == SEMANTICS_VERSION
    assert set(payload) == {"semantics_version", "disambiguation", "actions"}
    for entry in payload["actions"].values():
        assert {"visual_effect", "intents", "prerequisites", "side_effects", "alternatives", "limitations"} <= set(entry)
        assert set(entry["intents"]) == {"en", "de"}
        for texts in entry["intents"].values():
            assert texts, "every language lists at least one example intent"


def test_attach_semantics_never_mutates_the_input() -> None:
    catalog = action_catalog()
    before = {entry["name"]: set(entry) for entry in catalog["actions"]}
    attach_semantics(catalog)
    after = {entry["name"]: set(entry) for entry in catalog["actions"]}
    assert before == after
