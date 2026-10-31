# Issue #232: Studio HSL colour mixer

## Scope

A per-clip HSL mixer for photo and video Story clips. Eight ranges (red,
orange, yellow, green, aqua, blue, purple, magenta) each expose Hue,
Saturation, and Luminance from -100 to 100. Neutral is 0. There is a reset for
the selected range and for the whole mixer. Colour wheels, curves, sky masks,
and AI masking stay out of scope.

## Processing order

```
static grade (warmth, exposure, contrast/saturation, tonals)
  -> conversion LUT
  -> creative LUT (with strength)
  -> HSL mixer LUT
  -> sharpen / denoise
  -> saturation ramp
  -> framing / overlays / fades
```

Pause/scrub stills, the optional playback proxy, and MP4 export all call the
same builders in that order. A neutral HSL state adds no filter at all.

## Algorithm

The HSL mixer is compiled into a deterministic 33x33x33 `.cube` LUT and applied
through the existing `lut3d` path with tetrahedral interpolation. Generated
cubes live under `{data_dir}/hsl-luts/`, are content-addressed by the eight
ranges plus the algorithm constants, and are capped at 64 MB. Settings' cache
clear removes them.

Hue weighting uses the eight centres 0, 30, 60, 120, 180, 240, 270, and 300
degrees. Between two centres the weights crossfade with `smoothstep`, so the
weights sum to 1 everywhere and the derivative is zero at each centre. Hue at
15 degrees therefore gives 50/50 red/orange instead of a hard switch. A chroma
gate fades the effect out for near-gray pixels, which have no meaningful hue.

Internal mappings (UI values remain -100 to 100):

| Slider | Full-scale mapping |
|--------|--------------------|
| Hue | +/-45 degrees |
| Saturation | 0x to 2x the pixel HSL saturation |
| Luminance | +/-0.30 HSL lightness |

## Performance

- Slider input does not call FFmpeg. It only stores the draft values and
  invalidates the rendered still.
- Saves are debounced (150 ms) and serialized per session, so rapid releases
  coalesce. A response for an older state cannot overwrite a newer one.
- The existing preview-still cache key includes the HSL state, the clipped
  source time, and the existing grade/LUT settings. Old in-flight requests are
  aborted, and responses carry a token check.
- Building a new 33^3 cube takes roughly 0.2 s on the development machine.
  Repeated previews reuse the cached cube; full-video encoding never starts
  because of a slider.

## Preview / export parity

The tolerance test renders synthetic SMPTE bars with selected green, blue, and
magenta changes, exports MP4, and compares pause/scrub JPEGs against extracted
MP4 frames with `max(mean channel difference) < 8` in 8-bit RGB. This matches
the existing LUT parity tolerance and accommodates JPEG compression, H.264
chroma subsampling, and scaling. The test fails if the two paths use different
HSL implementations. It is not a claim of bit-identical pixels.

Live playback cannot apply a generated LUT in the WebView2 `<video>` element.
As with user LUTs, playback may omit HSL and shows a state chip; pause/scrub is
the honest preview. The optional playback proxy (`?lut_proxy=1`) accepts HSL
clips and uses the same chain.

## Verification notes

- Synthetic 320x180 media is used in automated tests.
- Real 4K DJI footage was not available in the automated environment; the
  project owner performs the realistic media check before release.
- Neutral HSL leaves existing project JSON and the existing grade/LUT chain
  unchanged. Old projects have no `hsl` key and load as neutral.
