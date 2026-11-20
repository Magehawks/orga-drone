# Precision mask performance — stamp raster + ROI skip (#522–#526)

Date: 2026-11-20  
Tree: precision-mask initiative on `develop` @ `61c283d`+  
Harness: `scripts/bench_spatial_grade.py`

## Root cause (confirmed)

After #508/#509, bake cost remained dominated by:

1. Analytic Pure-Python `brush_stroke_coverage` per pixel × stroke × segment.
2. Full-frame managed color loops even where leaf coverage is zero (invert BG still full-frame).

## Changes

| Change | Issue |
|---|---|
| `mix*coverage==0` early-out in `apply_managed_step` | #524 |
| Identity skip when all bound coverages are 0 | #524 |
| Stamp-based brush raster (`selection-raster-v2`) | #525 |
| Soft-band tolerance `BRUSH_STAMP_TOLERANCE=0.08` vs analytic evaluate | #525 |
| Polygon leaf (even-odd + feather) | #527 |

## Expected impact

- Brush ROI stamps: O(samples × disc pixels) instead of O(bbox × strokes × segments).
- Leaf steps outside the brush bbox skip primaries/HSL work.
- Invert-background desat still touches most pixels; remaining time is color ops, not mask.

## Measured (Windows, cold work dir, synthetic 1125×1984, Neon-like brush+invert)

| Stage | Wall time | Notes |
|---|---:|---|
| Baseline #507 | ~463 s | Analytic per-pixel brush |
| Post-#508 raster cache | ~270 s | Still Python brush eval |
| Neon Relic acceptance `61c283d` | ~517–705 s | Dense grades / EXE |
| **This change (stamp + ROI + compiled plan)** | **~29.6 s** | Partial vs &lt;10 s target |

256² inline profile: remaining cost dominated by `apply_managed_step` /
primaries / HSL domain converts per covered pixel — not mask geometry.

Preview clamp (512 edge) scales roughly with pixel count (~6 s class); warm
cache remains the path to &lt;500 ms. Full-res &lt;10 s not yet met; limiting
operation: Python managed color loop on invert-background pixels.

## Appearance note

Stamp raster may differ from analytic brush in the soft feather band within
`BRUSH_STAMP_TOLERANCE`. Hard interior/exterior should match. Polygon hard fills
match evaluate exactly.
