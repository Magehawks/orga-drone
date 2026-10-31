# PR #231: real-time LUT preview PoC

- **Status:** Implemented in the Studio preview
- **Date:** 2026-10-31
- **Method:** packaged Windows EXE, WebView2, CDP-injected test harness
- **Media:** real 77.3 s DJI 4K clip, 33³ local `.cube`, frame at 58 s
- **Goal:** corrected video playback in ≤ 5 s without a 100 s proxy

## Why the current proxy path misses the target

The current proxy applies the per-pixel LUT at 4K and then scales to 720p. On the
real clip that is ~101–105 s (even after scale-first + ultrafast CRF23). The fast
JPEG still (0.9–1.8 s) is corrected, but the video stays original until the
proxy finishes. That is a deliberate but unacceptable preview mismatch.

## PoC: WebGL2 LUT over the live video

The PoC loaded `/media/36991/stream` in WebView2, downscaled each decoded frame
to 1280×720 on a 2D canvas, uploaded it to WebGL2, and sampled a 33³ 3D LUT
texture with a strength uniform. No proxy, no FFmpeg call, no editor change.

Renderer: `ANGLE (AMD, AMD Radeon RX 6700 XT, Direct3D11)`.

| Measurement | Result |
|---|---|
| First corrected video after play/seek to 58 s | **931 ms** |
| Video advanced over 5 s | **5.002 s** |
| Dropped video frames | **0 / 332** |
| Canvas render loop | ~240 draws/s |
| Seek forward | **62 ms** |
| Seek backward | **233 ms** |
| LUT strength update | **0.02 ms** |
| System CPU average during run | **16.3 %** |
| Color error vs FFmpeg LUT-only still | **4.5–4.8 / 255** |

The 4.5–4.8 error compares WebGL linear 3D-texture sampling with FFmpeg
tetrahedral sampling; it is inside the existing 8/255 preview budget. The PoC
omitted the basic grade sliders, but those are a few extra shader uniforms and
do not change the frame rate.

## Option comparison

| Option | First corrected video | Smoothness / seek | Effort | Load | Fit |
|---|---|---|---|---|---|
| **A. WebGL2 LUT + grade shader** | **~0.9 s** | 0 dropped frames; seek 62–233 ms | Medium–high: compositor hook, LUT upload, grade limits | GPU via ANGLE; ~16 % system CPU | Best; no 100 s wait |
| B. Short proxy segments around playhead | Estimated ~3–5 s for 2–3 s segment | Rolling segments and joins need scheduling; seeks regenerate | High | High (continuous background FFmpeg) | Only if A fails |
| C. Current still + full proxy | 0.9–1.8 s still, video only after 101–105 s | Proxy seek good once ready | Low (current) | High for 100 s | Rejected: mismatched still/video |

Option A meets the product target with a wide margin. Option B still leaves
joins, cache identity, and background load; it does not remove the long-running
encoder. Option C is the current behavior the product decision rejects.

## Integration in Studio

The PoC is now the Studio preview path for eligible video clips:

1. `GET /api/luts/{asset}` serves the selected local `.cube` read-only.
2. `static/js/studio-lut-webgl.js` applies the existing grade factors plus the
   conversion/creative 3D LUTs on WebGL2 at the display size.
3. The WebGL canvas feeds the existing 2D compositor and mask sampling; framing,
   zoom/pan, overlays and transitions remain on the existing compositor.
4. Pause/seek use the same WebGL frame; the server still is suppressed once the
   LUT renderer is ready.
5. The proxy path remains as fallback when WebGL2 is unavailable or a clip is
   ineligible. Auto proxy preparation is skipped for WebGL-capable clips.
6. Export is unchanged.

### Packaged-EXE Studio smoke (real 77.3 s DJI 4K clip)

| Measurement | Result |
|---|---|
| WebGL2 supported | yes (ANGLE / AMD RX 6700 XT) |
| LUT fetch + first corrected Studio frame | **103–105 ms** after selection |
| Video source | original `/media/36991/stream` (no proxy) |
| Proxy files created | **0** |
| Still/chip | hidden; no soft JPEG overlay |
| LUT strength 100 → 50 while playing | canvas pixel changed, no reload |
| LUT selection while playing | new LUT fetched, canvas pixel changed |
| 1.5 s playback | 90 video frames, **0 dropped** |
| Seek to 58 s | source/time correct |
| Clip focus at 00:58 | same source and time |
| Mask + text overlay active | mask canvas visible, one overlay child |
| WebGL disabled fallback | auto proxy generated and played normally |
| Source file | unchanged |

The font/color grade is applied by the shader using the same `gradeFactors`
math as the CSS preview; LUT interpolation is WebGL linear 3D texture sampling.
The PoC LUT-only frame differed from the FFmpeg LUT-only still by 4.5–4.8/255.

## Limitations

- The renderer is GPU-dependent; unsupported WebView2/ANGLE environments fall
  back to the still/proxy path.
- Animated color (keyframes) still uses the existing fallback; static grade,
  creative/conversion LUT, LUT strength and saturation ramp are supported.
- Photos continue to use the existing still/proxy path.
- The WebGL renderer runs at preview resolution (max 1280×720 box), not at the
  full 4K source size. This is intentional and matches the displayed preview.
- Seek backward remains browser-limited (~233 ms in the PoC), still far below
  the 5 s target.
