# Transition preview/export parity spike (#301)

Status: **BLOCKED — V1 implementation stopped before enabling new transitions.**

The approved starting point is [the transition discovery](301-drone-transition-pack.md).
The human implementation request requires stopping if packaged WebView2 cannot
be validated or the proposed preview is visibly misleading. This spike reached
the packaged WebView2 compositor and found a visibly misleading blur candidate.
It does not approve or ship either effect family.

## Reproduction

Use Windows, Python 3.12, and the installed Evergreen WebView2 Runtime:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[dev]' pyinstaller
.venv/Scripts/python -m PyInstaller packaging/orga-drone.spec --noconfirm --clean --distpath dist
$spikeFfmpeg = (Get-ChildItem dist/orga-drone/_internal/imageio_ffmpeg/binaries/ffmpeg*.exe | Select-Object -First 1).FullName
.venv/Scripts/python packaging/e2e/transition_parity_spike.py --exe dist/orga-drone/orga-drone.exe --ffmpeg $spikeFfmpeg --output-dir build/transition-parity-301
```

The script imports the existing sibling `windows_e2e.py` harness, launches the
onefolder EXE with its opt-in E2E/CDP settings, and uses an isolated data directory.
It generates synthetic pictures, applies two different FFmpeg grades, renders
all five proposed `xfade` variants, and compares start/middle/end frames with
CSS candidates in both A-to-B and B-to-A order. All generated media, screenshots,
logs, and `report.json` remain under the ignored `build/` directory. Existing
source media and the user's library are not used.

The CSS is injected into an isolated document inside the packaged WebView2.
It deliberately does **not** replace or claim to test the production Studio
renderer. Exit code zero means measurements were collected; report status is
`EVIDENCE_COLLECTED_NOT_APPROVED`, never a parity pass. A launch or measurement
failure instead records `BLOCKED` and returns nonzero.

## Observed evidence (2026-11-06)

- Application baseline: `develop` at `8b996ae`; only this isolated harness,
  its failure-reporting tests, and this document are added by the spike.
- Windows 11, Python 3.12.3, PyInstaller 6.22.3, pywebview 6.2.1.
- Packaged WebView2 reported `Edg/156.0.4314.58` over CDP.
- EXE SHA-256: `2007dec3f3cea9a75cfef54a2fc61b044cb657f926acd94b2975492335b7bdaf`.
- The clean dependency install supplied bundled **FFmpeg 9.0.2**, rather than
  discovery's 7.1. The harness records the actual binary version. No dependency
  pin or production encoder behavior was changed for this probe.
- 30 paused comparisons: five effects, two clip orders, three progress samples,
  at 640x360. Both sides use different pre-baked grades so the same graded PNG
  inputs reach CSS and FFmpeg.
- `hblur` midpoint mean absolute RGB error (0–255): **39.11** A-to-B,
  **38.32** B-to-A. Its start/end errors were 0.08–0.14.
- Wipe midpoint errors: left 4.84/4.82, right 4.51/4.53, up 4.96/4.67,
  down 4.98/4.92 (A-to-B/B-to-A). These are measurements, not accepted tolerances.

Visual inspection of the generated blur midpoint screenshots confirms the
failure: FFmpeg preserves the horizontal dark bands while smearing detail
horizontally; the CSS Gaussian blur erases the bands and blurs vertically too.
The candidate's blur radius is `(frameWidth / 12) * (1 - abs(2 * progress - 1))`
with opacity equal to progress. Adjusting that radius cannot make an isotropic
Gaussian equivalent to FFmpeg's one-sided horizontal moving average. This
rejects this candidate, not every possible future preview implementation.

The bundled FFmpeg 7.1 source archive's `vf_xfade.c` documents that horizontal
algorithm: its window grows to half the image width at the midpoint. CSS
`blur()` is structurally different. Wipes use a linear alpha gradient in this
candidate, whereas FFmpeg uses smoothstep, so their residual error also needs
an explicit solution and tolerance before approval.

## Integration blockers and untested work

The current production `drawPreviewLayer` / `paintPreviewBlit` path redraws media
onto a canvas and does not apply CSS `mask-image`. Adding a mask to an underlying
video element alone would therefore leave the visible canvas misleading.

No new canonical ids, persistence behavior, inspector choices, translations,
timeline chips, overlap rules, history paths, or export effects were enabled.
There are no schema or `effect_settings` changes.

Not validated for the proposed effects: actual Studio seek/playback, moving
frames, 1080p/4K, LUT/color-animation interactions, mixed FPS/resolutions, speed,
loops, soundtrack, save/reload, undo/redo, short-clip fallback, or chained joins.
Passing existing regression tests does not validate those new effects.

To resume, first establish an approved preview strategy and tolerances, then
repeat the prerequisite in the actual paused and moving Studio composition
path. Discovery names transition-aware FFmpeg stills/proxies as a fallback;
that path was not implemented here. Do not treat this probe as a waiver of
the parity gate, PM/UX/CTO review, or the human product test.

## Regression evidence

- `ruff check .`: passed.
- MyPy: passed for `src`, the existing packaging CI scope, and the new probe
  (82 source files).
- `pytest tests/test_studio_transition.py tests/test_studio_export_transitions.py -q`:
  29 passed against this worktree.
- `pytest tests/test_transition_parity_spike.py -q`: 2 passed. Both missing-EXE
  and missing-FFmpeg failures replace an old report with `BLOCKED`, empty samples,
  and the actual error.
- `pytest tests/test_pr_journey_smoke.py -q`: 2 passed.
- `npm run check:js`: lint and formatting passed; 91 tests passed.

An initial system-Python run imported another checkout and was discarded.
The clean `.venv` imports this worktree. Sandboxed HTTP tests stalled in
Python's `asyncio` socket-pair setup; the focused and journey passes above ran
with loopback access outside that sandbox. No stalled run is counted as passed.
