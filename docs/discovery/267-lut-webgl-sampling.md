# WebGL LUT sampling parity (#267)

**GO for the bounded WebGL LUT sampling fix. NO-GO for the original strict
3/255 absolute gate, which is below the measured browser-vs-FFmpeg color path.
NO-GO for claiming universal LUT parity.**

This corrects the WebGL2 preview's `.cube` texture sampling. It does not change
FFmpeg export, LUT blending, grading, transitions, proxies, project data or
source media.

## Problem

The packaged #310 LUT smoke compared a paused/playing WebGL preview with the
application-exported MP4 using a deterministic tagged BT.709 limited fixture and
a 2x2x2 synthetic channel-transform LUT:

- whole-frame mean absolute RGB error: **26.129/255**;
- maximum interior-swatch mean: **36.333/255**;
- paused and playing previews were identical, so frame selection was not the
  cause.

The fixture, source hashes, EXE and export path were already controlled by the
#310 color probe. Selected captures and raw reports are under
[267-lut-evidence](267-lut-evidence/): [baseline paused](267-lut-evidence/baseline-paused.png),
[baseline export](267-lut-evidence/baseline-export.png),
[fixed paused](267-lut-evidence/fixed-paused.png),
[fixed seek](267-lut-evidence/fixed-seek.png),
[fixed playing](267-lut-evidence/fixed-playing.png),
[fixed export](267-lut-evidence/fixed-export.png),
[baseline report](267-lut-evidence/report-baseline.json),
[fixed report](267-lut-evidence/report-fixed.json), and
[conversion-LUT report](267-lut-evidence/report-conversion.json), and
[17x17x17 report](267-lut-evidence/report-17.json).

## Root cause

`studio-lut-webgl.js` sampled the 3D LUT with the raw normalized RGB value:

```glsl
texture(lut, clamp(c, 0.0, 1.0))
```

A 3D texture's texel centres are at `(i + 0.5) / size`, not at `i / (size - 1)`.
For a 2x2x2 LUT the raw coordinate maps input `0.5` to texture coordinate `0.5`,
but the correct sample is between texel centres; the effective mapping is
`0.25 + 0.5 * c`. The preview therefore applied a contrast-like expansion around
0.5 **before** the LUT. In the failing fixture this turned an input red of 180
into an inferred LUT input of about 233, explaining the 36-level error.

FFmpeg `lut3d` maps the cube domain correctly. The fix is the standard texel
centring:

```glsl
vec3 lutCoord(vec3 c, float size) {
  return (clamp(c, 0.0, 1.0) * (size - 1.0) + 0.5) / size;
}
```

The shader now receives `uConvSize` and `uCreativeSize` independently, so
conversion and creative LUTs of different sizes use their own dimensions.

## Before/after measurements

Packaged Windows onefolder app, WebView2 `Edg/156.0.4314.58`, bundled FFmpeg
9.0.2, same EXE and source. Baseline and fixed runs use a 2x2x2 cube.

- EXE SHA-256: `0cd47f35a3e98e5b80f3976a8e0bdb49e972c811ffacc8f69040c5aac2ed7930`
- Baseline `studio-lut-webgl.js`: `4e9b630cbc105185eb7270b0a66281ae3c55b9d1bd3c524db4e4067229baf04f`
- Fixed `studio-lut-webgl.js`: `12d4c18dc59caeffc505a75a5cf9c6f8a730450cdb8bf641a65a6fbc1e50ee12`
- Exported MP4 (identical before/after): `416cb21d93828323883aecbb8d6f89e75867be09a52cf095b3f392dcb7a3d0a3`

| Measurement | Baseline | Fixed |
| --- | ---: | ---: |
| Paused preview vs export, whole frame | 26.129 | **3.304** |
| Paused preview vs export, max swatch | 36.333 | **4.000** |
| Paused seek preview vs export, whole frame | not captured in #310 | **3.304** |
| Paused seek preview vs export, max swatch | not captured in #310 | **4.000** |
| Playing preview vs export, whole frame | 26.129 | **3.304** |
| Playing preview vs export, max swatch | 36.333 | **4.000** |
| Render path | WebGL | WebGL |
| Source unchanged | yes | yes |
| Exported MP4 SHA-256 | `416C...D0A3` | **identical** |

