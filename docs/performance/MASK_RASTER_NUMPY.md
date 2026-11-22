# Managed mask NumPy raster (#552)

## What changed

- Polygon (and solitary linear/radial) coverage rasters use a NumPy UV-space
  path that matches the pure-Python oracle (`polygon_coverage` / leaf math).
- With OpenCV available, hard fill + morphological feather-band extraction run
  first; exact even-odd and edge distance evaluate only on the band.
- Warm results are cached by rasterizer version + mask JSON + width/height.
- Brush stamp rasters are unchanged.
- Runtime deps: `numpy`, `opencv-python-headless`.

## Environment

| Variable | Values | Default |
|---|---|---|
| `ORGA_MASK_RASTER_BACKEND` | `auto` / `numpy` / `python` | `auto` (NumPy when importable) |
| `ORGA_MASK_RASTER_CACHE` | `1` / `0` | `1` |

Force the Python oracle with `ORGA_MASK_RASTER_BACKEND=python`.

## Parity gate

Tests assert max abs error ≤ `1e-9` vs the Python oracle on representative
feathered polygons (`NUMPY_POLYGON_PARITY_MAX_ABS`).

## Acceptance probe

Neon-like 59-vertex feathered polygon at ~2.23 MP should raster in under 0.5 s
on Ryzen-class Windows (source run). See harness notes under
`docs/performance/evidence/`.
