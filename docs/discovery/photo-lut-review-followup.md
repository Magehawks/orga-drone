# PR #319 review follow-up

**Status: `BLOCKED_PO_DECISION`.** Confirmed readiness, paused-composite and
photo-source defects are corrected. The unchanged strict **≤3.0** gate still
fails for the photo crossfade, mixed transitions and unchanged neutral controls.
No failing gate is waived, redefined or relabeled as passing.

## Scope and corrections

This follow-up addresses the Product Owner's explicit PR #319 review task.
The existing two-owner photo LUT lifecycle remains intact. No export, video
WebGL/proxy/clock architecture, schema, source media, threshold or warmth-only
filter behavior was changed. PR #319 remains draft and unmerged.

- `paintPreviewBlit()` now checks decoded graded still readiness on both layers
  before hiding the canvas. It draws the same resources checked by the guard.
  Regression coverage uses the production readiness predicate with zero-sized
  loading original photos and independently decoded primary/secondary stills.
- Pausing while a photo layer is visible reapplies the existing transition
  function at the frozen Story time. This clears an outgoing photo and restores
  full incoming video opacity after overlap exit, and reconciles progress inside
  the overlap. Video-only pause retains its existing behavior.
- Photo preview preparation now reuses export's existing read-only normalized
  JPEG helper in the disposable preview work directory before grade/LUT filters.
  A photo-only cache discriminator excludes old raw-source stills. Export and
  video inputs/cache keys remain unchanged. Actual JPG/PNG MP4 regression tests
  enforce the unchanged maximum interior-swatch mean RGB error of **3.0**.

Local independent read-only implementation review approved these targeted
changes. That advisory review does not substitute for the actual GitHub review
or human product test.

## Controlled color attribution

All inputs are the existing synthetic eight-swatch 1280×720 fixtures. The
application-exported PNG 0% MP4 is the fixed reference; the metric and threshold
are unchanged. Controls vary one preparation stage, not acceptance criteria.

Before matching export's input preparation:

- Production 720×406 JPEG q5: **3.7758620689655173**.
- Same dimensions, JPEG q1: **3.7356321839080464**.
- Lossless RGB after limited-BT.709 conversion, 720×406: **3.853448275862069**.
- Exact 640×360 JPEG q5/q1: **3.6666666666666665**.
- Exact-aspect even 704×396 JPEG q5/q1: **3.6666666666666665**.
- Full-size 1280×720 JPEG q5/q1: **3.6666666666666665**.
- 720×405 lossless converted control: **2.5948275862068964**. Odd-height JPEG
  encoding is deliberately not repeated because pinned FFmpeg 7.1 previously
  crashed. The even-dimension protection remains in production.

After feeding the **same export-normalized JPEG source** into the existing
preview filter chain, 720×406 JPEG q5 reaches **1.6666666666666667**. Exact-aspect
704×396 also reaches **1.6666666666666667**; full-size reaches **1.0**. Changing
dimensions or compression quality alone did not resolve the raw-PNG discrepancy.

The production photo export preparation plus production segment filter was
encoded at CRF **0** and **17**, with both one and two encoding stages. All four
controls reproduce the application-exported interior-swatch RGB values with
**0.0** error. Therefore additional H.264 compression does not explain this
synthetic case. Explicit BT.709 decoding of the MP4 reference also agrees with
the existing decode method (**0.0** difference).

Browser versus Pillow sampling of untagged RGB controls is **0.0** at exact
sizes, **0.040230** at 720×406 after limited-range conversion, and **0.160920**
for production JPEG q5. The much larger discrepancy predates browser sampling.
PNG controls are explicitly stripped of FFmpeg transfer metadata using Pillow;
otherwise browser/Pillow transfer-tag interpretation introduces a separate
12-level difference and confounds that control. Production JPEG tags are intact.

These results identify incompatible photo input preparation as a correctable
cause, rather than treating every codec/sampling difference as a product defect.
They do not prove parity for arbitrary ICC/EXIF/alpha images or real DJI photos.

## Mixed transition attribution

The readiness-only packaged control reproduces the reviewed pause defect:
Story **3.000799676898223 s**, incoming video time **1.0039 s**, incoming opacity
**0.7716**, outgoing photo still visible, RGB error **16.333333333333332**.
The reviewed earlier run reached **16.666666666666668** in the same class.
Both timestamps are after the one-second overlap ending at Story 3 s. Static
source video removes frame-motion ambiguity; both layers are decoded and ready.
This is stale transition state, not an undecoded/stale photo still.

