# Shared Studio action contract coverage matrix (#275)

Status: **audit / matrix** on `develop` @ `2f78fb7` (2026-11-12). Does not claim
Windows packaged MotW E2E unless a real run is recorded. Does not invent new
quality gates.

Related: `docs/architecture/STUDIO_ACTIONS.md`, ADR 0032, #272, #276–#282,
#283, #284, #293, #317.

## Layer model (binding)

| Layer | Proves | Does not prove |
|-------|--------|----------------|
| A — Domain/API (pytest) | Validation, persistence, Undo, stale/revision, UI/API same result | Rendered pixels, WebView2 UX |
| B — MCP adapter (external repo + thin journey tests) | Tool maps to same actions | Packaged EXE assistant UX |
| C — WebView2 / packaged E2E | Startup, selection, preview/export journeys | Full creator footage matrix (#283) |

Same validation, persistence, Undo/Redo and selection rules for UI and Control
API; no second editor implementation.

## Inventory vs evidence (honest)

Labels: **PASS** = automated evidence on develop; **PARTIAL** = some paths;
**GAP** = missing required evidence; **NOT_RUN** = harness exists, no fresh run
claimed here; **N/A** = out of this issue’s slice.

### Security / session fencing (Control API)

| Check | Layer | Status | Evidence |
|-------|-------|--------|----------|
| Loopback bind/peer, Host/Origin | A | PASS | `test_control_api.py` nonloopback / Origin |
| Wrong credentials / disable / restart empty | A | PASS | `test_security_lifecycle_and_payloads` |
| Stale project/session/state_token | A | PASS | selection/revision + stale tests |
| Idempotent command_id / lost ack | A | PASS | lost-ack / committed-outcome tests |
| Guarded Undo two-clip binding | A | PASS | `test_two_clip_undo_*` |
| Opt-in WebView2 control smoke | C | PARTIAL | `test_control_webview.py` (opt-in) |

### Shared actions by family

| Family | Actions (representative) | Layer A | Layer C | Notes |
|--------|--------------------------|---------|---------|-------|
| Library read | media search / availability | PASS | NOT_RUN | #277; open-media journey #293 |
| Project lifecycle | create/open/rename/delete | PASS | NOT_RUN | #278 |
| Timeline | add/remove/reorder/trim | PASS | NOT_RUN | #279; reload/resume synthetic |
| Color / LUT / effects | properties/image/look/hsl/wheels/detail | PASS | PARTIAL | #280/#296; LUT packaged stage exists |
| Audio (clip) + overlays | `clip.audio.edit`, `clip.overlays.edit` | PASS | PARTIAL | #281 part 1; overlay timeline e2e script |
| Music (project) | append/update/start/reorder/remove | PASS | PARTIAL | #281 part 2; audio timeline e2e script |
| Export jobs | start/status/result/cancel | PASS | PARTIAL | #282; packaged `export` journey |
| Open-media assistant journey | search→add→select→color | PASS | NOT_RUN | #293/#387; packaged rides dispatch |

### Packaged Windows journeys (`packaging/e2e/windows_e2e.py`)

| Journey | Status for this audit |
|---------|------------------------|
| startup, media_import, library_navigation, studio_open | NOT_RUN (harness present) |
| playback, edit_persistence, export, image_export | NOT_RUN |
| lut_parity, source_integrity, relaunch_persistence | NOT_RUN |
| MotW / downloaded-zip smoke (#317) | NOT_RUN / human |

Do **not** mark these PASS without a dated evidence JSON from a real run.

## Gaps still owned by #275 / #283

1. Single living matrix (this file) kept current as actions ship — update when
   new commands land (e.g. SFX after #391 merges).
2. Packaged WebView2 evidence refresh after #389/#391 land on develop.
3. Privacy-safe fixture manifest for optional real DJI/Potensic footage (#283);
   no copyrighted samples in-repo.
4. MCP adapter contract tests remain largely in `orga-drone-mcp` — link results
   from that repo; do not duplicate the editor there.

## Explicit non-claims

- #273 app-generated pairing / DPAPI handoff — blocked on PO spike (separate).
- Strict color parity (#320) — tracked; not claimed green here.
- Soft-wipe Story parity (#301) — prior NO-GO recorded.

## Recommended next engineering slices

1. After PO merges weekend PRs: re-run packaged `windows_e2e.py`, attach
   evidence under `docs/discovery/` with PASS/FAIL/NOT_RUN per journey.
2. #283: versioned fixture manifest schema + synthetic defaults; real footage
   opt-in path documented only.
3. Keep API regression in CI; never replace pixel/WebView2 proof with unit green.
