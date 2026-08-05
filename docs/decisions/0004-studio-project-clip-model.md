# ADR 0004: Studio non-destructive project and clip model

- **Status:** Accepted
- **Date:** 2026-08-05
- **Deciders:** Issue #16

## Context

GitHub Issue #16 requires a Studio **project** with an editable persisted title and
**clips** that reference library media without copying or modifying source files.
ADR 0001 stored a single global `studio_items` list keyed by `media_path` (because
`media.id` is unstable across full rescans). ADR 0003 added in/out offsets for Cut.

## Decision

1. Add `studio_projects` (`id`, `title`, `created_at`, `updated_at`).
2. Replace `studio_items` with `studio_clips` owned by a project
   (`ON DELETE CASCADE` from project → clips only; never cascade to `media`).
3. Each clip stores editing metadata: `source_start` / `source_end` (formerly
   `source_in_s` / `source_out_s`), `playback_speed`, `volume`, `transition`,
   `effect_settings` (JSON text), plus existing snapshots / photo duration.
4. Reference media non-destructively:
   - Durable: `media_path` + `identity_key` (rescan-safe, ADR 0001).
   - Convenience: `source_media_id` (live `media.id` when known; `ON DELETE SET NULL`).
5. Ensure one default project on migrate; migrate existing `studio_items` rows into
   clips of that project. The Studio UI edits that project’s title via API.
6. Deleting a clip or project never deletes `media` rows or files on disk.
7. Multi-project UI switcher remains out of scope; the data model supports more
   than one project.

## Alternatives considered

1. **Reference `media.id` only** — breaks after every full rescan.
2. **Keep global `studio_items` and only add a title row** — fails Issue #16 clip
   field model and project delete semantics.
3. **Copy media into a project folder** — violates non-destructive / local-first
   integrity.

## Consequences

- Positive: Persisted project title; clear project/clip separation; Cut and
  estimate continue via start/end offsets; source files untouched.
- Negative / trade-offs: `source_media_id` alone is not durable; path/identity
  remain required for relink.
- Follow-up: project picker UI, effect/transition render.
