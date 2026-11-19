# Windows HTTP responsiveness during spatial bake (#513 / #506)

Date: 2026-11-19  
Tree: `develop` @ `cb068da` (after #515–#517)  
Host: Windows 10, Python process

## Rescope note (honest acceptance)

Issue #513 originally asked for packaged WebView2 click-through with measured
HTTP/**UI** latency. This PR delivers the **automated hang-class regression**
that matches the Neon Relic incident root cause (GIL-bound bake starving
loopback HTTP in the desktop process).

| Layer | Status |
|---|---|
| Parent-process HTTP ping during bake (inline vs worker) | **DONE** — this doc |
| Packaged entry `freeze_support` for spawn workers | **DONE** in #517 |
| Full packaged WebView2 UI click-through latency | **Residual** — Product Owner smoke; not claimed here |

Closing #513 for the initiative means: hang-class HTTP responsiveness is
measured and green under process isolation. Packaged UI polish remains optional
PO verification, recorded under local `acceptance-evidence/` if run.

## Method

`scripts/bench_spatial_http_during_bake.py`:

1. Start a local `ThreadingHTTPServer` ping endpoint in the parent process.
2. Run `materialize_spatial_managed_media` on a background thread (256² synthetic
   brush grade).
3. Sample HTTP GET latency every ~50 ms during the bake.
4. Compare `ORGA_SPATIAL_BAKE_INLINE=1` vs process worker (`ORGA_SPATIAL_BAKE_PROCESS=1`).

## Results (2026-11-19)

| Mode | bake_s | http_ok | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|---:|---:|
| inline (in-process) | 3.48 | 22/22 | 6.8 | 314.3 | 318.7 |
| process worker | 3.32 | 59/59 | 2.3 | 3.0 | 3.2 |

Worker mode keeps p95 under 5 ms on this host; inline mode shows multi-hundred-ms
tails while the GIL-bound bake runs.

Raw JSON: `docs/discovery/spatial-perf-513/http-during-bake.json`

## Acceptance (rescope)

- [x] Measured HTTP latency during bake (inline vs worker)
- [x] Evidence that #509 isolation restores hang-class responsiveness
- [x] Docs distinguish proxy harness vs packaged UI residual
- [ ] Packaged WebView2 UI latency (optional PO smoke; NOT_RUN in this PR)

## Non-scope

- main/release
- Claiming packaged UI E2E complete without running the EXE
