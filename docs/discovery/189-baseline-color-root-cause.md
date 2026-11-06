# Existing Studio color parity: metadata diagnosis (#189 / #267)

**GO for the bounded diagnosis; NO-GO for changing color assumptions or grading.**
No application fix is justified by this result. Source, grade, LUT and export
semantics are unchanged. No #301 transition is implemented. This investigates
the baseline color mismatch reported by [#307](https://github.com/Magehawks/orga-drone/pull/307)
and [#308](https://github.com/Magehawks/orga-drone/pull/308), using ordinary
existing single-clip projects on `develop` at `8b996ae`.

## Reproduction and controls

The packaged Windows onefolder app was rebuilt from unmodified Studio source.
`packaging/e2e/studio_color_probe.py` generates static 720p H.264 swatches,
imports them into an isolated synthetic library, opens one ordinary clip per
project, captures the actual visible Studio blit, and exports through the
application API. No new effects, transitions, grades or LUTs are enabled.

Seven controls were measured:

- BT.709 and SMPTE 170M/BT.601, each explicitly limited (`tv`) and full (`pc`)
  range, with matrix, primaries and transfer metadata set on frames and encoder.
- Two untagged HD controls, encoded from known 601 or 709 YUV conversion.
- A metadata-only retag of the 601 limited control as 709: decoded first-frame
  YUV SHA-256 is identical. This intentionally changes interpretation to prove
  causality; it is **not** a recommended source-file repair.

Static swatches remove frame-selection differences. Interior swatch regions
exclude resize/codec edge ringing. Captures compare native video copied at
source size, browser downscaling, the real Studio blit, explicit/default sRGB
canvas contexts, FFmpeg source decode with auto/forced matrices, and the actual
application MP4 decoded by both FFmpeg and WebView2. The exported browser
control waits for a presented frame, rather than treating `loadeddata` alone
as evidence that a frame has reached the canvas.

Environment: Windows 11, Python 3.12.3, pywebview 6.2.1, WebView2
`Edg/156.0.4314.58`, FFmpeg 9.0.2. Exact EXE, Studio JavaScript, source, output,
decoded-YUV and raw-report fingerprints are in the
[summary](189-color-evidence/summary.json). All source hashes were unchanged.

## Findings

The large untagged-HD mismatch is an **input color interpretation difference**:
in this environment WebView2 renders the untagged samples like forced BT.709,
while FFmpeg auto decode/export uses the BT.601 interpretation. Metadata can
change that interpretation without changing decoded YUV picture samples.

Maximum interior-swatch mean absolute RGB error (8-bit levels):

- Untagged 601: browser vs FFmpeg auto **9.667**; browser vs forced 709
  **2.333**. Studio vs FFmpeg-decoded app MP4 **13.333**; source vs exported
  picture when both use WebView2 **11.333**.
- Untagged 709: browser vs FFmpeg auto **11.333**; browser vs forced 709
  **2.667**. Studio vs FFmpeg-decoded MP4 **13.333**; browser-to-browser
  source/export **11.333**.
- Fully tagged 709 limited: browser vs FFmpeg source/export **2.667**;
  source/export when both use WebView2 **0.000**.
- Fully tagged 709 full: browser vs FFmpeg source **1.000**;
  browser-to-browser source/export **1.333**.
- Fully tagged 601 limited/full: browser vs FFmpeg source **2.000 / 0.667**;
  browser-to-browser source/export **2.333 / 2.333**.
- Metadata-only retag control: same decoded YUV as 601 limited; browser vs
  FFmpeg source/export **2.333**, browser-to-browser source/export **0.000**.

These are diagnostic measurements, not a universal color tolerance or a claim
that every fixture passes the strict #308 RGB thresholds. Tagged 601 still has
up to **4.667** (limited) / **4.333** (full) Studio-vs-FFmpeg-export error; the
source-FFmpeg-vs-export-FFmpeg contribution is **3.667 / 5.000**. Those smaller
cross-matrix/rounding/re-encode contributions were not separately attributed to
a particular encoder or scaler operation, and are not silently subtracted.

### Components ruled out for the large flat-swatch discrepancy

- **Studio canvas composition:** native video copy and Studio blit have
  identical interior swatches in every case (error **0.000**).
- **Canvas color-space selection:** default and explicitly sRGB contexts
  report sRGB and give identical interior swatches (**0.000**).
- **Interpolation/resizing:** native-size copy, browser-scaled copy and blit
  have identical swatch interiors (**0.000**). This does not establish edge,
  high-frequency texture, wide-gamut, HDR or arbitrary-resize parity.
- **Frame selection:** all source frames are static; selecting a different
  decoded frame cannot explain the measured flat-region offset.
- **A general limited/full-range bug:** fully specified range controls decode
  much more closely. The metadata ambiguity, not a demonstrated global range
  conversion defect, explains the large untagged mismatch.

Export `_segment_vf()` explicitly converts to limited-range BT.709 and tags
that output. It relies on FFmpeg's input metadata/default interpretation.
Forcing 709 for all unknown inputs would improve one control and misinterpret
the other; making export imitate one browser's HD fallback is not a supported
fix. No grade/LUT or source-file semantics were changed to lower an error score.

## Reproduce

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[dev]' pyinstaller
.venv/Scripts/python -m PyInstaller packaging/orga-drone.spec --noconfirm --clean --distpath dist
$colorFfmpeg = (Get-ChildItem dist/orga-drone/_internal/imageio_ffmpeg/binaries/ffmpeg*.exe | Select-Object -First 1).FullName
.venv/Scripts/python packaging/e2e/studio_color_probe.py --exe dist/orga-drone/orga-drone.exe --ffmpeg $colorFfmpeg --output-dir build/color-fresh-run
```

Use a fresh output directory. Full measured artifacts remain locally under
`build/189-color-controls-v3/`: `report.json`, all seven source/export MP4s,
native/blit/scaled/sRGB/forced-matrix PNGs, palette, isolated app data and logs.
Selected committed images: [untagged preview](189-color-evidence/untagged-601-blit.png),
[its FFmpeg export decode](189-color-evidence/untagged-601-export_ffmpeg.png),
[its WebView2 export decode](189-color-evidence/untagged-601-export_browser.png),
[tagged 709 preview](189-color-evidence/709-tv-blit.png) and
[tagged 709 browser export](189-color-evidence/709-tv-export_browser.png).

Earlier diagnostic runs are preserved locally. The first exposed incomplete
fixture frame tags and an unpresented hidden-video control; the second still
had inconsistent container/VUI tags in the retag control. Neither is presented
as the final controlled result. V3 specifies complete metadata, waits for a
presented export frame, and verifies identical YUV in the retag control.

## Follow-up decision and limits

Do not silently reinterpret untagged media, rewrite source metadata, or adjust
grading/LUT behavior. A product/architecture follow-up must select an explicit
unknown-metadata policy: detection and disclosure first, then optional
per-source interpretation only if approved, consistently applied to preview,
stills/proxies and export. That is a separate decision from creative grading.
Avoid a forced global matrix heuristic.

The raw before/after contrast here is a **fixture metadata intervention**, not
an application fix or a proposal to relabel files. No HDR, log conversion,
wide-gamut, LUT, mixed-FPS, real drone footage, 1080p/4K or universal decoder
parity is claimed. The smaller tagged 601 residual remains a precise follow-up
for unencoded-conversion versus re-encode controls if stricter tolerances are
needed. This quality slice leaves shipping behavior unchanged.

Continuation check (2026-11-06): the same seven harness tests were re-run on the
inherited continuation branch (**7 passed**) and the packaged `summary.json`
values were re-checked against this document. No production code or media was
changed. The baseline diagnosis remains GO bounded and the LUT result remains a
separate NO-GO.

Seven harness regression tests verify actual encoded metadata for all four
matrix/range combinations, fail-closed setup, and preservation of prior
evidence. These test fixture reliability, not a claim to fix browser decoding.
Current-head CI and functional packaged regression results are recorded in the
PR. No merge or release is authorized.

## Functional regression and separate LUT limitation

The existing `packaging/e2e/windows_e2e.py` harness passed all ten journeys on
the restored application: startup, import, library navigation, Studio open,
playback, edit persistence, video export, image export, source integrity and
relaunch persistence. Its local provenance deliberately uses run/PR id 0 and
`local-not-uploaded`; it is **not GitHub admission evidence**, a MOTW test, or
a release approval. See [functional summary](189-color-evidence/functional-regression.json).

The additional `studio_lut_smoke.py` measurement applies one deterministic
creative cube to the fully tagged 709 limited fixture via existing APIs. Actual
WebGL preview is active, and both paused/playing blit captures were compared
with the actual application MP4. It returned **NO-GO**: whole-frame mean error
**26.129/255**, maximum interior-swatch mean **36.333/255**, for both paused
and playing. [Report](189-color-evidence/lut-report.json),
[paused preview](189-color-evidence/lut-paused.png), and
[export](189-color-evidence/lut-export.png) preserve this distinct #267 gap.

No production application code changed between the baseline and these checks;
this is an existing discrepancy, not a demonstrated regression from a fix.
Its cause was not isolated here. Do not attribute it to the untagged-input
diagnosis or claim LUT parity passed. A separate #267 plan should trace cube
sampling, shader/display color conversion and the shared FFmpeg LUT chain
with stage-level controls before changing any LUT semantics. A functional
smoke pass or the unit suite cannot waive this negative pixel result.

Local artifacts: `build/189-packaged-functional-final/` and
`build/267-packaged-lut-verified/`. Reproduce the LUT measurement after the
color probe with the same executable:

```powershell
.venv/Scripts/python packaging/e2e/studio_lut_smoke.py --exe dist/orga-drone/orga-drone.exe --ffmpeg $colorFfmpeg --fixture-dir build/color-fresh-run --output-dir build/lut-fresh-run
```

The script's nonzero exit for this fixture is an expected negative parity
result, not a passing test. A preliminary LUT capture had no numeric decision;
the final run adds an explicit 3-level swatch tolerance and records NO-GO.

The final LUT playback capture verifies advancing media currentTime, paused=false,
readyState=4, and decoded-frame observations; it is not inferred from a transport
click alone. Earlier captures lacking that proof are not the final playback evidence.
