"""Versioned semantic guidance for implemented Studio actions (issue #291).

Machine-readable metadata consumed alongside ``action_catalog()``: an MCP
assistant can map natural-language intents to existing actions, their
canonical ranges, neutral values, prerequisites, side effects and honest
limitations — without repository knowledge and without guessing.

Contract rules:

- ``SEMANTICS_VERSION`` bumps when guidance meaning changes, not when the
  underlying action changes (the action's own ``version`` covers that).
- Entries exist only for IMPLEMENTED actions. Adding an action means adding
  its entry here in the same PR; ``tests/test_studio_action_semantics.py``
  fails on missing/orphan entries and on range/neutral drift.
- Ranges and neutral values are IMPORTED from the live validators/preview
  models — this module never restates a number the engine already owns.
- Guidance is descriptive, non-prescriptive: example ranges inform, they do
  not promise universally correct presets.
- No embedded AI, no provider prompts, no claims of object-selective
  editing from hue-based tools.
"""

from __future__ import annotations

from typing import Any

from orga_drone.studio_actions import (
    ACTION_SPECS,
    DETAIL_PARAMETERS,
    HSL_PARAMETERS,
    IMAGE_PARAMETERS,
    LIMITS,
    LOOK_PARAMETERS,
    WHEEL_PARAMETERS,
)
from orga_drone.studio_detail import detail_preview_model
from orga_drone.studio_hsl import hsl_preview_model
from orga_drone.studio_image import image_adjust_preview_model

_IMAGE_MODEL = image_adjust_preview_model()
_HSL_MODEL = hsl_preview_model()
_DETAIL_MODEL = detail_preview_model()


def _number(model: dict[str, Any], key: str) -> float:
    """Preview models carry untyped values; guidance only prints them."""
    return float(model[key])  # type: ignore[arg-type]

SEMANTICS_VERSION = 1

#: The required distinctions between look-alike controls (issue #291).
DISAMBIGUATION: dict[str, str] = {
    "global_saturation_vs_hsl_saturation": (
        "clip.color.image.saturation and clip.color.properties.saturation_percent "
        f"scale the whole picture uniformly (image: {IMAGE_PARAMETERS['saturation']['minimum']}"
        f"..{IMAGE_PARAMETERS['saturation']['maximum']} slider around the current grade; "
        f"properties: {LIMITS['saturation_percent'][0]}..{LIMITS['saturation_percent'][1]} percent). "
        "clip.color.hsl saturates eight hue ranges independently with "
        f"{HSL_PARAMETERS['ranges']['minimum']}..{HSL_PARAMETERS['ranges']['maximum']} sliders. "
        "Use HSL when only specific colours should change."
    ),
    "conversion_lut_vs_creative_lut": (
        "A conversion LUT (clip.color.look with input_profile dlog_m and "
        "conversion_confirmed=true) is a technical camera-log transform and "
        f"runs once before grading. A creative LUT is a stylistic look blended "
        f"by creative_strength {LOOK_PARAMETERS['creative_strength']['minimum']}"
        f"..{LOOK_PARAMETERS['creative_strength']['maximum']}. They are separate assets and "
        "separate confirmations; do not fake a conversion with a creative LUT."
    ),
    "hue_edits_vs_object_masking": (
        "HSL ranges and hue curves select COLOURS, not objects: a blue range "
        "edit reaches every blue pixel in the clip. Selective object or sky "
        "editing needs masks/qualifiers, which are not implemented; never "
        "claim subject isolation from HSL alone."
    ),
}

