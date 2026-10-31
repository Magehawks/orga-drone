# Issue #224: LUT playback proxy identity and cleanup

- **Status:** Experimental path only; no public activation
- **Date:** 2026-10-31
- **Related:** #222 generator, #223 opt-in playback, ADR 0028

## Cache identity

`cache_key_for()` now covers:

- absolute source path, mtime (ns), and size;
- clip source in/out;
- every static grade slider;
- conversion/creative LUT references, confirmation, and strength;
- the **SHA-256 of every LUT file that actually participates** in the render;
- proxy width/height box, saturation, fps, CRF, preset, GOP;
- proxy format version (`PROXY_VERSION = 2`).

LUT content is hashed, not just the filename. Replacing bytes in
`{data_dir}/luts/<name>.cube` while keeping the same name produces a different
key, so an old proxy can never be served as the current output. LUTs that are
assigned but inactive (creative strength 0, unconfirmed conversion) are excluded
from the content hash because they do not affect pixels.

Changing source mtime/size, trim range, grade, LUT file/content, LUT strength,
or proxy version therefore misses the old key. The old file may remain on disk
until cleanup, but the page and API cannot activate it.

## Superseded or failed work

- FFmpeg still writes to a unique `work/<uuid>/proxy.mp4`.
- The result is moved into the final cache path only after a successful,
  non-empty encode.
- Before publishing, the generator recomputes the full key from current source
  stats and LUT content. If anything changed while FFmpeg ran, it raises
  `PlaybackProxyError(code="superseded")` and deletes the work directory. No
  partial or stale proxy is published.
- Concurrent requests use separate work directories. Both may publish files
  for their own key; only the key for current settings is visible to Studio.
- Missing LUTs surface as `LutMissingError`; cached lookups return no proxy
  instead of serving old pixels.

## Bounded cleanup

Constants in `studio_playback_proxy.py`:

| Constant | Value | Effect |
|---|---|---|
| `PROXY_CACHE_MAX_BYTES` | 512 MiB | Oldest proxies are removed until the `*.mp4` total fits |
| `PROXY_CACHE_MAX_AGE_S` | 14 days | Older proxies are removed |
| `PROXY_ORPHAN_WORK_AGE_S` | 6 hours | Old orphan work directories are removed |

Cleanup runs after each successful publish and keeps the just-published file.
It only touches direct `*.mp4` children of `{data_dir}/playback-proxies/` and
direct child directories of its `work/` folder. Every deletion resolves the path
and verifies its parent first. Original media, LUT assets, and files outside the
proxy cache are never deleted.

The cleanup is intentionally a simple bounded sweep, not a scheduler or job
queue. If no new proxy is generated, existing files are not swept in the
background.

## Fallback and playback behavior

#223 behavior is unchanged: the developer flag `/studio?lut_proxy=1`, only the
selected clip uses a ready proxy, and missing/erroring proxies fall back to the
original stream. There is no automatic generation at play time.

## Verification

- `tests/test_studio_playback_proxy.py`:
  - key changes for source, mtime/size, trim, grade, size box, saturation, LUT
    strength, proxy version, and same-name LUT content;
  - cache reuse only while the LUT bytes match;
  - cleanup removes expired/oversized files and old work dirs while preserving
    the current file, non-MP4 files, and files outside the cache;
  - a simulated LUT change during generation yields `superseded` and leaves no
    playable artifact.
- `tests/test_studio_playback_proxy_api.py`: unchanged clip reuses the proxy;
  rewriting the LUT bytes invalidates the API URL and the Studio page attribute.
- Existing #222/#223 tests, Ruff, MyPy, and the WebView2 smoke are rerun.

### Regression smoke result

Source desktop app (not a packaged EXE), WebView2 Edg/156, CDP: proxy
generated at 12,544 B in 0.203 s, video source was the proxy URL, play advanced
0.906 s over ~0.9 s, pause was stable, ruler seek to 1.05 s landed at
1.044956 s, and the decoded flash pixel stayed RGB(230,165,205).

## Known limitations

- Cleanup is generation-triggered; there is no periodic background sweeper.
- The size/age limits are constants, not user settings.
- Content hashing adds a small cost when a page or request resolves a cached
  proxy; cube files are typically small.
- Stale files remain visible on disk until a later generation triggers cleanup.
- Custom clip-audio trimming, transitions, slow motion, repeats, and animated
  color remain outside this experimental path (see #223).
