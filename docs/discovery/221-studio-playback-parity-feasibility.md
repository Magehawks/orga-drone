# Issue #221: Studio playback parity feasibility (1/4)

- **Status:** Feasibility evidence for a follow-up decision
- **Date:** 2026-10-31
- **Scope:** measurement only. No playback, export, or UI behavior changed.
- **Related:** ADR 0028, `docs/LUT_PREVIEW_PARITY.md`, #220, #222-#224

## Question

A selected `.cube` LUT is visible on pause/scrub stills and in MP4 export, but
not during continuous Studio playback. Before choosing an architecture, compare:

1. **Local pre-rendered playback proxy** for one clip, rendered with the existing
   FFmpeg grade/LUT builders and played as ordinary H.264.
2. **GPU live LUT** in the WebView2 preview.

## Current architecture (inspected)

- Desktop shell: `pywebview` EdgeChromium/WebView2 (`src/orga_drone/desktop.py`).
  WebView2 runtime on the test machine: 156.0.4314.50. No custom GPU flags or
  WebGL path are configured.
- Playback: native `<video>`/`<img>` elements are composited to a 2D canvas
  (`drawPreviewLayer` / `paintPreviewBlit`, `static/js/studio.js:5042` and
  `:5106`). The canvas applies the clip's CSS filter for the approximate grade.
- LUT stills: `GET /api/studio/{id}/preview-frame` (`app.py:2151`) calls
  `render_preview_frame` (`studio_preview_frame.py:174`), which builds one
  FFmpeg graph per quantized source time and caches a 720-edge JPEG under
  `{data_dir}/preview-stills/`.
- Still and export share `ffmpeg_grade_chain` and `ffmpeg_lut_chain`
  (`studio_lut.py:338`); order is grade → confirmed conversion LUT → creative
  LUT → saturation ramp. Export adds CFR 30, BT.709 limited-range H.264
  (`export/studio_encoder.py:67`, `:89`).
- Playback deliberately omits the LUT and shows "Playing without color file"
  (`studio.js:2351`). This is ADR 0028's accepted behavior, not a bug.

## Option comparison against the current tree

