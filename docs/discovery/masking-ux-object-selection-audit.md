# Masking UX, precision editing & local object selection — audit

Date: 2026-11-20  
Baseline: `develop` @ `12ad437` (PR #534 precision-mask follow-up)  
Initiative: Mask list · on-canvas geometry · local object selection · Neon Relic

This document states **what already ships** versus **what this initiative must add**.
It is discovery only; shipping claims remain gated by PRODUCT_VISION / ROADMAP
updates in implementation PRs.

## Authoritative selection model (reuse)

Managed Color Workspace grades already own selections:

| Piece | Location | Notes |
|---|---|---|
| Grade envelope | `grade.selections[]` + `grade.steps[].selection_id` | Stable IDs; invert; mask + qualifier |
| Mask leaves | linear / radial / brush / polygon | `studio_managed_masks.py`, `studio_managed_selection.py` |
| Rasterizer | `selection-raster-v2` | Stamp brush + polygon even-odd + feather |
| Apply / cache | `studio_managed_apply.py` | Spatial bake, parallel strips (#534), workers |
| Commands | `upsert_selection`, bind/clear via grade commands | Undo/redo via grade revision |
| Persistence | Clip `effect_settings` / grade JSON | Save/reopen; session undo only |

**Invariant for this initiative:** one authoritative selection representation.
Do not invent a second mask engine, layer stack, or AI-only mask type that
cannot bind to managed steps.

## Feature A — Mask list in Inspector

### Available now

- Compact binding summary (`data-managed-selection-summary`) listing selection
  IDs → bound step types, invert flag, active binding highlight.
- Selection create/apply/clear, shape picker, feather, invert, bind-to-step.
- Draw brush / polygon / eyedropper qualifier tools in the Managed Color panel.

### Missing

- Dedicated **Masks / Masken** section with human-readable names (not raw IDs).
- Click-to-activate mask as first-class Inspector item.
- Per-mask rename / edit / delete / overlay visibility controls.
- Semi-transparent region overlay when a mask is selected (preview-only; never
  in export).
- Schema field for display `name` (and optional overlay prefs) with compatible
  round-trip.
- Keyboard accessibility for the list; clean state when no mask selected /
  clip switch.

## Feature B — Direct on-canvas geometry

### Available now

- Polygon draw (click points, Enter/double-click close, Esc cancel).
- **Vertex drag** for an existing closed polygon while polygon tool active
  (#533 / #534) via `hitTestPolygonVertex` + `onPolygonEdited`.
- **Add vertex on edge click**, **Alt/Meta+click remove** (keeps ≥3 points), and
  **whole-mask interior move** (#538) via `hitTestPolygonEdge` /
  `pointInPolygon` + `onPolygonEdited`. Selecting a polygon in the Inspector
  arms polygon edit mode so handles work without re-arming Draw.
- Esc cancels an in-progress vertex/move edit and restores the last committed
  contour overlay.
- Brush stroke add (paint path); UV mapping via `pointerToSourceUv`.
- Linear / radial leaf params via form fields (not full on-canvas handles).
- Rectangular **privacy** masks (blur/pixelate) — separate from color selections.
- Overlay hide without disabling grade (#537).

### Missing / later polish

- Dedicated pan-vs-edit cursor affordances.
- Brush: optional whole-selection move.
- Linear/radial: improve geometric controls without regressing privacy masks.

## Feature C — Local object-aware selection

### Available now

- Manual brush / polygon / qualifier paths only.
- PRODUCT_VISION explicitly marks AI / freeform sky masks as **Later** today;
  this initiative is PO-authorized scope to ship a **local offline** object
  proposal path and must update vision labels when implemented.

### Missing (entire workstream)

- Technology evaluation (classical vs ONNX/local model) with Neon Relic and
  other fixtures.
- Offline inference; optional transparent model download; core app usable
  without model.
- License / redistribution ADR.
- Click-object → proposal overlay → accept/discard → named selection in list.
- Map downscaled inference → full-res geometry; refine with brush/polygon.
- Persist accepted mask without re-inference; cancellable non-blocking job.
- Dense mask asset storage if polygon approximation is insufficient (compatible
  extension + cleanup rules).

## Neon Relic creative context

Evidence lives under worktree acceptance paths (e.g.
`orga-drone-wt/precision-mask-develop/acceptance-evidence/neon-relic/`), not
in the main repo tree.

Prior creative refine (API/polygon) achieved high TARGET-chroma coverage
(~99.9%) but still showed:

- Hot pink / residual cyan droplet casts vs TARGET deep magenta.
- Manual polygon workflow friction (no object click, weak Inspector list).
- EXE spatial export requires `ORGA_SPATIAL_APPLY_WORKERS=1` to avoid nested
  ProcessPool hang on packaged Windows.

Final acceptance for this initiative must use the **new** mask list + canvas
edit + local object selection path inside the packaged app.

## Performance baseline (historical, #534 era)

| Path | Observation |
|---|---|
| Warm brush preview | ~0.55 s |
| Brush full-res export | ~8.3 s |
| Polygon + invert export | ~16 s (varies; dense grades slower) |

Preserve parallel apply gains; re-measure after each workstream.

## Proposed child workstreams

1. Schema/compat: optional `name` (+ overlay meta) on selections; migration.
2. Inspector mask list + active-mask state + overlay (preview-only).
3. Canvas contour/handles; add/remove vertex; whole-mask move.
4. Local segmentation evaluation ADR + chosen runtime spike.
5. Segmentation integration + persistence + refine.
6. API/tests + Windows packaged UX acceptance.
7. Neon Relic creative acceptance on the integrated path.

## Explicit non-goals (unchanged)

Photoshop layer stack, blend modes, nesting, timeline-wide masks, motion
tracking, video object segmentation, cloud inference, second grading pipeline.
