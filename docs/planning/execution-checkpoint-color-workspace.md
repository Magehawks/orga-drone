# Color Workspace execution checkpoint

Updated: 2026-11-13. Integration branch `develop` tip
`c47b9b3` (after #431 animation clocks, #432 imageio-ffmpeg guard,
#433 shared grade commands).

A merged PR is not full issue acceptance. This file records shipped slices vs
remaining gaps after the PO complete-Color-Workspace directive.

## Merged develop PRs (this cycle)

| PR | Merge SHA | Slice |
|---|---|---|
| #412 | (Phase 1 packaged E2E) | Packaged Windows WebView2 journey extensions |
| #413–#422 | (on develop) | Managed color feature slices |
| #425 | `c33f59d…` | Spatial managed video export |
| #426 | `ddbf018…` | Eyedropper + interactive brush tools |
| #427 | `e223528…` | WebGL managed bake-approx adapter (#360) |
| #428 | `02418f7…` | Live managed-preview scopes (#362/#366) |
| #429 | `99424fb…` | Canonical grade opaque merge + undo remint |
| #430 | `057c1df…` | Managed-SDR API parity journey |
| #431 | `2d788a1…` | #358 canonical animation clocks |
| #432 | `f7bfb13…` | Warn on stale imageio-ffmpeg <0.8.0 |
| #433 | `c47b9b3…` | #363 shared grade command bridge |

## Feature matrix (honest)

| Capability | Status | Evidence |
|---|---|---|
| Canonical grade + persistence | Available now | #413/#429; #351 closed |
| Primaries / curves / wheels / HSL / LUT | Available now | UI + bake |
| Spatial masks/qualifiers | Available now | Photo + video CPU export |
| Eyedropper / brush | Available now | #426 |
| Animation clocks (#358) | Available now (partial) | Source-local preview/export; story-local plan + fail-closed full-source bake; client `story_s` pending |
| GPU WebGL managed adapter (#360) | Available now (tetrahedral) | `webgl-bake-tetrahedral`, `exact:false` (RGBA8); packaged budgets NOT_RUN |
| Live scopes (#362/#366) | Available now (managed) | Tagged preview-frame; packaged latency NOT_RUN |
| Shared Control API grade actions (#363) | Available now (slice) | `clip.grade.command` + HTTP `/grade/command`; editor PUT migration partial |
| Managed-SDR API journey | PASS (unit) | #430; packaged WebView2 NOT_RUN |
| Full #365 acceptance matrix | OPEN | Remaining AC + packaged deferred by PO |

## Regression investigation (3 suite failures)

| Case | On develop tip | Root cause | Fix |
|---|---|---|---|
| Odd-height stills (2 params) | Reproduced under 0.6.0; PASS on 0.8.1 | Env drift vs `imageio-ffmpeg>=0.8.0` | Upgrade + #432 warning |
| Neutral color scenario mean | Same; PASS after upgrade | Cascaded from broken ffmpeg stills | Same |

## Open Color Workspace issues (honest remaining)

| Issue | After this cycle | Remaining |
|---|---|---|
| #351 | CLOSED | — |
| #352–#357 | Feature slices merged | Packaged AC / PO close comments where AC require it |
| #358 | #431 merged | Client `story_s`; story-local export beyond fail-closed; full ClipTimingInputs wiring |
| #360 | Tetrahedral sampling shipped | Float exact parity blocked by RGBA8; Windows budgets NOT_RUN |
| #361 | Serial workspace incomplete | Step editor UX |
| #362/#366 | Live tap shipped | Packaged latency/memory NOT_RUN |
| #363 | #433 merged | Preview tokens; migrate managed editors from full PUT to `postGradeCommand` where applicable |
| #364/#365 | OPEN | Strict matrix + packaged deferred |

## Explicitly deferred by PO (this sprint)

- Windows EXE / PyInstaller / packaged WebView2 E2E
- Installer / RC / merge to `main` / Steam/itch

Record packaged-only evidence as `NOT_RUN — deferred by PO`.

## Exact next tasks

1. Continue #363 editor migration + preview tokens; #364/#365 matrix.
2. Issue evidence comments; close only when AC fully met.
3. Do not build packaged Windows EXE in this sprint.
