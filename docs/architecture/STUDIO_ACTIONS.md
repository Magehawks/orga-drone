# Studio action architecture for 2.4.0

Status: **analysis for issue #272.** This document describes the implementation
that exists today and the shared action contract used by #276. It is not a
promise that every Studio control becomes an MCP tool. Product truth remains
[`../PRODUCT_VISION.md`](../PRODUCT_VISION.md); the frontend module map is
[`../STUDIO_MODULES.md`](../STUDIO_MODULES.md).

## 1. Goal and boundary

The Studio UI, the opt-in local Control API, and an external MCP adapter must
invoke **one domain implementation per action**. Transports stay separate:

- Browser UI: `static/js/studio.js` and `static/js/studio/*` call existing HTTP
  routes under `/api/studio/*` or `/studio/*`.
- Control API: `control.py` validates a process-local command and `control_routes.py`
  authenticates the loopback request. It must not contain a second editor.
- MCP (separate repository): a thin client of Control API v1. No provider code,
  credentials, or MCP transport enters this repository.

Existing security boundaries stay unchanged: loopback bind and peer checks,
exact Origin, bearer authentication for external clients, 8192-byte JSON bodies,
bounded identifiers, process-local leases, idempotent command IDs, and guarded
Undo. See [`../CONTROL_API.md`](../CONTROL_API.md) and ADR 0032.

## 2. Shared action contract

An action has a stable name, an explicit contract version, a scope, a target, a
validated parameter object, a result, and a set of side effects. The transport
never invents semantics.

```json
{
  "action": "clip.color.image",
  "action_version": 1,
  "target": {"project_id": 1, "clip_id": 2},
  "params": {"contrast": 15, "saturation": 20}
}
```

### Identity and target

- `project_id` and `clip_id` are positive SQLite identifiers in JavaScript's
  safe integer range. `clip_id: null` means "no editable Story clip" (for
  example an Original preview) and must be rejected by clip actions.
- The editor must report the current target through the existing polling state.
  An action prepared for another clip is rejected, not retargeted.
- `session_id` identifies one Studio window. A live second editor cannot take over.
- `state_token` binds project rows, selection revision, history revision, and
  session. A new command reads a fresh token.
- Actions that create or open a project establish an explicit project context;
  they never infer one from the last rendered page.

### Command identity and idempotency

- Clients generate `command_id`. Repeating the same ID and exact payload returns
  the original outcome. Reusing the ID with another payload is
  `COMMAND_ID_CONFLICT`.
- Admission queues; execution runs under the editor lease. Long actions
  (especially export) return a job instead of blocking the call.
- Bounded storage refuses new IDs at capacity instead of evicting and permitting
  replay.
- Capability discovery is read-only and returns only implemented actions,
  parameter ranges, and asset identifiers. It never returns filesystem paths or
  credentials.

### Result envelope

```json
{
  "action": "clip.color.image",
  "action_version": 1,
  "status": "persisted",
  "persisted": true,
  "ui_applied": false,
  "preview_status": "refresh_requested",
  "no_op": false,
  "project_id": 1,
  "clip_id": 2,
  "canonical": {},
  "can_undo": true,
  "can_redo": false
}
```

`persisted` is a committed database operation. `ui_applied` is an inspector /
dataset acknowledgement. `refresh_requested` is not rendered-pixel proof.
Committed outcomes survive UI disconnect; process-local Undo/Redo does not.

### Errors

Stable codes are part of the contract: `CONTROL_DISABLED`, `INVALID_CREDENTIAL`,
`LOOPBACK_REQUIRED`, `ORIGIN_REQUIRED`, `INVALID_JSON`, `INVALID_PAYLOAD`,
`PAYLOAD_TOO_LARGE`, `UNKNOWN_ACTION`, `UNKNOWN_COMMAND`, `TARGET_NOT_FOUND`,
`STALE_SELECTION`, `STALE_STATE`, `EDITOR_BUSY`, `EDITOR_NOT_READY`,
`EDITOR_DISCONNECTED`, `EDITOR_SESSION_CONFLICT`, `COMMAND_EXPIRED`,
`COMMAND_ID_CONFLICT`, `COMMAND_CAPACITY_REACHED`, `LUT_UNAVAILABLE`,
`MEDIA_UNAVAILABLE`, `UNSUPPORTED_CLIP`, `ANIMATED_SETTINGS_UNSUPPORTED`,
`UNDO_CONFLICT`, `INVALID_CLIP_SETTINGS`, and `DATABASE_ERROR`.

