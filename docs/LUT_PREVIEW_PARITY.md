# Studio LUT preview parity (#219)

## Root cause and repair

The high-DPI preview canvas painted the original media above the FFmpeg LUT
still. The still could render successfully while remaining invisible. Mutable
clip/time URLs were also browser-cached for 60 seconds, color saves did not
refresh paused previews, and late request invalidation allowed obsolete frames
to appear during scrubbing. JavaScript treated creative strength zero as 100.

The existing compositor now uses decoded still pixels, keeps the clip's framing
and opacity, and does not apply CSS grading twice. Requests invalidate immediately,
deduplicate identical inputs, wait for pending grade/color saves, and bypass HTTP
caching. Content-keyed disk caching remains. Missing LUT files are checked before
returning cached pixels. Errors and pending work remain visible in the preview.

Both paths retain grade → confirmed technical conversion → creative LUT →
saturation ramp. Quick Looks continue to replace the basic sliders. Technical
conversion is independent of creative strength and never enabled automatically.
The JPEG path reproduces export's limited-range BT.709 output interpretation
before conversion to full-range JPEG. Cache version 2 invalidates earlier stills.
Source media and stored LUT references are unchanged.

## Boundaries

Continuous playback still uses native video and approximate CSS grading, with
the visible “Playing without color file” indicator. Pause or scrub to inspect
the LUT. This follows ADR 0028; no second LUT engine has been introduced.

Stills have a maximum edge of 720 pixels and a 0.1-second scrub clock. JPEG/H.264
compression, chroma subsampling, scaling and display color management permit small
differences. Sharpen/denoise remain omitted from stills. This is a color inspection
path, not a full-story reference render: crossfade partners and loop-overlap
partners still use their existing preview path. Inspect outside those joins for
grade comparisons. Overlays, masks, HUD and map remain separate preview layers.

A narrowly scoped follow-up should investigate a local cached graded playback
proxy for a selected clip: source/grade/LUT cache identity, cancellation, seek and
audio synchronization, temporary-file limits, and measured cold-start latency.
Do not promise continuous parity before a packaged WebView2 prototype proves it.

## Regression evidence

`tests/js/lut_preview.cjs` executes production scheduling and compositor functions
with controlled network/decode timing. It checks stale responses during debounce
and decode, repeated redraws, pause/play/removal, creative strength, decoded LUT
pixel selection, framing, transition opacity and avoidance of double grading.

`tests/test_studio_lut_pixel_parity.py` generates moving synthetic footage and a
non-identity synthetic LUT, exports actual MP4s, and compares two source timestamps
after trimming. It checks creative strength 0/50/100 with and without confirmed
technical conversion, non-neutral basic/tonal adjustment, ordered strength changes,
missing LUT after caching, and unchanged source SHA-256. Maximum per-channel mean
absolute error must remain below 8/255. No private media, coordinates, SRT or vendor
LUT is a fixture.

The packaged GUI checklist is: assign LUT, inspect paused pixels, seek, export and
compare, change strength 50 → 0 → 100, remove/reassign, play/pause, inspect zoom,
close/reopen the project and repeat. Human product testing and the final merge
decision follow `AGENT_WORKFLOW.md`.
