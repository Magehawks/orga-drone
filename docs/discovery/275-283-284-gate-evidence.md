# Permanent regression gates evidence (#275 / #283 / #284)

Date: 2026-11-24 (UTC)  
Branch pin: `feat/permanent-regression-gates-275-283-284` @ develop base `ed22c9d`

## Suites run (actual)

| Command | Result |
| --- | --- |
| `pytest tests/test_regression_gates.py -q` | **7 passed** |
| Curated gate pytest (control/history/transition/collage/HSL/mask/intent/local_http/packaged_e2e/journey + inventory) | **156 passed**, 14 warnings |
| `npm run test:js -- tests/js/scopes_accumulate.test.js tests/js/control_bridge.test.js tests/js/scopes_nonpackaged_perf.test.js` | **28 passed** |
| `ruff check tests/test_regression_gates.py scripts/regression_mutation_check.py` | **All checks passed** |
| `python scripts/regression_mutation_check.py` | **9/9 caught**, all reverted (`all_caught: true`) |
| Packaged Windows `windows_e2e.py` fresh EXE run | **NOT_RUN** (CI job is main-only; no dated `evidence.json` claimed here) |

## Mutation results

| Case | Target | Outcome | Revert |
| --- | --- | --- | --- |
| `canvas_coordinate_mapping` | `src/orga_drone/studio_mask.py` | exit 1 → caught | reverted |
| `hsl_export` | `src/orga_drone/studio_hsl.py` | exit 1 → caught | reverted |
| `clip_targeting` | `src/orga_drone/control.py` | exit 1 → caught | reverted |
| `persistence` | `src/orga_drone/studio_history.py` | exit 1 → caught | reverted |
| `undo_redo` | `src/orga_drone/studio_history.py` | exit 1 → caught | reverted |
| `transition_timing` | `src/orga_drone/studio_transition.py` | exit 1 → caught | reverted |
| `collage_export_cleanup` | `src/orga_drone/studio_collage_export.py` | exit 1 → caught | reverted |
| `scope_accumulation` | `src/orga_drone/static/js/studio/scopes/accumulate.js` | exit 1 → caught | reverted |
| `authorization_bypass` | `src/orga_drone/local_http.py` | exit 1 → caught | reverted |

Machine-readable: `docs/discovery/275-283-284-mutation-results.json`.

## Performance baseline highlights

- Scopes non-packaged Node harness: 28 JS tests including cold/warm samples and evidence schema check against `docs/planning/362-scopes-node-perf.json`.
- Packaged WebView2 scopes latency/memory remain **NOT_RUN**.

## Close recommendations (honest)

| Issue | Close? | Reason |
| --- | --- | --- |
| #275 | **Not yet** | Matrix, mutation integrity, Control API wrong-clip/stale coverage, and CI inventory are in place; fresh packaged WebView2 evidence and external MCP adapter CI link remain open. |
| #283 | **Not yet** | Fixture manifest + synthetic defaults shipped; optional real DJI/Potensic slots are `NOT_SHIPPED` / `NOT_FABRICATED`; no dated real-footage Windows gate. |
| #284 | **Not yet** | Integration/PR-gate documentation and additive CI job exist; RC Windows EXE validation and sequential merge process still require human PO sessions and main admission. |

## Remaining blockers

1. Fresh packaged WebView2 `evidence.json` after build (main CI or local acceptance).
2. Privacy-safe local real-footage paths from PO (never commit private media).
3. External `orga-drone-mcp` contract results to link (not duplicated here).
4. Parallel workstream suites to wire on merge (Masking, Color Workspace, Scopes, Collage, Playback, Assistant).
5. Branch-protection required-check changes need explicit PO approval (none applied by this PR).