### Versioning

- `/api/control/v1` stays the transport path for compatible additions.
- Adding a command type, action, parameter, or discovery field is compatible.
- Removing or renaming a field, changing units, changing validation meaning, or
  changing target semantics requires `/api/control/v2` and a compatibility note.
- Existing `set_clip_properties` remains a v1 command. New generic actions use a
  new command type and do not silently change its payload.
- Persisted `effect_settings` and the SQLite schema are not changed by the action
  contract. Project compatibility is preserved.

## 3. Current action inventory

Line references point at `develop` when this analysis was written. Route names
and function names are more stable than line numbers.

### Library and media (read-only candidate for #277)

| Operation | UI entry | Backend | Persistence / side effect | Undo | API today | Tests |
|---|---|---|---|---|---|---|
| Browse list and filters | `/browse`, `/media`; `browse.js` | `app.py` browse routes; `db.list_media*` | reads only | n/a | none | `test_browse_pagination.py`, `test_browse_timeline.py` |
| Search | `/api/search`; `browse.js` | `search/`, `app.py` | reads only | n/a | none | `test_search.py` |
| Media metadata / detail | `/media/{id}`; `detail-*.js` | `app.py`, `db.get_media`, `parse/` | reads only | n/a | none | `test_media_meta.py`, `test_generic_media.py` |
| Thumbnail / preview / stream | `app.py` media routes | `thumbs.py`, `media_files.py` | local files only, source read-only | n/a | none | `test_photo_preview.py`, `test_srt_track.py` |

### Project and Story lifecycle (candidate for #278)

| Operation | UI entry | Backend | Persistence | Undo | API today | Tests |
|---|---|---|---|---|---|---|
| List projects | `/studio/projects`; `studio/project-browser.js` | `app.py` 1651 | reads | n/a | none | `test_studio_project.py`, `test_studio_projects_browser.py` |
| Create / open / rename | project browser | `app.py` 1306, 1663, 1840, 1808 | `studio_projects` | rename participates in Story history only through the UI route | none | same |
| Delete project | project browser | `app.py` 1314, 1867 | drops project rows only | no cross-project Undo | none | same |
| Add media / bulk add | Browse and Studio | `app.py` 3822, 3853; `db.add_studio_item` | `studio_clips` | existing story edit | none | `test_studio.py`, `test_studio_bulk_add.py` |
| Clear Story | Studio | `app.py` 3911 | `studio_clips` | existing story edit | none | `test_studio.py` |
| Undo / Redo | Studio buttons and Ctrl+Z | `app.py` 3888; `studio_history.py` | process-local snapshots | owner | control exposes guarded Undo only | `test_studio_history.py`, `test_control_api.py` |

### Timeline and clip editing (candidate for #279)

| Operation | UI entry | Backend | Persistence | Undo | API today | Tests |
|---|---|---|---|---|---|---|
| Reorder | Story drag | `/api/studio/reorder`; `db` | `position` + updated_at | yes | none | `test_studio.py`, `test_studio_timeline.py` |
| Trim / split / remove cut / merge | inspector/timeline | `studio_cut.py`, `studio_merge.py`, `app.py` 1990, 3202, 3275, 3293 | clip rows | yes | none | `test_studio_cut.py`, `test_studio_merge.py`, `test_studio_remove_clip.py` |
| Speed / repeat / section / loop | inspector/effect lane | `studio_speed.py`, `studio_forward_loop.py`, `studio_loop_match.py`, `studio_effect_lane.py` | clip columns / effect_settings | yes | none | `test_studio_speed.py`, `test_studio_section_repeat.py`, `test_studio_forward_loop.py` |
| Transition | clip edge picker | `studio_transition.py`, `app.py` 3071 | clip columns | yes | none | `test_studio_transition.py`, `test_studio_export_transitions.py` |
| Reuse source | context menu | `studio_reuse.py`, `app.py` 3333, 3377 | new clip rows | yes | none | `test_studio_reuse.py` |
| Photo duration | inspector | `app.py` 1990 | `photo_duration_s` | yes | none | `test_studio_timeline.py` |

