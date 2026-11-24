# ADR 0038: Studio Collage Composer

- **Status:** Accepted
- **Date:** 2026-11-15
- **Deciders:** Product Owner task (Studio Collage Composer); parent tracking via GitHub epic #456 / WP1 #457

## Context

Creators need to combine several photos and/or videos into one Story layout
(side-by-side multi-cam, photo grids, mixed still + video) inside the existing
Studio journey. The photo-workspace Image Composer (#453 / PR #454,
`photo_combine.py`) only stacks stills for a detail-tab PNG/JPEG export. It is
not a Story timeline item, has no video, no grades, and must stay unchanged.

Current Studio preview and export compose **one media clip per Story time**
(plus overlays/masks/map/HUD). Crossfade uses a temporary A/B pair of full
frames. There is no `xstack` / multi-source layout path. Preview has at most
two `<video>` elements. Simultaneous multi-video collage therefore needs an
explicit model, preview strategy, and export graph extension — without a second
timeline, a second encoder pipeline, or new dependencies.

Constraints from AGENTS / ADR 0004 / ADR 0008 / ADR 0009 / ADR 0028:

- Local-first; never modify source media.
- Generated Story items use `item_kind` + dedicated persistence (not
  `effect_settings` grade bags).
- External soundtrack/SFX paths are the pattern for non-library files.
- LUT honesty: pause/scrub stills are the graded source of truth; realtime
  multi-stream LUT playback is not required.

## Decision

### 1. Collage as a generated Story item

Add `item_kind='collage'` beside `media` and `title_card`.

- `media_path` / `identity_key` / `source_media_id` remain NULL on the collage
  row so rescan never marks the item missing.
- Persist a dedicated JSON column `collage_spec` (TEXT, NOT NULL for collage
  rows) plus `card_duration_s`-style duration via `collage_duration_s` (or reuse
  `card_duration_s` only if migration clarity suffers — prefer
  `collage_duration_s`).
- Do **not** store the layout SoT in `effect_settings`.
- Do **not** change or call `photo_combine` as the Studio engine.

Widen the `studio_clips` CHECK and history `_CLIP_COLUMNS` accordingly.
Existing projects stay valid (`item_kind='media'|'title_card'`).

### 2. Shared recursive split layout model

One immutable layout document drives editor geometry, pause/scrub stills, and
export:

```text
Node = Leaf | Split
Leaf  = { id, media?, fit, zoom, pan, start_offset_s, grade? }
Split = { id, dir: h|v, ratio: 0..1, a: Node, b: Node }
Spec  = { version: 1, aspect, gap_px, background, corner_radius_px?,
          duration_s, root: Node }
```

- Presets (1+1, 2+1, 1+2, 2×2, 3×2, 1+2+1, 3|2) are constructors over the same
  tree; custom layouts are split/merge edits on that tree.
- No arbitrary small grid cap; enforce resource limits (max leaves, max edge,
  working-set estimate) with clear errors.
- Fit = contain (letterbox inside cell); Fill = cover (crop). Zoom/pan reuse
  the framing window math spirit of ADR 0018, scoped to the cell rect.
- Same source may appear in multiple leaves. Missing library or external files
  mark the leaf unavailable without dropping the collage or project. Preview
  may show a placeholder. PNG, JPEG and Story MP4 export fail if an assigned
  source is unavailable or cannot be rendered. Intentionally empty cells can
  still export with their placeholder.
- Each export owns its frame cache and removes it with its staging files.
  At video EOF it holds the last decodable frame, even when the container
  has a longer audio stream or ffprobe is unavailable.
- Collage video export keeps the existing full-sequence JPEG staging path
  for composed frames. Before and during composed-frame (and source-sequence)
  writes it checks usable free space on the staging volume and aborts before
  a write would leave less than 1 GiB free
  (`COLLAGE_STAGING_FREE_SPACE_RESERVE_BYTES`). The localized error is:
  "Not enough temporary disk space. Free up space and try again." Staging
  directories and intermediate segment MP4s are removed; incomplete output is
  never published.
