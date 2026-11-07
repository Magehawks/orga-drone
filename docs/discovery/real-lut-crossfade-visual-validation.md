# Real DJI LUT crossfade visual validation

Tested candidate: `develop` at `c97ac2ef71dd9f7c4492ac26189e31527106b5a6`.
Collection date: 2026-11-07. Fresh onefolder build prepared on 2026-11-06.

**CONDITIONAL GO for focused human release-candidate testing only. NO-GO for
release sign-off or a claim of one-frame LUT crossfade/color parity.** The strict
existing timing and color gates remain unchanged and unmet/unproven as described
below. This record does not authorize merge or release.

## Finding and classification

The remaining synchronization problem is measurable on original DJI footage.
In this 4K/50 fps workload it also occurs without a LUT, so the evidence does not
isolate a LUT-specific cause. All four combinations exceed the existing one
30 fps frame (33.333 ms) timing gate. Offline application MP4 exports have the
correct five-second duration and transition alignment against an independently
constructed FFmpeg reference; no export-visible defect was demonstrated.

- **A - demonstrated:** preview presented-frame drift with no demonstrated
  LUT-specific visible defect causally attributable to that drift. This is not a finding
  that visual defects are absent.
- **B - demonstrated, bounded to captured output:** a held/stale preview crop in
  the **no-LUT control**, while the time-matched export changes. This occurred
  under recording load and does not establish an uninterrupted whole-display
  freeze or a LUT-specific cause. See the three-sample proof below.
- **C - not demonstrated:** export-visible glitch or incorrect transition output.
  The tested exports match zero temporal offset best against the independent
  reference. This is bounded evidence, not universal export certification.
- **D - remaining limitation:** whether the intermittent pair drift itself is
  perceptible to a human, and whether other footage/devices/LUTs produce visible
  defects, remains inconclusive. Do not substitute automated test success for
  that judgment.

## Preparation and prior findings

