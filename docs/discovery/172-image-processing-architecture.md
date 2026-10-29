# Discovery: Image processing architecture and permissive license audit

- **Issue:** [#172](https://github.com/Magehawks/orga-drone/issues/172)
- **Date:** 2026-10-29
- **Status:** Discovery only. No runtime change in this note.
- **Tree checked:** `main` at discovery time (post-2.2.0 photo grade path)

Related product issues: [#76](https://github.com/Magehawks/orga-drone/issues/76),
[#152](https://github.com/Magehawks/orga-drone/issues/152),
[#168](https://github.com/Magehawks/orga-drone/issues/168), and the Studio/Bild
follow-ups [#173](https://github.com/Magehawks/orga-drone/issues/173)–[#177](https://github.com/Magehawks/orga-drone/issues/177).

## Question

What image-processing path should Orga Drone use before shipping LUTs, D-Log M
conversion, tonal controls, sharpening, or denoising — and which dependencies
are legally and technically acceptable for a MIT-licensed, local-first Windows
app that already redistributes a GPL FFmpeg binary?

## Method

Code and packaging evidence only (no new libraries, no UI redesign):

- Studio grade model: `src/orga_drone/studio_image.py`
- Studio segment chain: `src/orga_drone/export/studio_encoder.py` (`_segment_chain`)
- Photo still export: `src/orga_drone/export/still_export.py`, `studio_export.py`
- Preview: `static/js/studio.js`, `static/js/detail-export.js`
- ADRs `0011-studio-image-adjust.md`, `0019-studio-saturation-ramp.md`
- FFmpeg packaging: `packaging/WINDOWS_THIRD_PARTY.md`, `ffmpeg_bin.py`,
  `packaging/windows_third_party.py`

## What exists today

| Capability | Status | Notes |
| --- | --- | --- |
| Brightness / contrast / saturation / warmth | Shipping | Field `exposure` (±1 EV at ±100); warmth → Kelvin via mired around 6500 K |
| Linear video saturation ramp (grade → B&W) | Shipping | `effect_settings.saturation_ramp`; video only |
| Photo detail grade + JPEG/PNG export | Shipping | `media_meta.image_adjust_json`; neutral best-quality may byte-copy |
| Privacy blur / pixelate | Shipping | Masks, not a grade filter |
| Zoom / pan | Shipping | Separate `frame` effect; after grade in export |
| LUT / `.cube` | Absent | `lut3d` exists in bundled FFmpeg filters but is unused |
| D-Log M / log presets | Absent | No parser, preset, or docs |
| Curves / HSL / scopes | Absent | Linear sliders only |
| Sharpen / denoise | Absent | No `unsharp` / `hqdn3d` / `nlmeans` in app code |
| Lens correction | Absent | Out of this note; see [#178](https://github.com/Magehawks/orga-drone/issues/178) |

### Filter order (contract for follow-ups)

**FFmpeg static grade** (`ffmpeg_grade_chain`):

1. `colortemperature` (only when warmth ≠ 0)
2. `exposure`
3. `eq` contrast + saturation

**Video ramp:** `hue=s='…'` after the static grade.

**Studio segment (simplified):** slow trim → grade → ramp → zoom/pan →
scale/pad/fps/yuv420p BT.709 → overlays / masks / map / HUD → fades /
transitions.

**Preview:** CSS approximates the same order (warmth matrix → brightness →
contrast → saturate → optional ramp). Preview is intentionally not
pixel-identical to YUV export (documented in ADR 0011 / 0019).

## Feature-to-technology matrix

| Proposed feature | Export path | Preview path | New dependency? | License risk |
| --- | --- | --- | --- | --- |
| Organize existing sliders (#173) | Unchanged FFmpeg | Unchanged CSS | No | None |
| Local `.cube` LUT + D-Log M (#174) | FFmpeg `lut3d` (+ optional matrix before LUT) | Hard: CSS cannot apply `.cube`; options are server stills, Canvas/WebGL, or “approximate” | Optional MIT `.cube` parser only | FFmpeg already GPL; avoid second renderer |
| Quick Looks / before-after (#175) | Reuse grade chain | UI + optional dual preview | No runtime lib | None if looks are JSON of existing knobs (+ LUT id later) |
| Advanced tonal / scopes (#176) | Extend FFmpeg filter graph | CSS/Canvas approx; scopes need histogram sampling | Prefer no native GPL image lib | High if scopes claim accuracy they lack |
| Sharpen / denoise (#177) | FFmpeg `unsharp` / `hqdn3d` (or similar) | CSS `contrast`/`blur` approx only | No | FFmpeg filters already in GPL build |
| Lens / Gyroflow (#178) | Research only | Research only | See that issue | Separate discovery |

## License inventory (verified in tree)

| Component | Role | License signal in repo |
| --- | --- | --- |
| Application | Source | MIT |
| `imageio-ffmpeg` Python wrapper | Locates bundled exe | BSD-2-Clause |
| Bundled Windows `ffmpeg.exe` (Gyan 7.1 essentials via wheel) | Encode + filters | Built with `--enable-gpl --enable-version3` and libx264 → treat as **GPL v3** redistribution obligations |
| Optional `packaging/third_party/ffmpeg-gpl/` | Source-accompanying path for verify-zip | GPLv3 texts; CI NO-GO without corresponding source bundle |

Conclusions:

1. The app already redistributes a **GPL FFmpeg** binary; filter-string use of
   `lut3d`, `unsharp`, etc. does **not** by itself require a new native library.
2. A **permissive** Python helper (MIT/BSD/Apache) for parsing `.cube` or preset
   JSON is acceptable if rendering still goes through FFmpeg.
3. Statically linking additional GPL/LGPL image libraries into the app process
   is a **No-Go** relative to today’s “FFmpeg as subprocess” model: more
   redistribution surface for little gain.
4. Do not assume a permissive dependency is legally required merely because the
   app is MIT; FFmpeg redistribution is already the hard compliance case
   (`WINDOWS_THIRD_PARTY.md`).

## Recommended architecture

1. **Single source of truth for pixels in export:** extend
   `studio_image.py` / segment chain; keep numbers as JSON in
   `effect_settings` / `image_adjust_json`.
2. **Preview stays approximate** unless a follow-up explicitly funds a shared
   still-render or WebGL LUT path. Product copy must keep saying “preview
   approximates export” for LUT/sharpen/denoise until parity tests exist
   ([#189](https://github.com/Magehawks/orga-drone/issues/189)).
3. **D-Log M:** ship as a named look that maps to a documented FFmpeg chain
   (LUT file under app data or a matrix + LUT), never as an invented “AI
   color” feature. Prefer a user-supplied or project-bundled `.cube` over
   guessing camera profiles from filenames alone. SRT `color_md=dlog_m` is a
   **hint**, not automatic grade (see [#188](https://github.com/Magehawks/orga-drone/issues/188)).
4. **Color space assumption for Studio MP4:** continue BT.709 limited after
   scale/pad; document that log footage without a conversion look will look
   flat — honest empty/default state.
5. **Filter order for new stages (proposal):** static grade → optional log/LUT →
   sharpen → denoise → existing ramp → frame (zoom/pan) → scale. Confirm with
   [#189](https://github.com/Magehawks/orga-drone/issues/189) fixtures before
   locking.
6. **Legacy projects:** missing keys mean neutral; never rewrite stored JSON on
   open.

## Go / No-Go for dependencies

| Dependency idea | Verdict | Why |
| --- | --- | --- |
| FFmpeg-only filters for LUT/sharpen/denoise | **Go** | Matches current export; filters already in bundled build |
| Small MIT/BSD `.cube` / preset parser in Python | **Go** (optional) | Validation + path sanitizing; render still FFmpeg |
| Second pixel engine (OpenColorIO, Magick, etc.) as export truth | **No-Go** for MVP slices | Preview/export drift and packaging cost |
| Extra statically linked GPL image libs | **No-Go** | Compliance cost without replacing FFmpeg |
| Cloud color APIs / API keys | **No-Go** | Violates local-first product principles |

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Windows package size / GPL source accompaniment | Release verify-zip NO-GO | Keep existing third-party pipeline; no new bundled codecs |
| Preview ≠ export for LUT | User distrust | Gate LUT behind clear copy + [#189](https://github.com/Magehawks/orga-drone/issues/189) matrix; prefer still-frame check before shipping |
| Performance (3D LUT + denoise on 4K) | Slow export | Cap resolution paths already exist; denoise default off |
| Legacy `effect_settings` shape | Break old stories | Additive JSON only |
| Treating SRT `color_md` as auto-LUT | Wrong look | Hint in UI only after [#188](https://github.com/Magehawks/orga-drone/issues/188) |

## Suggested staging (implementation issues already filed)

1. **#173** — Organize existing controls (UI only; no new filters). Lowest risk.
2. **#175** — Quick Looks / before-after on **current** knobs (no LUT required).
3. **#174** — `.cube` import + optional D-Log M look via FFmpeg `lut3d`; spike
   preview strategy first if product requires WYSIWYG.
4. **#177** — Sharpen / denoise as optional FFmpeg stages after grade.
5. **#176** — Advanced tonal / scopes last; scopes stay educational unless
   sampling matches export.

Required spike before #174 ships: one Windows desktop path that applies the
same `.cube` in export and shows either a true still preview or an explicitly
labeled approximation, plus a synthetic `.cube` fixture (no customer media).

## Non-scope (honored)

No code implementation in this discovery, no UI redesign, no AI, no cloud, no
API keys, no new runtime dependencies added to the tree by this note.

## Outcome

Discovery acceptance for #172 is met by this document: feature-to-technology
matrix, verified license inventory, recommended architecture, packaging risks,
and explicit Go/No-Go. Follow-up work stays on the existing Studio/Bild issues;
do not open duplicate architecture tickets.
