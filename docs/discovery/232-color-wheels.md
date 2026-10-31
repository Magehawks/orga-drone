# Issue #232 follow-up: interactive Studio colour wheels

## Scope

Three per-clip colour wheels for shadows, midtones, and highlights, added beside
the existing eight-range HSL mixer. Each wheel is a point in the unit disc:
angle selects the hue direction, distance selects intensity, and the centre is
neutral. Per-wheel reset. HSL and the wheels are independent and combine with
Looks, LUTs, and global image adjustments. Curves, sky masks, AI grading,
glow/bloom, and a new player are out of scope.

## Processing order

```
static grade (warmth, exposure, contrast/saturation, tonals)
  -> conversion LUT
  -> creative LUT (with strength)
  -> HSL mixer LUT
  -> colour wheel LUT
  -> sharpen / denoise
  -> saturation ramp
  -> framing / overlays / fades
```

Pause/scrub stills, the optional playback proxy, and MP4 export use the same
builders. A neutral wheel state adds no filter. Existing Looks and LUTs are not
overwritten.

## Algorithm

The three wheel points compile into a deterministic 33x33x33 `.cube` applied
through `lut3d` with tetrahedral interpolation. Cubes are content-addressed
under `{data_dir}/color-wheel-luts/`, capped at 64 MB, and removed by Settings'
cache clear.

Tonal weighting uses smoothstep crossfades between shadow (luma 0), midtone
(luma 0.5), and highlight (luma 1) centres. The three weights always sum to 1,
so a pixel receives a continuous mix instead of a hard tonal cut.

A wheel tint is a zero-luma RGB direction: the hue angle is converted to an RGB
vector, that vector's luma is subtracted, and the result is peak-normalised.
Full radius adds at most 0.20 per channel before clamping. The centre is
exactly neutral.

## UI

The Image tab keeps the existing base/HSL sections and adds an open,
collapsible **Color Grading** section:

- three hue wheels side by side with a clearly visible white marker
- pointer drag with pointer capture, no snapping
- keyboard nudge with arrow keys; Shift uses a finer step
- numeric status such as `45° · 40%` and `Neutral` at the centre
- individual reset for each wheel
- HSL keeps its eight colour circles and three sliders per colour

## Performance

- Pointer movement updates the clip dataset and marker only; FFmpeg does not
  start while dragging.
- Saves are debounced (150 ms), serialised per clip, and grouped so rapid
  releases coalesce.
- The rendered still is invalidated immediately; the existing token and cache
  key checks reject older responses.
- A new 33^3 cube takes roughly 0.2 s; repeated previews reuse the cached cube.

## Preview / export parity

The parity test renders synthetic SMPTE bars with HSL + all three wheels,
exports MP4, and compares pause/scrub JPEGs against extracted MP4 frames with
`max(mean RGB channel difference) < 8`. This matches the existing LUT/HSL
tolerance and allows for JPEG, H.264 chroma subsampling, and scaling.

Live playback cannot apply a generated LUT in the WebView2 `<video>` element.
As with user LUTs and HSL, playback may omit the generated grades and shows a
state chip; pause/scrub is the honest preview. The optional playback proxy
accepts wheel clips and uses the same chain.

## Reported limitations

Real 4K DJI footage was not available in the automated environment; the
project owner performs the realistic media check before release. This document
does not claim an AI or automatic correction system.

## Verified on the Windows EXE

The packaged EXE was tested through Edge/DevTools against a live Studio page:

- Both sections were open without a developer flag: HSL with eight swatches and
  Color Grading with three wheels.
- A pointer drag on Shadows changed the marker, status (`329° · 70%`), clip
  dataset, preview still, and persisted value. Reloading kept the value.
- The Midtones reset returned the point to `Neutral` at `50% / 50%`.
- Sixteen pointer moves caused **zero** additional `/preview-frame` requests;
  one request was made after release.
- A real 1888x812 video export with a LUT, HSL, three wheels, and a global
  exposure adjustment completed in 3.0 s for a 6.8 s clip.
- Real-media preview/export parity at 720p: mean absolute RGB differences were
  `[2.46, 1.86, 3.09]` and `[2.48, 1.87, 3.06]` at two timestamps, below the
  documented tolerance of 8. The export frame was compared in its fitted
  content rectangle (the 16:9 frame letterboxes the 1888x812 source).
- Cold preview still for the real clip: about 295 ms. Cached still: about 68 ms.
