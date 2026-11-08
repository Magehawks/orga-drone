# Issue #320: residual Studio color parity

## Decision boundary

**`BLOCKED_PO_DECISION`. Strict color parity remains FAIL at the unchanged
maximum interior-swatch mean RGB error of ≤3.0.** No production correction is
retained in this investigation PR. The localized neutral-photo prototype was
rejected because its improved color score sacrifices existing preview detail.
Application code, tests, LUT lifecycle, WebGL, proxies, export, clock, cache keys
and thresholds are unchanged from develop.

The next correction needs an agreed source/precision contract across existing
FFmpeg still, proxy and export paths, including cache invalidation and quality/
performance checks. The task explicitly requires stopping before significant
cross-module changes. The proposal below is for Product Owner approval; it is
not implemented, and does not authorize a rendering rewrite or tolerance waiver.

## Baseline and reproducibility

- Develop baseline: `3d72528126931569ad8490a1a79b94c1326f17f2`, merge of #319.
- Its production `src/` and packaging spec are identical to packaged-tested
  `ac5bacfa46f3ea20de30bde439654340548c8906`. That verified ZIP-extracted binary
  was reused to rerun the existing probe against current develop behavior.
- Windows 11 / WebView2 **157.0.4341.42** / pinned FFmpeg **7.1**, SHA-256
  `e9041e42f9cb1e1faccae46aa4af03ffd70e11474cc085846abdc3dd6e8aadcf`.
- Fixtures are generated eight-swatch 1280×720 JPG, PNG and static 30 fps H.264,
  plus the existing synthetic 17³ red/blue LUTs. No private media is used.
- Fresh baseline: **13 scenarios / 71 actual preview/application-export pairs**.
  Both synthetic application runs preserve all source hashes and record zero
  additional still requests during unchanged playback intervals.

See [build identities](issue-320-color-parity-evidence/build-identity.json),
[fresh develop baseline](issue-320-color-parity-evidence/develop-baseline.json)
and [all before/prototype/final values](issue-320-color-parity-evidence/before-prototype-final.json).

Reproduced develop errors; final production remains identical:

- Neutral JPG: **4.333333333333333**, FAIL.
- Neutral PNG: **4.666666666666667**, FAIL.
- Different-LUT JPG→PNG: **3.313218390804598**, FAIL.
- Photo→video: **4.0**, FAIL.
- Video→photo: **3.6666666666666665**, FAIL.
- Colored single photos remain PASS: strengths 0/50/100 reach
  **1.6666666666666667 / 1.3333333333333333 / 2.2241379310344827**;
  confirmed conversion reaches **2.2241379310344827** in both formats.

The strict probe exits nonzero. No bounded result is substituted for strict
acceptance. Decorated results from #319 remain **9.461147030651341** colored /
**18.625** neutral, with existing spatial/filter approximations; they were not
rerun or reclassified as a strict interior-swatch pass.

## A — Neutral photos: source mismatch and rejected correction

`scheduleLutPreviewStill()` deliberately clears the owner for a neutral clip.
The canvas therefore samples the full-resolution original browser image, while
`_render_photo()` exports a Pillow-normalized quality-95 JPEG, then limited-range
BT.709 YUV420 and H.264. #319 already matches that preparation for LUT stills,
including 0% strength, but neutral photos do not enter that path.

Existing source/scaling/codec controls were rerun against fresh develop exports:

- Original untagged RGB PNG, browser scaled to the measurement size:
  **4.666666666666667** against export.
- Export-normalized source through existing 720×406 JPEG q5 still path:
  **1.6666666666666667**.
- Raw source through 720×406 JPEG q5: **3.7758620689655173**;
  q1: **3.7356321839080464**. Exact 640×360 / 704×396 / full-size JPEG
  controls still reach **3.6666666666666665** without matched preparation.
- CRF 0/17, one/two native-size encoding stages with export preparation and
  production segment filters: all reproduce exported interior swatch means with
  **0.0** error. Added H.264 compression does not explain this static case.
- Explicit input matrix/range does not remove the source mismatch. Native
  conversion controls show the original limited-range round-trip at
  **4.666666666666667** versus the original RGB fixture; accurate rounding alone
  reaches **3.3333333333333335**. A float-RGB intermediate plus accurate rounding
  reaches **2.3333333333333335** in that isolated conversion control.

The last figures are analysis controls, not changed export settings or accepted
corrections. They vary conversion precision while keeping the reference metric;
they do not establish that one filter flag safely fixes every pipeline.

