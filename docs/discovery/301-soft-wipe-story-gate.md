# One soft wipe in the real Story compositor (#301)

Decision: **NO-GO. Stop before shipping or exposing the transition.**

The Product Owner narrowed V1 to one `soft_wipe_left` / FFmpeg `smoothleft`
vertical slice after rejecting CSS Gaussian blur for `hblur`. Blur and the other
directions remain deferred. [PR #307](https://github.com/Magehawks/orga-drone/pull/307)
and its original parity evidence are unchanged. This is a separate experiment
against `develop` at `8b996ae`, not an amendment to that result.

## Smallest candidate and its boundary

The nonshipping [candidate patch](../../packaging/e2e/candidates/301-soft-wipe-left.patch)
adds only the minimum timing/export/compositor scaffold needed to measure the
effect. It adds no inspector option, translation, renderer, proxy, track,
parameter, clock driver, or migration. It reuses outgoing transition persistence
and overlap timing, and stitches finished segments with `xfade=smoothleft`.

The real `paintPreviewBlit` draws the outgoing layer as before. Incoming media
is drawn by the existing `drawPreviewLayer` into an opaque black scratch canvas
at opacity 1, using the existing grade path and content fit. A one-row alpha
mask is expanded across that finished incoming canvas with `destination-in`,
then drawn onto the actual visible blit canvas. The mask is in device/output
coordinates, independent of source pan/zoom:

```text
u = clamp(x / outputWidth + 2 * progress - 1, 0, 1)
incomingAlpha = u * u * (3 - 2 * u)
```

This is the `smoothleft` equation in the bundled FFmpeg source (its internal
progress runs from 1 to 0). No CSS mask or radius tuning is involved.

PM and CTO approved this bounded, nonshipping neutral-media experiment. They
did not approve global UI exposure or a new eligibility restriction. After the
failed measurement, all candidate changes were removed from `src/`; only the
reproducible patch, probe, tests, and evidence remain in this PR. Cut,
fade-through-black, crossfade, persistence, and history behavior are unchanged.

## Criteria fixed before collection

The probe's `CRITERIA` constants were set before its first measurement:

- Each region: mean absolute RGB error at most **3/255** and 95th percentile
  of the maximum per-pixel channel error at most **6/255**.
- Regions: whole frame, leftmost/rightmost 10%, central 10%, and a lower
  moving-marker region. An edge failure cannot hide inside a whole-frame mean.
- Flat midpoint reveal profile: alpha error at most **0.03**, 50% reveal
  position error at most **2 pixels** in the normalized 640-pixel output.
- Both source clocks within **one 30 fps frame (0.033333 s)** of the actual
  Story time; both pictures must advance during playback.
- Boundary coverage: one frame before/start/one frame after start,
  quarter/midpoint/three-quarter, one frame before/end/one frame after end.
  Timeline event coordinates are quantized by the browser; the report records
  actual achieved times, not just requested times.
- References come from the actual application MP4 export. The closest frame
  within one frame of the measured Story time may be used; no unrestricted
  time alignment or synthetic clock injection is allowed.
- No empty frame, reversed reveal, boundary flash, or residual mask is
  acceptable. Automated pixel/clock checks are necessary, not human approval.

## Measured run (2026-11-06)

The [raw report](301-soft-wipe-evidence/report.json) contains all 37 captures:
nine paused seeks and 28 actual Story playback captures. The app exported a
five-second, 150-frame, 1280x720 MP4 from two three-second videos with a
one-second overlap. The visible preview canvas was 640x360 at DPR 1. The
synthetic sources have moving markers and no audio, grade, LUT, speed changes,
loops, or overlays. Color metadata was not explicitly tagged in the fixtures.

Environment: Windows 11, Python 3.12.3, PyInstaller 6.22.3, pywebview 6.2.1,
packaged WebView2 `Edg/156.0.4314.58`, bundled FFmpeg 9.0.2. The locally built
onefolder EXE was used; this was not source-mode browser testing. No release,
MOTW validation, or installer claim follows from the build.

Fingerprints:

- EXE: `48cfabbebd071551ad3cb0c41d74fd2e833e741904b5840d19307b00a318137c`
- Packaged `studio.js`: `6adc5b2ff6d770bc667c14777cff80c2707daece0624ccf0d9f349aa30cabd5d`
- Packaged `studio/soft-wipe.js`: `5717ffaf44b7e7f5b03d70555231f2ad08f2ebaad1144892f947a0a70c117d88`
- Candidate patch: `73ed52310f4ce82bcb724d5c105fe5696508fcea6cefc6e01c6d70da97a68fff`
- MP4: `01b4d5501c4a6c7901fc2a6887ded6f6c0b99c2b65c57102cca3a68e7cbda570`

### Spatial result: failed

Even before the wipe, at Story time 1.966123 s, whole-frame mean error was
**7.780/255**, P95 **13/255**. After the overlap, at 3.032359 s, mean was
**4.641/255**, P95 **10/255**. This is evidence of a baseline color difference
in this fixture/environment, not proof that the wipe caused it. The source of
the difference (for example video color conversion/metadata) was not diagnosed
or changed in this slice.

At the paused midpoint (actual 2.499241 s), mean/P95 were:

- Whole frame: **7.147 / 16**.
- Left edge: **9.321 / 16**; right edge: **4.328 / 12**.
- Center reveal region: **6.266 / 10**.
- Moving-marker region: **8.723 / 16**.

All nine paused samples exceeded the spatial gate. The raw export-endpoint
alpha calculation also failed: **0.08552** max error and **19 px** apparent
position error. That diagnostic is confounded by the baseline color difference.
An [offline diagnostic](301-soft-wipe-evidence/alpha-diagnostic.json), using the
already captured **preview** endpoint colors and actual achieved midpoint time,
isolates mask geometry: max alpha error **0.00853**, reveal error **0.972 px**.
This suggests the mask equation is promising; it does not waive the failed
preview/export pixel criteria or turn the experiment into a pass.

### Moving result: failed

At playback sample `play-22`, actual Story time was **2.748700 s**. The incoming
video was playing, readyState 4, not seeking, at source time **1.012100 s**;
its expected time was **0.748700 s**. The **0.263400 s** discrepancy is nearly
eight output frames. The outgoing layer remained paused at **2.748700 s**.
Both source positions advanced over the run, but their updates did not stay
within the one-frame requirement.

The trace shows Story progress plateaus while the primary video's currentTime
continues advancing. The inspected `onVideoTimeUpdate` updates Story time from
native `timeupdate` events; `paintPreviewBlit` uses that Story time for mask
progress, and `showOutgoingLayer` seeks the outgoing picture to that time.
No clock/synchronization changes were made. Some instantaneous canvas captures
can straddle a scheduled paint, so peak transient pixel errors alone are not
attributed to a new visible flash. The repeated stable clock discrepancy and
paused spatial failures already make this a NO-GO.

All synthetic source SHA-256 values were unchanged after export and playback.

## Screenshots and local artifacts

- [Visible packaged Studio at midpoint](301-soft-wipe-evidence/visible-studio-midpoint.png).
- Paused midpoint: [visible canvas](301-soft-wipe-evidence/seek-4-preview.png),
  [MP4 reference](301-soft-wipe-evidence/seek-4-export.png).
- Clock-failure sample: [visible canvas](301-soft-wipe-evidence/play-22-preview.png),
  [MP4 reference](301-soft-wipe-evidence/play-22-export.png).
- Full local set: `build/301-soft-wipe-story-v5/` — all 37 preview/reference
  PNG pairs, `story-export.mp4`, raw report, offline diagnostic, synthetic
  library and isolated app logs/data. Generated binaries/media remain ignored.

The committed screenshots contain only synthetic imagery and application UI.
Earlier `build/301-soft-wipe-story*` directories preserve setup attempts with
zero parity samples: session-collapsed same-second fixtures (first two), an
unsupported upscale request from 360p sources (third), and a preview border/
timeline-coordinate assertion (fourth). Harness-only setup fixes led to v5;
the candidate compositor and numerical thresholds were not tuned between runs.

## Reproduction

Use a throwaway checkout at the recorded `develop` baseline. The patch is
experimental and must not be applied to a release candidate or user library:

```powershell
git apply --check packaging/e2e/candidates/301-soft-wipe-left.patch
git apply packaging/e2e/candidates/301-soft-wipe-left.patch
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[dev]' pyinstaller
.venv/Scripts/python -m PyInstaller packaging/orga-drone.spec --noconfirm --clean --distpath dist
$wipeFfmpeg = (Get-ChildItem dist/orga-drone/_internal/imageio_ffmpeg/binaries/ffmpeg*.exe | Select-Object -First 1).FullName
.venv/Scripts/python packaging/e2e/soft_wipe_story_probe.py --exe dist/orga-drone/orga-drone.exe --ffmpeg $wipeFfmpeg --output-dir build/soft-wipe-fresh-run
git apply -R packaging/e2e/candidates/301-soft-wipe-left.patch
```

Use a new or empty output directory; the harness refuses to overwrite previous
evidence. It performs real Story ruler events, transport playback, persistence
reload for the scaffold, and `/api/studio/export`. It does not replace the
document, call renderer internals, or inject time. The build remains an
experimental candidate even after reverting source; never distribute it.

## Remaining blockers and limitations

Do not expose this transition or complete inspector/i18n/history work on top
of a failed gate. A separate approved plan would need to address the observed
baseline color and Story/media synchronization behavior, then re-run the gate.
No new renderer or proxy pipeline is justified by this experiment alone.

Title Card text and privacy/map/HUD/annotation layers are outside the media
blit canvas. They would need finished-layer composition parity or an explicitly
approved, consistently enforced eligibility decision before UI exposure.
Existing crossfade approximations are not sufficient evidence for a wipe.

Not validated: photos, title cards, LUT/color animation or grade interactions,
1080p/4K, mixed FPS/resolutions, speed, loops, audio/soundtrack, new-transition
undo/redo, duration editing, short-clip fallback, or realistic drone footage.
Only the scaffold's API save/reload and fixed one-second overlap were exercised.
Existing regression passes do not validate combinations that were not tested.

Human product testing, merge, and release remain with the Product Owner.

## Regression checks and independent review

- Ruff: passed. MyPy: passed for the existing packaging CI scope, `src`, and
  the new probe (82 source files).
- `pytest tests/test_soft_wipe_story_probe.py -q`: **4 passed**. Covers localized
  edge rejection despite a low full-frame average/P95, identical-frame spatial
  checks, fail-closed preflight reporting, and preserving existing evidence.
- `pytest tests/test_pr_journey_smoke.py tests/test_studio_transition.py tests/test_studio_export_transitions.py -q`:
  **31 passed** after removing the candidate from production. The candidate's
  existing transition suite also passed 29 tests before the gate run.
- `npm run check:js`: lint/format passed, **91 tests passed**.
- Independent read-only verdict: **REVIEW_APPROVED** for the nonshipping probe,
  candidate patch, and NO-GO evidence. This is not transition approval.

These regressions do not waive the negative packaged gate. Full-suite and
current-head CI outcomes are recorded in the follow-up PR.
