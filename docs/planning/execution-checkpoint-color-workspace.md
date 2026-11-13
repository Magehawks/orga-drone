# Color Workspace execution checkpoint

Updated: 2026-11-13. Integration branch `develop` tip after #438
tetrahedral GPU sampling.

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
| #438 | `f8382be…` | #360 tetrahedral WebGL LUT sampling |

## Feature matrix (honest)

| Capability | Status | Evidence |
|---|---|---|
| Canonical grade + persistence | Available now | #413/#429; #351 closed |
| Primaries / curves / wheels / HSL / LUT | Available now | UI + bake |
| Spatial masks/qualifiers | Available now | Photo + video CPU export |
| Eyedropper / brush | Available now | #426 |
| Animation clocks (#358) | Available now (partial) | Client `story_s`; story-local export with Story anchor (constant-speed single play); ramps/repeats/loop fail-closed |
| GPU WebGL managed adapter (#360) | Available now (tetrahedral) | `webgl-bake-tetrahedral`, `exact:false` (RGBA8); packaged budgets NOT_RUN |
| Live scopes (#362/#366) | Available now (managed) | Tagged preview-frame; packaged latency NOT_RUN |
| Shared Control API grade actions (#363) | Available now | Commands for enable/mix/reorder/params/selection; preview tokens; PUT escape hatch |
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
| #358 | #431 + story_s/export PR | Complex ClipTimingInputs export (ramp/repeat/loop) NOT_RUN |
| #360 | Tetrahedral sampling shipped | Float exact parity blocked by RGBA8; Windows budgets NOT_RUN |
| #361 | Step editor shipped | Packaged keyboard/E2E NOT_RUN; Creative preset compile depth |
| #362/#366 | Live tap shipped | Packaged latency/memory NOT_RUN |
| #363 | Tokens + upsert_step_params/selection | PUT escape hatch only; packaged E2E NOT_RUN |
| #364/#365 | OPEN | Strict matrix + packaged deferred |

## Explicitly deferred by PO (this sprint)

- Windows EXE / PyInstaller / packaged WebView2 E2E
- Installer / RC / merge to `main` / Steam/itch

Record packaged-only evidence as `NOT_RUN — deferred by PO`.

## Exact next tasks

1. Merge #436 story_s/export and #437 step editor + tokens.
2. Issue evidence comments; close only when AC fully met.
3. Do not build packaged Windows EXE in this sprint.
