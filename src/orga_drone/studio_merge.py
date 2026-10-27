"""Join two adjacent Story clips that are still one forward source range.

A cut stores two ``studio_clips`` rows. It does not change the file. This
module plans the inverse only when the join keeps every visible setting.
Anything that would drop, average, or guess a setting is refused.

Source ends must meet within ``MERGE_SOURCE_TOLERANCE_S`` (0.001 s). That is
tighter than one frame at 60 fps, so a trimmed edge is not filled in.
Overlay times are stored in 0.1 s steps, so a split overlay may be rejoined
when its halves meet within ``MERGE_OVERLAY_SEAM_S`` (0.15 s) and share an id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from orga_drone.db import StudioClip
from orga_drone.studio_cut import (
    resolve_source_range,
    section_repeats_from_effect_settings,
)
from orga_drone.studio_forward_loop import loop_to_soundtrack_enabled, loop_transition_choice
from orga_drone.studio_image import RAMP_KEY, saturation_ramp_from_effect_settings
from orga_drone.studio_overlay import MAX_OVERLAYS, Overlay, overlays_from_effect_settings
from orga_drone.studio_speed import coerce_playback_speed, output_duration_s

MERGE_SOURCE_TOLERANCE_S = 0.001
MERGE_OVERLAY_SEAM_S = 0.15

MERGE_REASONS: dict[str, str] = {
    "not_found": "That Story clip is no longer there.",
    "not_adjacent": "This clip has no previous clip to join.",
    "not_video": "Only two video clips can be joined.",
    "different_file": "These clips come from different files.",
    "range_unknown": "The source range is unknown.",
    "reversed": "The source ranges are in reverse order.",
    "not_contiguous": "The source ranges do not meet.",
    "speed": "Playback speed does not match.",
    "volume": "Volume does not match.",
    "transition": "The transition between these clips is not a cut.",
    "repeats": "A repeat is set on one of these clips.",
    "loop": "A soundtrack loop is set on one of these clips.",
    "image": "Image adjustment does not match.",
    "masks": "Privacy masks do not match.",
    "frame": "Zoom does not match.",
    "map": "The flight map does not match.",
    "hud": "The telemetry display does not match.",
    "overlays": "Overlays cannot be combined without dropping one.",
    "ramp": "The color change does not match.",
    "settings": "Clip settings do not match.",
}

_IGNORED_KEYS = frozenset(
    {"overlays", RAMP_KEY, "section_repeats", "loop_to_soundtrack"}
)
_NAMED_KEYS = {
    "image": "image",
    "masks": "masks",
    "frame": "frame",
    "map": "map",
    "hud": "hud",
}


class MergeBlocked(Exception):
    """The join would drop or guess a setting. ``code`` is a ``MERGE_REASONS`` key."""

    def __init__(self, code: str) -> None:
        self.code = code if code in MERGE_REASONS else "settings"
        super().__init__(MERGE_REASONS[self.code])


@dataclass(frozen=True)
class MergePlan:
    """One safe write: extend the left row and drop the right row."""

    left_id: int
    right_id: int
    project_id: int
    source_end: float
    effect_settings: str
    transition: str | None
    transition_duration_s: float | None


def plan_merge(items: list[StudioClip], right_id: int) -> MergePlan:
    """Plan a join of ``right_id`` with the clip immediately before it."""
    index = next((i for i, item in enumerate(items) if item.id == right_id), None)
    if index is None:
        raise MergeBlocked("not_found")
    if index == 0:
        raise MergeBlocked("not_adjacent")
    left = items[index - 1]
    right = items[index]
    if left.kind != "video" or right.kind != "video":
        raise MergeBlocked("not_video")
    if not left.media_path or left.media_path != right.media_path:
        raise MergeBlocked("different_file")
    if (left.identity_key or "") != (right.identity_key or ""):
        raise MergeBlocked("different_file")
    left_range = resolve_source_range(
        source_in_s=left.source_start,
        source_out_s=left.source_end,
        media_duration_s=left.duration_s,
    )
    right_range = resolve_source_range(
        source_in_s=right.source_start,
        source_out_s=right.source_end,
        media_duration_s=right.duration_s,
    )
    if left_range is None or right_range is None:
        raise MergeBlocked("range_unknown")
    if right_range.source_in_s + MERGE_SOURCE_TOLERANCE_S < left_range.source_in_s:
        raise MergeBlocked("reversed")
    gap = right_range.source_in_s - left_range.source_out_s
    if abs(gap) > MERGE_SOURCE_TOLERANCE_S:
        raise MergeBlocked("not_contiguous")
    if coerce_playback_speed(left.playback_speed) != coerce_playback_speed(
        right.playback_speed
    ):
        raise MergeBlocked("speed")
    if abs(float(left.volume) - float(right.volume)) > 0.001:
        raise MergeBlocked("volume")
    if (left.transition or "cut") != "cut":
        raise MergeBlocked("transition")
    _reject_repeat_or_loop(left.effect_settings)
    _reject_repeat_or_loop(right.effect_settings)
    speed = coerce_playback_speed(left.playback_speed)
    left_source_s = left_range.duration_s
    left_timeline_s = output_duration_s(left_source_s, speed)
    right_timeline_s = output_duration_s(right_range.duration_s, speed)
    settings = _join_settings(
        left.effect_settings,
        right.effect_settings,
        left_source_s=left_source_s,
        left_timeline_s=left_timeline_s,
        right_timeline_s=right_timeline_s,
    )
    return MergePlan(
        left_id=left.id,
        right_id=right.id,
        project_id=right.project_id,
        source_end=right_range.source_out_s,
        effect_settings=settings,
        transition=right.transition,
        transition_duration_s=right.transition_duration_s,
    )


def _reject_repeat_or_loop(raw: str | None) -> None:
    if section_repeats_from_effect_settings(raw) != 1:
        raise MergeBlocked("repeats")
    if loop_to_soundtrack_enabled(raw) or loop_transition_choice(raw) != "off":
        raise MergeBlocked("loop")


def _load_object(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise MergeBlocked("settings") from exc
    if not isinstance(parsed, dict):
        raise MergeBlocked("settings")
    return parsed


def _canon(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _join_settings(
    left_raw: str | None,
    right_raw: str | None,
    *,
    left_source_s: float,
    left_timeline_s: float,
    right_timeline_s: float,
) -> str:
    left = _load_object(left_raw)
    right = _load_object(right_raw)
    keys = (set(left) | set(right)) - _IGNORED_KEYS
    for key in sorted(keys):
        if _canon(left.get(key)) != _canon(right.get(key)):
            raise MergeBlocked(_NAMED_KEYS.get(key, "settings"))
    joined = {key: value for key, value in left.items() if key not in _IGNORED_KEYS}
    overlays = _join_overlays(
        left,
        right,
        left_timeline_s=left_timeline_s,
        right_timeline_s=right_timeline_s,
    )
    if overlays:
        joined["overlays"] = overlays
    ramp = _join_ramp(left, right, left_source_s=left_source_s)
    if ramp is not None:
        joined[RAMP_KEY] = ramp
    return json.dumps(joined, separators=(",", ":"), sort_keys=True)


def _raw_overlays(data: dict[str, Any]) -> list[object]:
    items = data.get("overlays", [])
    if items is None:
        return []
    if not isinstance(items, list):
        raise MergeBlocked("overlays")
    return items


def _join_overlays(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_timeline_s: float,
    right_timeline_s: float,
) -> list[dict[str, Any]]:
    left_raw = _raw_overlays(left)
    right_raw = _raw_overlays(right)
    left_items = list(
        overlays_from_effect_settings(
            json.dumps(left),
            duration_s=max(left_timeline_s, 0.1),
        )
    )
    right_items = list(
        overlays_from_effect_settings(
            json.dumps(right),
            duration_s=max(right_timeline_s, 0.1),
        )
    )
    if len(left_items) != len(left_raw) or len(right_items) != len(right_raw):
        raise MergeBlocked("overlays")
    if len({item.id for item in left_items}) != len(left_items):
        raise MergeBlocked("overlays")
    if len({item.id for item in right_items}) != len(right_items):
        raise MergeBlocked("overlays")
    right_by_id = {item.id: item for item in right_items}
    used: set[str] = set()
    merged: list[Overlay] = []
    for item in left_items:
        other = right_by_id.get(item.id)
        if other is None:
            merged.append(item)
            continue
        used.add(item.id)
        merged.append(
            _rejoin_split_overlay(
                item,
                other,
                left_timeline_s=left_timeline_s,
            )
        )
    shift = float(left_timeline_s)
    for item in right_items:
        if item.id in used:
            continue
        merged.append(
            Overlay(
                **{
                    **item.as_dict(),
                    "start_s": round(item.start_s + shift, 4),
                    "end_s": round(item.end_s + shift, 4),
                }
            )
        )
    if len(merged) > MAX_OVERLAYS:
        raise MergeBlocked("overlays")
    return [item.as_dict() for item in merged]


def _rejoin_split_overlay(
    left: Overlay,
    right: Overlay,
    *,
    left_timeline_s: float,
) -> Overlay:
    left_body = left.as_dict()
    right_body = right.as_dict()
    for key in ("id", "start_s", "end_s"):
        left_body.pop(key, None)
        right_body.pop(key, None)
    if left_body != right_body:
        raise MergeBlocked("overlays")
    if abs(left.end_s - left_timeline_s) > MERGE_OVERLAY_SEAM_S:
        raise MergeBlocked("overlays")
    if abs(right.start_s) > MERGE_OVERLAY_SEAM_S:
        raise MergeBlocked("overlays")
    return Overlay(
        **{
            **left.as_dict(),
            "end_s": round(left_timeline_s + right.end_s, 4),
        }
    )


def _join_ramp(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_source_s: float,
) -> dict[str, object] | None:
    left_ramp = saturation_ramp_from_effect_settings(json.dumps(left))
    right_ramp = saturation_ramp_from_effect_settings(json.dumps(right))
    if not left_ramp.is_active and not right_ramp.is_active:
        if RAMP_KEY in left and isinstance(left.get(RAMP_KEY), dict):
            return left_ramp.as_dict()
        return None
    if left_ramp.is_active != right_ramp.is_active:
        raise MergeBlocked("ramp")
    unshifted = left_ramp.__class__(
        enabled=right_ramp.enabled,
        start_s=round(right_ramp.start_s + left_source_s, 4),
        end_s=round(right_ramp.end_s + left_source_s, 4),
        start_saturation=right_ramp.start_saturation,
        end_saturation=right_ramp.end_saturation,
    )
    if left_ramp.as_dict() != unshifted.as_dict():
        raise MergeBlocked("ramp")
    return left_ramp.as_dict()
