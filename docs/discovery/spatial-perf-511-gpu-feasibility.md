# GPU spatial grading feasibility (#511 / #506)

Date: 2026-11-19  
Tree: `develop` @ `cb068da` (after #515–#517)

## Question

Can the existing WebGL managed/LUT path accelerate **spatial** photo grades
(brush / radial / linear masks) enough to justify an incremental GPU
implementation?

## What exists today

| Path | Spatial masks | Notes |
|---|---|---|
| WebGL LUT / managed bake-approx (`studio-lut-webgl.js`) | **No** | Pointwise / global cube; labeled exact when float path allows |
| CPU `apply_managed_grade_image` + mask raster (#508) | **Yes** | Exact reference; brush bbox raster |
| Process-isolated photo bake (#509) | **Yes** | Keeps HTTP/UI responsive under GIL load |
| Preview edge clamp 512 (#508) | **Yes** | Interactive viewport budget |

`managedGradeNeedsCpuPreviewStill` already forces CPU stills when selections are
spatial — WebGL is intentionally skipped for that case.

## Spike conclusion (reject for 2.4.0 spatial)

Implementing GPU spatial grades would require a **new** mask-texture + fragment
pipeline (stroke tessellation or pre-raster upload, feather in shader, invert /
multi-selection bind), plus CPU↔GPU parity harnesses. That is a second grading
engine surface, not a reuse of the current WebGL LUT adapter.

## Numbers that gate the reject (from #507 / #509 / #513)

| Evidence | Value |
|---|---|
| Neon Relic BEFORE bake @1125×1984 (#507) | **463.4 s** (~0.0048 MPix/s) |
| Dominant cost (#507 cProfile) | ~80% mask / brush coverage, nested Python |
| Preview budget after #508 | max edge **512** + mask raster cache |
| HTTP during 256² bake inline (#513) | p95 **~314 ms** |
| HTTP during 256² bake process worker (#509/#513) | p95 **~3 ms** |

A WebGL pointwise LUT path cannot absorb the brush/mask hotspot without a new
mask-texture + feather pipeline. Building that second engine for a 2.4.0
incremental win is not justified while:

1. Interactive editing already has a ≤512 CPU preview path (#508).
2. Full-res export correctness stays on the CPU reference.
3. Process isolation already restores HTTP/cancel responsiveness (#509).

### Correctness tolerances (mask / feather) — N/A for reject

No GPU spatial path is implemented, so there is no GPU↔CPU mask/feather parity
budget to set. Existing CPU reference + preview raster remain the contract.
If a future ADR proposes GPU spatial grades, it must define mask/feather
tolerances before merge.

**Decision:** Do **not** implement GPU spatial grading in this initiative.
Document rejection with the numbers above; keep CPU reference + process
isolation + viewport preview. Revisit only with a dedicated ADR if interactive
full-res spatial preview becomes a product requirement.

## Acceptance for #511

- [x] Feasibility recorded with explicit reject **and numbers**
- [x] No new renderer
- [x] No weakening of CPU fallback semantics
- [x] Mask/feather GPU tolerances marked N/A (no GPU path)
