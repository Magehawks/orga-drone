# Discovery: Studio Creator Workflow

Status: **discovery complete for planning** (not shipped).  
Tracking issue: [#465](https://github.com/Magehawks/orga-drone/issues/465).  
Baseline: `origin/develop` @ `27c7e87` (includes Collage WP1 #457 / PR #471).  
Collage Composer baseline: epic [#456](https://github.com/Magehawks/orga-drone/issues/456), ADR 0038
(Accepted) + `docs/architecture/STUDIO_COLLAGE_COMPOSER.md`. WP1 persistence is on develop;
WP2+ UI/media/export remain in flight (PRs #472 / #473 and later WPs).

Implementation ideas (`status:idea`, not `ready-for-dev`):

| # | Issue |
|---|--------|
| [#466](https://github.com/Magehawks/orga-drone/issues/466) | Browse Edit in Studio + new/existing project chooser |
| [#467](https://github.com/Magehawks/orga-drone/issues/467) | Skippable empty-project start (Normal vs Collage) |
| [#468](https://github.com/Magehawks/orga-drone/issues/468) | Library selection seeds collage leaves |
| [#469](https://github.com/Magehawks/orga-drone/issues/469) | Per-leaf grading via Color Workspace |
| [#470](https://github.com/Magehawks/orga-drone/issues/470) | Creator journey tests Library → Export |

This document specifies the end-to-end journey

```text
Sources → Library → Project → Studio → Collage / Editing → Export
```

so implementation can proceed after the Collage Composer work packages land,
without another foundational discovery pass.

## 1. User problems

1. Selecting several photos/videos in Browse and wanting to **edit them in Studio**
   currently means “append to whatever project is open,” with no choice of new vs
   existing project, and no guarantee the selection survives a missing-project
   redirect.
2. An empty new project drops the user into a blank Story with only “add from
   Browse / Title Card” hints. There is no clear, skippable choice between a
   normal sequential story and starting a collage.
3. Collage Composer (#456) will add layout/preview/export for a collage *item*,
   but does not by itself close the Mediathek → Project → Collage handoff or
   the “reuse Color Workspace per cell” creator journey.
4. Creators must not re-pick the same media inside Studio after they already
   selected them in the library.

## 2. Target audiences

| Audience | Need |
|----------|------|
| Hobby / FPV pilots | Multi-select a short flight set → one Story or one collage → local MP4 |
| Travel / content creators | Side-by-side multi-cam or photo grids inside a longer memory story |
| Photographers / videographers | Per-cell grade/framing without leaving Studio or learning a second color UI |

Out of product scope: professional NLE, cloud sync, replacing Photo Workspace
Image Composer (`photo_combine.py` / #453).

## 3. Current state (Available now)

### 3.1 Library → Studio

| Capability | Today |
|------------|--------|
| Single add | `POST /media/{id}/studio/add` from detail/browse; opens project required |
| Multi-select | Browse checkboxes + `POST /studio/add-bulk` (`browse.js`, `index.html`) |
| Photos + videos | Both kinds supported |
| Target project | Always `db.resolve_studio_page_project()` (open project only) |
| New vs existing chooser | **Missing** |
| No project open | Redirect `/studio?msg=studio_need_project`; **selection not applied** |
| After add | Usually stay on Browse (`return_to`); clips appended as sequential `item_kind=media` |
| Bulk duplicates | Skips paths already in project (`add_studio_media_ids`); single-add may duplicate (#16) |
| Cap | Bulk capped to one Browse page size |

Copy today: **Add selected to Studio** / **Add to Studio**, not “Edit in Studio.”

### 3.2 Project start

| Capability | Today |
|------------|--------|
| Gallery | `/studio/projects`; create via form or `POST /api/studio/projects` |
| Open | `POST /api/studio/projects/{id}/open` → editor |
| Empty editor | “Your story is empty” + link to Browse + Add title card |
| Normal vs Collage chooser | **Missing** |
| Collage entry | **Not on develop**; planned in #456 WP2 as Studio **Collage** action |

### 3.3 Timeline / clip model

- Ordered `studio_clips` per `studio_projects` (`position`).
- `item_kind`: `media` | `title_card` | `collage` on develop (ADR 0038 / WP1).
- Duration: video trim/speed/ramps; photos `photo_duration_s`; title cards
  `card_duration_s`; collage will use `collage_duration_s`.
- Grades/framing/overlays live in `effect_settings` (and canonical grade) on
  **media** clips. Generated items keep structured columns / JSON outside the
  grade bag (Title Card pattern; collage_spec per ADR 0038).
- Undo/Redo: in-memory snapshots of `_CLIP_COLUMNS` + music start + SFX
  (`studio_history.py`); not persisted across process restart. Collage fields
  must be added to `_CLIP_COLUMNS` (WP1).

### 3.4 Preview / export

- One primary media (plus crossfade A/B) per Story time; pause/scrub stills via
  grade path; MP4 via `FfmpegStudioEncoder` segment chain.
- No multi-source layout on develop; #456 WP4–WP6 add still compositor + play
  sync + `xstack` segment.
- Color honesty: pause/scrub graded stills are SoT for LUT/HSL; realtime
  multi-stream graded play is not required (ADR 0028 / 0038).

### 3.5 Collage Composer (in flight, do not contradict)

Locked by ADR 0038 / epic #456:

- One Story item; recursive split layout SoT; library + desktop leaves.
- Shared duration and Story position; internal media relative to collage time.
- Hold last frame for short videos; cut long videos at collage end; photos hold;
  no auto-loop; no extra main Story track per leaf; muted leaf audio.
- Optional per-leaf grade envelope using the **existing** Color Workspace
  contract; apply once on leaf render (still + export).
- `photo_combine` unchanged.

Work packages: WP1–WP7 = issues #457–#463. WP1 closed on develop; WP2–WP7
`status:ready-for-dev` until each lands. External collage leaves use opaque
`source_key` handles for public round-trips (WP1 review follow-up).

## 4. Proposed end-to-end UX flow

### 4.1 Happy path A — Library multi-select → new Story

1. Browse: multi-select photos and/or videos (existing checkboxes; extend copy).
2. Action **Edit in Studio** / **Im Studio bearbeiten** (primary; keep Add-to-open
   as secondary or rename carefully for DE/EN).
3. Chooser: **New project** | **Existing project** (list recent projects).
4. On New: create empty project, open it, append selected media as Story clips
   **or** offer “Start as collage” when the Collage Composer is available
   (see 4.3). Selection must not be discarded if the user cancels the chooser.
5. Land in Studio with those items already on the Story; no mandatory re-pick.

### 4.2 Happy path B — Existing project

1. Same multi-select → Edit in Studio → Existing project → pick target.
2. Append (or seed collage) into that project; open it; select the first new
   item or the new collage.
3. No empty-project start dialog on projects that already have clips.

### 4.3 Empty project start (skippable)

When opening a **new empty** project (clip count 0), show a lightweight panel
(not a blocking modal chain):

- **Edit normally** — dismiss panel; empty Story + Browse hint (today’s path).
- **Create collage** — create `item_kind=collage` (WP2 API) and focus inspector.
- **Skip / dismiss** — same as Edit normally; remember dismissal for this
  project session (optional: until first clip added).

Collage remains available anytime via Studio **Collage** action (#456 WP2).

### 4.4 Selection → collage seed (after #456)

When the user chose collage (start panel or “Edit in Studio → New → as collage”):

1. Create collage Story item with default/preset layout sized to N leaves when
   possible, or create collage then assign selected media to leaves in order.
2. Excess media beyond leaf count: either expand layout (split) within resource
   limits, or append leftover media as normal Story clips after the collage —
   product default should be documented in the implementation issue; recommend
   **fill leaves in order, then append leftovers as media clips**.
3. Do not require opening the library picker again for already-selected ids.

### 4.5 Collage on the main timeline

- One tile on the Story track (Title Card / photo duration pattern).
- Position freely among media/title cards; transitions apply to the collage
  item as a whole (outgoing transition from collage → next clip), not per leaf.
- Inspector: layout + leaf list; selecting a leaf scopes Color/Framing UI to
  that leaf’s grade/fit envelope.
- Hold-last-frame timing per ADR 0038 / WP5; Seek, composed still, play, and
  MP4 must agree.

### 4.6 Export

- Unchanged Studio export entry: MP4 story including collage segments (WP6).
- Optional PNG/JPEG of a static collage (WP4) remains a collage-item action,
  not a replacement for Story MP4.

## 5. Architecture and integration (proposal, no new ADR here)

| Area | Integration approach |
|------|----------------------|
| Project model | Reuse `studio_projects` + open-project pointer; no new project type |
| Persist selection handoff | Prefer atomic server action: create/open project + add media ids / seed collage in one transactional story edit; optional short-lived server-side “pending media ids” only if UI needs a multi-step wizard |
| Collage item | Owned by #456 (`collage_spec`, `collage_duration_s`); this workflow only seeds and navigates |
| Per-leaf grade | Store under leaf in `collage_spec` (ADR 0038 `grade?`); apply via existing preview-frame + encoder grade path; **no second color engine** |
| Leaf framing | Collage fit/fill/zoom/pan (WP3) is cell-local; do not reuse full-clip Ken Burns `effect_settings.frame` on the collage row |
| Inspector | Extend selection model: collage item vs leaf id; Color tabs bind to leaf grade when a leaf is selected |
| Undo/Redo | One history step for “create project + add N media / seed collage”; collage field columns via WP1 |
| Preview/Export | Depend on WP4–WP6; workflow issues must not fork compositor/encoder |
| Image Composer | Stay on photo detail; do not call `photo_combine` from Studio |

## 6. Dependencies on Collage Composer

| Workflow slice | Depends on |
|----------------|------------|
| Browse Edit-in-Studio + project chooser + append media | None (can ship before collage) |
| Empty-project “Create collage” | WP1 + WP2 (#457, #458) |
| Seed collage from library selection | WP1–WP3 (#457–#459) |
| Hold-last-frame / multi-video play parity | WP5 (#461) |
| MP4 including collage in story | WP6 (#462) |
| Per-leaf HSL/LUT/wheels via Color Workspace | WP1 leaf `grade?` + WP4 apply path; Color Workspace contracts (#348+) |
| Journey polish / honesty docs | WP7 (#463) |

**Conflict rule:** Do not change ADR 0038 layout/timing decisions in this
workflow stream. If a workflow requirement fights the in-flight collage PRs,
document the conflict on both issues and wait for PO direction.

## 7. Gaps vs desired behavior

| Desired | Gap |
|---------|-----|
| Multi-select photos+videos | Exists |
| Action “Edit in Studio” | Copy/flow gap; bulk is “Add selected to Studio” |
| New or existing project | Missing chooser; open-only target |
| Preserve selection | Lost on need-project redirect; cancel path undefined |
| No re-pick in Studio | Partial (clips appended) but not collage-seeded |
| Empty project Normal/Collage skippable | Missing |
| No start dialog on existing projects | Already true; keep it |
| Collage anytime later | Planned WP2; keep |
| Collage one timeline element + hold last frame | Specified in #456; not on develop yet |
| Per-cell color via existing engine | Specified optionally in ADR; needs explicit WP/issue after still/export path |

## 8. Non-goals

- Implementing Collage Composer itself (owned by #456–#463).
- Changing or replacing Photo Workspace Image Composer.
- Second timeline inside collage; per-leaf main Story tracks.
- Second color/encoding pipeline; cloud accounts; React/bundler migration.
- Cross-page Browse selection beyond current page (unless a later issue expands it).
- Auto-import of desktop-picked files into the library.
- Merge to `main`, EXE, or public release as part of this discovery.

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Parallel edits to `studio.js` / browse templates with collage PRs | Sequence after WP2/WP3 or isolate browse handoff PR with minimal Studio touch |
| Schema/history column races with WP1 | Workflow seeding waits for WP1 migration on develop |
| Selection loss / open-redirect mistakes | Allowlisted return URLs (existing helpers); persist ids through chooser |
| Per-leaf grade vs Color Workspace unfinished surfaces | Apply only grade ops already on the shared still/export path; defer unfinished CW editors |
| Bulk “skip existing path” vs intentional duplicates | Edit-in-Studio append should follow single-add duplicate policy (#16) or document membership-safe choice |
| Empty-project chooser annoyance | Skippable; never on non-empty projects |
| Timing drift Seek ≠ Export | Owned by WP5/WP6 tests; workflow E2E asserts journey only |

## 10. Recommended implementation order

1. **Browse Edit-in-Studio + project chooser + preserve selection** (no collage dependency).
2. Finish Collage **WP1–WP3** (layout, UI, media pickers) on develop.
3. **Empty-project start panel** (Normal / Collage / skip) wired to WP2 create API.
4. **Seed collage / append leftovers** from library selection.
5. Collage **WP4–WP6** (still, play sync + hold-last-frame, MP4).
6. **Per-leaf grade inspector** reusing Color Workspace apply path.
7. **Creator journey tests** + PRODUCT_VISION/ROADMAP honesty (coord with WP7).

## 11. Acceptance criteria (discovery complete when)

- [x] Current Library→Studio and project APIs documented with file/route names.
- [x] Desired UX flow specified including skippable empty-project chooser.
- [x] Collage timeline/timing decisions aligned with ADR 0038 (hold last frame).
- [x] Per-cell editing strategy = reuse existing grade/framing contracts, no second engine.
- [x] Dependencies and conflicts with #456–#463 documented.
- [x] Parent discovery issue + `status:idea` implementation issues filed on GitHub.
- [ ] Human PO acknowledges order before `ready-for-dev` promotions.

## 12. Evidence commands (analysis only)

```text
gh issue view 456..463
git worktree: orga-drone-wt/studio-creator-workflow @ discovery/studio-creator-workflow
git worktree: orga-drone-wt/studio-collage @ feat/457-studio-collage-model (docs only)
Routes: app.py studio_add, studio_add_bulk, studio projects APIs
DB: add_studio_item, add_studio_media_ids
History: studio_history._CLIP_COLUMNS
```
