# Parallel exact spatial apply (#532)

Date: 2026-11-20  
Tree: `feat/precision-mask-followup-perf`

## Root cause (post-#531)

Stamp raster + ROI skip left bake dominated by the Python managed color loop.
Invert-background selections keep nearly every pixel active, so mask cost alone
cannot meet preview &lt;1 s / export &lt;10 s.

## Changes

| Change | Effect |
|---|---|
| Full-frame coverage once, then process row strips | Correct UVs across workers |
| `ProcessPoolExecutor` with reusable pool | Bypass GIL; warm preview avoids respawn |
| Mask JSON dedupe + invert from cached base | Leaf+invert-bg stamps once, not twice |
| Coverage-before-domain + encoded-only desat path | Skip useless decode/encode |
| `managed_hsl` sat=0 short-circuit | Cheaper invert-background gray |
| Float64 array strip payloads | Cheaper Windows spawn pickle |

Env: `ORGA_SPATIAL_APPLY_WORKERS` (1 = serial; default min(8, cpu)).

## Measured (Windows, synthetic 1125×1984 Neon-like brush+invert)

| Stage | Wall time |
|---|---:|
| Post-#531 serial | ~29.6 s |
| Parallel + dedupe (warm pool) brush preview 290×512 | **~0.55 s** |
| Parallel brush full-res | **~8.3 s** |
| Polygon+invert preview | ~1.1 s |
| Polygon+invert full-res | ~16 s |

Brush path meets preview &lt;1 s and export &lt;10 s. Polygon+invert remains
full-frame color work (every pixel covered by leaf or invert); limiting
operation documented for follow-up. Pillow desat composite was spiked then
rejected (nested pool deadlock + slow float↔8-bit pack).

## Correctness

Parallel strips must match serial exactly (float64 transfer). Coverage strips
are sliced from the full-frame raster so UVs stay image-correct.
