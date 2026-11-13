# Color Workspace execution checkpoint

Updated: 2026-11-13. Integration branch `develop` tip
`6950f72` (after #441–#443; GPU float precision + complex story timing).

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
| #436 | `28d1f3b…` | Client `story_s` + story-local export |
| #437 | `7e14ebe…` | Serial step editor + preview tokens |
| #438 | `f8382be…` | GPU tetrahedral sampling (#360) |
| #439 | `cb807a3…` | Node scopes latency/heap harness |
| #440 | `a60cbbc…` | `upsert_step_params` / selection commands |
| #441 | `a0d37c1…` | Creative Quick Look → managed primaries |
| #442 | `6950f72…` | GPU float precision / RGBA8 measured (#360) |
| #443 | `946ae13…` | Complex Story-local timing export (#358) |

## Feature matrix (honest)

| Capability | Status | Evidence |
|---|---|---|
| Canonical grade + persistence | Available now | #413/#429; #351 closed |
| Primaries / curves / wheels / HSL / LUT | Available now | UI + bake |
| Spatial masks/qualifiers | Available now | Photo + video CPU export |
| Eyedropper / brush | Available now | #426 |
| Animation clocks (#358) | Available now (bounded) | Client `story_s`; constant/trim/single-play ramp/repeats/forward-loop; fail-closed slow_span, loop+ramp, ramp+repeats; packaged NOT_RUN |
| GPU WebGL managed adapter (#360) | Available now (tetrahedral + float-gated) | `webgl-bake-tetrahedral`; RGBA32F → `exact:true`; RGBA16F/RGBA8 → `exact:false` + measured; packaged budgets NOT_RUN |
| Live scopes (#362/#366) | Available now (managed) | Tagged preview-frame; Node harness; packaged latency NOT_RUN |
| Shared Control API grade actions (#363) | Available now (unit) | Commands for enable/mix/reorder/params/selection/preset; preview tokens; PUT escape hatch; packaged E2E NOT_RUN |
| Creative Quick Look → managed primaries | Available now (unit) | `apply_preset` + studio.js managed path |
| Managed-SDR API journey | PASS (unit) | #430; packaged WebView2 NOT_RUN |
| Full #365 acceptance matrix | OPEN | Packaged rows deferred by PO |

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
| #358 | Bounded ClipTimingInputs export | Packaged NOT_RUN; fail-closed slow_span, loop+ramp, ramp+repeats |
| #360 | Float-gated RGBA32F exact + measured RGBA8/16F fallback | Packaged GPU budgets NOT_RUN |
| #361 | Step editor + `apply_preset` compile | Packaged keyboard/E2E NOT_RUN |
| #362/#366 | Live tap + Node accumulate harness | Packaged latency/memory NOT_RUN |
| #363 | Tokens + upsert_step_params/selection/preset | PUT escape hatch only; packaged E2E NOT_RUN |
| #364/#365 | OPEN | Strict matrix + packaged deferred |

## Explicitly deferred by PO (this sprint)

- Windows EXE / PyInstaller / packaged WebView2 E2E
- Installer / RC / merge to `main` / Steam/itch

Record packaged-only evidence as `NOT_RUN — deferred by PO`.

## Exact next tasks

1. PO decision to start the final packaged Windows verification phase (EXE / WebView2).
2. Packaged rows still NOT_RUN: WebView2 parity, scopes latency/memory, GPU budgets, ≥5 cold/warm samples.
3. Do not build packaged Windows EXE until PO starts that phase.
4. Remaining technical fail-closed (document, not silent PASS): story-local `slow_span`, `forward_loop`+ramp, ramp+repeats; GPU exact only on RGBA32F.