### Color, LUT, and effects (priority, candidate for #280)

| Operation | UI entry | Backend / validator | Persistence | Undo | API today | Tests |
|---|---|---|---|---|---|---|
| Basic image sliders | inspector Image | `studio_image.py`; `db.set_studio_image_adjust`; `app.py` 2038 | `effect_settings.image` | yes | `set_clip_properties` subset: contrast + saturation | `test_studio_image.py`, `test_control_api.py` |
| Quick Looks | inspector Image | `studio_looks.py`; `app.py` 2237 | `effect_settings.image/look` | yes | none | `test_studio_looks.py` |
| LUT / input profile | Color profiles | `studio_lut.py`; `db.set_studio_color_look`; `app.py` 2496 | `effect_settings.color` | yes | creative LUT subset | `test_studio_lut.py`, `test_studio_lut_pixel_parity.py` |
| HSL mixer | inspector Color | `studio_hsl.py`; `app.py` 2436 | `effect_settings.hsl` | yes | none | `test_studio_hsl.py` |
| Color wheels | inspector Color | `studio_color_wheels.py`; `app.py` 2466 | `effect_settings.color_wheels` | yes | none | `test_studio_color_wheels.py` |
| Sharpen / denoise | Fine-tune | `studio_detail.py`; `app.py` 2211 | `effect_settings.detail` | yes | none | `test_studio_detail.py` |
| Saturation ramp / color animation | Fine-tune / effect lane | `studio_image.py`, `studio_color_animation.py`; `app.py` 2539, 2570 | `effect_settings` | yes | intentionally unsupported for animated clips | `test_studio_saturation_ramp.py`, `test_studio_color_animation.py` |
| Effect lane | Timeline | `studio_effect_lane.py`; `app.py` 2600 | `effect_settings` | yes | none | `test_effect_lane.py` |

The priority demo path is a single clip with an explicit identity, basic grade,
creative LUT and strength. Preview/export parity retains its existing tolerance
and is not certified by API tests.

### Audio and overlays (candidate for #281)

| Operation | UI entry | Backend | Persistence | Undo | API today | Tests |
|---|---|---|---|---|---|---|
| Project music playlist | inspector Music | `studio_audio.py`, `app.py` 1679-1807 | `studio_audio_clips`, project music start | yes | none | `test_studio_music.py` |
| Clip audio detach / volume | inspector Audio | `studio_audio.py`, `app.py` 2650 | clip columns / effect_settings | yes | none | `test_studio_clip_audio.py` |
| Text/image overlays | overlays panel | `studio_overlay.py`, `app.py` 2680, 2722 | `effect_settings.overlays` + local asset | yes | none | `test_studio_overlay.py` |
| Masks | mask panel | `studio_mask.py`, `app.py` 2746 | `effect_settings.masks` | yes | none | `test_studio_mask.py` |
| Frame / Ken Burns | framing panel | `studio_frame.py`, `app.py` 2774 | `effect_settings.frame` | yes | none | `test_studio_frame.py` |
| Flight map | map panel | `studio_map.py`, `app.py` 2812 | `effect_settings.map` | yes | none | `test_studio_map.py` |
| Telemetry HUD | HUD panel | `studio_hud.py`, `app.py` 2840 | `effect_settings.hud` | yes | none | `test_studio_hud.py` |

### Preview, playback, and export (candidate for #282)

