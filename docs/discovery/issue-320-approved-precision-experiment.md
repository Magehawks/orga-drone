# Issue #320: conditionally approved precision experiment

> Final follow-up: the [RGB24-boundary isolated experiment](issue-320-final-rgb24-boundary.md) also failed its mandatory detail gate. No production/cache change was made. Precision work is stopped; `BLOCKED_PO_DECISION` remains. The report below is historical evidence.

## Outcome

**`BLOCKED_PO_DECISION`. Experimental production/cache changes were reverted.**
The [conditional Product Owner approval](https://github.com/Magehawks/orga-drone/pull/321#issuecomment-6725783159)
authorized a bounded proof, with a mandatory no-detail-regression retention gate.
The experiment improves several color comparisons but does not clear that gate:
graded 1080p fixtures at DPR 3 have up to **2.0396325096460832% lower normalized gradient
energy** and **0.5313130330715121% lower medium-to-broad stripe response**.
No detail tolerance was invented to retain the change. Native neutral photos
remain pixel-identical, but that does not establish graded-photo safety.

These are measured response changes, not a claim that every difference is visible
blur. RGB/JPEG rounding can contribute, and the precise share is not fully
attributed. Under the explicit retention condition we cannot sign off detail
preservation from these results, so the experiment is not retained. Performance
also costs time/memory and is not presented as a free color improvement.

**Final production, cache keys, tests, WebGL, proxy architecture and #319 lifecycle
are unchanged from develop.** The rejected patch includes the implementation
and its six cache-contract tests for reproduction only. No binary is committed
or published. PR #321 remains draft/open/unmerged; issue #320 stays open.

## Tested correction and cache contract

The rejected implementation modified only three production files:

1. `studio_lut.py`: prefix the shared `ffmpeg_lut_chain()` with
   `format=gbrpf32le` only when there is an actual confirmed conversion and/or a
   creative LUT at strength >0. It appears once before conversion→creative.
   Neutral, unconfirmed conversion-only and creative-0%-only paths are unchanged.
2. `studio_preview_frame.py`: append `lut_rgb_precision=1` to cache-key payloads
   only for those affected looks.
3. `studio_playback_proxy.py`: use the same conditional cache discriminator.

Base still version **7** and proxy version **3** were deliberately preserved
for unaffected content; affected outputs received a new namespace via the
precision field. Tests demonstrate old affected files are not served as new
hits, new entries are reused, and unaffected keys remain exactly compatible.
All three consumers of the shared LUT builder were inspected: preview still,
playback proxy and export. Generated `.cube` files are unchanged mathematical
data; export segments are temporary and finished exports are not a render cache.

Grade→LUT→HSL→wheels order, strength blending, confirmed conversion semantics,
photo preparation, dimensions, source integrity and the frontend remain intact.
No global float conversion or rejected neutral-720 path was applied. The
experiment nevertheless changes the representation entering downstream filters
and scaling, which is why swatch-only acceptance is insufficient.

See [rejected implementation/tests patch](issue-320-color-parity-evidence/approved-precision-experiment/rejected-active-lut-precision.patch),
[build identities](issue-320-color-parity-evidence/approved-precision-experiment/build-identity.json)
and [checks](issue-320-color-parity-evidence/approved-precision-experiment/checks.json).

## Actual packaged color results

Baseline is develop `3d72528126931569ad8490a1a79b94c1326f17f2`; its verified
packaged production source/spec equals `ac5bacf`. The candidate was freshly
onefolder-built, pinned to FFmpeg 7.1, notices GO, ZIP-extracted, and tested in
WebView2 **157.0.4341.42**. Fixtures and LUTs are identical synthetic inputs.
Neither the strict **≤3.0** metric nor its reference decoding was changed.

Baseline → rejected candidate (final production remains baseline):

- Neutral JPG: **4.333333333333333 → 4.333333333333333**, FAIL.
- Neutral PNG: **4.666666666666667 → 4.666666666666667**, FAIL.
- Different-LUT photo crossfade: **3.313218390804598 → 3.3333333333333335**, FAIL.
- Photo→video: **4.0 → 3.1120689655172415**, FAIL.
- Video→photo: **3.6666666666666665 → 3.103448275862069**, FAIL.
- Colored single-photo 0%: **1.6666666666666667 → 1.6666666666666667**, PASS.
- Colored single-photo 50%: **1.3333333333333333 → 1.3304597701149425**, PASS.
- Colored single-photo 100% / conversion:
  **2.2241379310344827 → 2.043103448275862**, PASS, in both formats.

The main probe completed **13 scenarios / 71 preview/application-MP4 pairs**;
its strict exit remains nonzero. Sources remain unchanged and all fixed
playback intervals have **0 additional still requests**. Playback/pause and both
photo layers continue to retain their grading, with no double application or
stale decoded resource observed in this run; focused lifecycle tests also pass.

Exact settled photo alpha controls preserve requested and CSS-serialized alpha:

- Frame 67 / alpha 7/30: **3.3936781609195403 → 3.451149425287356**, FAIL.
- Frame 75 / alpha 0.5: **2.327586206896552 → 2.46551724137931**, PASS for this pair.
- Frame 82 / alpha 22/30: **2.9310344827586206 → 2.6666666666666665**, PASS for this pair.

Reconstruction with actual CSS alpha matches candidate preview exactly at all
three points. The first two worsened comparisons are retained; no difference is
silently attributed to rounding or relabeled PASS beyond the unchanged threshold.
The independent single-video comparison improves **4.0 → 2.6666666666666665**
paused/playing/after pause, but this does not certify mixed transitions. #316
timing remains separate. Decorated historical results were not rerun or waived.

Evidence: [all color values](issue-320-color-parity-evidence/approved-precision-experiment/color-summary.json),
[packaged run](issue-320-color-parity-evidence/approved-precision-experiment/candidate-color-parity.json),
[matched-alpha/video controls](issue-320-color-parity-evidence/approved-precision-experiment/candidate-aligned-controls.json).

## Native and high-DPI detail

The new analysis driver captures the actual application blit, not a replacement
renderer. Each build captures **16 cases**: JPG/PNG × 1920×1080/3840×2160 ×
neutral/creative-100% × DPR 1/3. Source hashes match. DPR 3 backing canvases are
native **1920×1080** or **3840×2160**. The test pane overrides its layout-only
max-height to make those backing sizes possible and asserts the dimensions.
An initial harness run was incomplete because the editor's max-height capped
the requested 4K pane; that was corrected identically for both builds before
the reported captures. It was not treated as a rendering defect or passing run.

The generated fixture includes 2-, 8-, 32- and 64-pixel stripes/fine edges.
All eight neutral captures are **pixel-identical**. Graded captures preserve
dimensions but change pixel values. To distinguish global color gain from
spatial response, the comparison retains raw error/stddev and also compares
mean/contrast-normalized structure and fine/medium-to-broad stripe responses:

- Graded structure correlation is approximately **0.999727–0.999833**.
- 1080p JPG/PNG normalized gradient energy: up to **−2.0396325096460832%** at DPR 3.
- 1080p JPG/PNG fine-to-broad response: **−0.49638608892126346%** at DPR 3.
- 1080p JPG/PNG medium-to-broad response: **−0.5313130330715121%** at DPR 3.
- 4K DPR-3 fine-to-broad response: **+0.177517399640581%**;
  medium-to-broad: **−0.058030548002030446%**.

This does not establish a universal loss of resolution or visible blur; it
does establish small measurable response changes that cannot be ignored under
this approval. No new numeric tolerance or different color methodology was used
to retain the implementation. The package/codec transforms need a narrower
precision boundary before another retention attempt.

Statistics were recomputed in float64 from the unchanged captured PNGs to avoid
float32 correlation accumulation artifacts; initial float32 values are retained
in the report. The measured negative response remains. Every native image pair
is available alongside [baseline detail](issue-320-color-parity-evidence/approved-precision-experiment/baseline-detail/report.json)
and [candidate detail/comparisons](issue-320-color-parity-evidence/approved-precision-experiment/candidate-detail/report.json).

## Performance and memory

The new backend benchmark uses the same read-only synthetic 1080p/4K JPG/PNG
and two-second 30-fps video fixtures. Baseline and candidate use isolated caches
and the same Python/FFmpeg environment, with **two repetitions per case**. The
primary runs are serialized without concurrent agent builds or tests. Earlier
measurements overlapping package construction are retained but excluded from
the primary comparison; they are not mixed into the means.

Cold generation means a fresh application render cache, not an OS disk-cache
flush. Timing covers the complete backend render call, including Pillow photo
preparation, FFmpeg, publication and cache handling. It excludes HTTP/browser
decode and LUT import/setup. Export uses existing default **High** quality
(CRF 20 / veryfast) at native resolution, including segment and final output.

Arithmetic mean wall time (seconds), baseline → candidate:

- 1080 JPG still: **0.1590 → 0.1699**, **+6.8%**.
- 1080 PNG still: **0.1481 → 0.1595**, **+7.7%**.
- 4K JPG still: **0.2870 → 0.3309**, **+15.3%**.
- 4K PNG still: **0.2516 → 0.2888**, **+14.8%**.
- 1080 proxy: **0.6785 → 0.4061**, **−40.1%**.
- 4K proxy: **0.8008 → 0.7343**, **−8.3%**.
- 1080 export: **1.1058 → 1.2092**, **+9.4%** (+0.1034 s).
- 4K export: **3.6598 → 4.0570**, **+10.9%** (+0.3972 s).

The negative proxy deltas are not advertised as a speedup: two short synthetic
repetitions and first-run/cache/system variance cannot establish that claim.
The positive export delta can add user-visible waiting on longer projects;
these two-second synthetic clips do not bound real DJI/long-project costs.
Cold-still increases are small in absolute time (~11–44 ms), but not zero.

Maximum sampled summed process-tree RSS over repetitions (MiB), baseline → candidate:

- 1080 JPG still: **78.3 → 105.7**, **+34.9%**.
- 1080 PNG still: **80.7 → 108.1**, **+33.9%**.
- 4K JPG still: **123.7 → 197.8**, **+59.9%**.
- 4K PNG still: **115.2 → 219.6**, **+90.7%** (~104.4 MiB additional).
- 1080 proxy: **338.0 → 357.9**, **+5.9%**.
- 4K proxy: **711.8 → 734.6**, **+3.2%**.
- 1080 export: **726.4 → 770.7**, **+6.1%**.
- 4K export: **2535.8 → 2673.0**, **+5.4%** (~137.2 MiB additional).

Memory sampling is every 10 ms and records backend worker + child RSS and each
observed child's peak working set. It is not whole-OS, GPU or WebView2 memory.
The extra still memory can compound when #319 prepares two cold 4K photo owners;
that combined case was not measured before the detail gate failed. No bounded
overlap-memory or general user-visible-performance PASS is claimed.

Candidate still cache hits are **1.586–2.182 ms**, proxy hits **2.698–6.483 ms**;
all reuse the same file and mtime. Baseline hit values and exact, unrounded
absolute/percentage changes are in the reports. All benchmark input hashes are
unchanged. All **16** serialized benchmark proxy/export outputs fully decode
without FFmpeg errors. The failed retention gate makes these measurements
evidence, not permission to ship the added cost.

Evidence: [summary](issue-320-color-parity-evidence/approved-precision-experiment/performance-summary.json),
[serialized baseline](issue-320-color-parity-evidence/approved-precision-experiment/baseline-performance.json),
[serialized candidate](issue-320-color-parity-evidence/approved-precision-experiment/candidate-performance.json),
[preliminary baseline](issue-320-color-parity-evidence/approved-precision-experiment/preliminary-baseline-performance.json),
[preliminary candidate](issue-320-color-parity-evidence/approved-precision-experiment/preliminary-candidate-performance.json),
[media validity](issue-320-color-parity-evidence/approved-precision-experiment/media-validation.json).

## Regression, rollback and next decision

Before rollback: **64 focused tests PASS**, including six new selective-cache
tests, LUT strength/conversion, HSL/wheels/tonal filter ordering, real MP4 pixel
comparisons, preview/proxy generation and #319 lifecycle harnesses. JS tooling:
**106 PASS**. Ruff/MyPy pass. Those new cache tests are retained only inside the
rejected patch, not as failing tests for unchanged production.

After rollback: **23 focused baseline regressions PASS**, Ruff/MyPy pass, and
`git diff -- src tests .github` is empty. No full local suite, general packaged
functional journey suite, MOTW/release check or real-media PO test was repeated.
The actual packaged color/detail tests above are distinct from those checks.
All experimental data/cache directories are isolated; no user cache migration,
source write or destructive cleanup was performed. Existing baseline cache
contracts remain authoritative after rollback. Local independent review found
no cache/order code defect, but does not approve the failed retention gate or
replace renewed independent GitHub review.

**Narrower alternative for PO decision:** test float input/LUT computation with
an explicit return to the existing 8-bit RGB representation immediately after
the actual LUT stages, before downstream resampling/conversion; alternatively
evaluate a bounded 16-bit intermediate. These are hypotheses, not demonstrated
fixes. Preserve source/detail/native-resolution behavior and the strict ≤3.0
gate, use a distinct precision-cache discriminator for any changed experimental
pixel contract, retest the same captures/cache contracts, and add the unmeasured two-cold-
owner memory case before retention. Do not accept this rejected variant by
silently changing detail or performance allowances.

## Reproduction

Use the attached patch only in an isolated experimental checkout; never apply
it to an existing user's data or treat it as retained PR application code.
Build/ZIP-extract via the existing Windows packaging/pinned-FFmpeg procedure.
Use `PYTHONPATH=src`. Analysis tooling additionally uses installed `psutil` and
NumPy; no application dependency was added. All output directories must be new.

```powershell
python packaging/e2e/studio_precision_benchmark.py --prepare --fixtures <fixtures> --ffmpeg <pinned-ffmpeg>
python packaging/e2e/studio_precision_benchmark.py --source-root <baseline>/src --fixtures <fixtures> --ffmpeg <pinned-ffmpeg> --output <baseline-perf> --label baseline
python packaging/e2e/studio_precision_benchmark.py --source-root <experiment>/src --fixtures <fixtures> --ffmpeg <pinned-ffmpeg> --output <candidate-perf> --label candidate
python packaging/e2e/studio_precision_quality.py --exe <baseline-exe> --fixtures <detail-fixtures> --output <baseline-detail>
python packaging/e2e/studio_precision_quality.py --exe <candidate-exe> --fixtures <detail-fixtures> --output <candidate-detail> --compare-baseline <baseline-detail>
python packaging/e2e/studio_photo_lut_probe.py --exe <candidate-exe> --ffmpeg <pinned-ffmpeg> --output <candidate-color> --expect-photo-fix
python packaging/e2e/photo_lut_transition_attribution.py --exe <candidate-exe> --ffmpeg <pinned-ffmpeg> --fixture-run <candidate-color> --output <candidate-aligned>
```

The strict color probe deliberately exits nonzero. All baseline/prototype and
earlier investigation evidence remains intact. This experiment does not change
issue #316, release workflows, security boundaries or project persistence.
