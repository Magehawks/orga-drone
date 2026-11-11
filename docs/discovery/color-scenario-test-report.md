# Color scenario tests — measured deviations and performance

Companion to `tests/test_studio_color_scenarios.py` and
`tests/test_studio_color_history.py` (branch `qa/color-scenario-hardening`).
Reference scenarios (Cinematic Autumn Landscape, Nordic Red Boat, Cinematic
Urban Architecture, D-Log M material) are represented as deterministic
synthetic scenes; they are visual targets, not pixel goldens. All numbers
below were measured on the development machine (Windows, imageio-ffmpeg
v7.1.1 binary) with develop at 8ff2545.

## Fixture design

- Scenes are built in-memory with PIL from fixed patch colors; no binary
  fixtures, no randomness, no external assets. A `scale` factor renders the
  same layout at 320×180 (pixel-math tests) or 1280×720 (ffmpeg parity tests).
- LUTs are generated `.cube` text from pure functions (flat-to-contrast
  conversion, creative channel boost) — deterministic by construction.
- Source media hashes are asserted unchanged after every ffmpeg test.

## Processing order (shared by still, proxy, export)

`grade -> conversion/creative LUTs -> HSL mixer -> wheels -> detail -> ramp`

Verified by printing both generated filter strings with the full stack:
the still chain (`preview_filter_chain`) and the export segment VF contain the
identical filter sequence; only scale/pad/fps differ by design.

## Measured deviations (patch mean RGB, max channel)

Comparison below the still's native edge (640×360), matching the established
photo parity pattern in `tests/test_studio_lut_pixel_parity.py`.

| Case | Patch | still↔export | export↔source |
|---|---|---|---|
| neutral | sky (pale blue) | 2.33–4.0 | 4.0 |
| neutral | orange | 3.01 | 5.0 |
| neutral | yellow | 3.39 | 5.0 |
| neutral | green | 3.43 | 6.0 |
| neutral | water | 2.64 | 4.0 |
| full stack | worst (green) | 3.19 | n/a (grade intended) |

Reading:

- `export↔source` at neutral settings measures H.264 quantization only
  (quality `best`): ≤6 levels on flat patches.
- `still↔export` is dominated by the still-side representation: preview
  stills are JPEG (`-q:v 5`) written through the BT.709→BT.601 full-range
  conversion (`JPEG_COLOR_CHAIN`). Pale desaturated patches shift by up to
  ~3.4 levels even with everything neutral. This reproduces the residual
  class already recorded for the packaged E2E in issue #320
  ("neutral PNG 4.67"), isolated here to the still cache, not the export path.
- The scenario tests therefore pin `still↔export ≤ 5.0` as a documented
  characterization bound and keep the strict ≤3.0 gate where the existing
  suite already proves it (single-effect saturated swatches). No existing
  tolerance was changed; #320 owns raising the residual.

## Findings

1. **ffmpeg heap corruption on JPEG + fully neutral still chain**
   (new, low app impact). `render_preview_frame` with a JPEG source and a
   fully neutral chain crashes the imageio-ffmpeg v7.1 binary with
   `0xC0000374` (STATUS_HEAP_CORRUPTION), empty stderr, rc 3221226356.
   Reproduction: call `render_preview_frame(PreviewFrameRequest(<1280×720
   .jpg>, "photo", 0, ImageAdjust(), ColorLook()), data_dir=...)`.
   The UI never reaches this window: `/api/studio/{id}/preview-frame`
   refuses neutral color state (`app.py`, `color_needs_preview_still` guard),
   and photo detail export uses a different module. Recorded here so the
   boundary stays visible; no product code changed.
2. **Preview-still cold latency** for 1280×720 sources with 17³ LUTs:
   2.75–2.99 s against the 1.0 s warning budget (`PREVIEW_COLD_LATENCY_WARN_S`).
   Smaller/uncached renders measure 79–171 ms (table below). Not a
   regression — the budget warning fired for the largest test renders on this
   machine.
3. No functional color-path bug found in the combined stack: preview still,
   playback-proxy chain builder, and export produce equivalent filter
   sequences, and all pure-pixel selectivity/tonal assertions hold.

## Performance (uncached, median of 5; 1280×720 stills)

| Operation | Median |
|---|---|
| preview still: neutral | 79.4 ms |
| preview still: grade only | 116.0 ms |
| preview still: grade + conversion LUT | 110.6 ms |
| preview still: full stack (grade+LUT+HSL+wheels) | 171.0 ms |
| write HSL mixer cube (33³) | 196.6 ms |
| write color wheels cube (33³) | 135.1 ms |

Cube writes are one-time per settings state (content-keyed cache); the
per-pixel Python apply functions are test-only helpers, not app paths.

## Test map

| Test file | Covers |
|---|---|
| `tests/test_studio_color_scenarios.py` | Selective HSL (autumn foliage, red boat, urban sky), HSL luminance selectivity, wheels tonal-band + zero-luma tints, neutral identity (byte-exact), extreme settings (bounded, deterministic), D-Log conversion contrast/saturation restoration, full-stack still↔export parity (photo PNG/JPG, video), neutral encode fidelity |
| `tests/test_studio_color_history.py` | Undo/redo for HSL, wheels, and look edits; grouped slider steps; color settings across a database reopen |

## How to run

```bash
pytest tests/test_studio_color_scenarios.py tests/test_studio_color_history.py
```

FFmpeg-backed tests skip when no ffmpeg binary is available; pixel-math tests
always run. On failure the assertion messages include patch name and measured
error; compare against the tables above before investigating.
