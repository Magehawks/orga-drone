# Collage export reliability and resource safety (#487 / #489)

## Acceptance matrix

### #487 Benchmark and bound Studio collage export staging

| Criterion | Status | Evidence |
| --- | --- | --- |
| Benchmark 1080p and 4K with representative synthetic media | Extended | Issue comment: A (1080p 30s) PASS. This PR: 1080p/4K 3s pilots PASS with the production free-space guard; control-path overhead measured. Full B/D remain NOT_RUN (runtime/disk budget). |
| Measure peak temporary disk, runtime, cleanup (incl. failure/cancel) | Satisfied | Pilots below + prior A; failure/cancel cleanup in automated tests and native E2E. |
| Evaluate bounded staging or streaming | Satisfied | Keep full-sequence JPEG staging; add free-space guard (#489). Streaming/batches need separate evidence. |
| Document results and recommend smallest viable solution | Satisfied | This document + ADR 0038. |

**Close recommendation for #487:** Close as **benchmarking + recommendation complete**. Implementation of the recommended guard is #489.

### #489 Guard collage frame staging against a full temporary volume

| Criterion | Status |
| --- | --- |
| Check usable space before/during staging; documented reserve; abort before breach | Done — 1 GiB reserve |
| Localized actionable low-space error; simulated budget tests (no real disk fill) | Done — EN/DE + tests + TEST-ONLY env under ORGA_DRONE_E2E=1 |
| Low-space abort cleans temps, no publish, preserves destination; success decodes | Done |
| Control-path overhead measured; pipeline unchanged | Done |

**Close recommendation for #489:** Close after independent review + merge of this PR.

## Disk-safety design

**Chosen:** free-space guard on existing full-sequence composed JPEG staging (not streaming / bounded batches).

**Why:** #487 showed ~737 MiB peak temp for 1080p/30s with no integrity defect. Streaming/batches add risk without phase-level proof. Smallest reliability win is aborting before the staging volume breaches a documented 1 GiB reserve.

## Benchmark results

| Scenario | Status | Runtime | Peak temp | Temp files | Tree RSS | Encode start | Cleanup |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Control-path overhead | PASS | 54.5 us/ensure (n=5000) | — | — | — | — | — |
| 1080p pilot 3s | PASS | 91.6 s | 72.4 MiB | 272 | 0.76 GiB | 84.8 s | clean |
| 4K pilot 3s | PASS | 247.2 s | 110.2 MiB | 272 | 2.53 GiB | 232.0 s | clean |
| A 1080p 30s (this PR, with guard) | PASS | 871.9 s | 737.7 MiB | 2702 | 1.58 GiB | 850.8 s | clean |
| Prior A 1080p 30s (#487 @ 3fb40c8) | PASS | 512.7 s | 736.9 MiB | 2702 | 1.58 GiB | 495.4 s | clean |
| B / C / D full | NOT_RUN | Beyond local time/disk safety budgets | | | | | |

## Native Windows WebView2 E2E

**PASS** (`packaging/e2e/studio_collage_export_disk.py` via `python -m orga_drone` + CDP): collage create/assign/preview, export, cancel with destination preserved, TEST-ONLY low-space abort, retry, decode, no temp leftovers. Screenshots under `acceptance-evidence/collage-487-489/`.

## Regression contract

Disabling `ensure_staging_space` caused low-space tests to FAIL (DID NOT RAISE). Restored. CI unit job includes `tests/test_studio_collage_disk_safety.py`.

## Independent review

Requires independent ChatGPT GitHub PR review. No self-merge.