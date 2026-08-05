# ADR 0003: Studio video cut via source in/out offsets

- **Status:** Accepted
- **Date:** 2026-08-03

## Context

Studio needs a first Cut action that splits a selected video Story clip at the
playhead without modifying the source media file. ADR 0001 used `media_path` as
a unique membership key, which blocked two Story items from referencing the
same file after a split.

## Decision

1. Drop the unique constraint on `studio_items.media_path`. Browse “In Studio”
   still treats path presence as membership. Add always inserts a new clip so
   the same source can appear more than once (Issue #16).
2. Store optional `source_in_s` / `source_out_s` on each Story row (NULL means
   the full media duration). Effective video duration is `out - in`.
3. Cut updates the original row to the left range and inserts a new row for the
   right range at the next `position`, sharing the same `media_path`.
4. Preview seeks into the source file using those offsets; files on disk are
   never rewritten.
5. Relink after rescan updates all rows that share a path; orphan relink may
   update multiple cut segments when they share one former path and identity.

## Alternatives considered

1. **Keep UNIQUE and store a segment list JSON on one row** — harder to reorder
   halves independently and conflicts with the one-row-per-Story-clip UI model.
2. **Copy/transcode files on cut** — violates local-first integrity and is out
   of scope for a light curation workspace.

## Consequences

- Positive: Non-destructive trim/cut; combined duration of parts equals the
  previous trimmed duration; playhead can stay at the cut boundary.
- Negative / trade-offs: Multiple Studio rows can share one library path;
  “remove from Studio” removes one Story item, not all segments of that file.
- Out of scope here: undo, ripple edit, razor mode, image cut, export.
