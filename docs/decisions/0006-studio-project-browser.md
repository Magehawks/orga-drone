# ADR 0006: Studio project browser and last-opened project

- **Status:** Proposed
- **Date:** 2026-08-14
- **Deciders:** Issue #19

## Context

ADR 0004 introduced `studio_projects` / `studio_clips` and migrated the
legacy `studio_items` workspace into a default project. The Studio UI still
edited only that first project (`ORDER BY id ASC`). Issue #19 requires a
local project browser and switcher so users can keep multiple non-destructive
edits, reopen them after export, and never touch source media.

Library albums remain out of scope. This decision is the Studio picker
follow-up named in ADR 0004.

## Decision

1. Reuse `studio_projects` / `studio_clips`. Do not add a second persistence
   model or copy media into project folders.
2. Store the last-opened project id in SQLite `app_state`
   (`studio_last_opened_project_id`), not `app_prefs.json`. Opening a project
   writes only `app_state`; it does not bump `studio_projects.updated_at`.
3. `GET /studio` restores that project when the id still exists. If the key
   was never set (upgrade), open the most recently edited project
   (`updated_at DESC, id DESC`). If the value is empty or stale (deleted
   open project), show the project browser — never silently reopen `id ASC`.
4. Add to Studio, Clear Studio, reorder, and export without an explicit
   `project_id` target the resolved open project. If none is open, Add/Clear
   redirect to the browser (`studio_need_project`); export returns 400.
5. Project list order is `updated_at DESC, id DESC`. Meaningful edits that
   bump `updated_at`: title, add, remove, reorder, cut, photo duration — not
   open or export.
6. Deleting a project cascades to its clips only. Deleting the open project
   clears last-opened and returns to the browser. Deleting the last project
   is allowed; migrate must not recreate a default “Your story” unless
   leftover `studio_items` still need importing.
7. Isolation is persisted title + `studio_clips`. Client-only music/transition
   stubs may remain session-global.

## Alternatives considered

1. **`app_prefs.json` for last-opened** — mixes a DB foreign key with a
   filesystem preference file; delete would not be atomic with clips.
2. **`/studio/{id}` routes** — collides with existing
   `POST /studio/{studio_item_id}/remove`.
3. **Always keep a default project** — recreating “Your story” after the user
   deletes the last project contradicts the empty-browser acceptance criterion.

## Consequences

- Positive: Multiple local Studio edit projects; existing ADR 0004 data remains
  listed; Add-to-Studio cannot land in the wrong project once one is open.
- Negative / trade-offs: Users must pick or create a project before the first
  Add on a fresh database; transition stubs are not per-project yet.
- Follow-up: Library albums stay Later; music persistence is ADR 0008.
