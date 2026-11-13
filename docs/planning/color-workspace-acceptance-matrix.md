# Color Workspace acceptance matrix (#364 / #365)

Pinned `develop` tip at authoring: `757976c` (2026-11-13).
Status labels: **PASS** | **FAIL** | **NOT_RUN** | **BLOCKED**.

A passing API/unit test is **not** packaged Windows UI parity.
Packaged WebView2 / EXE rows are **NOT_RUN — deferred by PO** for this sprint.

Strict thresholds unchanged: managed/legacy swatch RGB **≤ 3.0**; detail-retention
and stopped #320 precision experiments are not weakened.

## 1. Managed color operations

| Row | Verdict | Evidence |
|---|---|---|
| Primaries-v1 | PASS | #417/#414; `tests/test_studio_managed_*` |
| RGB / luma / hue-sat curves | PASS | #419; managed apply tests |
| Wheels-v1 + managed HSL | PASS | #420 |
| Creative LUT resolve/bake | PASS | #422 |
| Technical LUT metadata | PASS / reject | #352; non-null technical LUT typed reject until resolved asset |
| Serial step enable/mix/reorder | PASS | #433 `clip.grade.command` |
| Full serial step editor UX | PASS (slice) | enable/mix/reorder + Quick Look `apply_preset` → inspectable primaries |

## 2. LUTs, photo/video export

| Row | Verdict | Evidence |
|---|---|---|
| Pointwise bake preview/export | PASS | lut3d bake path |
| Spatial photo export | PASS | #421 |
| Spatial video export | PASS | #425 |
| Source-file integrity (no mutate) | PASS | product invariant + export tests |
| Legacy L320 ≤3.0 | BLOCKED / FAIL history | #320 remains FAIL/BLOCKED_PO; not relabeled |

## 3. Masks, qualifiers, tools

| Row | Verdict | Evidence |
|---|---|---|
| Linear/radial/brush masks | PASS | #421/#426 |
| Qualifiers + eyedropper | PASS | #426 |
| Interactive brush | PASS | #426 |

## 4. Animation clocks (#358)

| Row | Verdict | Evidence |
|---|---|---|
| Source-local mapping + trim | PASS | #431; `test_studio_grade_animation.py` |
| Story-local plan evaluation | PASS | unit |
| Story-local full-source bake (no anchor) | PASS (fail-closed) | explicit UNSUPPORTED |
| Story-local constant-speed single-play export | PASS | anchor + `_story_time_for_source_pts`; repeats/ramp/loop remain fail-closed |
| Speed/repeat/transition helpers | PASS | `studio_grade_clock` unit |
| Client `story_s` wiring | PASS | `preview-frame-url.js` + lut/scopes/compare |
| ClipTimingInputs full export wiring | NOT_RUN | remaining complex ramps/repeats |
| Packaged preview/export | NOT_RUN — deferred by PO | — |

## 5. Undo / persistence / migration

| Row | Verdict | Evidence |
|---|---|---|
| Opaque merge + transactional PUT | PASS | #429 |
| Undo remint | PASS | #429 |
| Shared grade commands | PASS | #433 |
| Save/reopen / clip switch | PASS (API) | grade route tests |
| Editor command migration (enable/mix/reorder) | PASS | `postGradeCommand` in step editor |
| Editor param body → `upsert_step_params` | PASS (unit) | primaries/wheels/HSL/curves/LUT/selection via commands + history group; PUT escape hatch |
| Async preview tokens | PASS (partial) | keyed store + fill/cache gating |

## 6. Preview / export numerical parity

| Row | Verdict | Evidence |
|---|---|---|
| Managed-SDR API journey + CPU delta | PASS | #430 `test_managed_sdr_parity_journey.py` |
| GPU bake-approx vs CPU | PASS (approx labeled) | #427 `exact:false` |
| GPU tetrahedral interpolation | PASS | #360 / #438 `lut-tetrahedral.js` + WebGL texelFetch |
| Exact GPU float parity | NOT_RUN | RGBA8 table storage; labeled `exact:false` / `rgba8-quantization` |
| Packaged WebView2 parity | NOT_RUN — deferred by PO | — |

## 7. Scopes (#362 / #366)

| Row | Verdict | Evidence |
|---|---|---|
| Histogram / waveform / parade / vectorscope | PASS (source) | #428 |
| ScopeFrameV1 + stale reject | PASS | unit/JS |
| Node synthetic accumulate latency + heap delta | PASS | `docs/planning/362-scopes-node-perf.json` (≥5 cold/warm; heapUsed/RSS; effective_pixels) |
| Packaged latency/memory | NOT_RUN — deferred by PO | — |

## 8. Performance / memory

| Row | Verdict | Evidence |
|---|---|---|
| Source-level export/spatial budgets | PASS (where tested) | spatial export limits |
| Node scopes cold/warm p50/p95 + heap | PASS | #362 Node harness (source-level only) |
| ≥5 cold/warm p50/p95 packaged samples | NOT_RUN — deferred by PO | #364 AC |
| WebView2 GPU budgets | NOT_RUN — deferred by PO | #360 |

## 9. Legacy regressions

| Row | Verdict | Evidence |
|---|---|---|
| Legacy color bar / saturation ramp | PASS | unchanged paths |
| Odd-height stills (#369) | PASS on ≥0.8.1 | #432 + `test_ffmpeg_odd_height.py` |
| Neutral color scenario | PASS after ffmpeg upgrade | env drift fixed |

## 10. Aggregator

Runnable inventory (does not claim packaged PASS):

```bash
pytest tests/test_studio_grade_animation.py \
  tests/test_studio_grade_bridge.py \
  tests/test_studio_grade_routes.py \
  tests/test_managed_sdr_parity_journey.py \
  tests/test_ffmpeg_odd_height.py \
  tests/test_studio_managed_apply.py \
  tests/test_studio_managed_spatial_export.py \
  -q
```

## Explicit deferred packaged Windows checks

1. Packaged WebView2 Color Workspace journey
2. Packaged numerical preview/export parity
3. Packaged scopes latency/memory
4. Packaged GPU budgets / exact tetrahedral
5. ≥5 cold/warm performance samples on packaged binary
6. Windows EXE / installer / RC (forbidden this sprint)

## Issue mapping

| Issue | Matrix implication |
|---|---|
| #358 | Client story_s + constant-speed story-local export shipped; complex timing NOT_RUN |
| #360 | Tetrahedral GPU sampling shipped; exact:false (RGBA8); packaged budgets NOT_RUN |
| #361 | Step editor + Quick Look `apply_preset` compile shipped; desktop E2E NOT_RUN — deferred by PO |
| #362/#366 | Node accumulate harness PASS; desktop latency/memory NOT_RUN — deferred by PO |
| #363 | Preview tokens + upsert_step_params/selection commands; PUT escape hatch only |
| #364/#365 | Open until this matrix is PO-accepted and remaining NOT_RUN rows resolved or waived |