With pause reconciliation, the next packaged control at Story
**3.0212035541195474 s**, video time **1.0229 s**, has no visible outgoing photo
and default/full incoming opacity. Its error is **4.0**, and the worst mixed
photo→video result is **4.0**. The residual is not silently accepted.

An independent **single-video** project using the same static video and LUT
reaches **4.0** paused, playing, and after pause. The pre-PR baseline executable
at `7dd593000844ab7b6832bb24608f2629ec515c1c` also reaches **4.0** in all three
phases. This independently confirms a pre-existing video color limitation.
Video WebGL source hashes are unchanged. The broader video timing limitation
tracked in #316 is not certified fixed or passing.

For the different-LUT photo crossfade, setting browser opacity to the exact
nearest exported frame's alpha gives **4.333333333333333**, **3.3333333333333335**,
and **4.022988505747127** at export frames 67/75/82 in the uncorrected-source
control. Thus CFR rounding/alpha alignment alone cannot explain that failure.
These are explicit analysis interventions, not altered acceptance captures.

## Final packaged results

Production candidate: **`ac5bacf`** (see the full SHA in the
[build identity](photo-lut-review-evidence/build-identity.json)). Earlier
`4a0781f` contains the readiness/pause fixes; `ac5bacf` adds photo-source parity.
Evidence/docs commits after this candidate do not change production code.
The extracted executable's `studio.js` hash matches the source file. Windows
WebView2 is **157.0.4341.42**, with pinned FFmpeg **7.1**. Public version remains
2.3.3. No binary is committed or uploaded.

Reviewed candidate → corrected candidate, worst across captured phases:

- JPG neutral: **4.333333333333333 → 4.333333333333333**, strict FAIL.
- JPG creative 0%: **2.6666666666666665 → 1.6666666666666667**, strict PASS.
- JPG creative 50%: **1.6666666666666667 → 1.3333333333333333**, strict PASS.
- JPG creative 100% / conversion: **2.6666666666666665 → 2.2241379310344827**, strict PASS.
- PNG neutral: **4.666666666666667 → 4.666666666666667**, strict FAIL.
- PNG creative 0%: **3.7758620689655173 → 1.6666666666666667**, strict PASS.
  The previously regressed paused phase also reaches **1.6666666666666667**;
  historical **2.741 → 3.776** normalization regression is corrected.
- PNG creative 50%: **2.0 → 1.3333333333333333**, strict PASS.
- PNG creative 100% / conversion: **2.6666666666666665 → 2.2241379310344827**, strict PASS.
- Different-LUT JPG→PNG: **4.0 → 3.313218390804598**, strict FAIL.
- Photo→video: **16.666666666666668 → 4.0**, strict FAIL.
- Video→photo: **4.0 → 3.6666666666666665**, strict FAIL.
- Decorated LUT playback: **9.458363266283525 → 9.461147030651341**, strict FAIL;
  the neutral decorated control remains **18.625**. This extra screen smoke
  includes existing framing/slider approximations and is not an exact spatial
  parity acceptance claim.

The final mixed post-pause capture is Story **3.0079967689822293 s**, video
**1.0094 s**, nearest export frame **90** (3.0 s), no outgoing photo and full
incoming opacity. Static media makes the 7.997 ms Story/CFR difference irrelevant
to source motion. Residual **4.0** agrees with standalone-video controls.

Final source-corrected photo controls at exact exported alpha remain
**3.3936781609195403**, **2.327586206896552**, **2.9310344827586206** at frames
67/75/82. Exact-alpha capture therefore still fails at frame 67. The evidence
isolates the residual beyond photo lifecycle/source ownership and mere timestamp
rounding, within the separate JPEG/scaling/RGB-versus-YUV export-composite color
paths. It does **not** prove that the residual is unavoidable or that those
paths are defect-free. Changing image transport, sampling or export color
composition to guarantee strict parity needs a separately approved investigation;
this PR does not tune preview resolution/quality to make the test pass.

