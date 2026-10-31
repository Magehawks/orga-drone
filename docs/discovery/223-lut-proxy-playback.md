# Issue #223: automatic single-clip LUT proxy playback

- **Status:** Automatic for eligible LUT clips; no developer flag
- **Date:** 2026-10-31
- **Related:** #221 feasibility, #222 proxy generator, #224 cache identity

## Normal workflow

1. Open a clip in Studio.
2. Choose a LUT.
3. The preview prepares the proxy for that clip in the background.
4. Play, pause, seek, and clip selection use the same proxy frame.

No query flag and no LUT-proxy button are required. When a LUT is selected (or a
project with a LUT clip is opened), the client debounces and calls the internal
`POST /api/studio/{clip_id}/playback-proxy` endpoint for the selected/active
clip only. The request runs in a worker thread; the Studio UI stays responsive.
Generation for other clips is not started.

`GET` on the same URL streams the cached MP4 with Range support. A page render
adds a `data-lut-proxy-url` only when a valid proxy is already cached; otherwise
the client prepares it. The server page no longer needs a developer flag or
cookie.

## Player behavior

- The **active playhead clip or selected** video clip uses the proxy. Other Story
  clips keep normal source playback.
- While a proxy is being prepared, pause/seek/selection keep the normal source
  and show the existing updating chip, so a focus change does not suddenly swap
  in a soft JPEG still.
- `videoSrcFor()` prefers the LUT proxy, then the existing media proxy, then the
  original stream. Missing proxy URLs fall back to the original stream.
- Proxy time is clip-local: `source time = source_in + proxy time`. Seeking and
  the playback clock use proxy time directly; source playback keeps subtracting
  `source_in`.
- The proxy already contains grade + LUT, so the preview canvas does not apply
  the CSS grade a second time.
- The proxy carries its own AAC audio. While it is active, the separate source
  audio element is paused and the video stays unmuted.
- If the proxy request fails after the page was rendered, an error handler drops
  the URL and reloads the original stream for that clip.
- Play/pause, short seeks, and the existing transport remain unchanged.

## Eligibility (automatic fallback when false)

A clip uses the proxy only when all of these are true:

- it is a video with an assigned conversion and/or creative LUT;
- the grade is static (no color-animation keys and no active saturation ramp);
- playback speed is 1× and no slow-motion bar is stored;
- section repeat / forward loop are not active;
- the clip is the active playhead clip or the Story selection.

This keeps source/proxy time mapping and audio simple. Animated LUTs,
transitions, slow motion, repeats, masks, overlays, maps, and HUD are not
routed through the proxy.

## Measured evidence

### API and media test (`tests/test_studio_playback_proxy_api.py`)

3 s synthetic clip with a white flash and a beep at 1.0 s, 320×180, static
creative LUT, explicit POST:

| Measurement | Result |
|---|---|
| Proxy generation | 0.21 s |
| Proxy size | 12,544 B |
| Seek to 2 s | 0.056 s |
| Audio onset delta vs source | 0.000 s |
| Source SHA-256 | unchanged |
| Proxy cache location | `{data_dir}/playback-proxies/`, not beside source |
| Range request | 206 with 100 bytes |

The proxy is dark before 1.0 s and bright at 1.05 s, and the beep onset matches
the source. Changing the creative strength to 50 % makes the old proxy URL
return 404 instead of serving stale colors.

### Real Windows WebView2 smoke

Source desktop app (`python -m orga_drone`, WebView2 Edg/156) with
`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9229`, driven by
CDP against `/studio`:

| Check | Result |
|---|---|
| Explicit POST creates proxy | 200, 12,544 B, 0.191 s |
| Video element source | `/api/studio/1/playback-proxy` |
| Play | playing, unmuted, 0.906 s advanced over ~0.9 s |
| Pause | paused, current time stable |
| Seek via ruler to 1.05 s | `currentTime = 1.044956` (inside one 30 fps frame) |
| Decoded proxy pixel at flash | RGB(230, 165, 205): warm LUT result |
| Screenshot | 99,163 B |

## Real 4K performance (before/after)

With a 77.3 s DJI 4K clip, its Golden Hour grade and the user's local LUT:

| Measurement | Before | After |
|---|---|---|
| First visible LUT preview | none until proxy done | **0.9–1.7 s** LUT JPEG still |
| Full proxy | 242 s | **101–105 s** |
| Encoding | LUT at 4K, x264 veryfast CRF20 | scale to 720p first, x264 **ultrafast CRF23** |
| Proxy size | 21.76 MB | 45.8–49.3 MB |
| Color difference vs old order | — | **< 2.4/255** on stable frames |

The faster proxy applies scale before the per-pixel LUT (the export keeps its
grade → LUT → scale order). The measured mean color difference against a fresh
reference with the old order was 1.5–2.3/255, inside the 8/255 budget.

During preparation the Studio shows a fast LUT still with
"Still frame with color file · LUT video is being prepared..."; during playback
it shows "LUT video is being prepared..." instead of claiming the video is
ready. Play/pause/seek/selection measured 1–8 ms while the 4K proxy encoded.
When the proxy is ready, the still and chip disappear and the 1280×720 proxy is
used for every state.

In the packaged-EXE 00:58 regression, selected, play, pause, seek to 58 s and
re-selection all used the same proxy source; the time stayed 58.026046 and the
source size/mtime was unchanged.

While a proxy exists, pause/seek/selection keep its decoded video frame instead
of overlaying the 720-edge JPEG still. The still is only used when no proxy is
available. The proxy is accepted for the selected clip and for the active
playhead clip, so moving the playhead does not silently disable it.

## Known limitations

- Automatic preparation is limited to the selected/active clip; there is no
  whole-project pre-render or background queue. #224 adds content-keyed LUT
  invalidation and bounded cleanup, but there is no periodic sweeper.
- A proxy is valid only for the settings that produced its cache key. Changing
  grade/LUT/source range makes the old URL return 404; the client clears it and
  schedules a new preparation.
- The proxy covers the active or selected clip; transitions with a non-active
  partner remain approximate.
- Clips with custom clip-audio trimming fall back to ordinary source playback
  instead of using the proxy; see #228.
- Long 4K clips still take minutes to prepare. The automatic preparation shows
  the existing updating chip; until it finishes, the clip uses the normal source
  rather than a soft JPEG still.
- No animated LUT, slow-motion, repeat, mask, overlay, map, or HUD parity.

## Verification

```powershell
python -m pytest tests/test_studio_playback_proxy_api.py -q -s
node tests/js/lut_proxy_mapping.cjs
python -m ruff check src/orga_drone/app.py src/orga_drone/studio_playback_proxy.py tests/test_studio_playback_proxy_api.py
python -m mypy
```
