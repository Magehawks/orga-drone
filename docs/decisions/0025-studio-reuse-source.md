# ADR 0025: Another scene from the same Studio source

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

A Story clip is often a trimmed range of a longer flight. Using a different
moment meant leaving Studio, adding the file again from Browse, and trimming
from scratch. The clip already in the Story was easy to change by mistake.
ADR 0003 already allows several Story rows to share one media path. ADR 0004
keeps those rows non-destructive.

## Decision

1. Right-click a video clip and choose another scene from the original. The
   existing Source in / Source out fields and the existing preview show a
   temporary full-duration view. That view is not saved.
2. Add scene inserts one new `studio_clips` row immediately after the clicked
   clip. It reuses the same path, identity, and library id. Effects start
   empty, speed is 1, and the outgoing transition is a hard cut.
3. The clicked row keeps its trim, effects, speed, and outgoing transition.
   No file is copied and no new library row is created.
4. The add is one session Undo step. Cancel, Escape, and a rejected range
   write nothing. Redo puts the same row back.
5. Photos, title cards, an offline file, and an unknown catalog duration do
   not invent a range.

## Alternatives considered

1. **Add a default span immediately, then trim it with the normal fields** —
   reuses save-on-change, but changes the Story before a range is chosen.
2. **Type the range without extending preview** — does not show footage
   outside the current in/out.
3. **A second source monitor or filmstrip** — a new editor, outside this slice.

## Consequences

- Positive: Another moment from the same file can be added without disturbing
  the take that is already edited.
- Negative / trade-offs: While the draft is open, the preview is not the Story
  clock. The clicked clip's outgoing transition plays into the new clip.
- Out of scope: dragging clip edges, scene detection, multicam, and copying
  the existing grade onto the new moment.
- A later slice keeps one Original row per cut video in the Story browser.
  The same preview opens that full recording. Dragging it onto the Story, or
  Add scene, inserts one clip. That row stays after the Story clips are
  removed and after a restart. It is still one preview, not a second monitor.
