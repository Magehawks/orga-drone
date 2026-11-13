# Color Workspace execution checkpoint

Updated: 2026-11-13. Integration branch `develop` tip
`99424fb` (after #429 persistence hardening).

A merged PR is not full issue acceptance. This file records shipped slices vs
remaining gaps after the PO complete-Color-Workspace directive.

## Merged develop PRs (this cycle)

| PR | Merge SHA | Slice |
|---|---|---|
| #412 | (Phase 1 packaged E2E) | Packaged Windows WebView2 journey extensions |
| #413 | (on develop) | #351 write-enable + safeguards |
| #414 | (on develop) | Kelvin/tint mappings |
| #417 | `611711f…` | Managed primaries UI |
| #418 | `0ec002b…` | Managed lut bake preview/export |
| #420 | `c7e1859…` | Wheels + managed HSL UI |
| #419 | `11bd8ea…` | Seven curve families UI |
| #421 | `c3eabdc…` | Mask/qualifier apply + UI; photo spatial; video fail-closed |
| #422 | `8f4cbc8…` | Creative LUT resolve/bake/UI |
| #425 | `c33f59d…` | Spatial managed video export |
| #426 | `ddbf018…` | Eyedropper + interactive brush tools |
| #427 | `e223528…` | WebGL managed bake-approx adapter (#360) |
| #428 | `02418f7…` | Live managed-preview scopes (#362/#366) |
| #429 | `99424fb…` | Canonical grade opaque merge + undo remint |

## Feature matrix (honest)

| Capability | Status | Evidence |
|---|---|---|
| Canonical grade + writes after safeguards | Available now (hardening in flight) | #413; opaque-merge + transactional PUT hardening |
| Primaries / curves / wheels / HSL / LUT | Available now | UI + bake |
| Spatial masks/qualifiers | Available now | Photo + video CPU export; interactive viewer tools |
| Eyedropper | Available now | Sample API + Accept → qualifier |
| Preview/export pointwise bake | Available now | lut3d bake |
| Spatial video export | Available now | CPU CFR materialize + remux |
| GPU WebGL managed adapter (#360) | Available now (approx) | `webgl-bake-approx`, `exact:false`; spatial → CPU |
| Live scopes (#362/#366) | Available now (managed) | Tagged preview-frame producer; packaged latency NOT_RUN |
| Shared Control API grade actions (#363) | Partial | Commands module exists; UI still PUTs full grade |
| Managed-SDR API numerical parity | PASS (unit) | `tests/test_managed_sdr_parity_journey.py` |
| Packaged managed-SDR WebView2 journey | NOT_RUN | Dedicated CDP/packaged binary still pending |
| Full #365 acceptance matrix | OPEN | Packaged evidence + remaining AC comments |

## Open Color Workspace issues

| Issue | After this cycle | Remaining |
|---|---|---|
| #351 | Writes + opaque merge / remint hardening | Separate DB/min-reader; full failure-injection |
| #352–#357 | Feature slices merged | Packaged AC comments / PO close |
| #358 | Animation clocks | Still unsupported (fail-closed) |
| #359 | FFmpeg/CPU adapters | Playback-proxy gaps remain |
| #360 | GPU bake-approx | Exact tetrahedral / Windows budgets NOT_RUN |
| #361 | Creative/Pro workspace | Serial step editor incomplete |
| #362/#366 | Live managed tap | Packaged WebView2 latency/memory NOT_RUN |
| #363 | Shared actions/bridge | Wire Control API to grade commands |
| #364/#365 | Parity harness / final matrix | Open |

## Exact next tasks

1. Merge persistence hardening (opaque root preserve, transactional grade PUT, undo remint).
2. Shared Control API grade actions (#363) + remaining #358/#361/#364/#365.
3. Packaged managed-SDR Color Workspace journey with numerical parity.
4. Issue cleanup comments with evidence; close only when AC fully met.
5. Do not merge to `main` or publish a release.
