# Managed grade NumPy apply (#553)

## What changed

- Vectorized CPU apply for `primaries-v1`, `managed-hsl-v1`, and `wheels-v1`
  when coverage maps are pre-rasterized (no live RGB qualifiers / LUT resolver).
- Still export pack/unpack uses NumPy `HxWx3` buffers to avoid multi-second
  nested-list copies.
- Python serial/process-strip paths remain the fallback oracle.

## Environment

| Variable | Values | Default |
|---|---|---|
| `ORGA_MANAGED_APPLY_BACKEND` | `auto` / `numpy` / `python` | `auto` |

## Parity

Tests gate mean abs error and max abs error vs the Python applicator
(`NUMPY_APPLY_PARITY_MEAN_ABS`, `NUMPY_APPLY_PARITY_MAX_ABS`). Near-clipped
primaries+HSL edge pixels may approach the max bound; mean stays very small.

## Acceptance probe

Neon-like 59-vert / 3-step bake with `ORGA_SPATIAL_APPLY_WORKERS=1` targets
under 5 s median on Ryzen-class Windows (source run).
