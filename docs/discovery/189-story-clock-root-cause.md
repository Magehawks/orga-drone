# Story/media clock sampling: root cause and bounded fix (#189)

**GO for the bounded primary Story clock sampling fix. NO-GO for claiming full
crossfade outgoing/incoming pair parity.** This change only samples the existing
canonical video-to-Story mapping during the preview paint tick. It does not add a
transition, effect, Dehaze control, or new playback mode, and does not change
grade, LUT, source, or export semantics.

## Problem

The packaged Windows Studio preview advanced `state.projectTimeS` from the
video element's native `timeupdate` event. WebView2 156.0.4314.58 delivers that
event at roughly 4 Hz. Between events the visible primary frame can advance while
the Story playhead and playlist clock stay on the previous value. A crossfade
made the difference visible:

- primary Story drift reached **0.264 s**;
- the longest Story plateau reached **296 ms**.

The existing preview paint scheduler already runs on `requestAnimationFrame`, so
the canonical media-to-Story mapping is available at display cadence without a
new timer.

## Inherited candidate and why it was rejected

Codex had a candidate patch that called the full `onVideoTimeUpdate()` from the
paint callback. It reduced primary drift to **0.0094 s** and the longest plateau
to **53 ms**, but it also called `applyTransitionPreview()` every frame. During a
crossfade that reaches `showOutgoingLayer()`, which assigns
`previewVideoB.currentTime` on every call. The outgoing video therefore entered a
seek storm:

- outgoing `seeking` events: **191** during the trace (baseline: **3**);
- fresh outgoing frame presentations: **0** (baseline: **3**);
- stable presented outgoing/primary pairs: **0** (baseline: **155**).

The candidate fixed the playhead by breaking the outgoing crossfade picture. It
was not shipped.

## Root cause

Two existing behaviors combined:

1. The primary clock is only updated by `timeupdate`, which is coarse in
   WebView2.
2. `onVideoTimeUpdate()` does more than advance the clock: it also runs
   transition preview synchronization, which seeks the paused outgoing video.
   Calling it from the paint tick couples frame-rate clock sampling to
   frame-rate seeking of the outgoing layer.

## Bounded fix

`studio.js` now extracts the existing video-to-Story mapping into
`videoStoryPosition()` and samples it from `syncStoryClockFromVideo()` on the
preview paint tick. The new path:

- uses the same source-in, speed, section-repeat, loop and LUT-proxy mapping as
  `onVideoTimeUpdate()`;
- updates only `state.projectTimeS` and the playhead chrome;
- skips while seeking, paused, hidden, ended, suppressed, in reuse draft, or on
  the wall clock;
- leaves transition layers, music sync and boundary handling on their existing
  `timeupdate` path.

This keeps the primary picture and Story playhead together without re-running
the outgoing crossfade seek on every frame.

## Before/after packaged measurements

Same packaged Windows onefolder app, synthetic 30 fps crossfade, real WebView2,
existing cut/crossfade APIs only. The only difference between runs is the
`studio.js` resource inside the copied app directory. The EXE and export are
unchanged.

| Measurement | Baseline | Candidate (rejected) | Bounded fix |
| --- | ---: | ---: | ---: |
| Primary Story drift max | 0.264 s | 0.0094 s | **0.0007-0.0021 s** |
| Story plateau max | 296 ms | 53 ms | **185-191 ms** (seek at crossfade entry) |
| Outgoing seeking events | 3 | 191 | **3-5** |
| Fresh outgoing presentations | 3 | 0 | **3** |
| Stable presented pairs | 155 | 0 | **125-137** |
| Presented pair drift max | 0.267 s | n/a | 0.233 s |
| Presented pair drift p95 | 0.234 s | n/a | 0.233 s |

The fix range is from three independent packaged runs (619, 618 and 610 samples). The
summary only counts primary drift when the incoming layer is ready, visible,
not paused, not seeking, and has switched away from the outgoing source. Without
that filter, a trace that sampled the still-loading primary at crossfade entry
reported a misleading 0.18 s outlier. The probe and its regression tests now
reject that unready sample instead of treating it as clock drift.

The only plateau above 53 ms after the fix is a **185-191 ms** pause while the
primary video is loading or seeking at crossfade entry (`readyState 0-1`; the
outgoing layer is also seeking).
Every other sampled plateau is below 53 ms. Treating a seeking video as a clock
source would be wrong, so this is expected behavior rather than a remaining
clock drift.

### Crossfade outgoing follow-up

The previously remaining outgoing crossfade drift was investigated separately
after this change. [Crossfade synchronization](189-crossfade-sync.md) records the
paused-outgoing root cause, the bounded play/pre-roll fix, and packaged WebView2
before/after measurements. LUT crossfade parity and the separate #267 LUT gap
remain unclaimed.

## Regression coverage

- `tests/js/clock_tick.test.js` loads the legacy `studio.js` as text and runs the
  canonical clock/paint functions in a VM.
  - Baseline failed: paint tick left Story at **0** instead of **5**, and the LUT
    proxy case stayed at **0** instead of **5.75**.
  - After the fix: both pass, and the paint tick calls no transition preview.
  - Native `timeupdate` still runs transition/music sync.
  - Paused, seeking, hidden, not-ready, suppressed, wall-clock and reuse-draft
    clocks never advance Story time during paint.
- `packaging/e2e/clock_tick_probe.cjs` is the explicit diagnostic. It failed on
  the baseline and passes with the bounded fix.
- `packaging/e2e/studio_clock_probe.py` reproduces the packaged measurements and
  records presented frames with `requestVideoFrameCallback`; it never sets source
  or Story time.
- `tests/test_studio_clock_probe.py` covers the summary rules: empty traces,
  non-crossfade traces, unready primary samples, the entry-sample exclusion, and
  missing presented frames never becoming a zero-error observation.

## Reproduce

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[dev]'
node packaging/e2e/clock_tick_probe.cjs
node --test tests/js/clock_tick.test.js
```

Packaged probe (use a fresh output directory):

```powershell
.venv/Scripts/python packaging/e2e/studio_clock_probe.py `
  --exe dist/orga-drone/orga-drone.exe `
  --ffmpeg (Get-ChildItem dist/orga-drone/_internal/imageio_ffmpeg/binaries/ffmpeg*.exe | Select-Object -First 1).FullName `
  --output-dir build/189-clock-after
```

The packaged functional harness also passed all ten existing journeys
(startup, import, library navigation, Studio open, playback, edit persistence,
video export, image export, source integrity, relaunch persistence) with the
fixed resource. Local provenance only; not release evidence.

## Checks

- `npm run check:js` — lint, format, and **95 tests** passed.
- `pytest --ignore=tests/test_pr_journey_smoke.py` — **1103 passed, 3 skipped**.
- `pytest tests/test_pr_journey_smoke.py` — **2 passed**.
- `ruff check .` and the mypy target — passed.
- The packaged probe and the packaged functional harness ran against the same
  unmodified `develop` base with only the test build's `studio.js` replaced.

## Limits and decision

- No new transitions, LUTs, color changes, Dehaze, or export behavior.
- No HDR, wide-gamut, variable-frame-rate, or cross-machine decoder claim.
- The crossfade outgoing follow-up is documented in
  [189-crossfade-sync.md](189-crossfade-sync.md); LUT parity remains unclaimed.
- No merge or release is authorized by this document.
