# Issue #222: single-clip LUT playback proxy

- **Status:** Internal prototype, not connected to playback
- **Date:** 2026-10-31
- **Related:** #221 feasibility, #223/#224 (not implemented), ADR 0028

## What was added

`src/orga_drone/studio_playback_proxy.py` renders one selected video clip to a
local 720p H.264 proxy with the static grade, confirmed conversion LUT, creative
LUT, and fixed saturation value. It reuses `ffmpeg_grade_chain` and
`ffmpeg_lut_chain`, so the color order matches Studio export and pause/scrub
stills: grade → conversion LUT → creative LUT → saturation → scale.

- Output: H.264, 1280×720 box (long edge/aspect preserved), 30 fps CFR, short
  GOP (30 frames), BT.709 limited range, `+faststart`, optional source audio.
- Location: `{data_dir}/playback-proxies/<cache-key>.mp4`, never beside the
  source. The cache key covers source path/mtime/size, in/out, grade, LUT
  references and strength, size box, and proxy version.
- Atomicity: FFmpeg writes to a unique work directory; the final file is
  published only after a successful non-empty encode. The work directory is
  removed on success and failure.
- No Studio UI, timeline, player, or export code was changed.

Issue #224 adds content-keyed LUT identity and a bounded cleanup sweep. This
module itself remains one deterministic file per request; there is still no
background scheduling or job queue.

## Measured on the test machine

AMD Ryzen 7 5700X (8C/16T), bundled FFmpeg 7.1. Fixture: 10 s, 1280×720,
30 fps H.264 color bars with a 440 Hz audio track, synthetic non-identity
`.cube` used as both conversion and creative LUT, non-neutral basic grade,
strength 0/50/100.

| Strength | Generation | Seek to 5 s | Proxy size | Max mean per-channel error vs export |
|---|---|---|---|---|
| 0% | 1.372 s | 0.062 s | 165,072 B | 0.317/255 |
| 50% | 1.331 s | 0.062 s | 164,333 B | 0.317/255 |
| 100% | 1.320 s | 0.061 s | 162,408 B | 0.317/255 |

The maximum per-channel mean error across all sampled strengths and times was
0.317/255, well inside the existing 8/255 parity budget.

The bars fixture is static and compresses far better than camera footage. The
#221 benchmark with moving `testsrc2` measured 2.61 MB for a 12 s 720p proxy and
8.27 s generation on the same machine; treat that as the more realistic size and
time estimate for real 4K source material.

`tests/test_studio_playback_proxy.py` also confirms:

- each proxy decodes at 1280×720 through the existing FFmpeg/WebView2-compatible
  H.264 path and matches the exported MP4 on stable frames;
- 0%, 50%, and 100% strength produce distinct expected color means;
- the source SHA-256 is unchanged;
- a synthetic FFmpeg failure surfaces as `PlaybackProxyError` and leaves no
  `.mp4` and no work files;
- repeating an unchanged request reuses the deterministic cached path.

## Reproduction

```powershell
python -m pytest tests/test_studio_playback_proxy.py -q -s
```

The test prints the JSON measurements above. The fixture is generated locally;
no private media or vendor LUT is committed.

## Recommendation

The prototype meets the #222 acceptance criteria and the #221 GO conditions for
generation, size, seek, color parity, source safety, and failure cleanup. #223
may now evaluate opt-in playback of an already generated proxy; this module must
stay internal until that experiment proves A/V sync and fallback behavior.
