# Discovery: Photo export quality and print workflow

- **Tree:** `origin/develop` @ `8532a3d635d456ee46977477c438171d91cbaf38`
- **Date:** 2026-11-14
- **Status:** Analysis only. No production code in this note.
- **Related shipping docs:** `docs/PRODUCT_VISION.md` (detail-page export),
  `docs/ARCHITECTURE.md`, `docs/discovery/172-image-processing-architecture.md`,
  `docs/discovery/189-preview-export-parity.md`, closed issues
  [#152](https://github.com/Magehawks/orga-drone/issues/152),
  [#168](https://github.com/Magehawks/orga-drone/issues/168)

## Question

Can Orga Drone already deliver high-quality, media-type-aware still exports for
social sharing, archiving, and print — and if not, what is the smallest honest
UX and pipeline change that exposes existing capability without rebuilding
Studio video export?

## Method

- Read the live pipeline on `origin/develop` (not packaging `dist-*` trees).
- Trace decode → grade → encode for detail still export and Studio photo clips.
- Run existing tests: `tests/test_media_detail_export.py`,
  `tests/test_studio_photo_export.py` (**38 passed**).
- Run isolated, non-production export experiments with synthetic RGB JPEGs
  (flat color and higher-res drone-typical sizes). No private media.

Evidence below is tagged **measured** or **architectural** (from code/docs only).

---

## 1. Current architecture summary

Orga Drone has **two different “photo export” paths**. They must not be
confused.

| Path | Entry | Output | Grade stack | Resolution policy |
| --- | --- | --- | --- | --- |
| **Detail still export** | Detail → Export tab → `run_media_export` → `export.still_export.export_photo_file` | Still file (JPEG/PNG/…); social JPEG presets | Basic `ImageAdjust` only (`ffmpeg_grade_chain`) | Best = source pixels (or byte copy); social = fixed / fitted size |
| **Studio story export** | Studio → Export dialog → `prepare_studio_export` → `FfmpegStudioEncoder` | Always **MP4** | Full stack: grade → LUT → HSL → wheels (+ masks/overlays/frame/…) | Photo-only stories unlock **720p / 1080p** only; mixed projects follow video source ceiling |

### What already ships for stills (detail)

- Non-destructive library grades on `media_meta.image_adjust_json` (+ optional
  Quick Look id). Source media is never modified.
- Presets: **Best quality**, **WhatsApp**, **Instagram**, **TikTok**.
- Best quality: **JPEG or PNG** chooser (UI). Neutral JPEG (and other
  copyable formats) can be a **byte-for-byte copy** of the library file.
- Graded stills re-encode through Pillow + an ffmpeg grade filter chain.
- Desktop save dialog, cancel, open/reveal after export.

### What does *not* ship for stills

- Configurable JPEG quality slider.
- Explicit “original resolution” vs “print profile” UX (Best is closest).
- TIFF as a user-facing output choice (internal `_save_best` can write TIFF if
  the *source* suffix was TIFF after a grade; library scan does **not** index
  `.tif` as a photo).
- 16-bit processing or 16-bit output.
- ICC profile preserve / convert / soft proof.
- EXIF / GPS / DPI preservation on re-encode.
- HSL, colour wheels, or `.cube` LUTs on the detail still path (Studio-only).
- Print size (cm/inch) and effective PPI calculator.
- Studio still-image export (Studio always encodes video).

### Key modules

| Concern | File / symbol |
| --- | --- |
| Still encode + presets | `src/orga_drone/export/still_export.py` (`export_photo_file`, `inspect_photo_preset`, `_grade_rgb`, `_write_preset`) |
| Orchestration + options API | `src/orga_drone/studio_export.py` (`build_media_export_options_payload`, `prepare_media_export`, `run_media_export`) |
| Grade math | `src/orga_drone/studio_image.py` (`ImageAdjust`, `ffmpeg_grade_chain`) |
| Studio full-color stills (pause) | `src/orga_drone/studio_preview_frame.py` |
| Studio MP4 (photos as frames) | `src/orga_drone/export/studio_encoder.py` (`_materialize_photo_still`, segment chain) |
| Photo-only MP4 ceilings | `src/orga_drone/studio_export_resolution.py` (`generated_only_export_resolutions`) |
| Detail UI | `templates/detail.html`, `static/js/detail-export.js` |
| Studio export UI | `templates/studio.html`, `static/js/studio/export.js` (+ monolith hooks) |
| Detail preview size cap | `thumbs.py` `PHOTO_PREVIEW_MAX = (1920, 1920)` |
| Library photo suffixes | `parse/__init__.py` `PHOTO_EXTS` |
| Tests | `tests/test_media_detail_export.py`, `tests/test_studio_photo_export.py`, color parity in `tests/test_studio_color_scenarios.py` (Studio path) |

---

## 2. Source → export pipeline

### A. Detail still export (single edited photo)

```text
Library file (JPEG / PNG / WebP / HEIC / HEIF / DNG / …)
        │
        ▼
Pillow Image.open (+ pillow-heif for HEIC/HEIF)
        │
        ├─ Neutral + Best + copyable format?
        │     └─ shutil.copyfile → publish   【byte-identical; EXIF/ICC kept】
        │
        └─ Else:
              ImageOps.exif_transpose
              convert("RGB")                 【8-bit RGB; alpha discarded】
                    │
                    ├─ Graded?
                    │     save temp PNG (8-bit)
                    │     ffmpeg -vf "<ffmpeg_grade_chain>,format=rgb24" -frames:v 1
                    │     reopen PNG → RGB
                    │
                    ├─ Preset geometry
                    │     best: keep WxH
                    │     whatsapp: fit longest ≤ 1600 (LANCZOS; no upscale)
                    │     instagram: cover-crop 1080×1350 (LANCZOS)
                    │     tiktok: cover-crop 1080×1920 (LANCZOS)
                    │
                    └─ Encode
                          JPEG quality 95 (best) / 85 (WA) / 90 (IG/TT), optimize=True
                          or PNG (best + still_format=png)
                          or other _save_best formats when graded from that suffix
                          → publish (never overwrite library / protected paths)
```

Grade filter order (**architectural**, `ffmpeg_grade_chain`):

1. `colortemperature` (warmth ≠ 0)
2. `exposure`
3. `eq` contrast / saturation
4. `colorlevels` highlights / shadows / blacks

### B. Studio photo clip inside an MP4 story

```text
Library photo
  → _materialize_photo_still: Pillow → oriented RGB → temporary JPEG q95
  → ffmpeg loop as video input
  → full Studio filter graph (grade, LUT, HSL, wheels, frame/zoom, overlays, …)
  → scale/pad to export WxH, yuv420p BT.709, x264 (Standard/High/Best CRF)
  → MP4
```

Photo-only projects: export heights **720 / 1080** only
(`generated_only_export_resolutions`). A 4K still becomes a **1080p video
frame**, not a 4K still file.

### C. Preview vs final pixels

| Surface | What the user sees | Same math as final still? |
| --- | --- | --- |
| Detail Image / Export preview | CSS filters on `<img>`; often `/media/{id}/preview` capped at **1920×1920** | **No** — approximate; reduced display resolution possible |
| Studio live playback | CSS / optional proxy | Approximate; LUT may be omitted with chip |
| Studio pause/scrub still | Server JPEG via same grade+LUT builders as MP4 | Matches **Studio MP4** color builders, not detail still export |
| Detail Best / social export | Full-resolution source (after geometry preset) | Export truth for that path |

Product copy already states that preview approximates export
(`PRODUCT_VISION.md`, ADR 0011 lineage).

---

## 3. Capability answers (inspected, not assumed)

| Question | Finding | Evidence |
| --- | --- | --- |
| Supported **input** image formats (library) | `.jpg` `.jpeg` `.png` `.webp` `.heic` `.heif` `.dng` | `PHOTO_EXTS` |
| Supported **output** still formats (UI) | JPEG, PNG (Best only); social always JPEG | `normalize_still_format`, detail UI |
| Internal / graded write helpers | Also WebP/GIF/TIFF/BMP when graded from that suffix | `_save_best`, `_REENCODE_SUFFIXES` |
| Max resolution | No hard pixel cap in still export; source dimensions kept on Best | Code + **measured** 5472×3648 |
| Internal bit depth | **8-bit RGB** after `convert("RGB")`; ffmpeg `format=rgb24` | Code |
| Color space | No managed conversion; browser/CSS sRGB assumption; Studio MP4 → BT.709 limited | Code / ADR notes |
| ICC | Not preserved on re-encode; preserved only on byte copy | Code + **measured** graded JPEG lost DPI/JFIF density |
| EXIF | Applied for orientation (`exif_transpose`); not written back on re-encode | Code |
| Alpha | Flattened to RGB | **Measured** RGBA → RGB PNG |
| JPEG quality | Fixed: 95 / 90 / 85 — **not user-configurable** | Constants in `still_export.py` |
| PNG | Pillow default PNG; 8-bit RGB | Code |
| Resize | LANCZOS; social fit/cover only | `_lanczos`, `_fit_longest`, `_cover_crop` |
| Edits destructive? | **Non-destructive** to library; export is a new file | Product + tests |
| Preview == export adjustments? | Directionally similar CSS vs ffmpeg; not pixel-identical; Detail lacks Studio HSL/LUT/wheels | Docs + code |
| Export from original or preview? | From **original path** via `resolve_media_file` | Code |
| Silent resolution/precision loss? | Social presets intentionally resize/crop. Graded Best stays full WxH but **8-bit re-encode** and drops metadata. Studio photo→MP4 downscales to chosen video height. Detail UI may show ≤1920 preview while exporting full res. | Code + **measured** |

### Scenario evaluation

| Scenario | Supported today? | Notes |
| --- | --- | --- |
| A. 3840×2160 → full-res JPEG | **Yes** | Neutral Best = byte copy (**measured**). Graded Best = full WxH JPEG q95 (**measured** ~0.9 s on synthetic flat 4K). |
| B. 3840×2160 → “lossless” PNG | **Partial** | Full WxH PNG from decoded RGB (**measured**). Lossless relative to the **8-bit RGB buffer**, not to a higher-bit master. From a JPEG source, PNG cannot recover camera precision that JPEG already discarded. |
| C. Higher-res JPEG/DNG → full-res | **JPEG: yes**. **DNG: fragile** | 5472×3648 Best keeps size (**measured**). DNG is indexed and previewed via Pillow/ffmpeg helpers; still export depends on what Pillow decodes (often a preview raster — **not** a true raw develop). No rawpy pipeline. |
| D. Large canvas print | **Weak for confidence** | Full pixels possible on Best, but no PPI/print-size UI, no ICC, graded path strips EXIF/DPI, preview may look softer than export, no 16-bit. |
| E. Cropped photo → correct dimensions | **Social: yes (fixed frames)**. **User crop: Studio frame only in MP4** | Instagram/TikTok center cover-crop to fixed sizes. Detail still export has no free crop. Studio zoom/pan affects MP4 framing, not a still file. |

### Feature capability matrix

| Capability | Status | Classification |
| --- | --- | --- |
| Original pixel dimensions (Best) | Implemented | Already implemented |
| Neutral Best byte copy | Implemented | Already implemented |
| JPEG / PNG choice (Best) | Implemented | Already implemented |
| Social share sizes | Implemented | Already implemented |
| Configurable JPEG quality | Fixed constants only | Supported by Pillow/ffmpeg; **not exposed** |
| High-quality resize (LANCZOS) | Implemented for social | Already implemented |
| Aspect-ratio handling | Fit / cover-crop presets | Already implemented (preset-only) |
| Show final WxH in UI | Preset labels when known; Best copy may omit WxH (`copied: true`) | Partially exposed |
| Quick vs print mental model | “Best” vs social names | Partial; no print language |
| Studio still export | Absent (MP4 only) | Requires backend + UX |
| Detail HSL / LUT / wheels in still export | Absent | Requires backend (reuse Studio builders) |
| TIFF export (user choice) | Not in UI; scan omits `.tif` | Requires backend + product decision |
| 16-bit pipeline / output | Absent; pipeline is 8-bit | **Significant architectural change** |
| ICC preserve / convert / soft proof | Absent on re-encode | Significant for soft proof; preserve-on-copy is free |
| sRGB tagging | Not written explicitly | Backend small if limited to embedding profile |
| Print dimensions / effective PPI | Absent | UX + small calc helper (metadata only) |
| AI upscaling | Absent / out of product AI policy | Out of scope |

---

## 4. Current export UX analysis

### How does a user export one edited image?

1. Open the photo on the **detail** page (Image tab for Look / sliders / fine-tune).
2. Open the **Export** tab.
3. Choose Output preset (Best / WhatsApp / Instagram / TikTok).
4. For Best, optionally choose JPEG or PNG.
5. Confirm filename; run Export (desktop save dialog).
6. Grade comes from saved `image_adjust` (and optional Quick Look); library file unchanged.

### Is a Studio project required?

**No** for still export. Studio is optional (Share tab) and produces **MP4**
stories, including photo-only slideshows at 720/1080.

### Are video and photo options mixed?

On detail: **same Export tab and preset names**, branched by `kind` in JS/API
(photo → still; video → MP4). In Studio: **video-centric** dialog
(resolution + x264 quality) even for photo-only stories.

### Controls irrelevant for stills

In Studio export: resolution ladder framed as video, Standard/High/Best **x264
CRF**, music mix, open-as-video copy. On detail video path: Image tab absent
(correct). On detail photo path: social presets that **crop** are irrelevant
for archive/print.

### Quick vs print-quality?

**Not clearly.** “Best quality” is the archive-ish choice, but the label sits
beside WhatsApp/Instagram/TikTok and does not say “full resolution / print”.
JPEG quality is not shown. DPI/PPI never appears.

### Final pixel dimensions in UI?

Often yes for social (`Name — W×H`). For Best byte-copy, options payload may
send `width/height: null` with `copied: true`, so the UI may **not** show
source dimensions unless the hint text covers it.

### Original source preserved?

**Yes.** Additive export only.

### What blocks confident canvas ordering?

1. No stated export pixel size + physical print size → effective PPI.
2. Graded export drops EXIF/DPI (**measured** DPI 300→1 on graded JPEG).
3. Preview may be capped at 1920 and CSS-approximated — sharpness/color trust.
4. Detail grade ≠ Studio full color stack if the user graded in Studio.
5. No ICC / soft proof; drone JPEG is usually already sRGB-ish but unstated.
6. DNG / HEIC graded path becomes 8-bit JPEG without explaining the develop.
7. Studio “export” of a photo is a video frame, easy to misunderstand as a print
   master.

### Can export stay media-type-aware without duplicating logic?

**Yes.** Keep `export_photo_file` / `run_media_export` as the still engine and
`FfmpegStudioEncoder` as the video engine. Make the **UI profiles** and options
payload branch on `kind` (and optionally “story has only photos”). Do not fork
a second grade implementation — extend `still_export` to call the same filter
builders Studio already uses if parity is required later.

---

## 5. Quality and performance evidence

### Tests (measured)

```text
pytest tests/test_media_detail_export.py tests/test_studio_photo_export.py -q
→ 38 passed
```

Covered behaviors include: neutral Best byte identity, graded pixels leave
library untouched, WhatsApp fit without upscale, IG/TT sizes, PNG Best,
saved grade persistence, Quick Look export, video ignores photo adjust,
photo-only Studio MP4 prepare at 720/1080.

### Isolated experiments (measured, synthetic)

Environment: Windows, Python 3.12, project `still_export` on develop tip above.
Images are flat or simple synthetic RGB — **not** camera noise floor tests.

| Case | Result |
| --- | --- |
| 3840×2160 JPEG → Best neutral | Byte-identical; **0.03 s**; DPI 300 preserved via copy |
| 3840×2160 → Best graded JPEG | Size **3840×2160**; ~**0.88 s**; JFIF density became 1×1 (metadata loss) |
| 3840×2160 → Best PNG | **3840×2160** RGB PNG; ~**0.15 s** neutral |
| 5472×3648 → Best neutral | Byte-identical; dims preserved |
| 5472×3648 → Best graded | Dims preserved; ~**0.9–1.3 s**; Python process RSS delta ~**2 MB** (ffmpeg is a **child** process — **not** full peak RAM) |
| WhatsApp / IG / TT from 4K | **1600×900** / **1080×1350** / **1080×1920** |
| RGBA PNG → Best PNG | Mode **RGB** (alpha dropped) |
| I;16 PNG → oriented RGB | Collapses to 8-bit RGB (white sample) |
| Neutral PNG pixels vs JPEG decode | Sampled pixels matched decode of source JPEG |

**Architectural (not measured here):** Studio pause still ↔ MP4 frame parity
budgets are documented in `docs/discovery/color-scenario-test-report.md`
(patch MAD ≤ ~3 for photo still↔export under that suite). That path is **not**
the detail `still_export` path.

### Quality caveats (do not confuse)

- JPEG **quality 95** ≠ more **resolution**.
- PNG from an 8-bit JPEG decode is lossless to that buffer, not a 16-bit master.
- File size on flat synthetics is a poor quality proxy (flat PNG can be smaller
  than JPEG).
- DPI tags do not create detail; missing PPI UI does not remove detail that is
  already in the pixel grid.

---

## 6. Quality risks (ranked)

| ID | Risk | Severity | Why |
| --- | --- | --- | --- |
| R1 | Users treat Studio MP4 (≤1080 for photo-only) as a print master | **P0** | Silent resolution loss relative to a 4K still |
| R2 | Graded Best re-encode is 8-bit, strips EXIF/ICC/DPI, fixed q95 — labeled only “Best quality” | **P0** | Print confidence / metadata / archive expectations |
| R3 | Detail preview can be ≤1920 + CSS approx while export is full-res ffmpeg | **P1** | “Looks soft / different” distrust |
| R4 | Detail still export omits Studio HSL/LUT/wheels | **P1** | Same photo graded in Studio vs Detail diverges |
| R5 | Social presets crop/resize without a print/archive profile grouping | **P1** | Easy mis-export for sharing vs print |
| R6 | DNG/HEIC develop quality unclear on non-copy paths | **P1** | May export embedded preview class rasters |
| R7 | No effective-PPI guidance for canvas sizes | **P2** | Education gap; pixels may still be enough |
| R8 | Alpha / 16-bit sources silently quantized | **P2** | Rare for DJI JPEG workflows; real for edge formats |
| R9 | TIFF / pro print package absent | **P2** | Later; not required to ship useful print JPEG/PNG |

---

## 7. Proposed photo export UX (MVP-ready)

**Surface:** Detail Export tab (primary). Studio remains the **story → MP4**
tool; do not invent a second still encoder there for MVP.

**Principle:** Profiles are presets over the existing `export_photo_file`
engine. Prefer exposing and labeling what already works.

### Profiles

| Profile | Intent | Format default | Geometry | JPEG quality (proposed) | Notes |
| --- | --- | --- | --- | --- | --- |
| **Web / Social** | Chat & feeds | JPEG | Keep today’s WhatsApp / Instagram / TikTok as sub-options **or** a single “fit longest 1600” + optional story sizes | 85–90 (current) | Cropping must stay explicit in copy |
| **Standard** | General share / email | JPEG | Longest edge ≤ 2048 (new) **or** 1600 if we refuse new sizes in MVP | 90 | If MVP must avoid new geometry, map Standard → today’s WhatsApp fit |
| **High Quality / Print** | Archive & print shops | JPEG default; PNG optional | **Always original pixel size** after orientation | 95 (current Best) → later optional 92–100 | Show W×H and optional PPI helper |
| **Custom** | Power users | JPEG / PNG | Original, or longest-edge cap, or width/height with lock aspect | Slider 60–100 (JPEG) | Still 8-bit; honest copy |

Map today’s **Best** → **High Quality / Print**. Keep social ids for
compatibility or rename in UI only with stable preset ids underneath.

### Controls (MVP)

1. **Profile** (required).
2. **Output format** JPEG / PNG (Print + Custom; social stays JPEG).
3. **JPEG quality** — Print: show read-only “95” until Custom exposes a slider
   (smallest change: display the constant; next slice: make it configurable).
4. **Pixel dimensions** — always show expected W×H before export (compute via
   existing `inspect_photo_preset`; for byte-copy Best, open source once for
   size — already done inside inspect when not copied, extend for copied).
5. **Aspect ratio** — display only in MVP; lock+resize in Custom later.
6. **Estimated file behavior** — “Exact copy of library file” vs “Re-encodes
   with adjustments” (already partially in hints).
7. **Output location / filename** — keep desktop dialog + editable name.
8. **Effective PPI** (Print profile) — optional calculator: user picks a common
   print size (e.g. 30×20 cm, 40×30 cm, 60×40 cm, A3/A2); show
   `min(W,H) / physical_inches` as **effective PPI**. Label as “pixels per
   inch at that paper size”, not “print quality guarantee”. No DPI tag rewrite
   required for MVP.

### Media-type-aware shell

- Photo: profiles above + still engine.
- Video: keep current Best/social MP4 presets (or rename quality carefully so
  “Best” video CRF is not confused with still Print).
- Shared: progress, cancel, open/reveal, non-overwrite publish.

---

## 8. Recommended MVP scope

**Prefer expose + validate over rebuild.**

1. **UX rename / grouping** on detail Export: Print / Standard / Social /
   Custom (Custom can be a thin second slice).
2. **Always show final pixel dimensions** for photo presets, including Best
   copy.
3. **Print profile copy** that states: full resolution, 8-bit, JPEG q95 or PNG,
   library unchanged; graded exports re-encode and may drop camera metadata.
4. **Effective PPI helper** (calculation only; no color-manage).
5. **Tests** for dimensions payload, copy vs re-encode messaging invariants,
   and PPI math unit tests.
6. Optional small backend: `inspect_photo_preset` returns WxH even when
   `copied=True`; optional `jpeg_quality` argument defaulting to today’s
   constants (no behavior change until UI wires it).

### Explicit out of scope (MVP)

- TIFF export, CMYK, ICC soft proofing, printer ICC profiles.
- True 16-bit processing or claim of 16-bit quality.
- AI / neural upscaling.
- Raw develop pipeline (DNG demosaic beyond what Pillow already opens).
- Studio still-image export (photo story → PNG/JPEG sequence).
- Unifying Detail still grade with full Studio LUT/HSL/wheels (track as
  follow-up; reuse `studio_preview_frame` / encoder builders).
- Changing Studio photo-only MP4 caps in the same slice (document the pitfall;
  separate issue if product wants 4K slideshows).
- Cloud upload destinations.

---

## 9. Acceptance criteria (for the first implementation issue)

1. On a library JPEG ≥ 3840×2160, Print/High-Quality export with neutral grade
   remains **byte-identical** to the source (today’s Best behavior).
2. With a non-neutral grade, export WxH equals oriented source WxH; library
   bytes unchanged.
3. UI shows the **numeric output width and height** before export for every
   photo profile.
4. Social profiles still produce the documented fixed/fitted sizes; copy states
   crop vs fit.
5. Print profile offers JPEG and PNG; JPEG uses quality **95** unless Custom
   changes it in a later slice.
6. PPI helper, if shipped, shows effective PPI for at least three preset paper
   sizes and never claims DPI metadata as detail.
7. No Studio project is required for still export.
8. Source media, albums, and Studio projects are untouched.
9. DE + EN strings updated; `PRODUCT_VISION` / `ARCHITECTURE` shipping claims
   updated only for what actually ships.
10. Focused pytest coverage for inspect/export dimension + copy invariants;
    existing `test_media_detail_export` suite stays green.

---

## 10. Test strategy

| Layer | What |
| --- | --- |
| Unit | `inspect_photo_preset` dimensions for copied Best; PPI helper pure functions; jpeg_quality clamp |
| Integration | `run_media_export` neutral copy, graded full-res, PNG, social sizes (extend current tests) |
| Regression | `tests/test_media_detail_export.py` full module |
| Parity (non-MVP) | If Detail gains LUT/HSL, reuse color-scenario metric A against `still_export` |
| Manual | Real DJI 4K JPEG: Print JPEG/PNG; open in print shop tool; confirm WxH; graded vs neutral metadata |
| Perf smoke | Graded 5472×3648 completes under a documented budget on a reference PC; record wall time (ffmpeg child RAM separately if needed) |
| Non-goals | Golden SSIM against Lightroom; 16-bit ΔE; private flight media in CI |

---

## 11. Implementation estimate and dependencies

| Slice | Effort (order of magnitude) | Depends on |
| --- | --- | --- |
| A. Discovery (this doc + issue) | Done | — |
| B. Detail Export profile UX + dimension display + copy | **~0.5–1.5 d** | PM/UX micro-copy; i18n |
| C. PPI calculator (UI + unit tests) | **~0.5 d** | B |
| D. Optional `jpeg_quality` plumb-through | **~0.5–1 d** | B; Custom profile |
| E. still_export uses full Studio color builders | **~2–4 d** | Color workspace maturity; parity tests |
| F. Studio still export / 4K photo-only video | Separate issues | Product call |

Dependencies: Pillow + bundled ffmpeg (already). No new native image engine.
No schema change for B–D. E may only need export payload fields already stored
on Studio clips — Detail `media_meta` today stores basic adjust + look id, not
full HSL/LUT/wheels.

---

## 12. Suggested GitHub issue breakdown

1. **Discovery (this)** — analysis + MVP recommendation (no code).
2. **PM/UX:** Photo export profiles on detail (Print / Standard / Social /
   Custom) — copy, layout, media-type branching; waive full UX subagent only if
   treated as microcopy on existing controls.
3. **Impl:** Expose dimensions for Best copy + profile labels wiring to existing
   presets (behavior-compatible).
4. **Impl:** Effective PPI helper for Print profile.
5. **Impl (optional):** Configurable JPEG quality for Custom.
6. **Follow-up discovery/impl:** Detail still path parity with Studio grade
   stack (LUT/HSL/wheels).
7. **Follow-up:** Honest Studio messaging when exporting photo-only stories
   (MP4 ≤1080) vs detail Print stills; optional 4K slideshow later.
8. **Later:** TIFF, ICC soft proof, 16-bit, raw develop — only with new
   discovery and license/architecture check (see #172).

---

## Recommendation

**Do not rebuild the still pipeline.** Detail `still_export` already supports
full-resolution JPEG/PNG suitable for many print shops when the user picks
**Best** and understands graded re-encode limits. The highest-value MVP is
**media-type-aware UX**: rename/group presets, always show output pixels, add a
simple effective-PPI helper, and document that Studio export is a video share
path — not a print master. Treat TIFF/ICC/16-bit/raw as later, explicitly out of
MVP, so photographers get confidence without false precision claims.
