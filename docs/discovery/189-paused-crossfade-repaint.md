# Paused crossfade repaint fix (#189 follow-up)

Build: `develop` at `0ee283fe79f0a251c970bfaa86b2decfc21f7458` (includes
#311/#312/#313). This fix is based on the release-validation finding in
[PR #314](https://github.com/Magehawks/orga-drone/pull/314).

**Decision: GO for the bounded paused-crossfade repaint fix. CONDITIONAL/NO-GO
for release-candidate sign-off because the separate LUT crossfade timing
blocker remains.**

## Root cause

After a paused seek into a crossfade, `paintPreviewBlit` could run while the
outgoing `<video>` was `readyState 4`, visible, paused and not seeking, but
before its seeked frame was actually available to `drawImage`. The outgoing
draw therefore contributed black, and the composite became the incoming layer
at transition opacity 0.5 over black: mean **62.09** instead of **124.63**.
No later paint was scheduled when the outgoing frame became presentable, so the
half-bright blit persisted for about 1.2 s until another repaint event.

The packaged paint trace showed the last paint with both layers visible/ready
and both draw calls returning success, yet the captured canvas remained half;
drawing the same outgoing element into a separate canvas at the same moment
produced the correct picture. This isolates the defect to the repaint timing
after the seeked frame becomes presentable, not to transition opacity or the
video source.

## Fix

`showOutgoingLayer` now, for a paused crossfade, registers a one-shot
`requestVideoFrameCallback` on the outgoing video after its seek and calls
`schedulePreviewBlit()` when that frame is presented. It falls back to the
immediate paint when the API is unavailable, and clears the pending flag when
playback starts, pre-roll is cleared, or the layer is hidden. The existing
#312 pre-roll and #313 texel-centre LUT sampling are unchanged.

## Before/after

Packaged Windows onefolder app, WebView2 `Edg/156.0.4314.58`, FFmpeg 9.0.2.
Synthetic 3 s tagged BT.709 clips, 1 s crossfade, story time 2.500 s.

- Fresh fix-build EXE: `0144585c41f4c69d5cc03ede62c1f17e5d68cb1a1a4e44cc003872ad642be9fb`
- Fixed `studio.js`: `78a38d6f0b538f2729c7cc02147ae154af198fb6d1288030ff120de896369cff`
- LUT WebGL resource unchanged: `12d4c18dc59caeffc505a75a5cf9c6f8a730450cdb8bf641a65a6fbc1e50ee12`

| Measurement | Before | After |
| --- | ---: | ---: |
| Blit brightness at 0.05/0.2/0.5/1.0 s | **62.09** all four | **124.63** all four |
| Paused composite vs export, full frame | 60.464 | **1.986** (no LUT) |
| Paused composite vs export, max swatch | 103.000 | **2.667** (no LUT) |
| Paused composite vs export, max swatch with 17-cube LUT | — | **4.000** |
| Repeated runs with correct immediate composite | — | **5/5** (3 no-LUT, 2 LUT) |

The after-fix no-LUT pair drift remained **0.033334 s** in the clock probe,
with zero outgoing seeks. Cut and fade-through-black packaged probes completed
with `NOT_A_CROSSFADE_TRACE` and no errors.

## Regression test

`tests/js/crossfade_clock.test.js` now has:

- a failing-before test that a paused crossfade requests a repaint when the
  outgoing frame is presented;
- the existing tests for playing outgoing playback, paused exact seek, pre-roll
  gating, speed mapping and transition exclusions.

The new test failed on the baseline (no frame callback) and passes with the
fix.

## Priority 2: LUT crossfade timing remains blocked

Repeated packaged 17-cube LUT crossfade runs on the fix build:

| Run | Pair drift max | Outgoing seeks | Fresh outgoing presentations |
| --- | ---: | ---: | ---: |
| 1 | 0.066667 s | 2 | 19 |
| 2 | 0.033334 s | 2 | 20 |
| 3 | 0.066667 s | 2 | 17 |

No-LUT clock runs remained **0.033334 s** with zero outgoing seeks. The LUT
runs still intermittently exceed the one-frame gate. Instrumented traces show
the pre-roll outgoing video starting late/behind under WebGL LUT rendering,
followed by entry corrections that momentarily lag the presented pair. This was
not safely fixed without changing pre-roll/visibility architecture; the
existing pre-roll and LUT sampling fixes were preserved. Do not weaken the
one-frame or LUT parity gates.

## Tests performed

- `npm run check:js` — **106 passed**
- `pytest --ignore=tests/test_pr_journey_smoke.py -q` — **1127 passed, 3 skipped**
- `pytest tests/test_pr_journey_smoke.py -q` — **2 passed**
- Packaged functional E2E — **10/10 journeys**
- Packaged paused crossfade — **3/3 no-LUT, 2/2 LUT immediate full composite**
- Packaged clock — no-LUT **3/3 at 0.033334 s**; LUT **0.0667/0.0333/0.0667 s**
- Packaged cut and fade-through-black — pass
- Packaged LUT creative smoke — **GO_BOUNDED_FIXTURE**
- `ruff check .` and mypy — passed

## Limits

- The paused composite fix is limited to outgoing video frames; photo/title-card
  crossfades retain their existing path.
- The LUT crossfade timing blocker remains; this PR does not claim LUT
  crossfade one-frame parity.
- No new transitions, playback engine, proxy architecture, effects, export
  changes, source media changes, merge or release.

Evidence: [189-paused-crossfade-repaint-evidence](189-paused-crossfade-repaint-evidence/).