- Per video leaf, export may prefetch a bounded source-frame JPEG sequence
  (duration × export fps) with one FFmpeg process, then reuse those frames
  while composing. Leaves that need per-frame CPU materialize keep the
  previous seek path. Streaming composed frames into the encoder remains a
  separate follow-up (#487 / #489).
- Collage stills and Story exports containing collages publish completed files
  through an exclusive claim. If the destination does not support an atomic
  claim, the export fails without replacing any existing file.

### 3. Media sources

- **Library:** existing media ids / identity keys; picker reuse.
- **This computer:** desktop open dialog (ADR 0008 pattern). Persist absolute
  paths server-side; never auto-import into the library; client never displays
  raw paths as the primary UX.
- Video assignment waits for best-effort duration metadata in the existing
  worker pool, so the API can serve reads while probing. Apply the assignment
  to the latest collage state after the probe returns. If the target media
  or resolved source changed during the probe, ask the caller to retry. The
  ffprobe timeout remains eight seconds.
- Grades/LUTs: optional per-leaf grade envelope using the canonical Color
  Workspace contract already used for media clips. Apply once on the leaf
  render path (preview still + export); no double grading.

### 4. Timing and audio

- Collage occupies one Story position with `collage_duration_s` (clamped range,
  default aligned with photo duration conventions).
- All video leaves share the Story clock for that item. Optional per-leaf
  `start_offset_s` into the source. After a leaf’s video ends, hold the last
  frame for the remaining collage duration.
- Embedded video audio inside collage leaves is **muted**. Soundtrack / SFX
  lanes remain the only intentional audio (existing Studio audio).

### 5. Preview

- **Geometry:** CSS or canvas layout from the same rect solver as export.
- **Pause / scrub / honesty:** server-composed collage still (bounded edge)
  that runs each leaf through the existing preview-frame / grade path, then
  composites — same visual contract as export for static and graded content.
- **Play:** up to a hard cap of concurrent muted HTML `<video>` (or image)
  elements positioned to cell rects, driven by the existing Story playhead.
  Graded realtime LUT on every cell is **not** required (ADR 0028). When the
  cap would be exceeded, play falls back to periodic composed stills.
- No second Story timeline inside the collage editor.

### 6. Export

- Extend `FfmpegStudioEncoder` with a collage segment path: resolve leaf
  sources → per-leaf trim/grade/scale/crop into cell sizes → `xstack` /
  overlay onto the aspect canvas with gaps/background → encode as one
  Story segment. Reuse existing resolution profiles, job store, cancel, and
  publish.
- Photo-only collages may also export PNG/JPEG via a Studio still-export
  adapter that shares the same compositor (not `photo_combine`).
- A static collage on the timeline still exports as a timed MP4 segment
  (`-loop` / still hold) like photos and Title Cards.
- No new encoder dependency and no full intermediate re-encode of each leaf
  as a standalone MP4 when filter-graph composition is feasible.

### 7. UI entry

- Studio toolbar / browser actions: **Collage** / **Collage** (DE/EN).
- Selecting a collage clip opens an inspector panel (Title Card pattern), not
  a separate app or photo-detail dialog.
- Editor supports presets, split/merge, divider drag, library + desktop add,
  leaf fit/fill/zoom/pan, empty and missing-media states.

### 8. Work package order

1. Layout model + persistence + ADR acceptance tests  
2. Studio UI + layout editor  
3. Media pickers + leaf editing  
4. Photo still preview + PNG/JPEG export  
5. Multi-video play sync  
6. MP4 collage export  
7. Integration tests, limits, UX polish  

## Alternatives considered

1. **Extend `photo_combine` into Studio** — wrong product surface; no video,
   grades, or timeline; would fork a second engine.
2. **Collage as overlays on a blank media clip** — overlays are decorations
   tied to one host clip; poor fit for equal multi-cell layouts and duration.
3. **Pack SoT into `effect_settings` on a fake media row** — fights rescan,
   availability, and ADR 0009’s generated-item pattern.
4. **Separate collage table outside `studio_clips`** — splits Story order /
   playhead / undo from the clip list.
5. **Realtime N-stream graded WebGL** — rejected under ADR 0028 cost and
   honesty rules for the first complete slice.

## Consequences

- Positive: One layout document for editor, stills, and export; Title Card–
  like Story integration; Image Composer remains intact; soundtrack/SFX
  unchanged.
- Negative / trade-offs: Schema migration; encoder gains an `xstack` path;
  play preview may be ungraded or still-fallback under load; HTML/CSS play
  layout vs ffmpeg composite must stay locked by shared rect math and tests.
- Follow-up: optional per-leaf audio pick, animated cell transitions, and
  raising the concurrent video cap after evidence — out of this ADR’s first
  complete slice unless a later issue expands it.