The main probe completes **13 scenarios / 71 pairs**, preserving JPG/PNG,
0/50/100/conversion, both photo layers, play/pause and both mixed directions.
All synthetic source hashes remain unchanged. All unchanged playback intervals
record **0 additional preview-frame requests**. The strict probe correctly
returns nonzero: `photo_fix_pass=false`, `strict_all_pass=false`. The bounded
photo gate remains a separately reported PASS and is insufficient for approval.

The packaged functional harness reports **10/10 PASS**, including persistence,
video playback, export and source integrity. Local artifact/run metadata is
explicitly non-admission evidence. Focused pinned-FFmpeg + lifecycle + Journey
tests: **25 passed**. JavaScript checks: **106 passed**. Ruff/MyPy pass.
Full Python regression suite on the corrected production source: **1136 passed,
1 opt-in Control WebView2 smoke skipped**, 68 warnings. The two newly added
strict photo cases also pass separately and are included in the 25 focused
tests; the full-suite collection began before those test cases were added.
Journey smoke is included in the final focused run (**2 passed**).

### Product Owner decision required

Keep PR #319 open/draft and keep strict parity failed. Decide whether to approve
a separate narrowly scoped color-pipeline investigation for the residual photo
crossfade plus pre-existing neutral/video limitations, or explicitly expand this
PR's scope to that work. The standalone-video residual is independently
confirmed on the pre-PR baseline; #316 remains a separate timing blocker.
Neither option silently changes the existing threshold or authorizes merging.
No further rendering/clock architecture changes are made while this decision is
pending. Real DJI validation and the human product decision remain outstanding.

Exact scenario data: [before/after](photo-lut-review-evidence/before-after.json),
[final 71 pairs](photo-lut-review-evidence/final-parity.json),
[readiness-only control](photo-lut-review-evidence/readiness-only-parity.json),
[source/codec controls](photo-lut-review-evidence/source-controls.json),
[final transition controls](photo-lut-review-evidence/final-transition-controls.json),
[uncorrected-source alpha controls](photo-lut-review-evidence/uncorrected-source-transition-controls.json),
[baseline video controls](photo-lut-review-evidence/baseline-video-controls.json),
[functional E2E](photo-lut-review-evidence/functional-e2e.json).

Synthetic visual pairs: [mixed before](photo-lut-review-evidence/photo-video-before.png),
[mixed after](photo-lut-review-evidence/photo-video-after.png),
[mixed export](photo-lut-review-evidence/photo-video-export.png),
[PNG 0% preview](photo-lut-review-evidence/png-zero-preview.png),
[PNG 0% export](photo-lut-review-evidence/png-zero-export.png),
[crossfade preview](photo-lut-review-evidence/crossfade-preview.png),
[crossfade export](photo-lut-review-evidence/crossfade-export.png).

## Reproduction

Build, pin FFmpeg, write notices, ZIP and extract per `packaging/README.md`.
Use `PYTHONPATH=src`. All output directories must be new.

```powershell
python packaging/e2e/studio_photo_lut_probe.py --exe <extracted-exe> --ffmpeg <pinned-ffmpeg> --output <run> --expect-photo-fix
python packaging/e2e/studio_photo_lut_probe.py --exe <extracted-exe> --ffmpeg <pinned-ffmpeg> --output <decorated-run> --decorated
python packaging/e2e/photo_lut_attribution.py --exe <extracted-exe> --ffmpeg <pinned-ffmpeg> --source <run>/synthetic-library/swatches.png --reference <run>/png-creative0/export.mp4 --output <color-controls>
python packaging/e2e/photo_lut_transition_attribution.py --exe <extracted-exe> --ffmpeg <pinned-ffmpeg> --fixture-run <run> --output <transition-controls>
```

The transition analysis adds only a synthetic video-control project to that
isolated probe database. It never operates on a user library. Controlled frame
metadata, exact timestamps, patch means and comparisons accompany the evidence.
The strict probe's return code and every failed gate must remain explicit.

## Evidence limits

Functional packaged journeys prove application behavior, not color acceptance.
Local run ID 0 is not GitHub admission evidence. There is no release, MOTW,
real-media, ICC/alpha-PNG or human product-test approval. The existing latency
log starts after Pillow materialization, so it cannot measure the new photo
preparation cost. No latency guarantee is made. Unchanged interval request counts
and owner lifecycle tests remain the check against per-tick FFmpeg rendering.
