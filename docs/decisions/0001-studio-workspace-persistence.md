# ADR 0001: Studio workspace persistence

- **Status:** Accepted
- **Date:** 2026-08-03

## Context

The Studio Workspace MVP needs a single curation list that survives application
restarts and full library rescans. Favorites already live in `media_meta`.
`media.id` is unstable across rescans (`clear_root_media` deletes and re-inserts
media rows). A JSON file would diverge from the existing SQLite-first app data
model.

## Decision

1. Store Studio membership in a dedicated SQLite table `studio_items`, not as a
   flag on `media_meta` and not in a JSON file.
2. Use `media_path` (resolved absolute path) as the primary membership key and
   `identity_key` (same hash as `media_meta`: filename + size + recorded_at) for
   controlled relinking after rescans.
3. Keep snapshot filename / recorded_at on each row for unavailable UI when the
   path is missing from `media`.
4. Relink rules:
   - Prefer exact `media_path` match and refresh `identity_key`.
   - If no path match, consider orphans with the same identity whose path is not
     currently in `media`.
   - Automatically relink only when exactly one orphan candidate exists.
   - If multiple candidates exist, do not guess; leave entries unavailable.
5. Rename repaths Studio rows the same way as `media_meta`.
6. Favorites and Studio stay independent: Favorites are general bookmarks;
   Studio is an active curation workspace.

## Alternatives considered

1. **Flag on `media_meta`** — couples curation order/snapshots to favorites/tags
   and makes a later multi-workspace model harder.
2. **JSON file next to the DB** — simpler to inspect, but inconsistent with
   durable app data in SQLite and harder to keep atomic with rename/rescan.
3. **Persist by `media.id` only** — breaks after every full rescan.

## Consequences

- Positive: Rescan-safe membership; clear separation from Favorites; append order
  via `position`; unavailable entries remain until manually removed.
- Negative / trade-offs: Identity collisions (same name/size/time) can leave
  Studio items unavailable instead of auto-merging.
- Follow-up work: Multi-project / albums UI remains roadmap; may later add a
  workspace id without changing the Favorites model.
