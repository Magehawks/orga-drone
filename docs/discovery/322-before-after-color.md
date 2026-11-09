# Issue #322 — temporary Before/After color comparison

## Architecture review before implementation

Base: develop `14b542a169c0185b24934d28947aecf9706d1713`, including merged #321.
Reviewed #322, `STUDIO_MODULES.md`, the still route and renderer, grading/LUT/HSL/
wheels, WebGL/proxy selection, dual photo-still owners and their decode tokens.

The existing comparison checkbox neutralized CSS/basic grade factors but left
creative LUTs and graded proxies available and globally suppressed still owners.
It could therefore not meet the technical-conversion/creative separation contract.

The smallest safe slice replaces that checkbox with a hold button. A separate
ephemeral controller requests a read-only `preview-frame?before=1` JPEG through
the existing renderer. The route constructs neutral image/HSL/wheels/ramp inputs
and a conversion-only look; it never edits the clip. Confirmed technical LUTs are
retained and checked even on cache hits. An unconfirmed conversion is not applied.

The effective-input cache key remains still **v7**; proxy **v3** and export are
untouched. Before reuses a normal neutral/conversion-only cache identity. No new
renderer, cache namespace, schema, effect setting or proxy switch is introduced.
The controller owns only held state, an AbortController, monotonically increasing
request/decode token and object URL. Release/context changes revoke those resources.
Both normal #319 owners remain untouched, including prefetch and tick deduplication.

The compositor substitutes the temporary picture only for the selected layer,
bypassing already graded WebGL/proxy pixels and CSS filters. Framing, layer alpha
and masks retain their existing paths. While loading/failing it keeps After and
shows an explicit status; it does not display an unconverted raw frame as Before.
Release restores current normal rendering, rather than restoring a captured old
grade snapshot. Active playback is deliberately excluded. A same-clip loop blend
has two source offsets and is excluded from the single-picture comparison.

Pointer capture supports release outside the button. Space/Enter hold/release,
focus loss, pointer cancellation, page hiding/navigation, selection/seek/edit
changes and playback all restore After. Reload starts in After. No comparison
interaction calls a save, Undo or export API.

## Validation

Focused Python tests exercise JPG/PNG/video Before requests with separate
technical and creative LUTs, exact conversion-only reference bytes, immutable
database/history snapshots, missing-LUT checks on cached results, unchanged
effective cache identities, original hashes and byte-identical real MP4 output.
Node tests control fetch/decode races, rapid holds, selection/edit invalidation,
focus/cancel/navigation and read-only request counts. The legacy compositor
harness checks Before precedence over graded pictures and immediate owner restore.

The reproducible Windows source-app journey is
`packaging/e2e/studio_color_compare.py --output-dir <new-directory>` with `src` on
`PYTHONPATH`. It uses synthetic JPG/PNG/video, real WebView2 and FFmpeg; this is
not packaged-candidate or MOTW evidence. Final command results and limitations
are recorded in the PR. No private media or locations are attached.

## Color-parity limitations remain unresolved

This feature is not a fix for #320. The unchanged strict maximum swatch RGB error
threshold is **≤3.0**. Historical failures remain explicitly FAIL:

- Neutral JPG: **4.333333333333333**.
- Neutral PNG: **4.666666666666667**.
- Different-LUT photo crossfade: **3.313218390804598**.
- Photo → video: **4.0**.
- Video → photo: **3.6666666666666665**.

The #321 precision candidates remain rejected. No precision experiment or color
threshold change is included. Before uses the existing preview JPEG path and
inherits its detail/color limitations; it is a color inspection aid.


## Completed checks

- Focused Python preview/cache/LUT/image/look/compare/parity set: **48 passed**.
- `pytest tests/test_pr_journey_smoke.py -q`: **2 passed**, including real MP4.
- `npm run check:js`: lint/format PASS; **111 Node tests passed**.
- `node tests/js/lut_preview.cjs`, `hsl_preview.cjs`, `wheels_preview.cjs`: PASS.
- `ruff check .`: PASS.
- `mypy src packaging/e2e/studio_color_compare.py`: PASS (77 source files).
- Windows command: `python packaging/e2e/studio_color_compare.py --output-dir build/issue322-e2e-reviewed`:
  PASS in real WebView2 **157.0.4341.42**, launched from this checkout.

[Machine-readable evidence](issue-322-evidence/evidence.json) contains tested-file
SHA-256 identities and synthetic source/export hashes. The JPG/PNG/video journey
checks exact After canvas restoration, unchanged project/history snapshots,
rapid keyboard holds, real pointer capture/release outside the button, clip
changes, creative-LUT removal, reload, zero repeated held comparison requests,
zero additional playback-interval still requests, unchanged original hashes and
byte-identical fully decoded MP4 exports before/after comparison interactions.
The observed playback interval covers the photo path; video eligibility is
covered by the controller and existing proxy/lifecycle regressions. This is not
a full release-candidate, real-media or packaged Windows certification.

Early harness attempts were not passes: a wrong root ID, counting unrelated
background requests and comparing different backing dimensions were corrected.
The fixed 640×360 preview test surface keeps the exact pixel-restore assertion;
no color tolerance was introduced. Screenshot inspection also found overlapping
status pills; the comparison status now sits above the image separately from
the normal still-status pill. Final evidence is from the complete passing run.

Synthetic UI captures: [Before](issue-322-evidence/ui-before.png),
[After](issue-322-evidence/ui-after.png). No private media is included.
