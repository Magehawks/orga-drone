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
Both output scalers explicitly convert to limited-range BT.709, instead of
tagging pixels whose conversion matrix depended on FFmpeg graph negotiation.
The still then converts to full-range BT.601 JPEG with matching metadata in the
existing single FFmpeg invocation. JPEG cache entries publish atomically after
successful rendering; temporary files are removed on success or failure.
Cache version 5 invalidates earlier stills.
Source media and stored LUT references are unchanged.
An assigned creative LUT at 0% still uses the FFmpeg output color path (with
the LUT filter skipped), avoiding a switch to browser-specific source decoding.

## WebGL LUT sampling follow-up (#267)

The existing WebGL2 LUT preview path now maps normalized RGB domain values to
3D-texture texel centres. The previous raw `texture(lut, c)` lookup applied a
size-dependent contrast-like expansion before the LUT; on the #310 2x2x2 fixture
it produced a 36.333/255 max swatch error. Packaged WebView2 paused, seek and
playing previews now measure 3.304/255 whole-frame and 4.000/255 max swatch,
against a 2.667/255 no-LUT browser-vs-FFmpeg baseline. See
[267-lut-webgl-sampling.md](discovery/267-lut-webgl-sampling.md). The strict
3/255 absolute gate remains unmet because it is below that baseline color path;
the bounded gate and remaining limits are recorded there.

## Boundaries

Continuous playback uses the existing optional WebGL2 LUT renderer when it can
handle the clip; otherwise it uses native video plus approximate CSS grading and
the visible "Playing without color file" indicator. Pause or scrub uses the
shared FFmpeg still, WebGL renderer, or existing proxy path. This does not add a
new rendering architecture.

Stills have a maximum edge of 1080 pixels and a 0.1-second scrub clock. JPEG/H.264
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

`tests/test_studio_lut_pixel_parity.py` generates synthetic color bars with a timed
color change and a
non-identity synthetic LUT, exports actual MP4s, and compares two source timestamps
after trimming. Sample times lie inside stable sections so adjacent-frame CFR
rounding does not masquerade as a color error. It checks creative strength
0/50/100 with and without confirmed
technical conversion, non-neutral basic/tonal adjustment, ordered strength changes,
missing LUT after caching, and unchanged source SHA-256. Maximum per-channel mean
absolute error must remain below 8/255. No private media, coordinates, SRT or vendor
LUT is a fixture.

The packaged GUI checklist is: assign LUT, inspect paused pixels, seek, export and
compare, change strength 50 → 0 → 100, remove/reassign, play/pause, inspect zoom,
close/reopen the project and repeat. Human product testing and the final merge
decision follow `AGENT_WORKFLOW.md`.
