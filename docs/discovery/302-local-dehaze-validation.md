# Local dehaze real-fixture validation (#302)

Status: **validation complete. NO-GO for adding a Dehaze slider in the current
FFmpeg-only Studio pipeline.** The synthetic GO in
[`302-local-dehaze.md`](302-local-dehaze.md) did not survive real aerial
fixtures. A future attempt needs a separately approved implementation issue, a
multi-frame robust atmosphere sampler, and proof of preview/playback/export and
packaged-Windows behaviour.

- Date: 2026-11-06
- Tree: `develop` at `8b996ae`
- Host: Windows, Python 3.12, bundled FFmpeg 7.1 (`imageio-ffmpeg`)
- Related: issue #302, issue #76 (image adjust), issue #283 (real footage
  fixtures), ADR 0011 (image adjust), ADR 0027 (LUT order), ADR 0028 (LUT
  preview stills)
- Evidence: [`302-local-dehaze-benchmark.py`](302-local-dehaze-benchmark.py),
  [`302-local-dehaze-measurements.json`](302-local-dehaze-measurements.json)

This document and the benchmark add no product control. Source media was read
only. No private footage, file names, locations, or coordinates are committed.

## 1. Why this validation exists

The discovery probe used one synthetic scene. It found that global
atmospheric-light subtraction improved PSNR/SSIM against a clean synthetic
reference and recommended a bounded one-slider V1 pending real fixtures. Issue
#302 explicitly requires before/after evidence from the **same** real hazy
source frame, documented failure cases, a 4K cost estimate, preview/export
parity, and a clear GO/NO-GO decision.

This validation repeats the comparison on private local drone footage with
visible atmospheric haze, a clear control scene, a sunset scene, and a twilight
photo. It also re-tests the atmosphere estimator and the FFmpeg
`colorlevels` mapping that the proposed V1 depends on.

## 2. Fixtures

Seven anonymised local sources were used. They are not committed and are not
part of the repository test suite:

| Label | Content | Format |
|---|---|---|
| A | Overcast forest hills with a bright cloudy sky | 1080p frame |
| B | Aerial city ridge with distance haze | 4K frame |
| C | Aerial farmland with distance haze | 4K frame |
| D | Clear autumn river (no haze control) | 1080p frame |
| E | Sunset aerial city with low foreground light | 1080p frame |
| F | Vineyard town with distance haze | 1080p frame |
| G | Twilight aerial city photo | 4000 x 2256 photo |

Each video source was sampled at 20%, 50%, and 80% during the exploratory
sweeps; the committed benchmark table uses one representative frame per source
so the media never leaves the operator's machine. The clear and sunset scenes
are deliberately included: a safe control must not destroy scenes where the
user should leave Dehaze at 0.

## 3. Method

The benchmark estimates one atmospheric-light colour, then applies a bounded
per-channel linear veil subtraction:

```text
t = 1 - strength * (1 - t_min)          # strength 0..1, t_min = 0.85
J = (I - A * (1 - t)) / t
```

That is exactly an FFmpeg `colorlevels` input-range change per channel:
`imin = A * (1 - t)`, `imax = imin + t`, output 0..1.

**Robust estimator (proposed):**

1. Downscale to at most 640 px on the long edge.
2. Dark channel = per-pixel `min(R, G, B)`, then a 15 px minimum filter.
3. Exclude near-white pixels (`max(R,G,B) >= 0.97`) so clouds and clipped sky
   are not treated as haze.
4. Take the brightest 0.5% of the remaining dark-channel pixels.
5. Average their RGB and clamp each channel to `0.35..0.90`.