The minimal prototype allowed neutral photos into the existing two-owner still
path and photo preview-frame API, keeping neutral video rejection and proxy/
WebGL behavior unchanged. It reached **1.6666666666666667** for both neutral
formats in all five captured phases. The 26 prototype-focused tests passed,
with zero extra requests during fixed playback intervals. The other failures
remained: photo crossfade **3.2931034482758625**, mixed **4.0 / 3.6666666666666665**.
The small crossfade difference from baseline is not credited as an improvement:
the colored source paths are identical and live capture timestamps differ.

### Why the prototype was not retained

The existing neutral preview samples its original resolution. The prototype
instead upscales a 720×406 still. In actual WebView2, a generated 1920×1080
two-pixel stripe fixture at CSS 640×360 / DPR 3 loses detail:

- Original channel standard deviation: **127.5** on each channel.
- Prototype channel standard deviation: approximately **14.8**.
- Full-frame mean RGB difference: **126.61055057227367**.

This diagnostic is a detail-preservation test, **not** the strict swatch color
metric. It demonstrates a real detail regression, rather than declaring the
prototype safe because flat swatches pass. The task permits corrections only
when they do not weaken existing rendering. All prototype production/test edits
were removed. Its exact application patch is retained as rejected experimental
evidence and must not be applied to this PR.

Evidence: [source/scaling/codec](issue-320-color-parity-evidence/source-scaling-codec-controls.json),
[YUV controls](issue-320-color-parity-evidence/yuv-controls.json),
[RGB precision controls](issue-320-color-parity-evidence/rgb-precision-controls.json),
[rejected package run](issue-320-color-parity-evidence/rejected-neutral-prototype.json),
[rejected patch](issue-320-color-parity-evidence/rejected-neutral-720-prototype.patch),
[detail metrics](issue-320-color-parity-evidence/high-dpi-detail-control.json),
[original detail](issue-320-color-parity-evidence/detail-original.png) /
[rejected detail](issue-320-color-parity-evidence/detail-rejected-prototype.png).

## B — Photo crossfade: exact alpha and independent reconstruction

The existing transition probe samples paused Story times and chooses nearest
30 fps export frames. It also explicitly sets alpha to the exported frame's
progress. Final controlled frame indices and alpha are:

- Frame **67**, alpha **7/30**: strict error **3.3936781609195403**, FAIL.
- Frame **75**, alpha **0.5**: **2.327586206896552**, PASS for this pair only.
- Frame **82**, alpha **22/30**: **2.9310344827586206**, PASS for this pair only.

The probe fetches the two existing rendered JPEG inputs and independently
reconstructs the canvas with the same `Image.decode()`, smoothing, integer fit
and layer opacity. It retains initial and settled captures after two paint
frames. Reconstruction versus settled preview reaches **0.0** at frames 75/82
and **0.5258620689655172** at frame 67. That last sampling difference is retained
and not claimed to be fully explained. Changing the controlled fit back to the
original 16:9 rectangle does not change the worst interior-swatch errors.

The strict failure survives exact alpha and settled paints; no conclusion relies
on time rounding. No stale layer, double grading or new lifecycle defect is
established by these controls. The data narrows the remaining work to the color/
quantization/sampling differences between graded JPEG RGB inputs, canvas blending
and export's pre-encoded YUV segment composition. It does **not** prove that
every residual is unavoidable or that any of those stages is defect-free.

## C — Mixed transitions: isolate the video path

The existing independent single-video project again reaches **4.0** paused,
playing and after pause. #319 also established this on its pre-PR baseline.
Static video and exact export indices eliminate source motion as a confound;
the separate #316 clock/drift acceptance is neither changed nor declared passed.

Additional CPU captures use the same video/LUT and production segment filter.
Negotiated pixel-format logs accompany each image comparison:

- FFmpeg source decode versus browser video decode: **2.3333333333333335**.
- Production LUT result before output YUV conversion versus WebGL: **1.6666666666666667**.
- Same LUT result after production YUV conversion versus WebGL: **4.0**.
  This stage matches actual MP4 export swatches with **0.0** error.
- Explicit Float-RGB before the same LUT: **1.0** before YUV and
  **2.6666666666666665** after YUV, versus WebGL.
- The float/YUV control differs from current actual export by
  **2.3333333333333335**; it changes the rendered output, not just measurement.

Verbose logs confirm default LUT negotiation uses **`rgb24`**, while the
explicit precision control uses **`gbrpf32le`** before the same limited-range
BT.709 YUV420 output. This establishes a numerical precision contribution to
the pre-existing video mismatch. The source-decoder difference is an additional
potential contributor/confound; its causal share is not established by the
separate source-only measurement, without matched decoded inputs through both LUTs.
The evidence does not assign the whole error to WebGL or to one rounding stage.
The WebGL renderer and shader remain untouched.

