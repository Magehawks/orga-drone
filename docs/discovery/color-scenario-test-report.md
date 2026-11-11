# Color scenario tests — measured deviations and performance

Companion to `tests/test_studio_color_scenarios.py` and
`tests/test_studio_color_history.py` (PR #368, branch
`qa/color-scenario-hardening`). Reference scenarios (Cinematic Autumn
Landscape, Nordic Red Boat, Cinematic Urban Architecture, D-Log M material)
are represented as deterministic synthetic scenes; they are visual targets,
not pixel goldens. All numbers in this revision were measured against
develop tip 8ff2545 (PR #368 head 768c835) with `PREVIEW_MAX_EDGE = 1080`,
`PREVIEW_JPEG_Q = 3`, and the `imageio-ffmpeg` 0.8.1 binary
(`ffmpeg-win-x86_64-v9.0.2`) on Windows. Earlier numbers that circulated
during review were measured on the older tree state (c8f55ce:
`PREVIEW_MAX_EDGE = 720`, `PREVIEW_JPEG_Q = 5`) with the `imageio-ffmpeg`
0.6.0 binary (ffmpeg v7.1) and are superseded; that environment is also what
issue #369 documents.

## Fixture design

- Scenes are built in-memory with PIL from fixed patch colors; no binary
  fixtures, no randomness, no external assets. A `scale` factor renders the
  same layout at 320×180 (pixel-math tests) or 1280×720 (ffmpeg parity tests).
- LUTs are generated `.cube` text from pure functions (flat-to-contrast
  conversion, creative channel boost) — deterministic by construction.
- These are **D-Log-style synthetic approximations**, not real DJI D-Log M
  colorimetry. Real-footage claims belong to #283's fixture matrix.
- Source media hashes are asserted unchanged after every ffmpeg test.

## Parity metric definitions

Three different metrics appear across this suite and the existing tests.
They are not interchangeable; each use names its metric.

| Metric | Definition | Used by |
|---|---|---|
| **A — patch MAD (mean RGB)** | Per-patch mean of absolute pixel differences, averaged over R,G,B: `sum(ImageChops.difference(patch).mean)/3` | `test_full_stack_still_matches_export_photo` (≤3.0 here); the existing `test_studio_lut_pixel_parity` photo swatch gate uses the same metric class at ≤3.0 |
| **B — per-channel patch-mean difference** | `abs(mean_A[c] − mean_B[c])` per channel, asserted per channel (so effectively the worst channel) | `test_full_stack_neutral_settings_encode_without_grade` (≤3.0 still↔export, ≤6.0 export↔source) |
| **C — full-frame per-channel MAD** | Per-channel mean of absolute pixel differences over the whole frame, asserted at the worst channel: `max(ImageChops.difference(frame).mean)` | `test_full_stack_still_matches_export_video` (<8; the convention already used by `test_lut_strength_pixels_match_mp4`) |

Relationship to #320: the packaged-E2E strict gate is **swatch mean RGB error
≤3.0** (metric-A class on its own swatches). This PR neither reproduces that
gate nor presents its bounds as an admission decision; #320 owns the residual
and any acceptance change. On flat synthetic patches, metrics A and B agree
within measurement rounding, but they are computed differently and reported
separately below.

## Measured deviations (patch tables at 640×360, below the still's native edge)

### Still↔export, metric A (patch MAD mean RGB) and metric B (per-channel patch-mean, worst)

| Case | Patch | A | B |
|---|---|---|---|
| png / neutral | sky | 1.00 | 1.00 |
| png / neutral | orange | 1.33 | 2.00 |
| png / neutral | yellow | 0.67 | 2.00 |
| png / neutral | green | 1.67 | 2.00 |
| png / neutral | water | 1.00 | 1.00 |
| png / full-stack | sky | 0.67 | 1.00 |
| png / full-stack | orange | 1.00 | 1.00 |
| png / full-stack | yellow | 0.67 | 2.00 |
| png / full-stack | green | 1.67 | 3.00 |
| png / full-stack | water | 1.04 | 1.99 |
| jpg / neutral | worst (green) | 1.67 | 2.00 |
| jpg / full-stack | worst (green) | 1.67 | 3.00 |

(JPG rows match PNG rows on every patch; only the worst is listed.)

Reading:

- The still side carries the whole deviation: the export↔source check at
  neutral settings measures H.264 DC/chroma quantization only
  (metric-B worst **6.0**, asserted ≤6.0), while still↔export stays at
  ≤2.0 (metric B) on pale patches. The residual therefore sits in the
  preview-still JPEG (`-q:v 3`) plus BT.709→BT.601 conversion
  (`JPEG_COLOR_CHAIN`), not in the export path — the same residual class the
  packaged E2E records in #320 ("neutral PNG 4.67" there, on different
  swatches and pipeline constants).
