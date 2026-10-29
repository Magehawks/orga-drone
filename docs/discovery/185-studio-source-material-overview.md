# Discovery: Studio source-material overview (unused flight footage)

- **Issue:** [#185](https://github.com/Magehawks/orga-drone/issues/185)
- **Date:** 2026-10-29
- **Status:** Discovery only. No UI or API change in this note.
- **Related shipped work:** [#156](https://github.com/Magehawks/orga-drone/issues/156) / ADR 0025 (reuse + `studio_originals`), [#157](https://github.com/Magehawks/orga-drone/issues/157) edge trim, [#160](https://github.com/Magehawks/orga-drone/issues/160) remove cut, [#137](https://github.com/Magehawks/orga-drone/issues/137) time mapping

## Question

After several trims and cuts, how can a hobby pilot see **what of the original flight is still unused** and add another range **without** changing existing Story clips — and should that be a new monitor/strip or an extension of today’s Original / Reuse flow?

## What already ships

| Capability | Today |
| --- | --- |
| Add another scene from the same file | Context menu / Original browser / drag → `reuse-source` APIs |
| Original browser row | One `studio_originals` entry per project + media path when a video was trimmed |
| Overlap with existing ranges | Allowed; does not rewrite neighbor clips |
| Undo | One step removes the added clip |
| Used vs unused visualization | **Absent** — user must scrub manually |
| Source strip / second monitor | **Absent** (ADR 0025 deferred a second monitor) |
| Photos / title cards | No Original / reuse |

Evidence: `studio_reuse.py`, `studio_originals` in `db/__init__.py`, `openReuseDraft` / `openOriginalDraft` in `studio.js`, `tests/test_studio_reuse.py`, ADR `0025-studio-reuse-source.md`.

## User tasks

1. After five cuts from one long flight, find a unused stretch and add it.
2. Add a second clip from the same file without changing the first clip’s trim (already solved by #156; discoverability remains).
3. Reopen the project tomorrow and still see what was used.

## Concepts compared

| Option | Idea | Pros | Cons |
| --- | --- | --- | --- |
| **A – Extend Reuse draft** | In the existing Original preview, paint used intervals on the scrubber / inspector | Reuses #156; small UI; no new track | Easy to miss; still feels like a dialog |
| **B – Source strip** | Thin lane in **source time** above Story (not soundtrack coverage) | Always visible; clear used/unused | New lane; mapping UI; more cognitive load for families |
| **C – Original panel mini-timeline** | Expand Original browser row into a file-local used/unused bar + “Add gap” | Keeps Story simple; one file at a time | Less cinematic than a full monitor |
| **D – Status quo** | Copy + Original list only | Zero cost | Does not meet #185 problem |

## Technical mapping (for a follow-up)

For each `media_path` in the open project:

1. Collect Story video clips with that path (`source_start` / `source_end`; null = full file duration).
2. Merge intervals in **source seconds** (ignore Story speed/repeat/loop — those change occupancy on the Story clock only).
3. Unused = gaps in `[0, catalog_duration]` minus the merged used set.
4. Offline / missing duration: show Original row but disable gap picking (same honesty as reuse errors today).
5. Reopen: recompute from persisted clips; no new table required for a first slice (optional cache later).

Never invent a second exportable master track.

## Recommendation

1. **Do not** build an exportable second track.
2. **Prefer Option A, then C** for the first implementation slice aimed at hobby pilots:
   - Mark used ranges in the existing Reuse / Original draft preview.
   - Optionally surface the same bar under each Original browser row (Option C).
3. Defer a full source strip (Option B) until usability testing shows A/C are insufficient.
4. Keep adding clips via the existing reuse APIs so edits stay non-destructive.

## Acceptance for follow-up implementation issue(s)

- Used intervals for the open project’s Original files are visible in source time.
- Selecting an unused range adds a **new** clip; existing clips unchanged.
- Project reopen recomputes marks from stored clips.
- Explicit product copy that overlap is allowed and that Story speed/repeat do not shrink the “used” source mark.
- Tests for interval merge + reuse add; no customer GPS/media in fixtures.

## Non-scope (honored)

Second exportable master track, automatic scene selection, AI, destructive restore, node editor.

## Outcome

Discovery acceptance for #185: UX options, technical mapping, and a clear recommendation to extend #156 Reuse/Original rather than invent a new export track.
