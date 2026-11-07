# Windows manual RC acceptance package

Date: 2026-11-07. **CONDITIONAL GO for Product Owner manual testing only.
NO-GO for release/parity sign-off.** Human acceptance is **NOT TESTED**.
No merge, tag, public version change, itch.io upload or release is authorized.

## Build identity and local location

Fresh onefolder application from latest fetched `develop`, including merged
[#316](https://github.com/Magehawks/orga-drone/pull/316):
`7dd593000844ab7b6832bb24608f2629ec515c1c`. App version remains **2.3.3**.

| Item | Identity |
| --- | --- |
| EXE SHA-256 | `48914e0b376dc886b8aec4e058b5f8fd89e209b0944de00e758340798bdd2ab1` |
| ZIP SHA-256 | `79113b062cd8ef8418dcf6ef9612b0bd373a3a76fe21b3719482fcc6beb6d2cf` |
| ZIP bytes | 133441375 |
| WebView2 tested | `157.0.4341.42` |
| Bundled FFmpeg tested | `7.1`, pinned GPL build, SHA-256 `e9041e42f9cb1e1faccae46aa4af03ffd70e11474cc085846abdc3dd6e8aadcf` |
| Builder | Python 3.12.3, PyInstaller 6.22.3, pywebview 6.2.1 |
| Host | Windows 11 build 26300; Node 26.13.0 for JS checks |

On the preparation workstation, paths relative to this repository checkout:

- ZIP: `build/windows-rc-7dd5930/orga-drone-manual-rc-7dd5930.zip`
- Checksum: same path plus `.sha256`.
- Verified extraction: `build/windows-rc-7dd5930/extracted-test/`.
- **Start:** `extracted-test/Start-Manual-RC.cmd`.
- Build manifest: `build/windows-rc-7dd5930/rc-build.json`.
- Raw synthetic smoke outputs: `build/rc-smoke-7dd5930/`.

The ZIP stays local and is not a GitHub Release asset. The archived runtime is
the tested base commit; later PR changes are validation scripts/docs only.
The [machine-readable result](automated-results.json) records environment,
build identity, extraction, launcher isolation and individual probe results.

## Extraction, startup and source safety

The unchanged onefolder spec was freshly built. All **76** packaged Orga Drone
Python module origins were verified against this checkout; packaged Studio JS
matches source bytes. The documented release workflow's pinned FFmpeg replacement
and third-party notices were applied. The existing ZIP notice verifier reports
technical **GO**, which is not release authorization.

ZIP CRC and every extracted packaged file's SHA-256 passed (**718 files**).
The archive contains no `.env`, project database, source MP4, flight log or SRT.
It includes the German checklist, two synthetic 17-cube creative test transforms,
the launcher and `RC_BUILD.json`.

The extracted starter was actually launched: native WebView2 navigated, health
returned app 2.3.3, CDP was disabled, and the isolated database had zero media and
zero library roots. Existing normal user database/preferences hashes were
unchanged across that startup check. Automated media imports used synthetic
fixtures in separate data directories, and all source-integrity probes passed.
No production media or existing user projects were edited.

**Use the starter, not the EXE directly.** It fixes the data directory to
`manual-test-data` beside itself, uses an ephemeral loopback port, and disables
browser/E2E/CDP overrides. A direct EXE launch does not provide that isolation.
The Product Owner's real-footage test remains pending; synthetic hashes do not
claim acceptance of real DJI playback quality.

## Automated results

| Check | Result |
| --- | --- |
| Python regression suite excluding journey | **PASS: 1127 passed, 3 skipped**, 438.36 s |
| Journey smoke | **PASS: 2 passed**, 7.80 s |
| New RC safety/reporting + existing LUT gate focused tests | **PASS: 9 passed** (4 new RC tests, 5 existing LUT tests) |
| JavaScript | **PASS:** lint, format check, **106 tests**; locked `npm ci` |
| Ruff | **PASS** |
| MyPy | **PASS**, 80 files including both new RC Python scripts |
| Extracted packaged functional E2E | **PASS: 10/10 journeys**, source integrity and reopen/relaunch included |
| Playback, pause, seek, local MP4 export | **Functional smoke PASS**; this does not mean timing/color parity |
| Cut / fade through black | **Functional smoke PASS**, synthetic source hashes unchanged |
| Crossfade, no LUT / same LUT / different LUTs | **Functional smoke PASS; one-frame timing FAIL** in all three current traces |
| Creative / conversion LUT stage | **Functional smoke PASS**, requested stage persisted, paused/seek/playing comparisons recorded |
| ZIP extraction / isolated native launcher | **PASS**, programmatic extraction and normal startup, not a MOTW test |

The baseline regression suite ran before the added RC test file; all new tests
were then run explicitly with the existing LUT gate tests. No production code
changed. The LUT harness gained only `--lut-role creative|conversion` and a
persisted-stage assertion; no renderer, encoder or tolerance changed.

The conversion smoke uses a synthetic SDR palette and custom input profile to
exercise the technical LUT stage. It does **not** validate a real DJI D-Log M
conversion file. All smoke media and LUT transforms are synthetic; these are
supplemental functional checks, not a substitute for the German human test.

### Failed and untested gates remain explicit

| Gate | Result and evidence |
| --- | --- |
| Current synthetic crossfade, no LUT | **FAIL:** max presented pair drift **0.100 s**, versus one 30 fps frame (0.033333 s); 2 observed outgoing overlap seeks |
| Current synthetic crossfade, same LUT | **FAIL:** max pair drift **0.100 s** |
| Current synthetic crossfade, different LUTs | **FAIL:** max pair drift **0.100 s** |
| Creative LUT strict 3/255 color gate | **FAIL:** paused/seek/playing max swatch error **4.000** |
| Conversion LUT strict 3/255 color gate | **FAIL:** paused/seek/playing max swatch error **4.000** |
| Existing baseline-aware bounded LUT fixture gate | **PASS:** both stages; measured no-LUT baseline 2.667, unchanged bound 4.167. This is not the strict gate. |
| Real DJI one-frame gate from #316 | **FAIL remains recorded:** prior 40-160 ms; not promoted to PASS by any current smoke |
| Human real DJI/uninstrumented visual acceptance | **NOT TESTED**; Product Owner checklist below |
| MOTW-marked ZIP extracted with Windows Explorer into parentheses path | **NOT TESTED**, required before publication |
| Human native folder/music/save-dialog and 1080p/soundtrack release checklist | **NOT TESTED** as a complete release gate; API-driven exports do not prove native dialogs |
| GitHub Windows admission evidence | **NOT PROVIDED:** local E2E uses PR/run 0 and no Actions artifact identity |

No timing/color gate was weakened or silently passed. Timestamp rounding uses
only the pre-existing microsecond precision allowance, not another frame. Raw
diagnostic process exit 0 means collection completed, not parity passed. The
local coordinator returned **1** because strict gates failed and human/MOTW
checks remain untested; all nine underlying functional probe commands exited 0.
Final result labels distinguish known FAIL from NOT TESTED using those raw
observations. They are not substituted for missing measurements.

## Human instructions and known limitations

Use the [German 15-20 minute checklist](../MANUAL_RC_DE.md), also included inside
the ZIP as `MANUAL_TEST_DE.md`. Each of ten steps has exact actions, expected
visible behavior, PASS/FAIL/NOT TESTED choices and local failure-evidence guidance.
It covers original imports, ordinary seeking, creative LUT, pause/play color,
video crossfade, continuous and start-inside playback, 25/50/75% seeks, same and
different LUTs, MP4 comparison and isolated restart persistence.

[#316's report](../../discovery/real-lut-crossfade-visual-validation.md) remains
the real-DJI evidence source: 4K/50 fps Avata 2 footage showed preview drift even
without a LUT; a sampled stale no-LUT preview crop was demonstrated under capture
load. The visual impact specifically caused by LUT drift was inconclusive, and
no export timing defect was demonstrated for those four tested Stories. These
are bounded findings, not proof that other footage or exports are defect-free.

This candidate uses **WebView2 157 / pinned FFmpeg 7.1**, whereas #316 measured
WebView2 156 / FFmpeg 9.0.2. New synthetic exports passed, but the old real-footage
export conclusion is not automatically recertified for this environment. Watch
the actual new real-footage export during human acceptance. Fullscreen
perceptibility, HEVC/10-bit, D-Log M, HDR, other machines and 4K exports are not
covered by this package's automated quality conclusions.

## Release blockers and owner decision

1. Current one-frame crossfade timing and strict color gates are failed.
   Any explicit owner disposition of a preview limitation must be recorded;
   it must not rewrite a failed measurement as PASS.
2. Product Owner real-footage acceptance is unperformed. A visible unacceptable
   freeze, black flash, brightness jump or timing jump is a blocker; an export
   defect must be identified separately from preview-only behavior.
3. MOTW/Explorer and the complete native-dialog/1080p/soundtrack checklist from
   [packaging/README.md](../../../packaging/README.md) remain mandatory before
   any later explicitly authorized publication.
4. This local evidence does not satisfy main's GitHub admission binding and
   does not authorize merging, tagging or publishing.

**Recommendation: CONDITIONAL GO to run manual RC acceptance; NO-GO to publish
or claim timing/color parity.** The Product Owner records the final product
decision and accepted limitations in the checklist. This PR does not automate
that decision or grant permission to release.

Reproduction: [local RC tools](../../../packaging/rc/README.md). Independent
validation review: **REVIEW_APPROVED**; see [review](REVIEW.md).
