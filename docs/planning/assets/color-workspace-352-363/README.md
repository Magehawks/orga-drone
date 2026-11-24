# Color Workspace native E2E evidence (feat/color-workspace-352-363)

Pinned develop tip at branch creation: `ed22c9d`.

## Results

| Journey | Verdict | Notes |
|---|---|---|
| Unit/regression contract | PASS | `tests/test_color_workspace_regression_contract.py` (order / persistence / preview-export; reverse-order mutation proof) |
| Managed editor JS | PASS | slider/number sync + convert re-enable |
| Managed step editor JS | PASS | `reorderStepIds` + rendered orderedIds for Move up/down |
| Native source-app EN operators | PASS | `packaging/e2e/studio_color_workspace_operators.py --locale en` with hard reorder/video asserts |
| Native source-app DE operators | PASS | same harness `--locale de` |
| Packaged EXE WebView2 | NOT_RUN — deferred by PO | unchanged |

## Hard asserts restored

Reorder and video cases no longer soft-pass. API reorder must change step order, DOM must match, UI Move down must change order, and video managed controls must enable after convert.

## Product fix

`managed-step-editor.js` Move up/down now reorders from the **rendered** step id list (not a possibly stale `getGrade()` snapshot), and exposes `data-managed-step-move`.

## Screenshots

PNGs in this folder (`01-before-*` … `05-video-*` for EN/DE).

## Shared-file ownership vs Masking

Additive inspector number inputs, locales, tests, and E2E harness only.
No competing mask engine; no rewrite of `studio_mask.py`.