The no-LUT browser-vs-FFmpeg baseline for the same tagged 709 fixture is
**2.667/255 max**. The fixed LUT adds **1.333/255** over that baseline. The
bounded tolerance is:

```text
max(3.0, baseline_max + 1.5) = 4.167
```

The original strict 3.0 gate is recorded but not met; it is below the no-LUT
color path before any LUT is applied. A representative 17x17x17 channel cube
measured **3.667 max** (1.0 extra over baseline) with the same fix.

Conversion-LUT and creative-LUT packaged runs both reached WebGL and produced
the same paused/seek/playing measurements. The conversion run is preserved in
`report-conversion.json`.

## Tests

- `tests/js/lut_webgl_sampling.test.js` was added **before** the production
  change and failed on the baseline shader. It now verifies the per-LUT size
  uniforms and the texel-centre mapping.
- `tests/test_studio_lut_smoke.py` covers the baseline-aware gate: the original
  36-level failure is rejected, the fixed 2x2x2 measurement is accepted only
  through the documented baseline allowance, and seeking is part of the gate.
- `packaging/e2e/studio_lut_smoke.py` now records paused, seek and playing
  measurements plus baseline/strict/bounded decisions.
- Relevant existing tests: `tests/js/lut_preview.cjs`,
  `lut_webgl_hsl_gate.cjs`, `lut_proxy_mapping.cjs`, `lut_proxy_audio.cjs`,
  `lut_proxy_auto_prepare.cjs`, `test_studio_lut_pixel_parity.py`.

## Checks performed

- `npm run check:js` — lint, format, **97 tests passed**
- `pytest --ignore=tests/test_pr_journey_smoke.py -q` — **1126 passed, 3 skipped**
- `pytest tests/test_pr_journey_smoke.py -q` — **2 passed**
- `pytest tests/test_studio_lut_pixel_parity.py -q` — **2 passed**
- `ruff check .` — passed
- `mypy src packaging/itch_channel.py packaging/windows_third_party.py` — passed
- Packaged LUT smoke: baseline NO-GO; fixed paused/seek/playing
  **GO_BOUNDED_FIXTURE**, WebGL active, source unchanged, export unchanged
- Packaged functional E2E: **10/10 journeys passed**

## Limits

- The strict 3/255 absolute target is not achievable without changing the
  browser/FFmpeg color path; the 2.667 no-LUT baseline is documented in #310.
- Hardware trilinear sampling remains different from FFmpeg's tetrahedral
  interpolation. The bounded gate covers this for the synthetic fixtures; it is
  not universal LUT parity, HDR, wide-gamut, mixed-FPS or 4K proof.
- LUT sizes above the existing 2-65 validation range, missing/invalid LUTs,
  HSL/wheel fallback, proxies and crossfade composition keep their existing
  behavior and were not broadened here.
- No new rendering architecture, proxy system, dependency, schema, export
  change, source modification, merge or release.

## Reproduce

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[dev]'
node --test tests/js/lut_webgl_sampling.test.js
.venv/Scripts/python -m pytest tests/test_studio_lut_smoke.py -q
```

Packaged LUT smoke (use a completed color-probe fixture and a fresh output
directory):

```powershell
.venv/Scripts/python packaging/e2e/studio_lut_smoke.py `
  --exe dist/orga-drone/orga-drone.exe `
  --ffmpeg (Get-ChildItem dist/orga-drone/_internal/imageio_ffmpeg/binaries/ffmpeg*.exe | Select-Object -First 1).FullName `
  --fixture-dir build/189-color-controls-v3 `
  --output-dir build/267-lut-fixed
```

## Decision

GO for the bounded texel-centre LUT sampling fix. NO-GO for the original strict
3/255 absolute gate and for claiming universal LUT parity. No merge or release is
authorized by this document.
