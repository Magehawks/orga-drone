"""Per-leaf collage grade helpers (#469). Reuse clip grade dump/parse helpers.

Leaf ``media.grade`` is an effect_settings-shaped object applied once in the
collage still/export path. No second color engine.
"""

from __future__ import annotations

import json
from typing import Any

from orga_drone.studio_collage import (
    CollageSpecError,
    assign_leaf_media,
    collage_spec_from_raw,
    iter_leaves,
    normalize_spec,
)


def grade_blob(media: dict[str, Any] | None) -> str:
    """Serialize leaf grade to the effect_settings string form."""
    if not isinstance(media, dict):
        return "{}"
    grade = media.get("grade")
    if not isinstance(grade, dict) or not grade:
        return "{}"
    return json.dumps(grade, separators=(",", ":"), sort_keys=True)


def parse_grade_object(blob: str) -> dict[str, Any]:
    text = (blob or "").strip() or "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("grade must be JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("grade must be an object")
    return parsed


def _leaf_media(spec: dict[str, Any], leaf_id: str) -> dict[str, Any]:
    for leaf in iter_leaves(spec["root"]):
        if str(leaf.get("id")) == str(leaf_id):
            media = leaf.get("media")
            if not isinstance(media, dict):
                raise CollageSpecError("leaf has no media to grade")
            return dict(media)
    raise CollageSpecError(f"leaf not found: {leaf_id}")


def patch_leaf_grade(
    spec: dict[str, Any],
    leaf_id: str,
    *,
    mutator,
) -> dict[str, Any]:
    """Apply ``mutator(current_blob) -> next_blob`` to one leaf's grade."""
    normalized = normalize_spec(spec)
    media = _leaf_media(normalized, leaf_id)
    current_blob = grade_blob(media)
    next_blob = mutator(current_blob)
    if not isinstance(next_blob, str):
        raise ValueError("grade mutator must return a JSON string")
    next_obj = parse_grade_object(next_blob)
    if next_obj:
        media["grade"] = next_obj
    else:
        media.pop("grade", None)
    return assign_leaf_media(normalized, leaf_id, media)


def clear_leaf_grade(spec: dict[str, Any], leaf_id: str) -> dict[str, Any]:
    return patch_leaf_grade(spec, leaf_id, mutator=lambda _blob: "{}")


def apply_image_adjust(spec: dict[str, Any], leaf_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    from orga_drone.studio_image import (
        dump_effect_settings,
        image_adjust_from_effect_settings,
        parse_image_adjust_patch,
    )

    def mutator(blob: str) -> str:
        current = image_adjust_from_effect_settings(blob)
        updated = parse_image_adjust_patch(patch, current)
        return dump_effect_settings(blob, updated)

    return patch_leaf_grade(spec, leaf_id, mutator=mutator)


def apply_hsl(spec: dict[str, Any], leaf_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from orga_drone.studio_hsl import (
        dump_hsl_adjust,
        hsl_adjust_from_effect_settings,
        parse_hsl_payload,
    )

    def mutator(blob: str) -> str:
        current = hsl_adjust_from_effect_settings(blob)
        updated = parse_hsl_payload(payload, current)
        return dump_hsl_adjust(blob, updated)

    return patch_leaf_grade(spec, leaf_id, mutator=mutator)


def apply_color_wheels(
    spec: dict[str, Any], leaf_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    from orga_drone.studio_color_wheels import (
        color_wheels_from_effect_settings,
        dump_color_wheels,
        parse_color_wheels_payload,
    )

    def mutator(blob: str) -> str:
        current = color_wheels_from_effect_settings(blob)
        updated = parse_color_wheels_payload(payload, current)
        return dump_color_wheels(blob, updated)

    return patch_leaf_grade(spec, leaf_id, mutator=mutator)


def apply_color_look(
    spec: dict[str, Any], leaf_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    from orga_drone.studio_lut import dump_color_look, parse_color_look_payload

    def mutator(blob: str) -> str:
        look = parse_color_look_payload(payload)
        return dump_color_look(blob, look)

    return patch_leaf_grade(spec, leaf_id, mutator=mutator)


def leaf_grade_from_clip_raw(collage_spec_raw: str | None, leaf_id: str) -> dict[str, Any]:
    spec = collage_spec_from_raw(collage_spec_raw)
    media = _leaf_media(spec, leaf_id)
    grade = media.get("grade")
    return dict(grade) if isinstance(grade, dict) else {}
