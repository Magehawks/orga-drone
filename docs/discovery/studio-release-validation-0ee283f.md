# Studio playback / crossfade / LUT / export release validation

Build: `develop` at `0ee283fe79f0a251c970bfaa86b2decfc21f7458` (includes
#311, #312, #313). Validation date: 2026-11-06.

**Recommendation: NO-GO for release-candidate sign-off. CONDITIONAL GO only for
a limited manual exploratory RC test if the paused-crossfade half-bright frame
and the LUT crossfade timing variance are explicitly accepted as known
defects.**

This is a validation record. No production code, schema, export behavior,
source media, transition type or LUT semantics were changed by this branch.

## Tested build and environment

- Fresh PyInstaller onefolder build from `develop` at
  `0ee283fe79f0a251c970bfaa86b2decfc21f7458`
- App version 2.3.3
- EXE SHA-256: `0bfa4ddc0e2c1e6b703798f3a5a563893772626c54dd83f2829cafe7e294c092`
- Packaged `studio.js`: `48e7136ad7bca1b67f8cc2fcafb3f459f322d54d9d6cef4b324e4981abce29cd`
  (#312)
- Packaged `studio-lut-webgl.js`: `12d4c18dc59caeffc505a75a5cf9c6f8a730450cdb8bf641a65a6fbc1e50ee12`
  (#313)
- Bundled FFmpeg: `9.0.2-essentials_build-www.gyan.dev`
- WebView2: `Edg/156.0.4314.58`
- PyInstaller 6.22.3, Python 3.12
- Packaged ZIP SHA-256: `ce0588397f2ab3406c42b01b9ce12dd96db5f21bbc9510b64b6db9f8929635d8`
- Isolated synthetic library/data directories; original source media untouched.

WebView2 and FFmpeg versions were read from the packaged probes. The build used
a fresh worktree and a fresh `.venv`; the packaged JS hashes match the merged
#312/#313 resources.

## Method

Existing packaged probes were used where possible:

- `packaging/e2e/windows_e2e.py` — ten functional journeys.
- `packaging/e2e/studio_color_probe.py` — deterministic tagged color fixture.
- `packaging/e2e/studio_lut_smoke.py` — paused/seek/playing LUT preview versus
  actual application MP4 export.
- `packaging/e2e/studio_clock_probe.py` — Story clock and crossfade presented
  frames; cut and fade-through-black.
- `packaging/e2e/studio_crossfade_lut_probe.py` — LUT-enabled crossfades,
  different LUTs on adjacent clips, start-inside-crossfade, pre-roll
  cancellation, repeated seeks, and crossfade preview/export RGB comparison.
  It writes only synthetic fixtures and an isolated app data directory.

The integration fixture was synthetic 3 s tagged BT.709 limited palette clips
with a moving marker outside the comparison regions, one 1 s crossfade, and
17-cube synthetic LUTs. It is synthetic evidence, not universal parity.

## Scenario matrix

| # | Scenario | Result | Key evidence |
| --- | --- | --- | --- |
| 1 | Normal playback without LUT | **PASS** | packaged playback journey advanced; no crash |
| 2 | Playback with conversion LUT | **PASS** | paused/seek/playing max **4.000**, full **3.304**; WebGL active |
| 3 | Playback with creative LUT | **PASS** | paused/seek/playing max **4.000**, full **3.304**; WebGL active |
| 4a | 17x17x17 cube | **PASS** | max **3.667**, full **2.938**; WebGL active |
| 4b | 33x33x33 cube | **PASS** | max **3.667**, full **3.017**; WebGL active |
| 5 | Playback, pause, resume, seek with LUT | **PASS** | seek landed at 0.999697 s, paused, ready 4, WebGL active; all comparisons 4.000/3.304 |
| 6 | Crossfade without LUT | **PASS (timing)** / **FAIL (paused composite)** | clock 3/3 runs pair drift **0.033334 s**, 0 outgoing seeks; paused seek half-bright defect below |
| 7 | Crossfade with LUT | **CONDITIONAL / FAIL (timing)** | moving fixture + 17-cube LUT: pair drift **0.033334, 0.066667, 0.033334 s**; outgoing seeks **0/2/3**; two runs exceed one frame |
| 8 | Different LUTs on adjacent clips | **CONDITIONAL** | crossfade max swatch **4.667**, full **3.542**; above the single-clip bounded gate 4.167; timing also LUT-variant |
| 9 | Start playback directly inside crossfade | **PASS with note** | outgoing/incoming presented pair drift **0.000 s**, no outgoing seeks; primary Story drift max **0.05 s** in the first second |
| 10 | Repeated seeking across crossfade boundaries | **PASS** | all six seek captures non-black (brightness 94.6–124.6); paused seek errors ~1.3e-6 s |
| 11 | Rapid switching / cancel outgoing pre-roll | **PASS** | after seek-away: outgoing hidden, paused, not seeking; primary continued |
| 12 | Speed 0.5 with LUT | **PASS** | paused/seek/playing max **4.000**, full **3.304**; playback advanced |
| 12b | Loop boundaries | **NOT COVERED (packaged)** | synthetic fixture has no soundtrack; existing Python/JS loop tests pass |
| 13 | Story export compared with preview | **PASS bounded** | no-LUT max **2.667**; one LUT max **4.000**; two LUTs max **4.667** |
| 14a | Cut | **PASS** | packaged clock probe completed; `NOT_A_CROSSFADE_TRACE`; no errors |
| 14b | Fade through black | **PASS** | packaged clock probe completed; `NOT_A_CROSSFADE_TRACE`; no errors |

### LUT single-clip measurements

The #313 bounded gate is `max(3.0, no-LUT baseline 2.667 + 1.5) = 4.167`.
All single-clip runs kept WebGL active, the source unchanged, and the export
MP4 produced by the application.

| Cube | Full-frame error | Max swatch | Decision |
| --- | ---: | ---: | --- |
| 2x2x2 creative | 3.304 | 4.000 | GO_BOUNDED_FIXTURE |
| 2x2x2 conversion | 3.304 | 4.000 | GO_BOUNDED_FIXTURE |
| 17x17x17 creative | 2.938 | 3.667 | GO_BOUNDED_FIXTURE |
| 33x33x33 creative | 3.017 | 3.667 | GO_BOUNDED_FIXTURE |
| 17x17x17 creative, speed 0.5 | 3.304 | 4.000 | GO_BOUNDED_FIXTURE |

The strict 3.0 gate remains false; this is the documented baseline color-path
limitation from #310/#313, not a new LUT regression.

## Defects and severity

### 1. Paused crossfade can show a half-bright composite (high)

After seeking to Story 2.500 s inside a crossfade, the visible blit stayed at
mean brightness **62.09** (about half of the correct **124.63**) at 0.05, 0.2,
0.5 and 1.0 s after the seek. Both video elements were visible, paused, not
seeking, `readyState 4`, with primary opacity 0.499 and outgoing opacity 1. The
composite became correct at about 1.2 s; later seeks repainted correctly.

The half-bright value is exactly the incoming layer at opacity 0.5 over black,
so the outgoing layer was present in DOM state but not represented in the first
blit. A forced width repaint did not fix it; a later seek/paint did. This is a
visible paused-preview consistency/flicker defect and fails the "no unexpected
black/frozen/flicker" and "paused versus playing preview consistency" gates.

Evidence: [clock-seek-2.5-half.png](studio-release-validation-evidence/clock-seek-2.5-half.png),
[clock-seek-3.2-full.png](studio-release-validation-evidence/clock-seek-3.2-full.png),
and `crossfade-summary.json` (`no_lut.paused_brightness_samples`). The scenario
was observed on develop; it is not established as a regression from #311–#313,
but it is a release-quality blocker.

### 2. LUT crossfade timing is not consistently one frame (medium-high)

No-LUT crossfade was **0.033334 s** in three packaged runs with zero outgoing
seeks. With a 17-cube LUT on both moving clips, three runs measured
**0.033334 / 0.066667 / 0.033334 s**, with **0 / 2 / 3** outgoing seeks. The
0.066667 s runs exceed one 30 fps frame. This is not a seek storm, but it fails
the one-frame crossfade gate for the LUT-enabled integration scenario.

The root cause was not isolated. It correlates with the WebGL LUT rendering
load and delayed outgoing pre-roll/readiness. The #312 no-LUT validation remains
intact.

### 3. Two different LUTs across a crossfade exceed the single-clip gate (medium)

Two 17-cube LUTs on adjacent clips measured **4.667 max / 3.542 full** at the
crossfade preview/export midpoint. The single-clip bounded gate is 4.167; no
crossfade-specific tolerance was previously established. This needs a separate
crossfade blend tolerance or a color-path investigation before claiming parity.

### 4. Packaged loop-boundary coverage is incomplete (low)

Speed 0.5 with a LUT passed. Forward-loop boundaries were not packaged-tested
because the synthetic fixture has no soundtrack; existing loop Python/JS tests
pass. Do not treat this as packaged loop proof.

## Quality gates

| Gate | Result |
| --- | --- |
| Existing JS tests | **PASS** — `npm run check:js`, 105 tests |
| Existing Python tests | **PASS** — 1127 passed, 3 skipped |
| Journey smoke | **PASS** — 2 passed |
| Packaged functional E2E | **PASS** — 10/10 journeys |
| Cut / fade-through-black | **PASS** |
| No seek storms | **PASS** — max 3 outgoing seeks in crossfade; no 191-event storm |
| Existing LUT improvements | **PASS** single clip; 4.0/3.667 max, WebGL active, export unchanged semantics |
| Crossfade one-frame timing | **NO-GO** for LUT-enabled crossfade; no-LUT passes |
| LUT fixture-specific bounded gate | **PASS** single clip; **CONDITIONAL** two-LUT crossfade 4.667 vs 4.167 |
| Source-media integrity | **PASS** — hashes unchanged in all probes |
| Ruff / MyPy | **PASS** |

## Build and test evidence

- `release-summary.json` — consolidated build, matrix and findings.
- `clock-summary.json` — no-LUT/LUT clock runs, cut and fade.
- `lut-summary.json` — creative, conversion, 17, 33 and speed reports.
- `crossfade-summary.json` — no-LUT/one-LUT/two-LUT crossfade, start-inside,
  pre-roll cancellation, repeated seeking and paused-brightness states.
- `functional-e2e.json` — ten packaged journeys.
- Selected images: pause/seek half/full, LUT crossfade preview/export, LUT
  single-clip preview/export.

## Recommendation

**NO-GO for release-candidate sign-off.** A release candidate should not ship
with a visible half-bright paused crossfade and an intermittent LUT crossfade
timing failure above the one-frame gate.

**CONDITIONAL GO for a limited manual exploratory RC test** only if the release
owner explicitly accepts these as known defects and the test is limited to
scenarios that avoid paused crossfade inspection and LUT crossfade timing
claims. Otherwise the recommendation remains NO-GO.

No merge or release is authorized by this document.
