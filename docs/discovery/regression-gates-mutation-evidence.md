# Regression gate mutation evidence

Generated from controlled local runs of `scripts/mutation_check_regression_gates.py`
on worktree `regression-275-283-284` @ base `ed22c9d` (2026-11-24).
Deliberate production regressions were **not** committed. `git status -- src`
was clean after the run (no `MUTATION` markers in production sources).

## Mutation results (matching gates must FAIL)

| Mutation | Matching gate failed? | Notes |
| --- | --- | --- |
| `incorrect_canvas_coordinate_mapping` | YES | `test_letterbox_box_scales_between_resolutions` |
| `broken_hsl_export` | YES | `test_api_export_applies_blue_saturation_minus_100_jpg_and_png` |
| `incorrect_clip_targeting` | YES | `test_apply_action_wrong_clip_target_is_rejected` |
| `disabled_persistence` | YES | `tests/test_studio_history.py` |
| `broken_undo_redo` | YES | `tests/test_studio_history.py` |
| `incorrect_transition_timing` | YES | `test_clamp_user_duration_steps` |
| `missing_collage_export_cleanup` | YES | `test_story_cleans_up_failed_segment_and_preserves_existing_export` |
| `incorrect_scope_accumulation` | YES | `tests/js/scopes_accumulate.test.js` (histogramBin mutation) |
| `authorization_bypass` | YES | `test_loopback_hosts_are_trusted` |

Earlier weak scope mutation (`LUMA_COEFF` only) did **not** fail the JS suite and
was replaced; that attempt is not claimed as proof.

## Clean suite after revert

| Check | Result | Honesty |
| --- | --- | --- |
| Post-mutation curated `run_regression_gates.py` (same process) | **FAIL** (1) | `test_color_look_action_and_ui_routes_share_the_same_domain_result` raised `EDITOR_DISCONNECTED` after ~298 s / 170 passed |
| Immediate re-run of that single test | **PASS** | Isolation / ordering flake under long curated aggregation — not claimed as product FAIL |
| Subsequent full curated / large subset runs in agent shells | **ABORTED** | Exit `4294967295` (-1) mid-pytest with no failure traceback (process kill / agent interrupt / resource abort). **NOT_RUN / not PASS** |
| Inventory pin + scopes JS (small diagnostic) | **PASS** | 8 inventory + 7 scopes tests |

Do **not** treat aborted agent shells as green CI. CI Ubuntu jobs remain the
authoritative Layer 1–2 gate once this PR's workflow runs.

## Environment notes that caused false negatives earlier

- Shared editable venv pointed at another worktree (`exe-build-develop-083ec12`).
  Mutation scripts now force `PYTHONPATH=<this>/src`.
- Large curated aggregates in this agent environment were repeatedly killed
  mid-run; prefer CI or local human machines for full `run_regression_gates.py`.

## Native Windows

Packaged WebView2 E2E: **NOT_RUN** in this PR (no fresh evidence JSON).
Harness remains `packaging/e2e/windows_e2e.py`; required on main admission.
Develop PR CI does not run packaged E2E today — documented limitation, not a pass.
