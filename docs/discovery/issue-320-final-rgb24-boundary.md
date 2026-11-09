# Issue #320: final RGB24-boundary experiment

## Decision

**BLOCKED_PO_DECISION. The isolated candidate fails the mandatory detail gate.**
No production or cache changes were made. Stop further precision experiments;
keep the current renderer, issue #320 open and PR #321 Draft/unmerged.

This is the single final alternative authorized by the [Product Owner](https://github.com/Magehawks/orga-drone/pull/321#issuecomment-6726409065).
The previous [rejected float experiment](issue-320-approved-precision-experiment.md)
is historical evidence and was not restored. This run used floating-point LUT
computation followed immediately by explicit RGB24, before scaling/YUV.

The first inspection of the checkpoint found negative detail responses. The
running isolated worker and its FFmpeg child were terminated at that point.
The checkpoint remains **INCOMPLETE**, not relabeled as a completed matrix.
There are 18 indexed quality rows (three fixtures × neutral/graded × three
outputs), plus six completed 1080p performance rows. Additional completed 4K PNG
images and logs are preserved as unindexed artifacts; the interrupted 4K
benchmark is not accepted as a completed workload. The reproduction driver now
stops automatically after the first fixture with a negative response; that
safety guard was added after the measured run and was not rerun. No further
precision variant, production implementation or rendering experiment followed.

## Baseline and identical inputs

- Existing branch: `codex/320-color-parity`, starting head `31592b4`.
- Current remote develop, verified through GitHub: `3d72528126931569ad8490a1a79b94c1326f17f2`.
- `git diff origin/develop -- src tests .github` is empty before/after this work.
  Production LUT builder, still cache version 7, proxy version 3, #319 lifecycle,
  ordering and frontend contracts therefore remain unchanged.
- Pinned FFmpeg SHA-256: `e9041e42f9cb1e1faccae46aa4af03ffd70e11474cc085846abdc3dd6e8aadcf`.
- Existing synthetic 1080p/4K stripe JPG/PNG inputs from the previous detail
  experiment. Pillow decodes each fixture once to RGB24. Both FFmpeg variants
  read the exact same raw file, size, frame rate 30, frame index 0 / PTS 0.
  This deliberately isolates LUT precision from decoder variance. It is not a
  claim to reproduce the application's complete photo/JPEG preparation path.
- Same 17³ synthetic red LUT, creative strength 100%, neutral image controls.
  Grade/HSL/wheels are neutral in this isolated comparison; no production
  strength, conversion or order behavior was changed.
- One FFmpeg filter thread in both variants; identical dimensions, codecs and
  options. RGB24 raw inputs have unknown color metadata, identically on both
  sides; the RGB negotiation and explicit downstream BT.709 range are logged.

Input and decoded-buffer hashes are checked after interruption. Every recorded
input remains unchanged; the fourth decoded fixture also matches its raw file.
The hash manifest covers all retained synthetic PNGs, logs and measurements.
No private source media or application data was touched.

## Exact filter chains and negotiation

Let `L` be this literal filter, resolved relative to the checkout:

```text
lut3d=file=build/issue320-develop-baseline/synthetic-red.cube:interp=tetrahedral
```

A (existing LUT stage): `L`.
B (only authorized candidate): `format=gbrpf32le,L,format=rgb24`.
Neutral A and B both use `null`; no global float path is applied.

The suffix is identical for each A/B pair:

```text
Native RGB: ,scale=W:H,format=rgb24
One-third RGB: ,scale=W/3:H/3,format=rgb24
Native YUV round trip:
,scale=W:H:out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=colorspace=bt709:range=tv,scale=in_color_matrix=bt709:in_range=tv,format=rgb24
2-second encode:
,scale=W:H:out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=colorspace=bt709:range=tv
```

Here `W:H` is 1920:1080 or 3840:2160; one-third dimensions are
640:360 or 1280:720. The JSON checkpoint retains every fully expanded chain,
argv, source path and output name. Negotiation logs show baseline LUT input
`rgb24`; candidate `rgb24 -> gbrpf32le -> lut3d -> rgb24 -> scale`.
Thus the candidate really does return to RGB24 before downstream processing.
The output-YUV control is uncompressed before its RGB measurement; the
performance output uses libx264/veryfast/CRF20 for 60 identical frames.

PNG measurement outputs use one PNG encoder thread. There is no new browser
compositor, WebGL, proxy or export architecture. The one-third outputs are
isolated resampling controls, **not actual DPR1/3 WebView2 captures**.

## Detail results: mandatory failure

The same float64 luma analysis and stripe regions as the previous detail driver
compare normalized gradient energy, fine/broad response and medium/broad
response. Raw mean RGB difference is retained as well. No numeric tolerance was
introduced. Tiny floating-point differences are recorded, but the decision does
not rely on the approximately 1e-14% stripe changes of native constant regions.

Graded YUV-round-trip responses, baseline → candidate:

- 1080p JPG: normalized gradient **−0.06652453813409398%**;
  fine/broad **−0.2963040958792629%**; medium/broad **+0.04282268075894713%**.
- 1080p PNG: normalized gradient **−0.06574652986959251%**;
  fine/broad **−0.2963040958792629%**; medium/broad **+0.04282268075894713%**.
- 4K JPG: normalized gradient **−0.07029552672831452%**;
  fine/broad **−0.2962715836772545%**; medium/broad **+0.04282716861752078%**.

Native graded 1080p JPG gradient also changes **−0.0026232327754116547%**;
its mean RGB error is **0.8357253086419753**. One-third graded gradient responses
increase by approximately **0.252–0.253%**. These gains do not cancel the native
YUV response losses. All nine indexed neutral image pairs are pixel-identical.
See all absolute metric values and images in the evidence, including the
unindexed 4K PNG outputs preserved at interruption.

These are measured response changes, not a claim of universal visible blur or
proof of a specific perceptual resolution loss. Explicit RGB24 return does
**not** demonstrate the required no-degradation result. The candidate is
therefore rejected at the isolated gate.

## Performance and memory: partial evidence only

The already-completed isolated 1080p encoder control has three serial repeats
per variant, alternating the first runner. Arithmetic mean wall time:
**2.4195295333326308 s → 2.1358303999998802 s (−11.725384188304854%)**.
Maximum observed FFmpeg peak working set:
**593.68359375 MiB → 624.41015625 MiB (+30.7265625 MiB, +5.175578847634266%)**.
All absolute per-run timings and memory values remain in the checkpoint.

Memory is sampled every 5 ms, using Windows process peak working set where
available. This standalone FFmpeg process has no application worker/browser
memory included. Wall time includes process launch and PNG-independent MP4
encoding. These static two-second controls do not establish an application
speedup, material-cost acceptance or real-project upper bound.

4K timing/memory, cold application stills, proxies, cache hits and two
simultaneously cold 4K owners were **not completed**. No performance/memory PASS
is claimed. Continuing those experiments after the failed quality gate would
contradict the required early stop.

## Strict color parity and regression safety

No candidate application build was made. The queued isolated swatch/reference
comparison was not reached. Therefore **no new color improvement is claimed**;
there are no candidate strict PASS results. The established actual packaged
baseline remains historical, unchanged and FAIL at the unchanged ≤3.0 gate:

- Neutral JPG: **4.333333333333333**, FAIL.
- Neutral PNG: **4.666666666666667**, FAIL.
- Different-LUT photo crossfade: **3.313218390804598**, FAIL.
- Photo → video: **4.0**, FAIL.
- Video → photo: **3.6666666666666665**, FAIL.

Actual Windows WebView2 candidate preview/export parity, DPR1/3 captures,
transitions, simultaneous-owner memory, cache invalidation and packaged
functional validation were **not run**, because implementation was never
permitted past the isolated failure. Historical results are not represented as
new candidate measurements. There is no waiver for remaining strict failures.

Current unchanged production regression checks: **39 focused tests PASS**
(LUT, pixel parity, preview stills, proxies and JS lifecycle harness);
`ruff check .` PASS; MyPy PASS, 78 source files. No JavaScript module changed.
The full suite, general packaged journey, real-media PO test and release/MOTW
checks were not repeated for this analysis-only update. The previous experiment
and its checks remain separately labeled historical evidence.

No production/cache rollback was necessary: no production edits were made.
No selective cache tests were added for a pixel contract that was never
implemented. Source hashes, #319 code, grade/LUT/HSL/wheel order, no-double-LUT
behavior and per-tick request logic are preserved by the empty production diff;
this is a code-integrity statement, not a new packaged runtime certification.
DE/EN UI strings are unchanged and not applicable. No merge, release or tag.

## Reproduction and evidence

Analysis driver: `packaging/e2e/studio_lut_rgb24_boundary.py`.
It expects the previous synthetic fixture directories already present and a
**new** output directory. This records reproduction only; do not continue
precision experiments under this task.

```powershell
python packaging/e2e/studio_lut_rgb24_boundary.py --root . --ffmpeg packaging/third_party/ffmpeg-gpl/bin/ffmpeg.exe --output build/final-rgb24-isolated-reproduction
```

The checked-in guard stops on negative response after the first fixture, earlier
than the manually interrupted original run. That difference is intentional and
not a new measured result. Analysis dependencies are Pillow/NumPy/psutil; no
application dependency was added. Original fixtures come from
`studio_precision_quality.py` and the earlier packaged swatch probe.

[Raw interrupted checkpoint](issue-320-color-parity-evidence/final-rgb24-boundary/interrupted-checkpoint.json),
[decision and absolute/percentage summary](issue-320-color-parity-evidence/final-rgb24-boundary/summary.json),
[SHA-256 manifest](issue-320-color-parity-evidence/final-rgb24-boundary/manifest.json).
A scoped `.gitattributes` rule disables text normalization for this evidence
folder so raw checksums survive Git storage and checkout. Logs are copied
verbatim with `.txt` extensions; checkpoint `.log` names map
to the same basename `.txt`. PNG outputs are included. Raw decoded buffers and
benchmark MP4s remain local in ignored `build/`; they are not release artifacts.

Independent read-only ChatGPT review returned **REVIEW_APPROVED for the
analysis/evidence update only** after independently recomputing the three YUV
detail losses and checking all 107 manifest entries against staged Git blobs.
Its checksum/line-ending finding was corrected with the scoped attributes rule.
This does not approve the failed candidate or replace the human product/merge
decision. Renewed review is also requested on the existing GitHub PR.
The remaining risk is unresolved strict parity; the working renderer is
preserved. There is no further precision alternative proposed by this task.