Evidence: [exact-alpha and video stage data](issue-320-color-parity-evidence/precision-and-alpha-controls.json),
[browser video source](issue-320-color-parity-evidence/video-browser-source.png),
[WebGL preview](issue-320-color-parity-evidence/video-webgl.png),
[CPU pre-YUV](issue-320-color-parity-evidence/video-pre-yuv.png),
[actual export](issue-320-color-parity-evidence/video-export.png),
[analysis float/YUV](issue-320-color-parity-evidence/video-float-yuv.png).

## Classification and proposed next slice — approval required

- **Confirmed product mismatch:** neutral preview and export use different
  photo preparation/conversion paths. The apparent small fix regresses detail.
- **Pre-existing video contribution:** source decode and 8-bit LUT/YUV precision
  differ from browser/WebGL; this is reproducible outside transitions.
- **Measurement/sampling contribution:** live alpha rounding is controlled,
  and the first reconstructed photo pair retains a sub-level difference.
  Neither accounts for the remaining strict failures by itself.
- **Codec effects:** not presumed harmless or unavoidable. Lossless/production
  H.264 controls produce the same interior means in this static neutral case.
  Decorated spatial/filter error remains separate and unaccepted.

Proposed bounded follow-up, only after Product Owner approval:

1. Agree the existing FFmpeg RGB precision/source-normalization boundary for
   photo and video grading, before native-size YUV output. Preserve native neutral
   preview detail; reject reducing image resolution as a color-gate workaround.
2. Test explicit precision in the shared LUT/filter builders across **export,
   cached stills and playback proxies**, not just one path. Existing still cache
   key version 7 and playback proxy version 3 need a coordinated invalidation plan
   if rendered pixels change. No schema or `effect_settings` migration is needed.
3. Measure cold latency, encode cost and peak memory on realistic resolutions
   before retaining a float intermediate. Recheck LUT strength/conversion,
   HSL/wheels/grade ordering, no double grading, source integrity and #319 owner
   transfer/invalidation. Include native-resolution/high-DPI detail checks.
4. Rerun all five failing scenarios at matched Story/frame/alpha, with actual
   Windows WebView2 and application MP4 exports. Keep strict ≤3.0; report every
   remaining FAIL. Do not change #316 timing scope or WebGL/proxy architecture.

This is a proposed cross-path precision contract, not a one-line fix claimed
safe from the current controls. The Product Owner should approve this bounded
next slice or defer it while preserving the failures. No partial improvement is
presented as full acceptance, and no merge/release action is authorized.

## Reproduction and validation

Use the existing onefolder packaging procedure, pinned FFmpeg and a fresh
ZIP-extracted executable. Set `PYTHONPATH=src`. Output directories must be new.

```powershell
python packaging/e2e/studio_photo_lut_probe.py --exe <exe> --ffmpeg <pinned-ffmpeg> --output <baseline> --expect-photo-fix
python packaging/e2e/photo_lut_attribution.py --exe <exe> --ffmpeg <pinned-ffmpeg> --source <baseline>/synthetic-library/swatches.png --reference <baseline>/png-creative0/export.mp4 --output <color-controls>
python packaging/e2e/photo_lut_transition_attribution.py --exe <exe> --ffmpeg <pinned-ffmpeg> --fixture-run <baseline> --output <precision-controls>
python packaging/e2e/photo_lut_attribution.py --exe <exe> --ffmpeg <pinned-ffmpeg> --output <detail-controls> --detail-control
```

The first command deliberately returns nonzero on current develop. Rejected
prototype measurements can be reproduced only in a disposable checkout with
the attached experimental patch, rebuilding/ZIP-extracting there and using the
same main probe. The patch is evidence, not retained application code.

The transition probe adds synthetic control projects only to its isolated
fixture database. Portable `<fixture-data>` chain paths in evidence stand for
that directory. The float formats and rounding flags are analysis interventions;
they do not run in the application. Source/codec controls retain their existing
metric and strip PNG transfer metadata only in explicitly untagged controls.

Final unchanged-production regressions: **23 passed** (preview-frame/API,
actual MP4 LUT/pixel parity, LUT lifecycle/proxy harnesses, preview blit).
Ruff and MyPy on their existing scope pass; analysis scripts compile and run.
JavaScript tooling previously passed **106 tests** during this investigation;
all temporary JS/test changes were reverted. No full local suite or release
smoke was repeated for the retained analysis-only changes. New runtime evidence
is actual packaged WebView2; it is not release/MOTW or human real-media approval.