| Criterion | Local pre-rendered proxy | GPU live LUT |
|---|---|---|
| Pixel engine | Existing FFmpeg builders (one engine, export truth) | New WebGL/Canvas `.cube` path; second pixel engine |
| Change to player | Swap/add `<video>` source for one selected clip; map source↔proxy time | Replace or wrap canvas compositing with GPU shader and LUT upload |
| Continuous playback | Native H.264 decode in WebView2 | Shader must run per frame; WebView2 GPU path unproven here |
| Audio | Proxy can carry source audio, but timing must be validated | Existing source audio untouched |
| Seek | Keyframe-dependent; short GOP helps (measured below) | Shader responds immediately, but only if frame delivery is smooth |
| Cache/staleness | Needs cache identity, eviction, invalidation (#224) | No disk cache; LUT state must be pushed to GPU |
| ADR 0028 fit | Reuses accepted FFmpeg path; extends it to playback | Rejected alternative in ADR 0028 |
| Evidence today | Bounded encode/latency measurements below | No prototype and no measurement in this tree |

## Bounded local benchmark

**Machine:** AMD Ryzen 7 5700X (8C/16T), Windows, WebView2 156.0.4314.50,
bundled FFmpeg 7.1 (gyan.dev essentials build).

**Synthetic source:** 12 s, 3840×2160, 30 fps, H.264, yuv420p, BT.709,
65,748,489 bytes, generated with `testsrc2` (SHA-256
`3353693376988B0715F1DBF6BADACE91A5BAAD661BB04958F0158E740F5FB25B`). A
synthetic non-identity warm `.cube` LUT (`LUT_3D_SIZE 2`) was applied with
`interp=tetrahedral`. This source decodes more easily than real drone 4K, so
proxy encode times below are optimistic for actual footage.

Reproducible commands (run in a scratch directory; `$FF` is the app's FFmpeg):

```powershell
& $FF -y -hide_banner -loglevel error -f lavfi `
  -i "testsrc2=size=3840x2160:rate=30:duration=12" `
  -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p `
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv `
  source4k.mp4

& $FF -y -hide_banner -benchmark -i source4k.mp4 -an `
  -vf "lut3d=file=warm.cube:interp=tetrahedral,scale=1280:1280:force_original_aspect_ratio=decrease:out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv" `
  -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p `
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv `
  -movflags +faststart proxy720.mp4
```

Add `-g 30 -keyint_min 30 -sc_threshold 0` for the short-GOP variant. For the
still path, call `render_preview_frame` with a `PreviewFrameRequest` at
`source_time_s=6.0`, `ColorLook(creative_lut=<32-hex>.cube, creative_strength=100)`,
a cleared `cache_dir`, and `data_dir` containing `luts/<name>.cube`.

### Measured results (single run unless stated)

| Measurement | Result |
|---|---|
| 720p proxy encode, 12 s, default GOP | 8.27 s wall; 93.5 s CPU (≈11.3 cores); 2.61 MB |
| 720p proxy encode, short GOP (`-g 30`) | 8.63 s wall; 93.8 s CPU (≈10.9 cores); 2.93 MB |
| 1080p proxy encode, 12 s, default GOP | 8.54 s wall; 92.6 s CPU (≈10.8 cores); 7.14 MB |
| Proxy first-frame/seek decode, 720p default GOP | 82–98 ms (3 runs, `-ss 6`) |
| Proxy first-frame/seek decode, 720p short GOP | 45–61 ms (3 runs, `-ss 6`) |
| Proxy first-frame decode, 1080p | 66–78 ms (3 runs) |
| Current LUT still, cold cache, 720 edge | 1.017 / 0.911 / 0.921 s; median 0.921 s; 16,155 bytes |
| Current LUT still, warm disk cache | 1.5 ms |

Proxy encode uses roughly 11 of 16 logical cores for the whole clip, so on-demand
generation is a multi-second background operation, not a synchronous pause/seek
replacement. Extrapolated linearly, a 30 s 720p proxy costs ≈21 s wall and
≈6.5–7.3 MB; a 1080p proxy costs ≈21 s and ≈18 MB. The real cost on DJI 4K
footage is expected to be higher because source decode is harder.

The current cold still path meets ADR 0028's ≈1.0 s target on this machine with
the synthetic source (median 0.921 s), leaving almost no headroom for real 4K.

### Evidence still missing

- No instrumented continuous-playback CPU/GPU profile inside packaged WebView2.
  Native video decode and canvas compositing cost are unmeasured.
- No prototype of a GPU `.cube` shader in this WebView2 runtime; no frame-rate or
  GPU-memory evidence.
- No A/V sync measurement for a proxy with audio, and no measurement of switching
  between source playback, proxy playback, and pause/scrub stills.
- No measurement of cold-start behavior for a partially written proxy or of
  concurrent proxy jobs competing with export.
- Synthetic media is easy to decode; drone 4K and long-GOP source will be slower.
- Cache eviction, deterministic identity, and cancellation are design items
  (#224), not measured here.

## Recommendation

**Go for a single-clip local pre-rendered proxy prototype (#222) with explicit
asynchronous/cached behavior. No-go for GPU live LUT in the current slice.**

The proxy path reuses the accepted export color engine and has measured,
predictable cost. Its cold generation time rules out pretending it is a
pause/seek replacement; it can only be an opt-in, pre-rendered playback mode
with visible processing/fallback status. A GPU live LUT would add the second
pixel engine ADR 0028 rejected, and there is no evidence in this tree that it
would sustain continuous playback in WebView2.

Minimal next experiment (issue #222): render one selected 10 s synthetic clip
to a 720p H.264 proxy with the shared grade+LUT builders into a temp cache
directory, measure end-to-end generation, decode/seek of the result, output
size, and color difference against the existing export on stable frames. Do not
connect it to the player yet.

## Go/no-go criteria for the static-LUT single-clip prototype

GO only if all of the following hold in the #222 prototype:

1. A 10 s 720p proxy for a 4K source finishes in the background without blocking
   playback or editing; measured generation is reported, not assumed.
2. The proxy is playable by the existing WebView2 `<video>` element, and seeks
   inside it reach the requested frame in ≤150 ms median with short GOP.
3. Colors on stable frames stay within the existing parity budget (per-channel
   mean absolute error <8/255) versus export at 0/50/100% strength.
4. Temporary disk use is bounded and documented: ≤5 MB per 10 s at 720p, and
   ≤7.5 MB with short GOP, on the benchmark source; cache location is under the
   app data directory, never beside the source.
5. The source file SHA-256 is unchanged and a failed FFmpeg run leaves no
   playable partial artifact.
6. Missing/failed proxy always falls back to today's playback with an honest
   ungraded label; no existing play/pause/seek behavior regresses.

NO-GO if any of these occurs: blocking UI during generation, proxy seek
>500 ms, unbounded/stale cache, audio or A/V drift beyond one frame in the #223
test, or color error above the parity budget. Stop and report rather than
expanding into a renderer rewrite.

## Stop conditions honored

Investigation stayed within the issue: architecture inspection, one bounded
synthetic benchmark, and this document. No player, export, cache, or UI code was
changed; #222-#224 remain unimplemented.
