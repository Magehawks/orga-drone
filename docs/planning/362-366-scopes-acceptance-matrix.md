# Color Workspace scopes / parity / integration gates (#362, #364, #365, #366)

Pinned `origin/develop`: `572d6e6` (2026-11-24 acceptance PR).
Status labels: **PASS** | **FAIL** | **NOT_RUN** | **BLOCKED**.

This matrix is the acceptance inventory for the scopes + integration gate PR.
It does **not** declare full Color Workspace (#365) accepted while packaged EXE
rows remain incomplete.

Strict thresholds unchanged: managed/legacy swatch RGB **≤ 3.0**; detail,
temporal and performance gates stay separate. Rejected #320 experiments remain
FAIL/BLOCKED evidence.

## #362 Scopes UI

| AC | Verdict | Evidence |
|---|---|---|
| Four scopes: histogram / waveform / parade / vectorscope | PASS | `studio/scopes/*`, `tests/js/scopes_*.test.js`, WebView2 E2E |
| 256-bin histogram; waveform/parade axes; BT.709 vectorscope | PASS | `accumulate.js` + regression contract |
| Tap metadata / stale frames cannot show as current | PASS | `scope-frame.js`, panel sync, E2E clip switch |
| Synthetic fixtures disclosed; downsampling disclosed | PASS | fixture toggle + `sampleFactor` |
| Scope toggles never alter saved grade/export | PASS | E2E + `test_scopes_integration_gate.py` |
| Focused unit/integration evidence | PASS | Node + pytest gates below |
| Local CDP live journey + screenshots | PASS | docs/planning/362-scopes-live-cdp.json |
| Packaged EXE WebView2 latency/memory | FAIL (operators PASS; scopes harness) | `docs/planning/color-scopes-packaged-e2e-evidence.json` |
| Independent review / PO merge | NOT_RUN | Requested on PR; human decision |

## #366 Scope pixel tap + reference accumulation

| AC | Verdict | Evidence |
|---|---|---|
| ScopeFrameV1 immutable + identity fields | PASS | `scope-frame.js` |
| Clip post-grade / pre-frame tap via managed preview-frame | PASS | `preview-tap.js` (no second renderer) |
| Exact histogram / waveform / parade / vectorscope vs fixtures | PASS | `scopes_regression_contract.test.js` |
| Alpha weighting + legal-range expand once | PASS | regression contract |
| Deterministic subsampling separated from full-res reference | PASS | `sampleFactor` once in accumulate |
| Cancellation / stale generation | PASS | producer destroy test |
| Render latency/memory impact measured | PASS (source-app) | Node harness + WebView2 CDP samples |
| Packaged EXE impact | PARTIAL | Operators packaged PASS; scopes full journey FAIL |
| Project-composite tap | NOT_RUN | Out of this slice; remains labeled-only |

## #364 Independent fixtures / harness

| AC | Verdict | Evidence |
|---|---|---|
| Independent synthetic fixtures + CPU reference | PASS | fixtures + Python luma peak reference |
| #320 ≤3.0 unchanged; detail/temporal/perf separate | PASS | matrix policy + existing parity tests |
| ≥5 cold/warm p50/p95 + memory samples | PASS (source-level) | Node JSON + WebView2 CDP latency JSON |
| Packaged EXE matrix | PARTIAL | Operators packaged EN+DE; scopes `--exe` wired, journey blocked |
| Wrong bins / stale frames fail CI | PASS | mutation proof in `test_scopes_integration_gate.py` |

## #365 Complete Color Workspace admission

| AC | Verdict | Evidence |
|---|---|---|
| Feature controls/operators mapped | PASS (prior PRs) | See main acceptance matrix |
| Scopes + tap gates | PASS (source) | This PR |
| Strict numerical preview/export parity (API) | PASS | `test_managed_sdr_parity_journey.py` |
| Packaged WebView2 parity / EXE E2E | PARTIAL | Operators packaged PASS; scopes packaged FAIL (documented) |
| Full workspace accepted | **NOT declared** | Packaged gates incomplete |

## Shared renderer ownership

| Path | Owner for this PR | Notes |
|---|---|---|
| `static/js/studio/scopes/**` | Scopes agent (#362/#366) | Additive |
| `static/js/studio.js` (scopes mount only) | Scopes agent | `getView: currentScopeView` + `__orgaColorScopes` hook |
| Preview-frame / grade / export pipelines | Color Workspace | **Not modified** for grade/export math |
| Masking modules | Masking workstream | Untouched |

## Commands

```bash
node --test tests/js/scopes_*.test.js
pytest tests/test_scopes_integration_gate.py tests/test_managed_sdr_parity_journey.py tests/test_color_workspace_acceptance_matrix.py -q
python packaging/e2e/studio_color_scopes.py --out <out>            # source-app
python packaging/e2e/studio_color_scopes.py --exe <orga-drone.exe> --out <out>
python packaging/e2e/studio_color_workspace_operators.py --exe <orga-drone.exe> --out <out> --locale de
```

## Measured source-app CDP latency (this PR)

From `docs/planning/362-scopes-webview2-cdp-latency.json` (not packaged EXE):

- cold n=5: p50=202.0 ms, p95=216.4 ms
- warm n=5: p50=184.5 ms, p95=205.0 ms
- panel accumulate lastProcessMs ≈ 24.3 ms; droppedFrames=0
- heap_delta_samples recorded (Chromium `performance.memory`); packaged EXE budgets remain NOT_RUN

