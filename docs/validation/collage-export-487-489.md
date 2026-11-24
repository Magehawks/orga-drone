# Collage export reliability and resource safety (#487 / #489)

## Acceptance matrix

### #487 Benchmark and bound Studio collage export staging

| Criterion | Status | Evidence |
| --- | --- | --- |
| Benchmark 1080p and 4K with representative synthetic media | Extended | Pilots PASS; A 1080p/30s PASS after sequential prefetch; C 4K/30s ABORTED by local harness disk budget (~0.9 GiB / 5 GiB cap mid-compose); B/D NOT_RUN. |
| Measure peak temporary disk, runtime, cleanup (incl. failure/cancel) | Satisfied | JSONL under `acceptance-evidence/collage-perf-complete/`; failure/cancel PASS; cleanup_files=0. |
| Evaluate bounded staging or streaming | Satisfied | Keep full-sequence **composed** JPEG staging + 1 GiB free-space guard. Bound **source** frames via one sequential prefetch per eligible leaf (duration × fps). Streaming into the encoder still needs separate approval. |
| Document results and recommend smallest viable solution | Satisfied | Bottleneck was per-frame FFmpeg seeks (~75% wall). Smallest fix: sequential leaf prefetch + no export-cache eviction + faster composed JPEG encode. |

### #489 Guard collage frame staging against a full temporary volume

| Criterion | Status |
| --- | --- |
| Check usable space before/during staging; documented reserve; abort before breach | Done — 1 GiB reserve (composed + source sequence writes) |
| Localized actionable low-space error; simulated budget tests (no real disk fill) | Done — EN/DE + tests + TEST-ONLY env under ORGA_DRONE_E2E=1 |
| Low-space abort cleans temps, no publish, preserves destination; success decodes | Done |
| Control-path overhead measured; pipeline timing/schema/source media unchanged for Story encode | Done |
| Concurrent exports safe | Done — ExportJobStore single-flight + regression |
| Retry after failure | Done — unit + native WebView2 E2E |

## Bottleneck finding

Phase profile (720p / 2 s / two cells) **before** prefetch: wall ~27.0 s; `render_preview_frame` ~20.3 s across **120** cold FFmpeg seeks (0 cache hits); JPEG write ~2.2 s; segment encode ~0.8 s.

After sequential source prefetch: wall ~13.9 s on the same short fixture; compose reuses leaf sequences (0 per-frame seeks). 1080p/30s production Story export dropped from **~872 s** (#578 baseline with guard) to **~112 s** on this host.

## Benchmark matrix (this host)

| Scenario | Status | Runtime | Peak temp | Temp files | Tree RSS | Encode start | Prefetch | Cleanup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Phase 720p/2s before | PASS | 27.0 s | — | — | — | — | n/a (120 seeks) | clean |
| Phase 720p/2s after | PASS | 13.9 s | — | — | — | — | sequences | clean |
| 1080p pilot 3s | PASS | 14.9 s | 71.5 MiB | 272 | 0.77 GiB | 11.6 s | 2.7 s | clean |
| 4K pilot 3s | PASS | 46.4 s | 115.6 MiB | 272 | 2.56 GiB | 36.6 s | 3.3 s | clean |
| A 1080p 30s (prefetch) | PASS | 111.7 s | 750.5 MiB | 2702 | 1.58 GiB | 90.0 s | 24.1 s | clean |
| A 1080p 30s (#578 baseline) | PASS | 871.9 s | 737.7 MiB | 2702 | 1.58 GiB | 850.8 s | n/a | clean |
| C 4K 30s | ABORTED | 324.8 s @ 708/900 frames | 928.0 MiB | 2506 | 0.85 GiB | — | 28.2 s | clean (harness disk cap) |
| B 1080p 120s / D 4K 120s | NOT_RUN | Beyond local time/disk safety budgets | | | | | | |
| failure / cancel inject | PASS | <3 s | — | — | — | — | — | clean + dest preserved |

## Comparison vs previous implementation

| Workload | Before (#578 / prior A) | After (this change) | Delta |
| --- | --- | --- | --- |
| 1080p pilot 3s | 91.6 s (#578) / 35.0 s (pre-guard) | 14.9 s | much faster |
| 4K pilot 3s | 247.2 s (#578) | 46.4 s | ~5.3× |
| A 1080p 30s | 871.9 s (#578) / 512.7 s (pre-guard A) | 111.7 s | ~7.8× vs #578 |

Hardware-dependent. Not a CI gate.

## Deferred

- Streaming composed frames into FFmpeg (removes composed JPEG staging).
- Full B/D throughput runs.
- Completing C under a higher local temp budget (harness aborted at 5 GiB policy).

## Native Windows WebView2 E2E

**PASS** (`packaging/e2e/studio_collage_export_disk.py` via `python -m orga_drone` + CDP).
Screenshots under `acceptance-evidence/collage-perf-complete/e2e-webview2/`.

## Packaged EXE E2E

**PASS** (`packaging/e2e/studio_collage_export_disk.py --exe dist/orga-drone/orga-drone.exe`). Report/screenshots under `acceptance-evidence/collage-perf-complete/e2e-packaged/`.

## Regression contract

- Creator gates include `tests/test_studio_collage_disk_safety.py::test_low_space_before_render_preserves_destination`.
- Mutation `disabled_collage_staging_disk_guard` must FAIL that test; restore afterward.
- Mutation `missing_collage_export_cleanup` remains for staging `rmtree`.
- Focused mutation evidence: `acceptance-evidence/collage-perf-complete/mutation-results.json`.

## Independent review

Requires independent ChatGPT GitHub PR review. No self-merge / no main merge / no release.