- Gate provenance: photo still↔export ≤3.0 (metric A) matches the level the
  existing photo parity tests already pass; the neutral per-channel ≤3.0
  (metric B) and export↔source ≤6.0 are new bounds measured on this
  baseline and verified green on the CI runner in run 43077940167.

### Video still↔export, metric C

Full stack on synthetic CFR video: worst per-channel frame MAD **3.55**
across both sampled timestamps (budget <8, the established video convention).
Smaller than the photo budget because both sides decode through the same
YUV→RGB path at native size; the 8-budget stays as-is for H.264 chroma/scaling
tolerance on moving frames.

## E2E coverage boundary

What this suite proves and what it explicitly does **not**:

| Level | Status | Where it belongs |
|---|---|---|
| Pure pixel-math semantics (HSL selectivity, wheels tonal bands, identity/extremes) | **Covered** — always runs, no ffmpeg needed | this PR |
| FFmpeg render parity: preview still ↔ MP4 export (photo PNG/JPG, video) | **Covered** — deterministic synthetic scenes | this PR |
| Studio API/history integration: undo/redo, persistence across DB reopen | **Covered** — TestClient against real routes | this PR |
| Windows WebView2 UI journey (real clicks, paint path) | **NOT RUN** — out of scope | #275, #283 |
| Packaged EXE E2E (PyInstaller zip, MOTW, relaunch) | **NOT RUN** — out of scope | #267, #262 |
| MCP contract / natural-language intent | **NOT RUN** — out of scope | #292, #283 |
| Real DJI D-Log M colorimetry | **NOT RUN** — synthetic D-Log-style fixtures only | #283 |

These tests are API/render-level evidence. They cannot substitute the
release-level gates listed above.

## Findings

1. **ffmpeg odd-dimension crash — tracked in #369 (investigation issue).**
   The `imageio-ffmpeg` 0.6.0 binary (ffmpeg v7.1) crashes when the
   preview-still scale filter yields an **odd output height** followed by
   `format=yuv420p`: 720×405 → `0xC0000374` heap corruption (6/6 runs),
   1080×607 → `0xC0000005` access violation; even heights (406/608) and the
   v9.0.2 binary (0.8.1) are clean in the same matrix. The originally
   reported JPEG+neutral case was one instance (old tree: max_edge 720 →
   405). At the current tip a 16:9 photo fits to 608 and does not crash,
   which is why CI/packaged paths pass; the window stays reachable for other
   aspect ratios wherever the v7.1 binary is installed. Repro matrix and
   suggested fixes live in #369; no product code changed here.
2. **Preview-still cold latency — separate from the steady-state table.**
   During review on the older tree state (max_edge 720, JPEG q5, ffmpeg
   v7.1) uncached 1280×720 stills with 17³ LUTs measured 2.75–2.99 s against
   the 1.0 s warning budget (`PREVIEW_COLD_LATENCY_WARN_S`). On the current
   tip with the v9.0.2 binary this is **not** reproduced: uncached stills
   measure 83.1 ms (neutral) to 211.1 ms (full stack), max 217.9 ms — under
   budget. The warning infrastructure itself is untouched; if budget
   warnings reappear on slower machines or larger LUTs, that is a
   performance ticket of its own, not part of #320/#369.

## Performance (uncached, median of 5; 1280×720 stills, current tip + v9.0.2)

| Operation | Median | Max |
|---|---|---|
| preview still: neutral | 83.1 ms | 85.0 ms |
| preview still: full stack (grade+LUT+HSL+wheels) | 211.1 ms | 217.9 ms |
| write HSL mixer cube (33³) | 196.6 ms | — |
| write color wheels cube (33³) | 135.1 ms | — |

Cube-write numbers were measured on the older binary; they are pure-Python
and binary-independent, hence still quoted. Cube writes are one-time per
settings state (content-keyed cache); the per-pixel Python apply functions
are test-only helpers, not app paths.

## Test map

| Test file | Covers |
|---|---|
| `tests/test_studio_color_scenarios.py` | Selective HSL (autumn foliage, red boat, urban sky), HSL luminance selectivity, wheels tonal-band + zero-luma tints, neutral identity (byte-exact), extreme settings (bounded, deterministic), D-Log conversion contrast/saturation restoration, full-stack still↔export parity (photo PNG/JPG metric A, video metric C), neutral encode fidelity (metric B) |
| `tests/test_studio_color_history.py` | Undo/redo for HSL, wheels, and look edits; grouped slider steps; color settings across a database reopen |

## How to run

```bash
pytest tests/test_studio_color_scenarios.py tests/test_studio_color_history.py
```

FFmpeg-backed tests skip when no ffmpeg binary is available; pixel-math tests
always run. On failure the assertion messages include patch name and measured
error; compare against the tables above before investigating, and check the
metric definition (A/B/C) named in the failing assertion's comment.
