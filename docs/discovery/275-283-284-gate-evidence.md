# Permanent regression gates evidence (#275 / #283 / #284)

Date: 2026-11-24 (UTC)  
Surviving consolidation PR: `#574` (`feat/regression-gates-275-283-284`)  
Develop base pin: `ed22c9d`

## Authoritative commands

| Role | Path |
| --- | --- |
| Runner | `scripts/run_regression_gates.py` |
| Mutation harness | `scripts/mutation_check_regression_gates.py` |
| Fixture manifest | `tests/fixtures/regression_fixture_manifest.json` |
| Coverage matrix | `tests/fixtures/regression_coverage_matrix.json` |
| CI strategy | `docs/REGRESSION_GATES.md` |

## Suites run (actual, consolidation)

| Command | Result |
| --- | --- |
| `pytest tests/test_regression_gate_inventory.py -q` | **11 passed** |
| `python scripts/run_regression_gates.py` | **30 pytest + 25 JS passed** |
| `python scripts/mutation_check_regression_gates.py` | **9/9 production mutations caught**, all reverted, clean suite PASS |
| Packaged Windows `windows_e2e.py` fresh EXE run | **NOT_RUN** (required on `main`; develop PRs stay honest NOT_RUN) |

## Close recommendations (honest)

| Issue | Close? | Reason |
| --- | --- | --- |
| #275 | **Not yet** | Matrix, mutation integrity, Control API coverage, and mandatory develop CI gate land here; fresh packaged WebView2 evidence and external MCP adapter CI link remain open. |
| #283 | **Not yet** | Fixture manifest + synthetic defaults shipped; optional real DJI/Potensic slots are `NOT_FABRICATED`; no dated real-footage Windows gate. |
| #284 | **Not yet** | Integration/PR-gate documentation and required develop checks exist; RC Windows EXE validation still requires human PO sessions and main admission. |
