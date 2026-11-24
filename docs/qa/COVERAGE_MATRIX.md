# Creator journey coverage matrix (#275 / #283 / #284)

Audited commit base: `origin/develop` @ `ed22c9d` (before this PR).
Authoritative machine-readable matrix:
[`../../tests/fixtures/regression_coverage_matrix.json`](../../tests/fixtures/regression_coverage_matrix.json).
Update both when evidence changes. Labels follow
[`../REGRESSION_GATES.md`](../REGRESSION_GATES.md).

## Mandatory creator journeys

| Journey | L1 Unit | L2 Integration | L3 Browser | L4 Native Win | L5 Visual/Perf | Notes / evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Library import / browse / details | PASS | PASS | NOT_RUN | NOT_RUN | N/A | `test_pr_journey_smoke`, browse/search suites; packaged harness journeys exist |
| Metadata / telemetry | PASS | PASS | NOT_RUN | NOT_RUN | N/A | parse/SRT/HUD unit+API; real DJI matrix = #283 opt-in |
| Map | PASS | PASS | NOT_RUN | NOT_RUN | N/A | `test_dashboard_map`, `test_studio_map` |
| Photo adjustments / HSL | PASS | PASS | NOT_RUN | PARTIAL | PARTIAL | `test_photo_hsl_export_api` asserts chroma/export bytes; packaged image_export |
| Image Composer / photo combine | PASS | PASS | NOT_RUN | NOT_RUN | N/A | `test_photo_combine`, JS `photo_combine.test.js` |
| Photo export profiles | PASS | PASS | NOT_RUN | PARTIAL | N/A | `test_studio_photo_export`, packaged `image_export` |
| Studio photo editing | PASS | PASS | NOT_RUN | PARTIAL | N/A | studio image/HSL/wheels + packaged edit_persistence |
| Masks / object selection | PASS | PASS | PARTIAL | PARTIAL | PARTIAL | Local packaged masking UX + letterbox PASS (private evidence); matrix L4 PARTIAL until CI-bound native binding; Neon recall ≥0.90; magenta IoU ~0.60 |
| Color Workspace operators | PASS | PASS | PARTIAL | NOT_RUN | PARTIAL | acceptance/reference + managed operator suites on develop; deeper visual/perf still PARTIAL |
| Scopes | PASS | PARTIAL | PASS | NOT_RUN | PARTIAL | JS accumulate/panel/tap + non-packaged perf; packaged live-tap NOT_RUN |
| Video editing / playback | PASS | PASS | PARTIAL | NOT_RUN | PARTIAL | cut/speed/proxy/preview + JS clocks; packaged playback NOT_RUN on develop CI |
| Collage edit / export | PASS | PASS | PARTIAL | NOT_RUN | N/A | collage model/export cleanup + playback JS; native collage NOT_RUN |
| Supported transitions / effects | PASS | PASS | NOT_RUN | NOT_RUN | PENDING | transition timing unit+export; soft-wipe / drone packs parallel PENDING |
| Project persistence / Undo-Redo | PASS | PASS | NOT_RUN | NOT_RUN | N/A | `test_studio_history`, Control API undo conflict/two-clip |
| Control API / MCP | PASS | PASS | N/A | PARTIAL | N/A | Control API pytest PASS; MCP in external repo; WebView control smoke opt-in |
| Assistant connection | PARTIAL | PARTIAL | NOT_RUN | NOT_RUN | PENDING | pairing spike only; full assistant PENDING parallel |
| Packaged Windows startup | N/A | N/A | N/A | NOT_RUN | N/A | `packaging/e2e/windows_e2e.py` startup journey; required on main admission |

## UI/UX protection (no redesign)

| Check | Status | Evidence |
| --- | --- | --- |
| Short DE/EN labels on primary Studio/Library actions | PARTIAL | locale catalogs + journey HTML assertions; no full label audit automation |
| Visible accessible primary actions / selected/disabled | PARTIAL | history button sync + control disabled lifecycle tests |
| No misleading non-functional controls | PENDING | needs focused UI contract expansion as features land |
| No clipping/overlapping essential controls | NOT_RUN | native/browser visual; not claimed from HTTP |
| Responsive normal/constrained layouts | NOT_RUN | human / native |
| Direct canvas/timeline interactions | PARTIAL | domain geometry + JS module tests; native pointer NOT_RUN |
| Progress / cancel / error recovery | PASS | export cancel + job status suites |
| Consistent design components | PENDING | no redesign in this gate PR |

## Control API / MCP contract (#275)

| Check | Status | Evidence |
| --- | --- | --- |
| Wrong-clip targeting rejected | PASS | `test_apply_action_wrong_clip_target_is_rejected` |
| Stale Original preview (`clip_id: null`) | PASS | `test_original_preview_has_no_editable_target_*` |
| Two-clip Undo conflict | PASS | `test_two_clip_undo_binds_original_project_clip_and_command` |
| Command replay / lost ack | PASS | lost-ack + committed-outcome tests |
| Disable / restart empty | PASS | `test_security_lifecycle_and_payloads` |
| Auth / loopback / Origin | PASS | `test_local_http`, Control API nonloopback |
| MCP stdio discover/read/edit/poll/undo | PARTIAL | external `orga-drone-mcp` CI; not duplicated here |
| Playwright web UI | NOT_RUN | no in-repo Playwright harness |
| Packaged WebView2 | NOT_RUN on develop PRs | harness present; main-admission required |

## Fixture matrix (#283)

| Fixture class | In-repo | Status |
| --- | --- | --- |
| Synthetic JPEG/PNG/MP4 (generated) | yes (tests create) | PASS |
| Sanitized SRT samples | `tests/fixtures/*.srt` | PASS |
| Grade / intent / speed-ramp JSON | `tests/fixtures/*.json` | PASS |
| Versioned manifest | `tests/fixtures/regression_fixture_manifest.json` | PASS (this PR) |
| Optional privacy-safe DJI/Potensic | local opt-in only | PENDING / never fabricate |

## Integration / PR gates (#284)

| Gate | Status |
| --- | --- |
| Isolated worktree + branch per issue | PASS (process doc) |
| PR links issue, risk, API impact | PASS (process doc + template) |
| No unreviewed auto-merge of conflicting refactors | PASS (human + main admission) |
| Sequential develop merge + CI rerun | PASS (process); PO enforces |
| RC Windows EXE validation | NOT_RUN for this PR; required before release |

## Close recommendations (this PR)

| Issue | Close? | Reason |
| --- | --- | --- |
| #275 | **No — keep open until packaged WebView2 evidence is dated and MCP adapter link is recorded in a release note** | Matrix + commands + Control API coverage land here; Layer 4 still NOT_RUN on develop |
| #283 | **No — keep open** | Manifest + policy land; optional real-footage matrix and visual tolerances still PENDING |
| #284 | **Partial process only — keep open** | Ownership/PR gate docs land; RC stabilization continues with parallel workstreams |

## Performance baseline

No new performance claim in this PR. Existing spatial/scopes/precision probes remain
opt-in discovery artifacts. Record baselines under `docs/discovery/` with commit SHA,
FFmpeg version, and machine class before treating them as gates.
