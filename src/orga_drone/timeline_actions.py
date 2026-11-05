"""Shared existing Story edits; transports own leases and stale-state checks."""
from __future__ import annotations

import math
import sqlite3
from typing import Any

from orga_drone.db import Database, make_identity_key
from orga_drone.studio_cut import MIN_SEGMENT_S, section_repeats_from_effect_settings
from orga_drone.studio_forward_loop import soundtrack_once_s
from orga_drone.studio_estimate import summarize_studio_items
from orga_drone.studio_forward_loop import effective_item_seconds

MAX_TIME_S = 1_000_000_000.0


class TimelineActionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


TIMELINE_PARAMETERS: dict[str, dict[str, dict[str, Any]]] = {
    "timeline.add": {"media_id": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1}},
    "timeline.remove": {},
    "timeline.reorder": {"ordered_ids": {"type": "array", "items": "positive_integer", "exact_permutation": True}},
    "timeline.trim": {
        "source_in_s": {"type": "number", "minimum": 0, "unit": "source_seconds"},
        "source_out_s": {"type": "number", "unit": "source_seconds", "minimum_span_s": MIN_SEGMENT_S},
    },
}


def validate_timeline_params(action: str, params: Any) -> dict[str, Any]:
    if action not in TIMELINE_PARAMETERS:
        raise TimelineActionError("UNKNOWN_ACTION")
    if not isinstance(params, dict) or set(params) != set(TIMELINE_PARAMETERS[action]):
        raise TimelineActionError("INVALID_PARAMS")
    def valid_id(value: Any) -> bool:
        return type(value) is int and 0 < value <= 2**53 - 1
    if action == "timeline.add" and not valid_id(params["media_id"]):
        raise TimelineActionError("INVALID_IDENTIFIER")
    if action == "timeline.reorder":
        ids = params["ordered_ids"]
        if not isinstance(ids, list) or not all(valid_id(i) for i in ids) or len(set(ids)) != len(ids):
            raise TimelineActionError("INVALID_PARAMS")
    if action == "timeline.trim":
        start, end = params["source_in_s"], params["source_out_s"]
        if any(type(v) not in (int, float) for v in (start, end)):
            raise TimelineActionError("INVALID_PARAMS")
        if any(isinstance(v, float) and not math.isfinite(v) for v in (start, end)):
            raise TimelineActionError("INVALID_PARAMS")
        if not 0 <= start <= MAX_TIME_S or not 0 < end <= MAX_TIME_S:
            raise TimelineActionError("INVALID_PARAMS")
        if end <= start or end - start < MIN_SEGMENT_S:
            raise TimelineActionError("INVALID_PARAMS")
    return dict(params)


def timeline_view(db: Database, project_id: int, connection: sqlite3.Connection) -> dict[str, Any]:
    items = db.list_studio_items(project_id, connection=connection)
    music_s = soundtrack_once_s(db.list_studio_music(project_id, connection=connection))
    return {
        "clips": [{"id": c.id, "media_id": c.media_id, "kind": c.kind,
                   "position": c.position, "source_in_s": c.source_in_s,
                   "source_out_s": c.source_out_s,
                   "effective_duration_s": effective_item_seconds(c, items, music_s)} for c in items],
        "ordered_ids": [c.id for c in items],
        "summary": summarize_studio_items(items, soundtrack_once_s=music_s).as_dict(),
    }


def apply_timeline(db: Database, project_id: int, clip_id: int | None,
                   action: str, params: dict[str, Any], *,
                   connection: sqlite3.Connection, repeats: object = None) -> int | None:
    """Join the caller's Story transaction using the existing persistence helpers."""
    validate_timeline_params(action, params)
    if db.get_studio_project(project_id, connection=connection) is None:
        raise TimelineActionError("TARGET_NOT_FOUND")
    clips = {c.id: c for c in db.list_studio_items(project_id, connection=connection)}
    if action in {"timeline.remove", "timeline.trim"} and clip_id not in clips:
        raise TimelineActionError("TARGET_NOT_FOUND")
    if action == "timeline.add":
        item = db.get_media(params["media_id"])
        if item is None or item.kind not in {"photo", "video"}:
            raise TimelineActionError("TARGET_NOT_FOUND")
        added, _ = db.add_studio_item(item.path,
            identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
            filename=item.filename, recorded_at=item.recorded_at, kind=item.kind,
            project_id=project_id, source_media_id=item.id, connection=connection)
        return added
    if action == "timeline.remove":
        assert clip_id is not None
        db.remove_studio_item(clip_id, connection=connection)
    elif action == "timeline.reorder":
        db.reorder_studio_items(params["ordered_ids"], project_id, connection=connection)
    elif action == "timeline.trim":
        assert clip_id is not None
        clip = clips[clip_id]
        if clip.item_kind != "media" or clip.kind != "video":
            raise TimelineActionError("UNSUPPORTED_CLIP")
        db.set_studio_section(clip_id, **params,
            repeats=section_repeats_from_effect_settings(clip.effect_settings) if repeats is None else repeats, connection=connection)
    return clip_id

