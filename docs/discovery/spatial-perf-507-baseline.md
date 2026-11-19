# Spatial managed grade bake — baseline & hotspots (#507 / #506)

Date: 2026-11-19  
Host: Windows 11, Python 3.12.3  
Tree: `origin/develop` @ `083ec12` (worktree `agent/issue-507-spatial-baseline`)  
Harness: `scripts/bench_spatial_grade.py`

Incident protocol (packaged EXE):  
`orga-drone-wt/exe-build-develop-083ec12/acceptance-evidence/neon-relic/PROTOCOL-bake-blocking-2026-11-19.md`

## Reference media

| Asset | Size |
|---|---|
| Neon Relic BEFORE `00-before-original.jpg` | **1125 × 1984** (2.232 MPix) |
| TARGET `Magenta Blatt mit Regentropfen.png` | 944 × 1665 |

Synthetic benches use the same pixel count class without committing private media.

## Measured bake times (cold work dir, no cache hit)

Grade shape: brush leaf (~18 strokes) + invert BG + primaries + HSL sat 0 (Neon Relic–like).

| Resolution | Pixels | Wall time | MPix/s |
|---|---:|---:|---:|
| 64 × 64 | 4 096 | ~0.92 s (mean of 2) | ~0.0045 |
| 128 × 128 | 16 384 | 12.09 s | ~0.0014* |
| 256 × 256 | 65 536 | 13.47–13.52 s | ~0.0049 |
| **BEFORE 1125 × 1984** | **2 232 000** | **463.4 s (~7.7 min)** | **0.00482** |

\*128 run included cProfile overhead.

**Projection matches the incident:** full-res photo spatial bake on the order of **many minutes**, not seconds.

Raw JSON: `docs/discovery/spatial-perf-507/bench-*.json` (generated locally; BEFORE path is machine-local).

## cProfile hotspots (128 × 128, cumulative)

Dominant cost is **per-pixel selection / brush evaluation**, not I/O:

| Symbol | Role | Share (approx.) |
|---|---|---|
| `apply_managed_grade_rgb` | per-pixel grade entry | ~98% of bake |
| `evaluate_selection` / `mask_coverage` / `leaf_coverage` | mask weight | ~80% |
| `brush_stroke_coverage` + `_distance_to_segment` | brush geometry | large fraction of mask time |
| `apply_managed_step` / primaries | color ops | minority vs masks |

Implementation shape today (`studio_managed_spatial_export._grade_rgb_image` → `apply_managed_grade_image`):

- Nested Python loops over every pixel.
- Row/list of float tuples (heavy allocations).
- Each pixel re-evaluates brush strokes for every bound selection (no mask raster cache).

## HTTP / isolation signal

Harness `--http-contention` runs a **lightweight** `ThreadingHTTPServer` ping during a 256² bake:

- samples=42, all ok  
- p50 ≈ **247 ms**, p95 ≈ **323 ms**, max ≈ **329 ms**

This is **not** the FastAPI/WebView2 stack. It still shows latency inflation under GIL-heavy pure-Python work in-process. The packaged incident (HTTP hard timeouts, cancel unreachable) is consistent with **CPU + GIL saturation in the single desktop process**, plus long `asyncio.to_thread` / job-thread occupancy without process isolation.

## Cache / concurrency (from code + incident)

- Preview JPEG path: in-flight dedupe per destination file.
- Spatial `graded.png`: digest work dir + atomic replace; **no cross preview/export in-flight share** observed.
- Incident: parallel preview-frame + still-export amplified load; cancel timed out.

## Root causes established by evidence

1. **Algorithmic:** O(pixels × strokes × selections) pure-Python brush coverage each bake.  
2. **Resolution policy:** Preview uses the same full-res materialize path as export for spatial grades.  
3. **Process model:** Heavy work shares the desktop HTTP process; threads do not restore interactive latency under this workload.  
4. **Operational:** Duplicate concurrent bakes possible; cancel not reliable under saturation.

## Implications for follow-up issues

| Issue | Direction justified by this baseline |
|---|---|
| #508 viewport preview | Downscale bake for preview → order-of-magnitude win (e.g. 256² ≈ 13 s vs 463 s; further with mask rasterization) |
| #509 worker process | Required for HTTP/cancel SLOs under full-res export |
| #510 cache dedupe | Prevent double full-res work |
| #511 GPU | Optional; mask raster + vectorized CPU may land first |
| #512–#514 | After responsiveness path exists |

## Reproduce

```bash
python scripts/bench_spatial_grade.py --width 256 --height 256 --runs 1
python scripts/bench_spatial_grade.py --width 128 --height 128 --profile
python scripts/bench_spatial_grade.py --source /path/to/00-before-original.jpg
```

Do not commit private WhatsApp originals into the repo; BEFORE remains under local acceptance-evidence.