| Operation | UI entry | Backend | Persistence / side effect | Undo | API today | Tests |
|---|---|---|---|---|---|---|
| Paused/scrub still | preview | `studio_preview_frame.py`, `app.py` 2267 | cache only; source read-only | n/a | none | `test_studio_preview_frame.py`, `test_studio_parity_contract.py` |
| Playback proxy | playback | `studio_playback_proxy.py`, `app.py` 2362, 2396 | local cache; source read-only | n/a | none | `test_studio_playback_proxy*.py` |
| Export options | export dialog | `app.py` 3431 | reads | n/a | none | `test_studio_export_resolution.py` |
| Start export | export dialog | `studio_export.py`, `export/`, `app.py` 3443 | local output file | n/a | none | `test_studio_export*.py`, `test_export_jobs.py` |
| Progress / cancel / result | export dialog | `app.py` 3792, 3806 | job registry / output file | n/a | none | `test_export_cancel.py`, `test_export_jobs.py` |
| Open / reveal output | success banner | `app.py` 3814, 3818; `desktop.py` | desktop-only side effect | n/a | none | `test_desktop.py` |

## 4. Module ownership and dependency order

Issue #277 adds `library_actions.py`: read-only typed projections over the
existing `search` and `Database.list_media/count_media/get_media` boundary used
by the UI. Shared discovery advertises library-scoped version 1 reads through
`POST /api/control/v1/read-actions`; clip command admission rejects that scope.
Library reads require the paired editor lease but do not depend on a selected
clip, and never return source paths or generate media/cache artifacts.

```text
#272 docs (this file)
  └─> #276 studio_actions.py + control.py adapter + discovery
        ├─> #280 color/LUT/effects actions
        ├─> #277 library/read actions
        ├─> #278 project lifecycle actions
        ├─> #279 timeline actions
        ├─> #281 audio/overlay actions
        └─> #282 export job actions
              └─> #283 fixture matrix + Windows gate
                    └─> #284 RC integration and stabilization
```

`#275` owns the layered test contract and extends after #276. `#273` and `#274`
remain Connect issues; their pairing/security work must not be implemented in
these Studio module PRs. Only the loopback/credential boundary is reviewed for
compatibility.

Files that every module PR must coordinate, one owner at a time:

- `src/orga_drone/studio_actions.py` (new shared registry/facade)
- `src/orga_drone/control.py`
- `src/orga_drone/control_routes.py`
- `tests/test_control_api.py`
- `docs/CONTROL_API.md`

Module-specific new files should be added instead of editing `studio.js`,
playback, proxy, export encoder, or the SQLite schema. The existing route
handlers remain the UI transport until a dedicated migration says otherwise.

## 5. Existing code that needs no refactor

These areas already have a clear responsibility and must keep their behavior:

- Media scan/import/parse/search/dupes/geocode: `scan/`, `parse/`, `group/`,
  `search/`, `dupes/`, `geocode/`, `media_files.py`, `media_mutation.py`.
- Story time mapping: `studio_cut.py`, `studio_speed.py`, `studio_transition.py`,
  `studio_estimate.py`, `studio_forward_loop.py`, `studio_loop_match.py`,
  `studio_merge.py`, `studio_reuse.py`.
- Effect validation and serialization: `studio_image.py`, `studio_lut.py`,
  `studio_hsl.py`, `studio_color_wheels.py`, `studio_detail.py`,
  `studio_looks.py`, `studio_color_animation.py`, `studio_effect_lane.py`,
  `studio_overlay.py`, `studio_mask.py`, `studio_frame.py`, `studio_map.py`,
  `studio_hud.py`, `studio_audio.py`.
- Undo/Redo snapshots and guarded external Undo: `studio_history.py`.
- Playback/preview/proxy pipeline: `studio_preview_frame.py`,
  `studio_playback_proxy.py`, `static/js/studio-lut-webgl.js`, current browser
  clock/sync code.
- Export filter order and encoder: `export/studio_encoder.py`, `studio_export.py`.
- Loopback Host/Origin security: `local_http.py`, `LoopbackOriginMiddleware`.
- SQLite schema and migrations: `db/__init__.py`. No schema or
  `effect_settings` shape change is planned for 2.4.0.

The one justified refactor is to remove duplicated color validation/merge logic
from `control.py` into the shared action facade. That duplication is a real
second implementation risk, not a SOLID exercise.

