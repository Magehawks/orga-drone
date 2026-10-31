# Issue #228: LUT proxy audio and clip-switch safety

- **Status:** Experimental developer opt-in only
- **Date:** 2026-10-31
- **Related:** #223 playback, #224 cache identity/cleanup

## Audio rules

Studio's existing custom clip-audio path uses a separate `<audio>` element for
the source stream, with `source_in_s`, `source_out_s`, and `place_s` from the
clip's audio bar. The proxy contains untrimmed source audio, so it cannot
reproduce a custom trim by itself. The existing audio element also has startup
latency that is larger than one 30-fps frame on this machine (~0.27 s measured
when driving the proxy path).

We therefore use the safest narrow rule:

- **No custom clip audio:** the LUT proxy's own audio plays, the separate audio
  element is paused, and the global Studio volume is applied.
- **Custom clip audio active** (`readClipAudio` / detached audio is heard): the
  clip uses **ordinary source playback**. The LUT proxy is not exposed by the
  page or API for that clip, so the proven audio in/out/offset rules remain in
  charge. No duplicate tracks or time jumps are introduced.
- Clips with no custom audio and a proxy use the proxy audio; the existing
  media-proxy (`data-has-proxy`) path is unchanged.

This is an explicit fallback, not silent untrimmed proxy audio. The developer
sees the ordinary ungraded playback label for such clips.

## Clip switching

`videoSrcFor()` is selection- and eligibility-gated. It returns the LUT proxy,
then the existing media proxy, then the source stream. `loadedVideoSrc` and the
proxy error handler still clear/reload the source when a proxy cannot be used.

Focused JS coverage now checks:

- selected proxy -> ordinary clip -> selected proxy -> another selected proxy;
- source-in > 0 uses proxy-local time (`media target = local offset`), while
  source playback keeps `source_in + offset`;
- slow motion, slow bars, repeats, color animation, saturation ramp, and custom
  clip audio all fall back to ordinary playback.

Playback/clock mapping continues to use the proxy duration and a clip-local
offset. The canvas skips CSS grading for an active proxy, so there is no second
grade application.

## Windows WebView2 smoke

Source desktop app, WebView2 Edg/156, CDP, 3-clip story (custom-audio LUT clip,
plain clip, LUT clip with source in 1.0 s):

| Check | Result |
|---|---|
| Custom-audio LUT clip | fell back to `/media/.../stream`; video muted, separate source audio playing |
| Proxy -> original | source element, unmuted, playhead advanced |
| Original -> proxy (source in 1.0 s) | proxy URL active, `currentTime` advanced from 0.5 s, playhead correct |
| Proxy -> original reverse | source element, correct playhead |
| Play/pause | state and current time stayed stable |
| Deleted proxy after page load | no crash; a previously fetched media response stayed playable from WebView2's cache |
| Screenshot | 116,539 B |

The deletion case is intentionally reported honestly: an already-fetched proxy
may continue from the media cache. On a new load, the server recomputes the
cache key, returns 404 for a missing/stale proxy, and the page omits the proxy
URL; the client error handler also drops the URL and reloads the source.

## Known limitations

- Clips with custom clip-audio trimming do not get LUT proxy playback in this
  slice; they use ordinary playback to preserve audio semantics.
- Only the selected clip uses a proxy; transitions with a non-selected partner
  remain approximate.
- The browser may finish a proxy response already in its media cache even after
  the file is removed. New loads and API/page lookups do not activate stale
  proxies.
- No automatic generation, background queue, public toggle, or new effects.

## Verification

```powershell
node tests/js/lut_proxy_mapping.cjs
node tests/js/lut_proxy_audio.cjs
node tests/js/lut_preview.cjs
python -m pytest tests/test_studio_playback_proxy_api.py tests/test_studio_playback_proxy.py tests/test_studio_lut_preview_js.py -q
```