**Naive estimator (the discovery's original dark-channel pick):** no near-white
exclusion, no cap, brightest 0.1%, full strength with `t_min = 0.50`.

**Existing controls compared:**

| Variant | FFmpeg chain |
|---|---|
| Contrast + saturation | `eq=contrast=1.25:saturation=1.2` |
| Contrast + highlights | above + `colorlevels` upper bound `0.94` |
| Detail / sharpen | `unsharp=5:5:0.4` |
| Local contrast | `eq=contrast=1.25:saturation=1.12,unsharp=5:5:0.5` |

Metrics are no-reference for real footage: luma mean/std, gradient, high
frequency, clipping, mean R-B, and chroma. The synthetic scene also has PSNR
and SSIM against a known clean reference.

## 4. Synthetic reproduction

The committed benchmark rebuilds a synthetic aerial scene and reproduces the
discovery's direction:

| Variant | PSNR | SSIM | Gradient ratio vs clean |
|---|---:|---:|---:|
| Hazy input | 20.04 | 0.9892 | 0.688 |
| Global 50% (`t_min 0.85`) | 21.63 | 0.9937 | 0.753 |
| Global 100% (`t_min 0.85`) | 22.77 | 0.9975 | 0.807 |
| Contrast + saturation | 18.37 | 0.9842 | 0.866 |
| Contrast + highlights | 16.14 | 0.9731 | 0.897 |
| Detail sharpen | 20.17 | 0.9894 | 0.962 |
| Local contrast | 18.42 | 0.9845 | 1.281 |

Global subtraction improves the synthetic reference while manual contrast
lowers PSNR and clips highlights. This is why the synthetic probe looked
promising. The real fixtures show why that is not sufficient.

Python and FFmpeg `colorlevels` agree closely on the synthetic image: mean
absolute RGB difference 0.0016-0.0018 (about 0.4/255), maximum channel error 1.
The filter mapping itself is not the problem.

## 5. Real-fixture results

`clip<1%` is the share of channel samples below 1% (near black); `clip>99%` is
the share above 99% (near white). `std` is luma standard deviation; `HF` is
high-frequency energy. Values are from
`302-local-dehaze-measurements.json`.

| Fixture | Robust A | Source clip<1% | Global 50% clip<1% | Global 100% clip<1% | Naive 100% clip<1% | Contrast clip<1% | 100% clip>99% | Source std | 100% std | Source HF | 100% HF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A overcast hills | 0.900 | 0.01% | 1.24% | 15.01% | 61.9% | 8.3% | 3.59% | 82.7 | 96.5 | 3.47 | 3.87 |
| B hazy city 4K | 0.845 | 0.00% | 0.01% | 0.77% | 56.2% | 0.2% | 0.00% | 58.0 | 68.3 | 2.57 | 3.06 |
| C hazy fields 4K | 0.740 | 0.00% | 0.00% | 0.10% | 18.3% | 0.1% | 0.00% | 35.8 | 42.1 | 2.12 | 2.52 |
| D clear river control | 0.825 | 1.15% | 17.36% | 31.42% | 60.2% | 27.3% | 3.53% | 64.6 | 71.2 | 3.93 | 4.22 |
| E sunset city | 0.889 | 2.43% | 21.66% | 40.18% | 54.9% | 35.4% | 0.27% | 80.8 | 88.4 | 1.32 | 1.22 |
| F vineyard town | 0.888 | 0.00% | 0.01% | 0.71% | 52.7% | 0.2% | 2.61% | 64.0 | 75.1 | 4.23 | 5.01 |
| G twilight photo | 0.809 | 0.52% | 7.76% | 16.60% | 34.3% | 14.7% | 0.04% | 64.5 | 72.2 | 1.72 | 1.70 |

Colour shifts are modest but visible. At full strength the mean R-B value is
about +0.041 on the hazy city frame (source +0.031), +0.005 on the fields
(source -0.007), and -0.095 on the twilight photo (source -0.085); chroma moves
by roughly -0.008 to +0.011. The per-channel subtraction warms daylight haze and
cools the twilight scene.

### What works

- On the three haze scenes (B, C, F), robust 100% raises luma separation and
  high-frequency detail with little clipping. Visual inspection shows clearer
  distance layers and a slightly deeper sky.
- At 50% the effect is subtle and safe on B, C, F, and A. It is the most
  plausible strength for a default user move.
- The transform is per-pixel and monotonic, so it cannot create spatial halos.
  The samples show no halos. `unsharp`/local contrast does add edge energy and
  can halo, which is a reason not to use detail as a haze substitute.

### What fails

- **Bright clouds break the naive estimator.** A and F return an atmospheric
  light of exactly `(1, 1, 1)`. At the discovery's `t_min 0.50` this makes
  61.9% / 52.7% of samples near black. Even the robust cap is doing real work
  here; without it, the control is unusable on ordinary cloudy flights.
- **Global subtraction crushes foreground shadows when the scene is dark.** The
  clear control D goes from 1.15% near-black to 17.36% at 50% and 31.42% at
  100%. Sunset E goes from 2.43% to 21.66% / 40.18%. Shadows and foreground
  detail are lost even though those scenes have no haze to remove.
- **The effect is scene-dependent.** B, C, and F look better; D and E look
  worse at the same strength. A user cannot know which they have without
  inspecting the result, and the slider has no depth or sky protection.
- **It does not clearly beat existing contrast.** On B/C/F, manual contrast
  raises luma separation by a similar or larger amount (B 58.0→72.7 vs
  58.0→68.3; C 35.8→44.7 vs 35.8→42.1; F 64.0→78.3 vs 64.0→75.1). Manual
  contrast clips highlights more on A/F, so Dehaze has a colour-adaptive
  advantage, but the incremental value is not strong enough to justify a
  second overlapping control in V1.
- **Detail sharpen is not a dehaze substitute.** It raises HF energy but not
  luma separation, and it adds edge energy rather than removing a veil.

## 6. Sky gradients, noise, and halos

- **Sky gradients:** the global transform stretches the sky histogram, so
  gradients become more contrasty. No obvious 8-bit banding appeared in the
  samples, but 10-bit sources and compressed delivery were not tested.
- **Noise:** high-frequency energy moves by roughly -8% to +19% at full
  strength on the tested frames, rising most on the hazy scenes. That is
  expected from stretching dark values; it is visible in flat shadows and would
  be worse on noisy low-light clips.
- **Halos:** none from the global transform (no spatial kernel). Local contrast
  and sharpen can halo; they are not part of the proposed V1.
- **Colour:** the per-channel atmosphere estimate introduces a small warm/cool
  shift. The shift is bounded at these values, but a single global colour cannot
  model a sky that is blue at the horizon and warm at sunset.

## 7. CPU cost

Measured by the committed benchmark on this Windows host: 1 s of output, no
audio, `libx264 -preset ultrafast -crf 23`, CPU only. Not a release promise.

| Chain | 1080p median | 4K median |
|---|---:|---:|
| No filter | 0.186 s | 0.602 s |
| Contrast + saturation | 0.199 s | 0.645 s |
| Dehaze (`colorlevels`) | 0.280 s | 1.082 s |
| Dehaze + saturation | 0.287 s | 1.175 s |
| Dehaze + saturation + sharpen | 0.344 s | 1.363 s |

Dehaze adds about 0.09 s per second at 1080p and 0.48 s per second at 4K in this
benchmark. The 4K chain is roughly 1.8x the no-filter time. That is noticeable
but not the main blocker. A real encoder preset, hardware encoder, and longer
clips will change the ratio. The packaged Windows EXE was **not** profiled.

## 8. Preview, playback, and export parity

- Preview stills and MP4 export already share `ffmpeg_grade_chain`, so a filter
  added there would use the same FFmpeg stage. Python and FFmpeg agree on the
  transform within one 8-bit level.
- Image-only clips do **not** currently request FFmpeg preview stills: the
  endpoint requires a LUT, HSL, or colour-wheel effect. Continuous playback is
  a CSS/WebGL approximation. A Dehaze-only clip would therefore be CSS-only
  unless the preview-still gate and the playback transform are deliberately
  changed.
- The playback proxy also requires LUT/HSL/wheels. Dehaze-only clips would not
  get a proxy. If Dehaze is combined with those effects, the proxy would include
  the grade, but that is not the same as proving Dehaze-only parity.
- Storing the estimated atmosphere per clip would be needed for a consistent
  continuous-playback transform. That is an `effect_settings` shape change and
  needs an ADR and migration/validation plan. It was not implemented here.
- **FFmpeg 7.1 `colorlevels` crashed on a 4000 x 2256 PNG input** (exit
  `0xC0000005`). The same filter on the same dimensions as JPEG, on a
  3840 x 2160 PNG, or with `-threads 1` succeeds. Existing highlights/shadows/
  blacks already use `colorlevels`, so this is a pre-existing FFmpeg/photo-size
  risk rather than a Dehaze-only defect, but it must be understood before a
  photo Dehaze export ships.

## 9. Windows package and WebView2

No Windows packaged EXE and no real WebView2 GUI session were used for this
validation. The CPU and parity results are from the development Python
environment and the bundled FFmpeg only. This is an explicit gap.

## 10. Recommendation

**NO-GO for implementing a Dehaze control in the current FFmpeg-only pipeline.**

The bounded global transform is cheap enough and is deterministic, and it
improves the synthetic scene and some real haze scenes. But on real footage it:

- can return a white atmospheric light and destroy cloudy scenes without a cap;
- crushes foreground shadows on clear, dark, and sunset scenes at strengths
  that are useful for haze;
- does not clearly beat existing contrast/highlights/shadows;
- has no proven continuous-playback parity or stored-atmosphere design;
- hits a pre-existing large-PNG `colorlevels` crash risk; and
- has no packaged Windows EXE/WebView2 evidence.

That is not a convincing basis for another overlapping colour slider.

**NO-GO for per-pixel dark-channel dehaze in this architecture** (unchanged from
the discovery). It needs a new frame-processing/filter path, has no OpenCV
dependency, and is far too slow at 4K.

**GO only for a future, separately approved R&D slice** if product still wants
Dehaze. A credible follow-up would need:

1. A multi-frame sampler (at least three frames, median, cloud exclusion, cap,
   and a documented scene gate) shared by preview and export.
2. A conservative strength curve (`t_min >= 0.85`) plus a bounded blend that
   protects dark foregrounds, or a local transmission map with a new approved
   rendering path.
3. Stored atmosphere state with an ADR and migration/validation plan.
4. An exact SVG/WebGL per-channel transform for continuous playback; widened
   preview-still and proxy gates as needed.
5. Real fixtures across at least five independent flights including clouds,
   water, sunset, clear controls, and 4K, with before/after samples from the
   same frames.
6. Packaged Windows EXE and WebView2 evidence, plus the large-PNG
   `colorlevels` crash investigation.

This is not a 2.4.0 blocker and should not be implemented without the normal PM,
UX, and CTO gates.

## 11. Reproducing the evidence

Synthetic run:

```bash
python docs/discovery/302-local-dehaze-benchmark.py --out .dehaze-out
```

Private real sources (paths stay outside the repository):

```bash
python docs/discovery/302-local-dehaze-benchmark.py \
  --source "A=path/to/frame-a.jpg" \
  --source "B=path/to/frame-b.png" \
  --out .dehaze-out
```

Cost timing:

```bash
python docs/discovery/302-local-dehaze-benchmark.py \
  --skip-synthetic \
  --timing \
  --timing-source "1080p=path/to/1080.mp4" \
  --timing-source "4K=path/to/4k.mp4" \
  --out .dehaze-out
```

The script uses Pillow and the bundled FFmpeg only. It does not require OpenCV,
NumPy, SciPy, a network service, or generative AI.

## 12. Limitations

- The real fixtures are private and cannot be re-run by CI. The committed JSON
  records anonymised metrics, not media.
- The table shows the first sampled frame per video source. The benchmark
  samples 20/50/80% for videos; the full JSON contains all frame metrics.
- No-reference metrics cannot prove a picture looks better. The GO/NO-GO also
  relies on visual inspection of the benchmark sheets, which are not committed
  because they contain private footage.
- The 4K timing is a single-host CPU benchmark with an ultrafast encoder.
- The large-PNG `colorlevels` crash was reproduced on one file; its exact
  trigger is not isolated.
- No packaged EXE/WebView2 run, no 10-bit source, and no long-clip export.