ACTION_SEMANTICS: dict[str, dict[str, Any]] = {
    "clip.color.image": {
        "visual_effect": (
            f"Seven per-clip sliders (exposure, contrast, saturation, warmth, "
            f"highlights, shadows, blacks). Exposure is "
            f"{_number(_IMAGE_MODEL, 'exposureEvAtFull'):+g} stop at full travel, "
            f"warmth shifts {_number(_IMAGE_MODEL, 'warmthMiredAtFull'):+g} mired around "
            f"{_number(_IMAGE_MODEL, 'neutralKelvin'):g} K, tonal controls reshape input "
            "bounds without recovering clipped data."
        ),
        "intents": {
            "en": [
                "make it brighter / darker",
                "more or less colorful",
                "warmer / cooler",
                "lift shadows or tame highlights",
            ],
            "de": [
                "heller / dunkler machen",
                "mehr oder weniger Farbe",
                "w\u00e4rmer / k\u00fchler",
                "Schatten anheben oder Lichter z\u00e4hmen",
            ],
        },
        "prerequisites": ["A selected Studio video or photo clip."],
        "side_effects": [
            "Replaces the clip's stored image section; unrelated effect_settings keys are preserved.",
            "Undo/redo via the shared Story history when sent through editing routes.",
        ],
        "alternatives": [
            "Uniform saturation in percent: clip.color.properties.",
            "Colour-specific saturation: clip.color.hsl.",
        ],
        "limitations": [
            "Not optical-flow or HDR recovery; clipped data stays clipped.",
            "Static per clip; animation is a separate action.",
        ],
    },
    "clip.color.properties": {
        "visual_effect": (
            "Compact property set on the selected clip: contrast "
            f"({LIMITS['contrast'][0]}..{LIMITS['contrast'][1]}), uniform saturation_percent "
            f"({LIMITS['saturation_percent'][0]}..{LIMITS['saturation_percent'][1]}), an optional "
            f"creative LUT with strength {LIMITS['creative_lut_strength_percent'][0]}"
            f"..{LIMITS['creative_lut_strength_percent'][1]}."
        ),
        "intents": {
            "en": [
                "make it more colorful",
                "slightly more contrast",
                "apply a look with some strength",
            ],
            "de": [
                "mehr Farbe machen",
                "etwas mehr Kontrast",
                "einen Look mit bestimmter St\u00e4rke anwenden",
            ],
        },
        "prerequisites": ["A selected Studio video clip."],
        "side_effects": [
            "Writes image saturation, contrast and the color look section in one step.",
        ],
        "alternatives": [
            "Fine-grained sliders: clip.color.image.",
            "Colour-specific saturation: clip.color.hsl.",
        ],
        "limitations": [
            "No HSL ranges, no conversion LUT confirmation; use clip.color.look for that.",
        ],
    },
    "clip.color.look": {
        "visual_effect": (
            f"Technical input profile ({', '.join(LOOK_PARAMETERS['input_profile']['enum'])}), "
            "optional confirmed conversion LUT (runs once, before grading), "
            f"optional creative LUT blended by strength "
            f"{LOOK_PARAMETERS['creative_strength']['minimum']}..{LOOK_PARAMETERS['creative_strength']['maximum']}."
        ),
        "intents": {
            "en": [
                "convert DJI D-Log M footage",
                "apply a creative look / .cube file",
                "reduce the look strength",
            ],
            "de": [
                "DJI D-Log M Material umwandeln",
                "kreativen Look / .cube-Datei anwenden",
                "Look-St\u00e4rke reduzieren",
            ],
        },
        "prerequisites": [
            "The .cube asset is already imported into the local LUT library.",
            "A conversion LUT for dlog_m requires conversion_confirmed=true; "
            "the confirmation must come from the user.",
        ],
        "side_effects": [
            "Replaces the clip's color section; a missing LUT asset blocks export with an actionable error.",
        ],
        "alternatives": [
            "Stylistic-only changes: clip.color.properties (creative LUT + strength).",
        ],
        "limitations": [
            "A creative LUT is not a conversion; D-Log M hints from telemetry "
            "do not calibrate colour.",
            "Local user LUTs are user-declared transforms, not certified camera profiles.",
        ],
    },
    "clip.color.hsl": {
        "visual_effect": (
            f"Eight hue ranges ({', '.join(HSL_PARAMETERS['ranges']['ranges'])}), "
            f"each with hue ({_number(_HSL_MODEL, 'hueDegAtFull'):+g} degrees at full), "
            f"saturation (0..{_number(_HSL_MODEL, 'saturationScaleAtFull') + 1:g}x) and "
            f"luminance ({_number(_HSL_MODEL, 'luminanceDeltaAtFull'):+g}) sliders from "
            f"{HSL_PARAMETERS['ranges']['minimum']}..{HSL_PARAMETERS['ranges']['maximum']}. "
            f"Smooth hue crossfades; near-neutral pixels are gated out; baked "
            f"to a {_number(_HSL_MODEL, 'lutSize'):g}-point cube."
        ),
        "intents": {
            "en": [
                "desaturate everything except green (set every range's saturation to -100 and leave green at 0)",
                "strengthen or shift the blue colour range",
                "warm up the red colour range",
            ],
            "de": [
                "alles au\u00dfer Gr\u00fcn ent\u00e4ttigen (alle Bereiche auf -100, Gr\u00fcn auf 0 lassen)",
                "den Blau-Bereich st\u00e4rken oder verschieben",
                "den Rot-Bereich w\u00e4rmer machen",
            ],
        },
        "prerequisites": ["A selected Studio video or photo clip."],
        "side_effects": [
            "Replaces the clip's hsl section; ranges not in the payload reset to neutral.",
        ],
        "alternatives": [
            "Whole-picture saturation: clip.color.image.",
        ],
        "limitations": [
            "Selects COLOUR ranges, not objects or sky regions: every matching "
            "pixel in the clip changes. Object-selective editing is not "
            "implemented (see disambiguation).",
            f"Baked to a {_number(_HSL_MODEL, 'lutSize'):g}-point cube; not a curve editor.",
        ],
    },
    "clip.color.wheels": {
        "visual_effect": (
            f"Three tonal wheels ({', '.join(WHEEL_PARAMETERS['wheels']['wheels'])}) as "
            f"unit-disc points ({WHEEL_PARAMETERS['wheels']['minimum']}.."
            f"{WHEEL_PARAMETERS['wheels']['maximum']} per axis). Zero-luma tint: "
            "direction shifts colour without changing luma, weighted smoothly "
            "across tonal bands. These are not lift/gamma/gain controls."
        ),
        "intents": {
            "en": [
                "teal shadows with warm highlights (cinematic)",
                "cool down only the shadows",
            ],
            "de": [
                "T\u00fcrkise Schatten und warme Lichter (kinoreif)",
                "nur die Schatten k\u00fchler machen",
            ],
        },
        "prerequisites": ["A selected Studio video or photo clip."],
        "side_effects": [
            "Replaces the clip's color_wheels section; wheels not in the payload reset to neutral.",
        ],
        "alternatives": [
            "Hue-targeted shifts: clip.color.hsl.",
        ],
        "limitations": [
            "Tonal tint only; no contrast/lift/gamma/gain math.",
        ],
    },
    "clip.effects.detail": {
        "visual_effect": (
            f"Sharpen and denoise {DETAIL_PARAMETERS['sharpen']['minimum']}"
            f"..{DETAIL_PARAMETERS['sharpen']['maximum']} each on the selected clip "
        f"(sharpen amount {_number(_DETAIL_MODEL, 'sharpenAmountAtFull'):g}, denoise luma "
        f"{_number(_DETAIL_MODEL, 'denoiseLumaAtFull'):g} at full travel)."
        ),
        "intents": {
            "en": ["sharpen the footage a bit", "reduce noise"],
            "de": ["das Material etwas sch\u00e4rfen", "Rauschen reduzieren"],
        },
        "prerequisites": ["A selected Studio video clip."],
        "side_effects": [
            "Replaces the clip's detail section.",
        ],
        "alternatives": [],
        "limitations": [
            "Runs after colour in the established chain; not a restoration tool.",
            "Static per clip; heavy values cost export time.",
        ],
    },
}


