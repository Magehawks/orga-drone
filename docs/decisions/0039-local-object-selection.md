# ADR 0039: Local offline object selection (classical proposal)

- **Status:** Accepted
- **Date:** 2026-11-21
- **Deciders:** Product Owner authorization via initiative #535; engineering
  evaluation #539

## Context

Creators need a click→object proposal in Studio without cloud inference.
Neon Relic and similar photo fixtures require a refinable selection that maps
into the existing managed grade selection model. Packaging must stay local-first:
no required model download, no telemetry, core app usable offline.

Spike evidence (Neon Relic BEFORE vs TARGET chroma pseudo-GT):

| Method | Time | IoU |
|---|---|---|
| RGB flood-fill | ~0.10 s | ~0.23 |
| LAB-ish flood + morph + LCC | ~0.5 s | ~0.57 |

ONNX / MobileSAM-class models were considered for higher IoU but add large
binaries, license/redistribution review, GPU variance, and an optional download
path that conflicts with “works offline without extras” for the first ship.

## Decision

1. Ship a **classical** object proposal: chromatic-weighted flood fill on a
   downscaled source frame, light morphological close, largest component,
   polyline contour + Douglas–Peucker simplify into a closed UV polygon.
2. Persist accepted proposals as normal managed `polygon` selections
   (`upsert_selection`); no separate inference cache or cloud asset.
3. Do **not** add ONNX/SAM (or any required model) to the core package in this
   ADR. Optional model download remains a future ADR if classical+refine fails
   creative acceptance.
4. Label the feature honestly: local object **proposal**, not AI freistellung.
   Brush/polygon refine (Feature B) remain the precision path.

## Alternatives considered

1. **Required ONNX segmentation model** — better IoU potential; rejected for
   first ship due to size, license, packaging, and offline guarantees.
2. **Qualifier-only (color key)** — already exists; does not give a named
   geometric mask for canvas edit.
3. **Manual polygon only** — insufficient for initiative #535 Feature C.

## Consequences

- Positive: zero new heavyweight deps; works on CPU; integrates with mask list
  and on-canvas edit; cancellable request stays a single HTTP call.
- Trade-offs: proposal quality varies with lighting/texture; Neon Relic still
  needs refine for serrations/droplets; classical magenta IoU vs TARGET has a
  ceiling (~0.55–0.65) while leaf recall can exceed 0.90.
- Follow-up delivered in-tree: multi-seed union + connected expand (#550),
  sub-1s OpenCV path (#554), HTTP/JS regressions (#542), packaged masking UX
  harness (`packaging/e2e/studio_masking_ux.py`, #543). Revisit optional local
  model only with a new ADR.
