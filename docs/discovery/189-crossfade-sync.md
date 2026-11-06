# Crossfade outgoing/incoming synchronization (#189)

**GO for the bounded crossfade synchronization fix. NO-GO for claiming LUT
crossfade parity or full preview/export parity.** This change keeps the existing
crossfade model, renderer, FFmpeg export, project format, and transition types.
It only fixes the outgoing video layer's paused seek behavior during playback.

## Problem

After the primary Story clock fix in #311, packaged WebView2 measurements still
showed the outgoing crossfade picture lagging the incoming picture by about
**0.267 s** (eight 30 fps frames). The Story playhead tracked the incoming media,
but the outgoing layer was not presenting up-to-date frames.

## Reproduction

Synthetic 30 fps fixtures, one 1 s crossfade, existing cut/crossfade APIs only,
packaged Windows onefolder app with WebView2 `Edg/156.0.4314.58`, bundled FFmpeg
9.0.2. The baseline and fixed runs used the **same EXE** and the **same exported
MP4**; only the packaged `studio.js` resource differed.

- EXE SHA-256: `0cd47f35a3e98e5b80f3976a8e0bdb49e972c811ffacc8f69040c5aac2ed7930`
- Baseline packaged `studio.js`: `0e7a2339c704891dc2c38592eabe51cce1c858c0d4f4fe24076b11da070be201`
- Fixed packaged `studio.js`: `48e7136ad7bca1b67f8cc2fcafb3f459f322d54d9d6cef4b324e4981abce29cd`
- Export SHA-256 (unchanged): `8d2f98cdc1481d76cd63635b32388d1b40ca9886bf763e7b48b9a43b64d65ba2`
- Source files unchanged in both runs.

The probe captures actual `requestVideoFrameCallback` presentation timestamps,
`currentTime`, `paused`, `seeking`, `readyState`, Story time, opacity, and
`seeking`/`seeked` event counts. It does not set video or Story time.

## Root cause

`showOutgoingLayer()` assigned `previewVideoB.currentTime` on every native
`timeupdate` (about 4 Hz) but never played the outgoing video. Between those
events the outgoing element was paused and presented no new frames. During a
1 s crossfade this produced only **3** outgoing presentations; the presented
frame aged while the incoming video advanced, reaching a **0.267 s** pair gap.

Starting playback at the crossfade entry was not sufficient by itself. The first
seek/load completed after Story time had advanced, leaving a persistent
0.04-0.06 s offset (one to two frames). Correcting that by re-running the full
primary clock path on every paint frame was the rejected #311 candidate: it
produced **191** outgoing seeking events and **0** stable presented pairs.

## Bounded fix

1. **Play the outgoing crossfade video** while the Story is playing. Its
   existing seek correction only runs when drift exceeds 0.04 s.
2. **Keep paused seeking exact**: when the Story is paused, the outgoing video
   pauses and seeks to the exact requested time.
3. **Pre-roll the outgoing layer** for up to 0.5 s before a crossfade. It is
   loaded, muted, hidden, played, and corrected whenever it drifts more than
   0.02 s from the mapped source time. At crossfade entry it is already presenting the right frame, so the
   first visible frames do not wait for a load/seek.
4. **Clear the pre-roll** on pause, user seek, clip change, cut, fade-through
   black, or loop blend. Loop blends continue to use their existing
   `showLoopIncoming()` path.

This preserves #311's primary clock sampling and leaves the export path
untouched.

## Before/after measurements

| Measurement | Baseline | Fixed run 1 | Fixed run 2 |
| --- | ---: | ---: | ---: |
| Presented pair drift max | **0.266667 s** | **0.033334 s** | **0.033334 s** |
| Presented pair drift p95 | **0.266667 s** | **0.033334 s** | **0.033334 s** |
| Outgoing seeking events in overlap | 3 | **0** | **0** |
| Fresh outgoing presentations | 3 | **23** | **23** |
| Stable presented pairs | 138 | **96** | **95** |
| Primary Story drift max | 0.002498 s | 0.002600 s | 0.001103 s |
| Story plateau max | 183.2 ms | 191.5 ms | 191.6 ms |
| Paused-seek primary error | 0.0000013 s | 0.0000013 s | 0.0000013 s |
| Paused-seek outgoing error | 0.0000013 s | 0.0000013 s | 0.0000013 s |
| Paused-seek progress error | 0.0000023 | 0.0000023 | 0.0000023 |

One 30 fps frame is 0.033333 s. The maximum pair drift is exactly one frame; the
p95 is also one frame. The 185-192 ms primary plateau is the existing primary
seek/load at crossfade entry, not a regression from this change.

Paused-seek outputs were also compared pixel by pixel:

- all seven `seek-*.png` captures are **pixel-identical** to baseline;
- primary, outgoing and transition-progress errors are at or below **0.0000023**.

Cut and fade-through-black packaged probes completed with
`NOT_A_CROSSFADE_TRACE` and no errors. The packaged functional harness passed all
ten existing journeys (startup, import, navigation, Studio open, playback, edit
persistence, video export, image export, source integrity, relaunch).

## Regression coverage

- `tests/js/crossfade_clock.test.js`:
  - baseline failed because the playing outgoing layer stayed paused and was
    seeked unnecessarily;
  - playing crossfade now starts the outgoing video, keeps its speed mapping,
    and does not seek when the target already matches;
  - paused crossfade pauses and seeks exactly;
  - pre-roll starts only near a video crossfade, skips cut/fade-black/loop
    blends and active overlaps, and keeps the speed mapping.
- `tests/test_studio_clock_probe.py`: summary filtering plus paused-seek and
  progress-error fields.
- `packaging/e2e/studio_clock_probe.py`: records the additional paused-seek and
  progress metrics and accepts `fade_black` for the preserved-behavior probe.

## Tests performed

- `npm run check:js` — lint, format, **103 tests passed**
- `pytest --ignore=tests/test_pr_journey_smoke.py -q` — **1122 passed, 3 skipped**
- `pytest tests/test_pr_journey_smoke.py -q` — **2 passed**
- `pytest tests/test_studio_clock_probe.py tests/test_studio_transition.py -q` —
  **27 passed**
- `ruff check .` — passed
- `mypy src packaging/itch_channel.py packaging/windows_third_party.py` — passed
  (78 files)
- Packaged Windows probes: baseline, two fixed crossfade runs, cut, fade-black
- Packaged functional E2E: **10/10 journeys passed**

## Limits

- Crossfade with an active LUT proxy was not separately packaged-tested. This
  change preserves the existing outgoing source/target mapping and does not
  alter LUT code; LUT crossfade parity remains unclaimed and the separate #267
  LUT gap remains NO-GO.
- No audio crossfade was added; existing audio behavior is unchanged.
- Pre-roll begins only during continuous playback within 0.5 s of the crossfade.
  Starting playback directly inside an already-running overlap uses the normal
  seek path and may incur one initial seek; it was not part of the measured
  continuous-playback result.
- No new transition type, playback engine, proxy pipeline, renderer, dependency,
  schema change, export change, or source-media modification.
- No merge or release is authorized by this document.

## Decision

GO for the bounded outgoing/incoming crossfade synchronization fix. Do not
describe it as LUT crossfade parity or full preview/export parity approval.
