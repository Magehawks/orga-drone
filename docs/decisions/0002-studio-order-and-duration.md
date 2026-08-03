# ADR 0002: Studio order and duration estimate

- **Status:** Accepted
- **Date:** 2026-08-03

## Context

The Studio workspace (ADR 0001) stores a single curation list with append
`position`. Users need to **manually reorder** that list and see an
**estimated total runtime** for planning. Duration must not become a video
editor, timeline player, or export pipeline. Photo display duration is a
Studio planning value, not library metadata on `media` / `media_meta`.

After a full rescan, Studio rows can be unavailable. Kind and custom photo
duration still need to support estimates and UI while the path is missing
from `media`.

## Decision

1. Persist order via existing `studio_items.position` (1..n). Reorder requires
   an **exact permutation** of all Studio item IDs in one atomic update.
2. Add `kind_snapshot` on `studio_items`, set from `media.kind` on add.
   Survive rescan; do **not** wipe on relink. When the row is available,
   live `media.kind` wins for UI and estimate; otherwise use the snapshot.
   Legacy backfill joins `media`; remaining NULL → `'photo'` fallback only.
3. Add `photo_duration_s REAL NULL` on `studio_items` (not on `media_meta`).
   `NULL` means default **3.0** seconds. Clamp custom values to **[0.5, 60]**.
   Videos ignore this column; their duration is read-only from
   `media.duration_s` when available.
4. Estimate rules:
   - photo → `photo_duration_s` or 3.0
   - video → `media.duration_s` if available, else exclude (UI shows "—")
   - unknown → exclude
   - `estimated_total` = sum of known seconds; format always `HH:MM:SS`
5. JSON APIs: `POST /api/studio/reorder`, `PATCH /api/studio/{id}/photo-duration`.
   HTML5 drag-and-drop on the Studio page persists order; unavailable items
   remain reorderable.
6. Export / editor / in-Studio playback remain out of scope (later milestone
   may reuse order + estimate semantics).

## Alternatives considered

1. **Store photo duration on `media_meta`** — wrong layer; would affect the
   whole library and be cleared/confused with favorites/tags semantics.
2. **Partial reorder payloads** — risk of corrupting `position`; rejected in
   favor of strict full-list permutation.
3. **CDN Sortable library** — unnecessary dependency for a single list; native
   HTML5 DnD is enough for desktop Must.

## Consequences

- Positive: Order and custom photo durations survive restart and rescan;
  planning summary without claiming export readiness.
- Negative / trade-offs: Unavailable videos contribute no seconds; legacy
  `kind_snapshot` fallback may mis-label rare video orphans as photos until
  re-added.
- Follow-up: Simple Video Export can consume `ORDER BY position` and the same
  duration rules later — not implemented here.
