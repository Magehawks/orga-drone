# Studio Collage Composer – Discovery

Status: **architecture locked in ADR 0038** (Proposed until merged).  
Related: ADR 0004, 0008, 0009, 0018, 0028; Image Composer #453 / PR #454
(`photo_combine.py` — **out of scope to modify**).

## Problem

Users want multi-photo / multi-video layouts inside Studio Stories (multi-cam,
grids, mixed still+video) with preview, timeline duration, undo, save/reopen,
and PNG/JPEG or MP4 export. Today Studio renders one media item per Story time.

## Current landscape (as of `origin/develop` @ ADR write-up)

| Area | Finding |
|------|---------|
| Clip model | `item_kind` ∈ {`media`,`title_card`}; Title Cards are the template for generated items |
| Preview | One active media + optional A/B crossfade; pause stills via FFmpeg |
| Export | Per-clip segment chain → concat/xfade; **no** multi-source frame layout |
| Image Composer | Photo detail only; horizontal/vertical native stack; no Studio/timeline/video |
| External files | Music/SFX via ADR 0008 desktop picker + server path |
| Still export from Studio | Not available (Studio export is MP4) |
| Grades | Per media clip in `effect_settings` / canonical `grade`; Title Cards have none |

## Decision summary

See [ADR 0038](../decisions/0038-studio-collage-composer.md):

- New `item_kind='collage'` + `collage_spec` JSON + duration column.
- Recursive split tree shared by UI, still compositor, and FFmpeg `xstack`.
- Library + desktop sources; collage audio muted; Story clock owns time.
- Preview honesty via composed stills; play uses capped muted elements or
  still fallback.
- Keep `photo_combine` unchanged.

## Shared layout API (implementation target)

Pure module `studio_collage.py` (name may include `layout` helpers):

- `normalize_spec` / `validate_spec`
- `preset_spec(name) → Spec`
- `split_leaf` / `remove_leaf` / `set_ratio`
- `resolve_rects(spec, width, height) → {leaf_id: (x,y,w,h)}`
- `leaf_source_window(...)` for fit/fill/zoom/pan
- Resource admission (max leaves, max edge, working set)

JS mirror under `static/js/studio/collage-layout.js` for divider drag and
preview placement (same math, tested).

## Work packages → issues

| # | Package | Deliverable | Depends |
|---|---------|-------------|---------|
| 1 | Model + persistence | Schema, normalize, CRUD API, history columns, tests | ADR |
| 2 | UI + layout editor | Collage add entry, inspector, presets, split/divider | 1 |
| 3 | Media + leaf edit | Library picker, desktop picker, fit/fill/zoom/pan, missing media | 2 |
| 4 | Still preview + image export | Composed preview-frame; PNG/JPEG export (`studio_collage_still.py`, `/api/studio/{id}/collage/preview|export`) | 1, 3 |
| 5 | Video play sync | Multi muted video/image cells on Story clock; last-frame hold | 2, 3 |
| 6 | MP4 export | Encoder collage segment via existing pipeline | 1, 4 |
| 7 | Integration + polish | DE/EN, limits, journey smoke, packaged E2E where feasible | 4–6 |

## Explicit non-goals (first complete slice)

- Changing or replacing Image Composer.
- Second Story timeline inside the collage editor.
- New encoding stack or cloud services.
- Unguided simultaneous multi-leaf audio mix.
- Full realtime graded LUT on every playing cell (ADR 0028).
- Merge to `main` / public EXE / release.

## Risks

| Risk | Mitigation |
|------|------------|
| Preview ≠ export geometry | Single rect solver + parity tests |
| Decoder / RAM blow-up | Max leaf / concurrent video caps; still fallback |
| Schema CHECK rebuild | Same table-rebuild pattern as Title Cards |
| Touching `studio.js` / encoder | One package per PR; avoid parallel edits |
| External path security | ADR 0008 validation; no client path as SoT |

## UI entry (target)

Studio editor → left browser / toolbar action **Collage** → creates a collage
Story item → inspector **Collage** panel for layout and media. Timeline shows
the collage like a Title Card/photo with editable duration.
