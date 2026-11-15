"""Seed a Studio collage from library media IDs (#468 / ADR 0038).

Product rule: fill leaves in order from a sized preset, then append leftover
media as normal Story clips. Source files are never modified.
"""

from __future__ import annotations

from typing import Any

from orga_drone.db import Database, StudioClip, make_identity_key
from orga_drone.studio_collage import (
    assign_leaf_media,
    collage_spec_from_raw,
    iter_leaves,
    preset_spec,
)


def preset_for_count(n: int) -> str:
    """Choose a layout preset that covers up to ``n`` leaves (capped at 6)."""
    count = max(1, min(int(n), 6))
    if count <= 2:
        return "1+1"
    if count == 3:
        return "2+1"
    if count == 4:
        return "2x2"
    if count == 5:
        return "3|2"
    return "3x2"


def library_media_payload(db: Database, media_id: int) -> dict[str, Any] | None:
    """Build a collage leaf media object for a library row, or None if missing."""
    row = db.get_media(media_id)
    if row is None:
        return None
    kind = str(row.kind or "").strip().lower()
    if kind not in {"photo", "video"}:
        return None
    return {
        "source": "library",
        "kind": kind,
        "media_id": int(row.id),
        "identity_key": make_identity_key(row.filename, row.size_bytes, row.recorded_at),
        "fit": "fill",
        "zoom": 1.0,
        "pan_x": 0.5,
        "pan_y": 0.5,
        "start_offset_s": 0.0,
    }


def seed_collage_from_media_ids(
    db: Database,
    project_id: int,
    media_ids: list[int],
) -> tuple[StudioClip, int, int]:
    """Create a collage, assign library media in order, append leftovers as clips.

    Returns ``(collage_clip, assigned_count, leftover_clip_count)``.
    Missing media IDs leave their leaf empty and are skipped for leftovers.
    """
    ordered: list[int] = []
    seen: set[int] = set()
    for raw in media_ids:
        try:
            mid = int(raw)
        except (TypeError, ValueError):
            continue
        if mid <= 0 or mid in seen:
            continue
        seen.add(mid)
        ordered.append(mid)

    # Size the preset to N when a matching layout exists (≤6). Larger N fills
    # the 3x2 preset and appends leftovers as normal Story clips (#468).
    leaf_hint = min(len(ordered) if ordered else 2, 6)
    if leaf_hint < 1:
        leaf_hint = 2
    preset = preset_for_count(leaf_hint)
    spec = preset_spec(preset)

    collage = db.add_studio_collage(project_id, collage_spec=spec)
    next_spec = collage_spec_from_raw(collage.collage_spec)
    leaves = iter_leaves(next_spec["root"])

    assigned = 0
    for leaf, mid in zip(leaves, ordered, strict=False):
        payload = library_media_payload(db, mid)
        if payload is None:
            continue
        next_spec = assign_leaf_media(next_spec, str(leaf["id"]), payload)
        assigned += 1

    if assigned:
        collage = db.update_studio_collage(collage.id, collage_spec=next_spec)

    leftovers = ordered[len(leaves) :]
    leftover_n = 0
    if leftovers:
        added, _skipped = db.add_studio_media_ids(leftovers, project_id=project_id)
        leftover_n = int(added)

    return collage, assigned, leftover_n
