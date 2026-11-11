# Phase-A architecture review evidence (#348 / PR #367)

Status: documentation/arithmetic/baseline diagnosis only. No production rendering, UI, persistence, tests or CI workflow changes. ADR 0035 remains Proposed; independent re-review and PO architecture acceptance are pending. This report responds to [the PM review](https://github.com/Magehawks/orga-drone/pull/367#issuecomment-6803782603) and [the inline review](https://github.com/Magehawks/orga-drone/pull/367#discussion_r4541102237).

## Transfer reference vectors

These are scalar neutral RGB vectors computed from the literal transfer equations in the [contract](COLOR_WORKSPACE_CONTRACT.md#separate-managed-gate-m709-srgb8-v1), not measurements of a production color pipeline. All three channels have the same value. Full-range RGB8 is Q8=floor(255*x+.5). No video encode, color-managed screen, GPU or FFmpeg comparison was performed by this arithmetic check. Inverse OETF is a computational contract, not a claim about the reference display EOTF.

Expected values (decimal rounding shown; tolerance 1e-9 for printed transfer values, exact integer codes):

- Linear 0: sRGB 0, BT.709 0, raw codes 0/0, normalized code 0/0.
- Linear .001: sRGB .012920000000, BT.709 .004500000000, raw codes 3/1, normalized code 3/3.
- Linear .010: sRGB .099852822734, BT.709 .045000000000, raw codes 25/11, normalized code 25/25.
- Linear .180: sRGB .461356129500, BT.709 .409007728864, raw codes 118/104, normalized code 118/118.
- Linear .500: sRGB .735356983052, BT.709 .705515089922, raw codes 188/180, normalized code 188/188.
- Linear 1: sRGB 1, BT.709 1, raw codes 255/255, normalized code 255/255.

For .18 the unquantized raw-code difference is 13.348842162254. After first quantizing each encoding independently to RGB8 and then normalizing, sRGB 118 normalizes to 118 and BT.709 104 to 117; the one-code difference is retained. The mathematical float roundtrip becomes identical, but quantization, YUV/codec/scaling and detail errors must still be measured in implementation. This check cannot establish managed application parity or pass L320.

Reproduce with Python 3 standard library, e.g. paste the following into an isolated interpreter. It neither imports application code nor creates files:

```python
from math import floor, isclose


def srgb(x):
    return 12.92*x if x <= .0031308 else 1.055*x**(1/2.4)-.055


def bt709(x):
    return 4.5*x if x < .018 else 1.099*x**.45-.099


def decode_srgb(c):
    return c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4


def decode_bt709(c):
    return c/4.5 if c < .081 else ((c+.099)/1.099)**(1/.45)


def q8(x):
    return floor(255*min(1, max(0, x))+.5)


vectors = [
    (0, 0, 0, 0, 0),
    (.001, .012920000000, .004500000000, 3, 1),
    (.010, .099852822734, .045000000000, 25, 11),
    (.180, .461356129500, .409007728864, 118, 104),
    (.500, .735356983052, .705515089922, 188, 180),
    (1, 1, 1, 255, 255),
]
for linear, expected_s, expected_b, code_s, code_b in vectors:
    assert abs(srgb(linear)-expected_s) <= 1e-9
    assert abs(bt709(linear)-expected_b) <= 1e-9
    assert (q8(srgb(linear)), q8(bt709(linear))) == (code_s, code_b)
    assert abs(decode_srgb(srgb(linear))-linear) <= 1e-12
    assert abs(decode_bt709(bt709(linear))-linear) <= 1e-12
    assert q8(srgb(decode_bt709(bt709(linear)))) == code_s
assert isclose(255*(srgb(.18)-bt709(.18)), 13.348842162254, abs_tol=1e-9)
assert q8(srgb(decode_srgb(118/255))) == 118
assert q8(srgb(decode_bt709(104/255))) == 117
# Rounded standards constants have a small toe discontinuity: do not smooth it.
assert abs(bt709(.018)-.08124794403514046) <= 1e-12
assert abs(decode_bt709(.081)-.01794502336674779) <= 1e-12
assert abs(srgb(.0031308)-.040449936) <= 1e-12
assert abs(decode_srgb(.04045)-.0031308049535603713) <= 1e-12
print("PASS: six vectors, gray negative control, quantization and toe branches")
```

Result on Python 3.12.3: PASS. These values are separate from all #320 historical evidence. The existing #320 reference extractor at `packaging/e2e/studio_photo_lut_probe.py::reference` uses select(frame), scale=640:360 and PNG, without a BT.709-to-sRGB transfer conversion. It remains unchanged. Managed evidence must use the new explicitly profiled boundary and a distinct result ID; raw mismatched codes are INVALID_MANAGED_BOUNDARY.

## Completed original CI and develop comparison

PR original head: `599b5b31554ed713723865ffdebb8b01f11b2c00`; develop baseline and current fetched origin/develop: `8ff25454672de14b312e5b9e4d553a9c57d1b8ef`. The completed [PR run 43067423342](https://github.com/Magehawks/orga-drone/actions/runs/43067423342) and completed [develop run 42918380509](https://github.com/Magehawks/orga-drone/actions/runs/42918380509) BOTH fail the same two jobs. This is actual baseline-run evidence, not an inference from a docs-only label.

- Ruff and MyPy: pass in both runs (85 checked source files). Combined Python job: **FAIL** in both, with **1 failed, 1205 passed, 4 skipped**. Failure is `tests/test_studio_lut_preview_js.py::test_lut_preview_lifecycle`, whose Node subprocess exits 1 with `ReferenceError: previewIsFullscreen is not defined` at `tests/js/lut_preview.cjs:196`.
- Cause: the text-slicing VM harness loads `paintPreviewBlit` without its new `previewIsFullscreen` dependency. Production `studio.js` defines the helper; commit `37c5ad5` (integrated into baseline by #347) added the call in `paintPreviewBlit`. The isolated harness neither loads nor stubs it. This is a baseline harness/production-boundary mismatch, not evidence that the production helper is absent and not a rendering failure caused by this Markdown PR.
- JavaScript job: **FAIL** at `npm run format:check` in both runs. Pinned Prettier reports code style mismatches in `static/js/studio/speed-ramp-editor.js` and `speed-ramp.js`; these files and package manifests are unchanged. ESLint emits a nonfatal eqeqeq warning in overlay-persist.js; that warning does not cause the job failure. Node tests in this job are NOT_RUN because formatting stops the job. This is not an npm install failure.
- App journey smoke: PASS in the original PR run. This does not compensate for either failed required job or certify color parity.

Local reproduction in this same isolated worktree: `node tests/js/lut_preview.cjs` exits 1 with the identical ReferenceError. `python -m pytest tests/test_studio_lut_preview_js.py -q` reports **1 failed, 1 passed**, with the same cause (Python 3.12.3, local Node v26.13.0, not claimed to be CI's Node version). The full suite and local Prettier were not rerun; completed CI supplies their actual results.

`git diff origin/develop HEAD -- src tests packaging .github package.json package-lock.json` is empty. `git rev-parse origin/develop` and the baseline SHA in the existing develop run agree. No other worktree was opened or modified to reproduce this. Both required checks remain FAILED, not waived, and unrelated runtime/test/formatting corrections must use a separately approved scope. Re-run candidate CI after this documentation revision and report actual status; a baseline match is not a green check.

## Binding criteria observed on 47 issues

Read-only GitHub issue-body inventory on 2026-11-11 found the PO's binding Engineering/Integration criteria on exactly these 47 issues:

#184, #211, #267, #273, #274, #275, #281, #282, #283, #284, #291, #292, #293, #294, #295, #296, #297, #298, #299, #300, #301, #302, #320, #325, #331, #332, #333, #335, #336, #348, #350, #351, #352, #353, #354, #355, #356, #357, #358, #359, #360, #361, #362, #363, #364, #365, #366.

The criteria are additive: isolated worktree/feature branch, small testable modules, reuse, approved UI/tokens/Creative-Pro/A11y/DE-EN, common validated Action/API paths, secure capability-aware MCP adapters with target/revision/history semantics, and real E2E/regression evidence. They do not authorize features or expand the scope of any of these issues. The [contract](COLOR_WORKSPACE_CONTRACT.md#binding-po-engineering-criteria-across-the-47-issue-portfolio) provides the normative mapping for this package. Other portfolio issues keep their original owners/non-scope; this PR does not edit or relabel them.

Phase-A application: work remains solely in color-contract-348, branch codex/348-color-contract, PR #367 to develop. Changes are architecture Markdown only. Runtime module changes: N/A; concrete module/ownership boundaries are specified. Reuse: existing builders, adapters, actions, validation, saver/clip model/history and test utilities are inventoried. UI conformity: no UI change; #361/#362 must retain approved design/tokens/keyboard/A11y/DE-EN. Runtime API/MCP changes: N/A; #350/#351/#363/#296 own approved commands, capability/authorization/revision/history bindings. Runtime E2E: NOT_RUN because no new runtime journey exists; #364/#365 own real UI→action→persistence→preview/export and approved MCP/Control API journeys, with Windows/packaged evidence. No dummy endpoint or E2E pass was manufactured.

## Unresolved approval gates

ADR 0035 remains Proposed and implementation is not authorized by these planning documents. PO must accept the architecture, managed gate and budgets first. Before any canonical write, #351 must obtain explicit decisions on minimum-reader version/startup enforcement, separate database and backup names/locations/permissions, verified checksum/restore procedure and downgrade behavior/consent to losing later edits. The existing rejected #320 precision work remains stopped. No production migration, precision experiment or self-merge is performed here.