Read `AGENTS.md`, `docs/AGENT_WORKFLOW.md`, the packaging instructions and the
Studio module/architecture documents. Reviewed merged PRs
[#312](https://github.com/Magehawks/orga-drone/pull/312),
[#313](https://github.com/Magehawks/orga-drone/pull/313),
[#314](https://github.com/Magehawks/orga-drone/pull/314), and
[#315](https://github.com/Magehawks/orga-drone/pull/315), plus issues
[#189](https://github.com/Magehawks/orga-drone/issues/189) and
[#267](https://github.com/Magehawks/orga-drone/issues/267).

#312 started and pre-rolled the outgoing layer; #313 corrected LUT texel-centre
sampling; #314 recorded the half-bright paused composite and remaining LUT
variance; #315 repainted after outgoing frame presentation but explicitly left
LUT timing above one frame unresolved. This validation starts after all four.
No production code, database schema, timing tolerance or color tolerance changed.

`origin/develop` was freshly fetched before branching and checked again after
the interruption; it still pointed to the tested candidate. Interrupted and
sandbox-blocked attempts are excluded from the final repeated-run counts.

## Environment and provenance

- App 2.3.3; Python 3.12.3; PyInstaller 6.22.3; pywebview 6.2.1.
- Windows 11 Pro 10.0.26300; Ryzen 7 5700X, 8 cores/16 threads;
  approximately 32 GiB RAM; Radeon RX 6700 XT driver 32.0.21045.16010.
- WebView2 `Edg/156.0.4314.58`; bundled FFmpeg 9.0.2.
- Fresh unchanged `packaging/orga-drone.spec` onefolder build. A pre-existing
  isolated dependency venv was reused with `PYTHONPATH` set to this checkout's
  `src`; all 76 packaged Orga Drone Python module paths in PyInstaller's analysis
  were verified to resolve to this checkout. Packaged JS matches source bytes.
- EXE SHA-256:
  `49966e2b46a5519e471741a3ff86186a94943a042cbf9a8e97e5c0646ca4ea6a`.
- Packaged `studio.js`:
  `6c20bdcaa497bd559368ac5278428be49606a318774d7c98315fadb180519618`.
- Packaged `studio-lut-webgl.js`:
  `12d4c18dc59caeffc505a75a5cf9c6f8a730450cdb8bf641a65a6fbc1e50ee12`.
- Original media decoded at 4K. Preview canvas 640x360, 1500x1000 diagnostic
  viewport; actual application export at 1280x720, 30 fps, Best quality.
- Native packaged Windows/WebView2 app, using existing opt-in E2E/CDP support,
  not a standalone Chrome test. The production server/path checks are unchanged.
- Separate isolated app data per scenario; the normal user database was only
  queried read-only to locate footage. Selected original files stayed in place.

This was not a ZIP/MOTW/native-dialog release smoke test. No installer, release
workflow, upload or distribution was exercised.

## Footage and Story

Two original MP4 files identify their encoder as DJI Avata2; the read-only
library index identifies DJI Avata 2 / FC8485. Both are **3840x2160 H.264 High,
50 fps, yuv420p, BT.709 limited range**, approximately 130 Mbit/s. These are real
outdoor recordings with moving natural detail, not synthetic video. Full frames
also contain identifiable surroundings; those captures remain local.

| Alias | Indexed duration | Bytes | Source SHA-256 |
| --- | ---: | ---: | --- |
| A, outgoing | 109.778 s | 1846699867 | `432dcb948b8c50f43abd469e416aad5899bff8223dd3e79cbcb199663f50aaa9` |
| B, incoming | 223.656 s | 3779441351 | `e7836017531be29fed00b8370872f957be208f7c3f165f1dd8b88a90cdce8261` |

Both clips use source range 10-13 seconds, normal speed and one repeat. A linear
one-second crossfade runs from Story 2-3 seconds; Story duration is five seconds.
No soundtrack, overlays, masks, other grades, conversion LUT, HDR or slow motion
was enabled. Whole-file SHA-256 hashes matched after the batch.

LUTs are deterministic **test creative LUTs**, not manufacturer conversion LUTs:
17^3 cubes with `output = 0.1 + input x slope`; red slopes `(0.8, 0.5, 0.4)` and
blue slopes `(0.4, 0.5, 0.8)`, at 100% creative strength and Rec.709 input profile.
The footage is real; the test LUT transforms are synthetic. Same/different LUT
runs confirmed the existing WebGL path active. Mixed means LUT on outgoing A,
none on incoming B; the reverse direction was not tested.

## Coverage and method

Each of four LUT combinations received:

1. Ten continuous playbacks beginning near Story 1.3 s, through both boundaries.
2. Ten playbacks starting directly near Story 2.25 s inside the overlap.
3. Ten paused seeks each to requested 25%, 50%, 75% overlap progress (30 captures).
4. One actual application MP4 export of that same persisted Story.
5. Boundary/overlap preview captures and a separate captured playback comparison.
6. Supplemental paused captures at exact Story 2.0, 2.2, 2.5, 2.8 and 3.0 s.
7. Ten additional cropped visual continuous runs and ten cropped start-inside
   runs per combination: **80 additional visual runs**, kept separate from
   the 80 instrumented timing runs. All capture timestamps were saved.

Timing observations use the existing `requestVideoFrameCallback` metadata for
both video elements, sampled with `requestAnimationFrame`. Fresh, ready,
non-seeking, visible pairs are required. Since A starts two Story seconds before
B, pair drift is `abs(incoming.mediaTime + 2 - outgoing.mediaTime)`. These are
presented-element observations, not readback of the exact two source frames
sampled by each WebGL/composite draw and not a measurement of display photons.

The outgoing seek count is the seeking-event counter delta between sampled
first/last overlap observations. It can omit an entry event before the first
sample; it is not a claim of an exact event-time trace. Whole-run deltas and
per-run results are retained. Callback lateness is `max(0, callbackNow -
expectedDisplayTime)`. Decoder `processingDuration` is separately reported and
must not be interpreted as an equivalent visible stall.

The instrumented timing batch ran before the regression suite. An earlier
interrupted batch with overlapping checks is excluded. Full-image capture is
separate from timing measurements. Capture intervals are recorded; an image
capture gap alone does not prove a frozen UI. Part of the supplemental cropped
visual batch overlapped a stalled sandbox journey-smoke process; it is not used
as a controlled latency benchmark. The timing batch did not overlap that check.

## Repeated-run measurements

Numbers below are maximum pair drift in **milliseconds**, run order 1-10.
Every start-inside run in every combination measured 40 ms. All 80 measured
playbacks exceeded the unchanged 33.333 ms timing gate (one native 50 fps frame
is 20 ms, so those failures are also above one source frame).

| Combination | Continuous runs 1-10, ms | Observed outgoing seek deltas, continuous | Start-inside seek deltas |
| --- | --- | --- | --- |
| No LUT | 80, 40, 80, 40, 80, 160, 40, 80, 40, 80 | 2, 2, 2, 2, 2, 3, 2, 2, 2, 2 | all 0 |
| Same red LUT | 40, 80, 40, 80, 80, 40, 80, 40, 160, 40 | 1, 2, 1, 2, 2, 1, 2, 1, 2, 1 | all 0 |
| Different red/blue LUTs | 80, 40, 40, 80, 40, 40, 40, 80, 40, 40 | 2, 1, 2, 2, 1, 1, 1, 2, 2, 1 | all 0 |
| Red LUT to no LUT | 80, 80, 40, 40, 80, 80, 40, 80, 40, 40 | 2, 2, 1, 1, 2, 2, 1, 2, 2, 1 | all 0 |

| Combination | Maximum full callback gap during overlap, incoming/outgoing | Maximum callback lateness, continuous run | Maximum decoder processing, continuous run |
| --- | --- | ---: | ---: |
| No LUT | 83.3 / 121.0 ms | 37.5 ms | 148.9 ms |
| Same LUT | 79.1 / 116.7 ms | 41.8 ms | 316.1 ms |
| Different LUTs | 91.8 / 129.2 ms | 62.5 ms | 357.0 ms |
| LUT to no LUT | 75.1 / 175.0 ms | 33.2 ms | 131.0 ms |

Full callback gaps are derived from all recorded callbacks assigned to overlap
using the next sampled Story observation; boundary assignment has sampling
uncertainty. Lateness/decoder maxima cover the whole continuous run, including
entry, rather than just the overlap. Per-run p95 drift, sample counts, fresh
presentations and both forms of seek delta are in
[summary.json](real-lut-crossfade-evidence/summary.json). A sanitized worst-run
numeric timing trace per combination is included for independent inspection.

## Preview versus export frames

Regular ruler clicks have pixel rounding: requested 2.5 s landed near 2.49924 s.
Supplemental captures call the same ruler handler with an exact fractional
coordinate; they do not set internal Story clocks or video times directly.
Export comparisons use explicit frame indexes 66/75/84 at Story 2.2/2.5/2.8 s.
At 2.5 s, the browser reported presented source frames at 10.48/12.48 s, 20 ms
earlier than the desired 10.5/12.5 s. This is retained as evidence, not hidden by
matching a more convenient export frame. Quarter-progress regular captures also
have native/output frame-grid differences (50 versus 30 fps).

| Combination | Whole-frame preview/export MAE at exact Story 2.2 / 2.5 / 2.8 s, RGB levels |
| --- | --- |
| No LUT | 8.771 / 11.724 / 10.600 |
| Same LUT | 6.230 / 7.599 / 14.806 |
| Different LUTs | 6.199 / 7.583 / 14.191 |
| LUT to no LUT | 6.630 / 7.761 / 10.640 |

These moving-image errors combine timing, source-frame selection, scaling,
compression and browser/FFmpeg color paths. They are **not** a replacement for
the existing static-swatch strict 3/255 or baseline-plus-1.5 gates. No gate was
recalibrated, relaxed or declared passed using these values.

## Export-specific check

An independent FFmpeg graph reads the original 10-13 s ranges, scales to 720p,
converts to 30 fps limited-range BT.709, applies the configured test cubes with
tetrahedral interpolation, and performs a linear `xfade` at offset 2 s for 1 s.
It does not call the application encoder or its stitch helper. Both reference
and application output are decoded to 640x360 RGB for comparison.

| Combination | Transition mean / maximum per-frame mean RGB error | Mean error with application output shifted -1 / 0 / +1 frames |
| --- | --- | --- |
| No LUT | 2.706 / 3.102 | 16.369 / 2.706 / 15.423 |
| Same LUT | 3.084 / 3.534 | 9.856 / 3.084 / 9.051 |
| Different LUTs | 3.083 / 3.548 | 9.856 / 3.083 / 9.037 |
| LUT to no LUT | 2.871 / 3.545 | 12.303 / 2.871 / 11.713 |

Every application export decodes to 150 frames (five seconds), with no all-black
frames (whole-frame mean below 1/255) or byte-identical adjacent decoded frames.
The best tested temporal offset is zero for every combination, including the
wider -3 to +3 frame search. This supports correct export transition timing and
composition for these Stories; it does not prove all possible export effects or
colors are correct. The oracle shares FFmpeg with the application and is not an
independent codec implementation.

## Human-reviewable evidence

Public images/videos contain only a reviewed 200x160 upper-right tree/sky crop
from the 640x360 preview. This protects people, homes and precise-location
context present elsewhere in the real frames. The full-frame measurements were
computed before cropping. Crops can conceal a defect outside that region.

- [No LUT frame comparison](real-lut-crossfade-evidence/none-sanitized-exact-comparison.png)
  / [short comparison video](real-lut-crossfade-evidence/none-sanitized-preview-export.mp4)
- [Same LUT frame comparison](real-lut-crossfade-evidence/same-sanitized-exact-comparison.png)
  / [short comparison video](real-lut-crossfade-evidence/same-sanitized-preview-export.mp4)
- [Different LUT frame comparison](real-lut-crossfade-evidence/different-sanitized-exact-comparison.png)
  / [short comparison video](real-lut-crossfade-evidence/different-sanitized-preview-export.mp4)
- [LUT to no LUT frame comparison](real-lut-crossfade-evidence/mixed-sanitized-exact-comparison.png)
  / [short comparison video](real-lut-crossfade-evidence/mixed-sanitized-preview-export.mp4)

Images show preview, indexed export and unamplified absolute difference at the
same nominal Story timestamp. Videos preserve recorded capture wall intervals to within 0.5 ms after decoding
verification (1 ms input/output timebase, all capture frames retained, plus one
terminal duplicate to close the last interval);
the export panel uses the nearest 30 fps frame to the recorded Story time,
labelled on screen. They are sampled comparisons, not native screen recordings.
One full-frame visual run per combination contains 4-8 identical adjacent capture
pairs, mostly 33 ms apart. Some occur while Story advances and the export changes;
others occur on a Story plateau. The visual runs also have capture gaps up to
345.5 ms. Neither fact alone establishes how long the displayed picture froze.

### Repeated visual output and bounded preview hold

All 80 additional cropped visual runs completed (10 continuous + 10 start-inside
per combination), with no all-black crop samples. The maximum span between
identical sampled overlap crops was 124.9 ms without a LUT, 79.3 ms with the same
LUT, 41.6 ms with different LUTs, and 70.7 ms for LUT to no LUT. These spans are
not asserted continuous freeze durations. The repeated crop records and per-run
brightness/interval data are in
[repeated-visual-summary.json](real-lut-crossfade-evidence/repeated-visual-summary.json).

The no-LUT continuous run 5 recorded **three pixel-identical crops**, indices
23/24/25, at 15940.2/15973.5/16065.1 ms. Story changed from 1.99710 to 2.25860 s;
the corresponding export crop changed by mean 20.092 RGB levels. This
establishes a held/stale **sampled preview output** versus the export, category
B for this recorded control. The largest intervening capture gap is 91.6 ms,
so the samples cannot prove there were no unseen updates, or that the whole
display froze continuously for 124.9 ms. Recording overhead remains a possible
contributor; the result does not isolate LUT synchronization as its cause.

- [Six-frame proof strip](real-lut-crossfade-evidence/none-held-crop-proof.png)
- [Normal-speed recorded comparison](real-lut-crossfade-evidence/none-held-crop-comparison.mp4)
- [Matching timestamps and identical-pixel hashes](real-lut-crossfade-evidence/none-held-crop-proof.json)

No all-black full-frame capture or recurrence of the old half-bright paused
composite was demonstrated in the inspected captures. No brightness flash or
export boundary discontinuity was identified in the inspected frame comparisons;
that observation is limited to the sampled views. Human review of uninstrumented,
full-frame playback remains necessary before declaring intermittent flashes,
frozen frames or other boundary artifacts absent. The LUT-enabled drift remains
A plus D for its causal visual impact, rather than being promoted to B based on
callback delays alone.

Full local evidence is under `build/real-lut-20261107/`: original isolated Story
databases, reports, raw callbacks, full-frame paused/captured comparisons, actual
application exports, and independent-reference results. This directory contains
private paths/images and must not be uploaded or staged.

## Reproduction and checks

The evidence directory contains one-off collection and comparison scripts.
Run from the repository root with its dependencies and `PYTHONPATH=src`:

```powershell
python docs/discovery/real-lut-crossfade-evidence/collect.py --exe <onefolder-exe> --source-a <original-A> --source-b <original-B> --duration-a 109.778 --duration-b 223.656 --output-dir <fresh-private-directory> none same different mixed
python docs/discovery/real-lut-crossfade-evidence/capture_exact.py --exe <onefolder-exe> --evidence-dir <private-directory>
python docs/discovery/real-lut-crossfade-evidence/capture_repeated.py --exe <onefolder-exe> --evidence-dir <private-directory>
python docs/discovery/real-lut-crossfade-evidence/analyze_repeated.py --evidence-dir <private-directory>
python docs/discovery/real-lut-crossfade-evidence/render_comparisons.py --evidence-dir <private-directory>
python docs/discovery/real-lut-crossfade-evidence/verify_exports.py --evidence-dir <private-directory> --source-a <original-A> --source-b <original-B>
```

Validate source format/duration before using other files; the collector seeds
only the two read-only references into a new isolated index and is tailored to
this 4K/50 fps case. Outputs contain private media derivatives and are not safe
to share automatically. Review every crop for privacy with any new footage.
The committed CLI scripts are parameterized/formatted versions of the local
one-off collectors; the instrumented batch used the equivalent local recorder.

- Ruff: passed.
- MyPy required target: passed, 78 source files.
- Python suite excluding journey smoke: **1127 passed, 3 skipped**, 450.98 s.
- Journey smoke: **2 passed**, 5.08 s.
- JS checks: not rerun; no Studio JS or `tests/js/` changes.
- Timing and color gates: retained; timing fails on this workload; moving-image
  comparisons do not certify the existing color gate.
- Independent evidence review: **REVIEW_APPROVED** after movie-cadence and text-encoding corrections; human product test remains pending.

## Release impact and handoff

Proceed with **focused human RC exploration**, not release sign-off. The human
should watch continuous and start-inside crossfades repeatedly at normal speed,
inspect 25/50/75% paused states, and compare the same application exports.
Escalate a demonstrated preview glitch as B and an export defect as C; retain
A when only drift is demonstrated and D when the view is insufficient.

The strict timing failure and unresolved real-motion preview parity remain
release-quality limitations. Do not label the LUT crossfade fully synchronized,
do not weaken the gate, and do not infer a LUT-specific regression from this
4K/50 fps result relative to prior synthetic 720p/30 fps fixtures. HEVC/10-bit,
D-Log M conversion, HDR, other creative LUTs/sizes, reverse mixed direction,
4K exports, audio synchronization and other machines are untested.

**Final recommendation: CONDITIONAL GO for manual release-candidate testing;
NO-GO for release approval or parity sign-off.**