## 6. Test and fixture gaps

Existing coverage is strong for routes and effect math. Gaps for the shared
contract:

- Color action parity between UI and Control API is covered by #287 contracts.
- Library/read contracts, filter parity, availability and path privacy are covered
  by #277 tests; no additional metadata extraction is implied.
- Project lifecycle stale-context, concurrent requests, transaction rollback and
  lost-response navigation recovery are covered by #278 contracts.
- Timeline actions lack a two-clip wrong-target Undo contract at API level.
- Audio/overlay actions have route tests but no API persistence/Undo contract.
- Export jobs have job tests but no non-blocking Control API contract.
- No privacy-safe fixture manifest separates synthetic MP4/JPG/PNG, optional
  DJI/Potensic footage, and Windows-only visual checks.

Fixtures for 2.4.0 must use temporary synthetic media. Real creator footage is
opt-in and must not be committed. API tests cannot prove rendered color,
playback, or export pixels; those stay in the Windows/manual gate.

## 7. Release gate and rollback

Release candidate requires:

1. Sequential reviewed PRs for #276 and the module issues, each green on full
   Python and JS checks.
2. Control API v1 compatibility tests, including restart, disable, stale target,
   idempotent replay, two-clip Undo, and wrong credentials.
3. Windows packaged EXE smoke with WebView2 plus a human Studio/sample check.
4. No unresolved critical review finding.
5. No source-media modification and no export overwrite without explicit consent.

Rollback is per PR: revert the module PR without reverting the action contract
when possible. The contract foundation remains compatible because it does not
change SQLite or `effect_settings`. If an action is unsafe, remove it from
discovery and reject its command type; do not leave a partially working path.

No release is published automatically. #283 and #284 decide the RC evidence;
a human maintainer makes the final release decision.


## Project lifecycle implementation and next ownership batch (#278)

`project_actions.py` now shares existing create/open/rename/delete operations
between form routes, JSON routes and versioned Control API project actions.
Project reads use an allowlisted DTO and the common `read-actions` transport;
mutations use `project_action` with explicit source project/session/token and a
null clip target. Existing persistence helpers may join one caller-owned
transaction. Create+open is atomic; no schema or project format changes occur.
Project switches fence the previous editor, preserve project-scoped Story history
and request fixed `/studio` navigation; the next editor explicitly re-enables
control. Committed navigation remains UI-unconfirmed. See `../CONTROL_API.md`.

Recommended next batch, without implementing these issues here:

- **#279 timeline/clip owner:** build project-scoped editing actions first,
  using #277 media IDs and #278 session/project targeting. Reuse existing timing
  modules and transactional Story history; prove wrong-clip/two-clip Undo,
  persistence and stale requests. Own timeline actions and focused Python/JS
  tests. Serialize registry/control changes through one integration owner.
- **#281 audio/overlay owner:** follow stable project/clip contracts and reuse
  existing audio/overlay validators. Expose approved asset IDs; never accept an
  unrestricted path. ADR 0008's soundtrack exception stays read-only and does not
  justify incoming arbitrary paths. Own audio/overlay domain actions and tests.
- **#282 export/job owner:** follow stable targeting and explicit job ownership.
  Adapt existing nonblocking export/progress/cancel/publication with an explicit
  project snapshot. Use generated output identifiers instead of arbitrary output
  paths. Preserve cancellation/publication safety and encoder filter order.
- **#275/#283 QA owner:** maintain synthetic privacy-safe MP4/JPG/PNG and optional
  DJI fixture matrices plus packaged Windows WebView2 E2E evidence. Real-media
  visual/playback checks remain opt-in and human-owned.
- **External MCP adapter owner:** consume discovery and these versioned contracts
  from Magehawks/orga-drone-mcp. No provider/MCP transport enters this repository.

Each batch gets a focused PR and independent technical review. Shared registry,
Control API, route and documentation changes have one owner at a time. Windows
WebView2 and private real-media testing remain release evidence requirements;
this work does not publish 2.4.0 or claim those checks have passed.