def action_semantics() -> dict[str, Any]:
    """Discoverable semantics payload for the implemented color actions."""
    return {
        "semantics_version": SEMANTICS_VERSION,
        "disambiguation": dict(DISAMBIGUATION),
        "actions": {name: dict(entry) for name, entry in ACTION_SEMANTICS.items()},
    }


def attach_semantics(catalog: dict[str, Any]) -> dict[str, Any]:
    """Return the catalog with per-action semantics attached additively.

    Existing keys (contract_version, actions with their parameter schemas)
    stay untouched; each action dict only gains a ``semantics`` object when
    guidance exists for it.
    """
    actions = []
    for entry in catalog["actions"]:
        enriched = dict(entry)
        guidance = ACTION_SEMANTICS.get(str(entry.get("name")))
        if guidance is not None:
            enriched["semantics"] = dict(guidance)
        actions.append(enriched)
    result = dict(catalog)
    result["actions"] = actions
    result["semantics_version"] = SEMANTICS_VERSION
    return result


def color_action_names() -> tuple[str, ...]:
    """Implemented action names in the color/LUT/HSL/wheels/detail scope."""
    return tuple(
        spec.name
        for spec in ACTION_SPECS
        if spec.name in ACTION_SEMANTICS
    )


__all__ = [
    "ACTION_SEMANTICS",
    "DETAIL_PARAMETERS",
    "DISAMBIGUATION",
    "HSL_PARAMETERS",
    "IMAGE_PARAMETERS",
    "LOOK_PARAMETERS",
    "LIMITS",
    "SEMANTICS_VERSION",
    "WHEEL_PARAMETERS",
    "action_semantics",
    "attach_semantics",
    "color_action_names",
]
