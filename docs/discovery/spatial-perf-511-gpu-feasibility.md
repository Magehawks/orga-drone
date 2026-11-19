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

Measured CPU path after #508/#509:

- Neon Relic–class full-res bake remains minutes on pure Python (baseline #507),
  but no longer freezes HTTP when isolated in a worker.
- Interactive preview at ≤512 edge + mask raster is the practical editing path.
- Export correctness stays on the CPU reference.

**Decision:** Do **not** implement GPU spatial grading in this initiative.
Document rejection with evidence; keep CPU reference + process isolation +
viewport preview. Revisit only with a dedicated ADR if interactive full-res
spatial preview becomes a product requirement.

## Acceptance for #511

- [x] Feasibility recorded with explicit reject
- [x] No new renderer
- [x] No weakening of CPU fallback semantics
