# Permanent product regression and integration gates

Status: **living gate system** for issues [#275](https://github.com/Magehawks/orga-drone/issues/275),
[#283](https://github.com/Magehawks/orga-drone/issues/283), and
[#284](https://github.com/Magehawks/orga-drone/issues/284).

This document is the permanent entry point for creator-journey regression.
It orchestrates existing harnesses. It does **not** replace working pytest,
JavaScript, Control API, packaged Windows E2E, or MCP adapter suites.

Product truth remains [`PRODUCT_VISION.md`](PRODUCT_VISION.md). Risk-based PR
checks remain in [`PR_E2E.md`](PR_E2E.md). Shared Studio actions remain in
[`architecture/STUDIO_ACTIONS.md`](architecture/STUDIO_ACTIONS.md).

## Layer model (binding)

| Layer | What it proves | What it does **not** prove |
| --- | --- | --- |
| **1 Unit** | Deterministic domain logic, geometry, operators, validation, persistence, security | Rendered pixels, WebView2 UX, packaged EXE |
| **2 Integration** | Real API + DB + FFmpeg/export publication + shared Control API contracts | Native mouse/keyboard, MotW, GPU-specific playback |
| **3 Browser E2E** | Fast UI regression against the real app frontend (when a harness exists) | Packaged Windows acceptance |
| **4 Native Windows E2E** | Packaged EXE + WebView2, isolated profiles, real input, decoded output | Full real-drone creator footage matrix |
| **5 Visual / performance** | Independent numerical fixtures, targeted screenshots, approved tolerances, latency/memory | That browser-only green equals native acceptance |

Browser-only evidence must never be reported as native Windows acceptance.

## Status labels (honest)

| Label | Meaning |
| --- | --- |
| **PASS** | Automated evidence on the audited commit; assertions check user-visible behavior or artifacts |
| **PARTIAL** | Some paths covered; gaps named |
| **NOT_RUN** | Harness exists; no fresh dated evidence claimed |
| **PENDING** | Journey incomplete or owned by an in-flight parallel workstream |
| **N/A** | Out of scope for the cited issue |

Do not claim **PASS** for **NOT_RUN** or **PENDING**.

## Authoritative artifacts

Exactly one of each — competing runners, harnesses, or manifests are not allowed:

| Role | Path |
| --- | --- |
| Regression runner | [`scripts/run_regression_gates.py`](../scripts/run_regression_gates.py) |
| Mutation verification harness | [`scripts/mutation_check_regression_gates.py`](../scripts/mutation_check_regression_gates.py) |
| Fixture manifest | [`tests/fixtures/regression_fixture_manifest.json`](../tests/fixtures/regression_fixture_manifest.json) |
| Coverage matrix | [`tests/fixtures/regression_coverage_matrix.json`](../tests/fixtures/regression_coverage_matrix.json) |
| CI gate strategy (this doc) | [`REGRESSION_GATES.md`](REGRESSION_GATES.md) |

Human-readable companions: [`qa/COVERAGE_MATRIX.md`](qa/COVERAGE_MATRIX.md),
[`qa/FIXTURE_MANIFEST.md`](qa/FIXTURE_MANIFEST.md),
[`qa/INTEGRATION_OWNERSHIP.md`](qa/INTEGRATION_OWNERSHIP.md).
Module inventory pin: [`tests/fixtures/regression_gate_modules.json`](../tests/fixtures/regression_gate_modules.json)
(lean `python_gate_nodes` / `js_gate_nodes` for CI; broader module lists for
masking, Color Workspace, scopes, playback, and collage contracts when present
on `develop`). Mutation evidence:
[`discovery/regression-gates-mutation-evidence.md`](discovery/regression-gates-mutation-evidence.md),
[`discovery/275-283-284-mutation-results.json`](discovery/275-283-284-mutation-results.json).

## Exact reproduction commands

Pin the commit under test (`git rev-parse HEAD`) and the environment
(Python, Node, FFmpeg, WebView2) in evidence notes.

### Layer 1-2 — deterministic PR gates (fast)

```bash
pip install -e ".[dev]"
ruff check .
mypy src packaging/itch_channel.py packaging/windows_third_party.py packaging/main_admission.py packaging/packaged_e2e.py packaging/e2e/windows_e2e.py
pytest --ignore=tests/test_pr_journey_smoke.py
pytest tests/test_pr_journey_smoke.py
npm ci
npm run check:js
```

Curated creator regression gate (subset used by the dedicated CI job):

```bash
python scripts/run_regression_gates.py
```

Equivalent explicit list:

```bash
python scripts/run_regression_gates.py
# equivalent: pytest nodes from tests/fixtures/regression_gate_modules.json
# python_gate_nodes, then node --test on js_gate_nodes
# (scopes accumulate + control bridge by default)
```

### Layer 3 — browser UI

There is **no Playwright dependency in this repository today**. Historical RC
notes used Edge/Playwright off-tree. Do not treat browser-only runs as Layer 4.
When a browser harness is added, register it in the coverage matrix as Layer 3
only.

### Layer 4 — packaged Windows (reproducible; required for main admission)

On a Windows machine with WebView2:

```powershell
pip install -e ".[dev]"
pip install "pyinstaller==6.22.3" "websocket-client==1.8.0"
pyinstaller packaging/orga-drone.spec --noconfirm --clean --distpath dist
tar.exe -a -c -f orga-drone-windows-x64.zip -C dist orga-drone
Expand-Archive orga-drone-windows-x64.zip -DestinationPath $env:TEMP\orga-e2e-extract -Force
$exe = Get-ChildItem "$env:TEMP\orga-e2e-extract" -Recurse -Filter orga-drone.exe | Select-Object -First 1
python packaging/e2e/windows_e2e.py --exe $exe.FullName --output-dir docs/discovery/windows-e2e-local
```

CI workflow: [`.github/workflows/windows-e2e.yml`](../.github/workflows/windows-e2e.yml)
runs on PRs to **main** and is a **required** status check for `main` (native
Windows acceptance gate). `workflow_dispatch` supports reproducible offline /
develop acceptance runs without claiming PASS on every develop PR. Absence of a
fresh packaged `evidence.json` on a develop PR is **NOT_RUN**, not a pass.

### Mutation integrity prove-out

```bash
python scripts/mutation_check_regression_gates.py
```

Mutations must fail the matching tests, then every mutation is reverted and the
clean suite re-run. Deliberate production regressions are never committed.

### MCP adapter (external repo)

MCP stdio contract smoke lives in
[Magehawks/orga-drone-mcp](https://github.com/Magehawks/orga-drone-mcp).
This repository keeps Control API v1 journeys; the adapter must not reimplement
editor logic. Link adapter CI results from release notes; do not invent a second
editor here.

## CI check inventory

| Check | Workflow | Trigger today | Role |
| --- | --- | --- | --- |
| Ruff, MyPy and unit tests | `CI` | PR + push `main`/`develop` | Layer 1-2 bulk |
| JavaScript lint, format and tests | `CI` | PR + push `main`/`develop` | Layer 1 JS |
| App journey smoke | `CI` | PR + push `main`/`develop` | Layer 2 library->Studio smoke |
| Creator regression gates | `CI` | PR + push `main`/`develop` | Curated Layer 1-2 creator contracts |
| Windows packaged E2E | `Windows packaged E2E` | PR->`main` (+ local repro) | Layer 4 |
| Main admission policy | `Main admission` | PR->`main` | Evidence binding for promotion |

### Repository policy (required checks)

Deterministic regression checks are **mandatory** on `develop` via branch
protection required contexts:

1. `Ruff, MyPy and unit tests`
2. `JavaScript lint, format and tests`
3. `App journey smoke`
4. `Creator regression gates`

Native Windows acceptance is **mandatory** on `main` via required contexts
`Windows packaged E2E` and `Main admission policy`. Do not weaken those gates.
Requiring packaged Windows E2E on every develop PR remains a separate
cost/latency decision; until enabled, develop PRs document Layer 4 as
**NOT_RUN** and still cannot promote to `main` without the Windows gate.

## Test integrity rules

- Do not delete, skip, or weaken failing mandatory tests for green CI.
- Do not increase numerical tolerances without explicit PO approval.
- Do not regenerate reference outputs solely from a candidate implementation.
- Do not mock away the behavior under test.
- Do not replace real interaction tests with direct state injection.
- Do not use retries to conceal deterministic regressions.
- Do not claim PASS for NOT_RUN or PENDING.
- Fix implementation when established behavior regresses.
- Intentional product contract changes require PO approval and test updates.

## Parallel workstreams

Feature agents (Masking, Color Workspace, Scopes, Collage, Playback, Tracking,
Assistant) own their in-flight suites. This gate system **integrates** their
modules into the matrix as PASS only after they land on `develop`. Until then
they stay **PENDING** / **NOT_RUN**. See
[`qa/INTEGRATION_OWNERSHIP.md`](qa/INTEGRATION_OWNERSHIP.md).

## Close guidance for #275 / #283 / #284

Recommend closing an issue only when its acceptance criteria are actually met
on `develop` with honest evidence. See the coverage matrix for the current
recommendation.
