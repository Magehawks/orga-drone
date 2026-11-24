# Permanent product regression and integration gates

Status: **living system** for issues #275, #283, and #284 on `develop`.
Authoring pin: `ed22c9d` (refresh the machine-readable matrix when journeys change).

This document is the Product Owner–facing gate book. Machine-readable inventory:

- `tests/fixtures/regression_coverage_matrix.json`
- `tests/fixtures/regression_fixture_manifest.json`
- `scripts/regression_mutation_check.py`
- Inventory tests: `tests/test_regression_gates.py`

Related: [`PR_E2E.md`](PR_E2E.md), [`architecture/STUDIO_ACTIONS.md`](architecture/STUDIO_ACTIONS.md),
[`discovery/275-shared-action-contract-matrix.md`](discovery/275-shared-action-contract-matrix.md),
[`CONTROL_API.md`](CONTROL_API.md), [`packaging/README.md`](../packaging/README.md).

## Five layers (binding)

| Layer | Proves | Does not prove |
| --- | --- | --- |
| 1 Unit | Domain logic, geometry, operators, validation, persistence, security | Rendered pixels, WebView2 UX |
| 2 Integration | Real API, DB, FFmpeg, export publication, shared actions | Packaged EXE assistant UX |
| 3 Browser / frontend regression | Fast UI module and route regressions against real frontend assets | Native Windows acceptance |
| 4 Native Windows E2E | Packaged EXE + WebView2, real mouse/keyboard, decoded output | Full real-drone creator matrix |
| 5 Visual / performance | Numerical fixtures, targeted screenshots, approved tolerances, latency/memory | Marketing “AI” quality claims |

**Hard rule:** Layer 3 must never be presented as Layer 4. Playwright is **not**
in this repository; browser-layer coverage is Node module tests plus FastAPI
journey smokes. A future Playwright slice stays optional and still is not MotW
or packaged EXE proof.

## Status vocabulary

`PASS` / `PARTIAL` / `GAP` / `NOT_RUN` / `PENDING_INTEGRATION` / `N_A`.

Do not mark `PASS` for `NOT_RUN`. Parallel workstreams land suites that this
gate **consumes**; do not replace working feature harnesses without justification.

## Creator journey coverage (summary)

See the JSON matrix for suite paths and artifact checks. Headline statuses on
this branch (synthetic fixtures; no fresh packaged evidence claimed):

| Journey | Unit | Integration | Browser | Native Win | Visual/Perf |
| --- | --- | --- | --- | --- | --- |
| Library import / browse / detail | PASS | PASS | PARTIAL | NOT_RUN | N_A |
| Metadata / telemetry / map | PASS | PASS | PARTIAL | NOT_RUN | N_A |
| Photo HSL / composer / export | PASS | PASS | PARTIAL | NOT_RUN | PARTIAL |
| Studio photo / masks / object select | PASS | PASS | PARTIAL | PENDING_INTEGRATION | PARTIAL |
| Color Workspace operators | PASS | PASS | PARTIAL | NOT_RUN | PARTIAL |
| Color scopes | PASS | PARTIAL | PASS | NOT_RUN | PARTIAL |
| Video editing / playback | PASS | PASS | PARTIAL | NOT_RUN | PARTIAL |
| Collage edit / export | PASS | PASS | PARTIAL | NOT_RUN | N_A |
| Transitions / effects | PASS | PASS | PARTIAL | NOT_RUN | PARTIAL |
| Persistence / Undo / Redo | PASS | PASS | PARTIAL | NOT_RUN | N_A |
| Control API / MCP / assistant | PASS | PASS | PARTIAL | NOT_RUN | N_A |
| Packaged Windows startup | PASS | PASS | N_A | NOT_RUN | N_A |

UI/UX protection (not a redesign) reuses existing DE/EN, disabled-state,
layout, and export cancel suites listed in the matrix.

## CI check inventory

### Required today on pull requests (develop and main)

These jobs already run in `.github/workflows/ci.yml` and are the deterministic
PR gate. Failed mandatory checks must block integration via the approved merge
process.

| Check name | Command surface |
| --- | --- |
| **Ruff, MyPy and unit tests** | `ruff check .`; scoped `mypy`; `pytest --ignore=tests/test_pr_journey_smoke.py` (includes gate inventory + domain/integration suites) |
| **JavaScript lint, format and tests** | `npm ci`; `npm run lint:js`; `npm run format:check`; `npm run test:js` |
| **App journey smoke** | `pytest tests/test_pr_journey_smoke.py` |
| **Regression gate inventory** (additive) | `pytest tests/test_regression_gates.py -q` |

