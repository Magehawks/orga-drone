# Windows HTTP responsiveness during spatial bake (#513 / #506)

Date: 2026-11-19  
Tree: `develop` @ `cb068da` (after #515–#517)  
Host: Windows 10, Python process (same GIL isolation property as packaged desktop)

## Question

Does process-isolated spatial photo bake (#509) keep loopback HTTP responsive
while a bake runs, compared with in-process / inline bake?

## Method

`scripts/bench_spatial_http_during_bake.py`:

1. Start a local `ThreadingHTTPServer` ping endpoint in the parent process.
2. Run `materialize_spatial_managed_media` on a background thread (256² synthetic
   brush grade).
3. Sample HTTP GET latency every ~50 ms during the bake.
4. Compare `ORGA_SPATIAL_BAKE_INLINE=1` vs process worker (`ORGA_SPATIAL_BAKE_PROCESS=1`).

This measures the same class of incident as the Neon Relic WebView2 hang
(HTTP/status starved by GIL-bound bake), without requiring a fresh EXE build
for every regression. Packaged entry already calls `freeze_support` (#517).

## Results (2026-11-19)

| Mode | bake_s | http_ok | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|---:|---:|
| inline (in-process) | 3.48 | 22/22 | 6.8 | 314.3 | 318.7 |
| process worker | 3.32 | 59/59 | 2.3 | 3.0 | 3.2 |

Worker mode keeps p95 under 5 ms on this host; inline mode shows multi-hundred-ms
tails while the GIL-bound bake runs.

Raw JSON: `docs/discovery/spatial-perf-513/http-during-bake.json`

## Acceptance

- [x] Measured HTTP latency during bake (inline vs worker)
- [x] Evidence that #509 isolation restores responsiveness
- [x] No main/release; develop-only

## Residual

Full packaged WebView2 click-through remains optional Product Owner smoke;
this harness is the automated regression for the hang class.
