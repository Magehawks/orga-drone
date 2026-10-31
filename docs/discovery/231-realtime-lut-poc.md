# PR #231: real-time LUT preview PoC

- **Status:** PoC successful; editor integration not yet started
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

## Recommended integration (not implemented yet)

1. Expose the selected local `.cube` to the Studio client through a safe
   read-only route (or pass validated LUT data with the page).
2. Build one WebGL2 pass that applies the existing grade values and the 3D LUT
   to the decoded primary video at the preview display size.
3. Feed that WebGL canvas into the existing 2D preview compositor as the picture
   source, so framing, masks, overlays and transitions keep their current
   behavior. Keep the proxy/still fallback for WebGL-unavailable or ineligible
   clips.
4. Use the same WebGL pass for pause/seek so the still and video share one
   corrected source; no 720-edge JPEG over a WebGL frame.
5. Preserve the export pipeline and cache logic unchanged. The full proxy can
   remain an optional cache for export/other uses; it must not gate preview.

This is a larger compositor change than the current PR slice. Per the product
instruction, the PoC is reported before implementation rather than silently
rewriting the editor.

## Limitations of the PoC

- The PoC harness was injected into the packaged app; it is not yet connected to
  Studio's clip model, grade sliders, masks, overlays, transitions, or audio.
- The renderer is GPU-dependent; an unsupported WebView2/ANGLE environment must
  fall back to the current still/proxy path.
- Color management between browser video decode, WebGL, and FFmpeg stills still
  needs an integration test on stable frames.
- Seek backward is 233 ms (browser decode/cache), still below the 5 s goal.