### Main-only (promotion / admission)

| Check name | Notes |
| --- | --- |
| **Windows packaged E2E** | `.github/workflows/windows-e2e.yml` — builds EXE, WebView2 CDP, uploads evidence artifacts |
| **Main admission policy** | Validates evidence binding; does not configure branch protection itself |

### Product Owner approval required (settings)

This PR does **not** change GitHub branch protection. Any of the following need
explicit PO approval before enabling:

1. Changing required-check contexts on `develop` or `main`.
2. Requiring **Windows packaged E2E** on every develop PR (cost/latency).
3. Adding MotW/SmartScreen automation as a required check.

Optional (safe additive, still needs PO if made required): `workflow_dispatch`
on the Windows packaged E2E workflow for reproducible develop acceptance runs.

## Exact reproduction commands

From a clean checkout with `pip install -e ".[dev]"` and Node 22:

```bash
# Inventory + integrity of the gate book
pytest tests/test_regression_gates.py -q

# Deterministic PR surface (matches CI quality + journey)
ruff check .
mypy src packaging/itch_channel.py packaging/windows_third_party.py packaging/main_admission.py packaging/packaged_e2e.py packaging/e2e/windows_e2e.py
pytest --ignore=tests/test_pr_journey_smoke.py
pytest tests/test_pr_journey_smoke.py
npm ci
npm run check:js

# Curated creator-journey regressions (fast local iteration subset)
pytest tests/test_control_api.py tests/test_studio_history.py tests/test_studio_transition.py tests/test_studio_collage_export.py tests/test_photo_hsl_export_api.py tests/test_studio_mask.py tests/test_creator_journey.py tests/test_intent_matrix.py tests/test_local_http.py -q
npm run test:js -- tests/js/scopes_accumulate.test.js tests/js/control_bridge.test.js

# Mutation integrity (temporary; reverts all edits)
python scripts/regression_mutation_check.py

# Native Windows acceptance (NOT claimed PASS here without dated evidence.json)
# 1) Build onefolder zip per packaging/README.md
# 2) Extract and run:
# python packaging/e2e/windows_e2e.py --local --exe <extracted>/orga-drone.exe \
#   --output-dir <out> --ffmpeg <ffmpeg.exe> ...
```

## Fixtures (#283)

`tests/fixtures/regression_fixture_manifest.json` pins synthetic defaults and
optional real DJI/Potensic slots. Potensic remains `NOT_FABRICATED`. Real
footage is local-only with content hashes; never upload private media to public
CI artifacts.

## Mutation integrity protocol

`scripts/regression_mutation_check.py` mutates, expects the mapped test to fail,
reverts with `git checkout`, and writes
`docs/discovery/275-283-284-mutation-results.json`. Required cases:

- Incorrect canvas coordinate mapping
- Broken HSL export
- Incorrect clip targeting
- Disabled persistence
- Broken Undo/Redo
- Incorrect transition timing
- Missing collage export cleanup
- Incorrect scope accumulation
- Authorization bypass

Never commit deliberate production regressions. Do not skip/weaken failing tests
for green CI. Do not raise numerical tolerances without PO approval.

## Native Windows: covered vs limited

| Area | Status |
| --- | --- |
| Harness + required journey schema | PASS (unit tests on `packaging/packaged_e2e.py`) |
| Fresh packaged EXE run on this PR | **NOT_RUN** (Windows E2E CI is main-only) |
| MotW / SmartScreen / native dialogs | Manual / human release checklist |
| Real DJI creator footage matrix | **NOT_RUN** until PO local fixtures + dated evidence |

When PR CI cannot run native Windows, the mandatory reproducible acceptance gate
is the local `windows_e2e.py` command above plus uploaded `evidence.json`.

## Performance baseline highlights

- Scopes non-packaged Node harness: `tests/js/scopes_nonpackaged_perf.test.js`
  and `docs/planning/362-scopes-node-perf.json` (packaged latency **NOT_RUN**).
- Spatial bake smokes exist under `tests/test_bench_spatial_*.py` (smoke budgets,
  not release SLOs).
- No new global performance redesign is introduced by this gate.

## Coordination with parallel workstreams

Additive only. When Masking, Color Workspace, Scopes, Collage, Playback,
Tracking, or Secure Assistant land, update the JSON matrix to **wire** their
suites. Do not delete or soften their assertions.

## Independent review note

This change set establishes gate documentation, inventory tests, fixture
manifest, mutation harness, and additive CI wiring. It does not self-approve
feature workstreams, does not merge to main, and does not publish a release.
Independent ChatGPT GitHub PR review remains required.