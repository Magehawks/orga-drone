# Issue #223: opt-in single-clip LUT proxy playback

- **Status:** Experimental, opt-in, no public toggle
- **Date:** 2026-10-31
- **Related:** #221 feasibility, #222 proxy generator, #224 (not implemented)

## How it is enabled

The Studio page accepts a developer query flag:

```text
/studio?lut_proxy=1
```

Without the flag, the page renders no proxy URL and the player behaves exactly as
before. With the flag, the page adds a `data-lut-proxy-url` only for video clips
whose current settings already have a cached #222 proxy. Nothing is generated
automatically.

An explicit developer action builds one proxy for one clip:

```text
POST /api/studio/{clip_id}/playback-proxy?lut_proxy=1
```

It returns `{url, bytes, generation_s}`. `GET` on the same URL streams the
cached MP4 with Range support. Both endpoints return 404 when the experimental
flag is absent.

## Player behavior

- Only the **selected** video clip uses the proxy. Other Story clips keep the
  existing source playback and the existing "Playing without color file" label.
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
- the clip is the current Story selection.

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
CDP against `/studio?lut_proxy=1`:

| Check | Result |
|---|---|
| Explicit POST creates proxy | 200, 12,544 B, 0.191 s |
| Video element source | `/api/studio/1/playback-proxy?lut_proxy=1` |
| Play | playing, unmuted, 0.906 s advanced over ~0.9 s |
| Pause | paused, current time stable |
| Seek via ruler to 1.05 s | `currentTime = 1.044956` (inside one 30 fps frame) |
| Decoded proxy pixel at flash | RGB(230, 165, 205): warm LUT result |
| Screenshot | 99,163 B |

## Known limitations

- No automatic generation or background queue. #224 adds content-keyed LUT
  invalidation and bounded cleanup, but there is no periodic sweeper.
- A proxy is valid only for the settings that produced its cache key. Changing
  grade/LUT/source range makes the endpoint return 404; the page must be
  reloaded after generating the new proxy.
- Only the selected clip is proxied; transitions with an unselected partner
  remain approximate.
- Clips with custom clip-audio trimming fall back to ordinary source playback
  instead of using the proxy; see #228.
- The developer query flag is not a public feature toggle and is not advertised
  in the UI.
- No animated LUT, slow-motion, repeat, mask, overlay, map, or HUD parity.

## Verification

```powershell
python -m pytest tests/test_studio_playback_proxy_api.py -q -s
node tests/js/lut_proxy_mapping.cjs
python -m ruff check src/orga_drone/app.py src/orga_drone/studio_playback_proxy.py tests/test_studio_playback_proxy_api.py
python -m mypy
```
