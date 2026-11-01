# Orga Drone – Agent Context

Orga Drone is an **open-source, local-first drone media library** with flight
metadata, telemetry, map exploration, and a **Studio** memory-editor UI. It runs
as a Python/FastAPI application; the packaged desktop target is Windows
(pywebview + WebView2). Source media stays on disk and is never modified by
library, Studio, or export workflows.

- Product source of truth: [`docs/PRODUCT_VISION.md`](docs/PRODUCT_VISION.md)
- Current architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Studio frontend module map and migration rules: [`docs/STUDIO_MODULES.md`](docs/STUDIO_MODULES.md)
- Roadmap/status language: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- Agent workflow and gates: [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md)

Target users include hobby pilots, content creators, photographers and
videographers, and professional operators with large local libraries. Orga
Drone is **not** a professional NLE, mission planner, airspace suite, cloud sync
service, or generic drone administration product.

## Non-negotiable product limits

- Stay local-first. Do not add cloud accounts, uploads, telemetry, or required
  network services.
- Never modify, move, or delete source media. Studio projects, albums, grades,
  and exports are additive references.
- Path operations for library media stay under configured library roots. Studio
  soundtrack files are the documented read-only exception (ADR 0008).
- Preserve `media_meta`, `album_items`, and `studio_clips` across rescans unless
  an approved migration explicitly says otherwise.
- Treat `docs/PRODUCT_VISION.md` and `docs/ROADMAP.md` labels as binding:
  **Available now** is shipping; **Later** is not. Never present planned work
  as shipped.
- Do not invent frameworks, services, plugin APIs, AI features, installers, or
  cloud capabilities that are absent from the tree.
- No React/Vue/Svelte, no bundler, and no TypeScript migration without an
  approved architecture decision.
- Prefer small, complete user-journey slices. Challenge requirements that do not
  improve the journey in `docs/PRODUCT_VISION.md`.
- Do not add AI for marketing. Do not label rule-based features as AI.

## Security, privacy, and release safety

- Never commit or paste secrets, `.env` files, API tokens, private media, SRT
  files, flight logs, or screenshots with people, homes, or precise locations.
  Tests and docs use synthetic fixtures or the existing sanitized samples.
- Local loopback Host/Origin checks (`src/orga_drone/local_http.py`) and media
  path confinement are security boundaries. Do not weaken them.
- The application never uploads or posts media. Share presets write local files.
- Do not commit, push, tag, or publish a release unless the human asks.
- Agents do not publish GitHub Releases or attach binaries. The manual Windows
  build workflow produces a non-publishing artifact; a maintainer runs the
  Mark-of-the-Web smoke test before a notes-only release. See
  [`packaging/README.md`](packaging/README.md) and
  [`docs/RELEASE_SECURITY.md`](docs/RELEASE_SECURITY.md). Pushes, pull requests,
  merges, and tags must not publish, upload, or notify. The itch.io butler
  process is a manual Draft/Restricted test channel, not a public launch.

## Repository map

| Area | Where |
|---|---|
| App entry / HTTP routes / Studio view model | `src/orga_drone/app.py`, `src/orga_drone/__main__.py` |
| SQLite schema, migrations, media/Studio persistence | `src/orga_drone/db/__init__.py` |
| Library scan, parsing, grouping, search, dupes, geocode | `scan/`, `parse/`, `group/`, `search/`, `dupes/`, `geocode/` |
| Rename and flow merge | `ops/` |
| Studio business rules | `studio_cut.py`, `studio_speed.py`, `studio_transition.py`, `studio_estimate.py`, `studio_effect_lane.py`, `studio_forward_loop.py`, `studio_loop_match.py` |
| Studio color and detail | `studio_image.py`, `studio_hsl.py`, `studio_color_wheels.py`, `studio_lut.py`, `studio_detail.py`, `studio_looks.py`, `studio_color_animation.py` |
| Studio overlays, masks, framing, map, HUD, audio | `studio_overlay.py`, `studio_mask.py`, `studio_frame.py`, `studio_map.py`, `studio_hud.py`, `studio_audio.py` |
| Studio preview stills and playback proxy | `studio_preview_frame.py`, `studio_playback_proxy.py` |
| Studio export | `studio_export.py`, `export/` |
| HTML templates and CSS | `src/orga_drone/templates/`, `src/orga_drone/static/css/app.css` |
| Studio frontend | `src/orga_drone/static/js/studio.js` (current monolith), `static/js/studio-lut-webgl.js`, target modules under `static/js/studio/` |
| Desktop shell and pickers | `desktop.py` |
| Windows packaging and licensing evidence | `packaging/` |
| Python tests and fixtures | `tests/` |
| JavaScript tests and fixtures | `tests/js/` |
| User docs | `docs/user/` |
| Decisions | `docs/decisions/` |

## Where to change what

| Change | Primary files | Read first |
|---|---|---|
| Product scope, positioning, shipped-vs-later | `docs/PRODUCT_VISION.md`, `docs/ROADMAP.md` | product docs |
| Library scan / metadata / flows / sessions | `scan/`, `parse/`, `group/`, `db/` | `docs/ARCHITECTURE.md` |
| Browse, filters, detail page | `app.py`, `templates/`, `static/js/browse.js`, `static/js/detail-*.js` | `docs/ARCHITECTURE.md` |
| Studio cut, speed, repeat, transitions, timing | `studio_cut.py`, `studio_speed.py`, `studio_transition.py`, `studio_estimate.py`, `studio_effect_lane.py` | `docs/STUDIO_MODULES.md` |
| Studio color, LUT, HSL, wheels, detail | `studio_image.py`, `studio_hsl.py`, `studio_color_wheels.py`, `studio_lut.py`, `studio_detail.py`, `studio_color_animation.py` | `docs/STUDIO_MODULES.md` |
| Studio preview stills / playback proxy | `studio_preview_frame.py`, `studio_playback_proxy.py` | `docs/STUDIO_MODULES.md` |
| Studio MP4 export | `studio_export.py`, `export/` | `docs/ARCHITECTURE.md` |
| Studio frontend UI | `static/js/studio.js`, `templates/studio.html`, `static/css/app.css` | `docs/STUDIO_MODULES.md` |
| Studio masks / overlays / map / HUD / framing | corresponding `studio_*.py` plus `studio.js` | `docs/STUDIO_MODULES.md` |
| Studio music | `studio_audio.py`, `db/`, `studio.js` | `docs/ARCHITECTURE.md` |
| Desktop window, dialogs, open/reveal | `desktop.py` | `packaging/README.md` |
| Windows build/release | `packaging/` | `packaging/README.md` |
| UI strings | `locales/` + template `data-*` messages | `docs/UX_WRITING.md` |
| Tests | `tests/`, `tests/js/` | `docs/PR_E2E.md` |

`.cursor/` is local-only IDE and agent configuration. It is not tracked. Shared
agent guidance belongs in `AGENTS.md` and `docs/AGENT_WORKFLOW.md`; do not add
`.cursor/` back to the repository.

## Regression-critical areas

Change these only for an approved issue, with focused tests:

- Studio playback clock, video/audio sync, and source/proxy switching.
- Playback-proxy eligibility, cache keys/invalidation, and preview-still timing.
- Export filter-graph order and encoder behavior in `export/studio_encoder.py`.
- The `/studio` server view model and the `data-*` contract consumed by `studio.js`.
- Studio persistence setters in `db/__init__.py` and the `effect_settings` JSON.
- Rescan/data-loss behavior and migrations.
- Long-running export/scan job cancellation and file publication.

The current Studio frontend is one large `studio.js` IIFE. Read
[`docs/STUDIO_MODULES.md`](docs/STUDIO_MODULES.md) before moving code or adding
another cross-feature dependency.

## Commands

Python (3.11+; CI uses 3.12):

```bash
pip install -r requirements.txt
pip install -e ".[dev]"
ruff check .
mypy src packaging/itch_channel.py packaging/windows_third_party.py
pytest --ignore=tests/test_pr_journey_smoke.py
pytest tests/test_pr_journey_smoke.py
```

JavaScript checks (Node 22.13+; optional for runtime work, required for new
Studio modules):

```bash
npm ci
npm run lint:js
npm run format:check
npm run test:js
```

`npm run check:js` runs all three. The current JS lint/format scope is new
modules under `src/orga_drone/static/js/studio/` and `tests/js/**/*.test.js`.
The legacy `studio.js` monolith is not mass-formatted. Do not run
`npm audit fix --force`; known advisories are dev-only (see `CONTRIBUTING.md`).

Windows packaging is documented in [`packaging/README.md`](packaging/README.md).
Do not add release steps to pull-request CI.

## Definition of done

1. Implement only the approved issue and its explicit non-scope.
2. Inspect the existing implementation first; preserve compatibility.
3. Add or update focused tests (Python and JS where the change belongs).
4. Update docs when behavior, setup, or architecture changes.
5. Update DE and EN strings for user-visible text.
6. Run the required checks above and report evidence in the PR.
7. Avoid unrelated refactors, drive-by formatting, or speculative architecture.
8. Follow the PR template and keep the implementation/review roles separate.

## Workflow and gates

GitHub issues and pull requests are the handoff boundary. The canonical state
machine is [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md).

- **PM** (`product-spec-reviewer`): read-only; validates problem, user,
  milestone fit, smallest slice, acceptance criteria, non-scope; returns
  `PM_APPROVED`.
- **UX** (`product-ux-designer`): read-only; required for meaningful UI work,
  skipped for simple fixes, backend-only work, CI/tooling, and migrations
  without user-facing impact. UX does not create implementation issues.
- **CTO** (`engineering-planner`): read-only; validates architecture,
  compatibility, data/migration impact, performance, security, tests; returns
  `CTO_APPROVED` before `ready-for-dev`.
- **Developer**: implements only the approved issue and runs the checks. A human
  may explicitly waive a gate; do not waive it yourself.
- **Independent review** (`implementation-reviewer`): read-only; never fixes
  its own findings; returns `REVIEW_APPROVED`, `REVIEW_CHANGES_REQUESTED`, or
  `REVIEW_ARCHITECTURE_CONCERN`.
- **Human Product Owner**: realistic product test and final merge decision.

Do not automate the human product test or merge decision. After three
developer/reviewer correction loops, escalate to the human.

## Writing and communication

Documentation and UI copy stay precise, technically credible, understandable to
non-experts, and free of hype or empty AI terminology. State what exists today
and what is planned. Follow [`docs/UX_WRITING.md`](docs/UX_WRITING.md) for
user-visible text.

## Agent-written artifacts

Write **pull request titles and bodies, commit messages, issue comments, docs
updates, and release notes drafted by agents in English**. User-facing chat may
use the human's language (for example German). That preference does not apply
to repository artifacts.

## Canonical project docs

| Topic | Path |
|---|---|
| Product vision and honest limitations | `docs/PRODUCT_VISION.md` |
| Roadmap and status labels | `docs/ROADMAP.md` |
| Current architecture | `docs/ARCHITECTURE.md` |
| Studio frontend target modules | `docs/STUDIO_MODULES.md` |
| Agent workflow and roles | `docs/AGENT_WORKFLOW.md` |
| PR end-to-end checks | `docs/PR_E2E.md` |
| Decisions | `docs/decisions/` |
| User help | `docs/user/` |
| Packaging and release procedure | `packaging/README.md` |
| Release security and repository settings | `docs/RELEASE_SECURITY.md` |
| Agent roles and gates | `docs/AGENT_WORKFLOW.md` |

## Do not

- Do not implement unapproved features, speculative platform scope, or
  "while we are here" refactors.
- Do not change the SQLite schema or `effect_settings` shape without an ADR and
  migration plan.
- Do not modify, copy over, or delete source media or exports.
- Do not commit private media, SRT files, coordinates, secrets, or `.env`.
- Do not add a framework, bundler, plugin system, cloud dependency, or AI claim.
- Do not mass-format legacy files or mix refactoring into feature PRs.
- Do not commit, push, tag, release, or merge unless the human explicitly asks.
- Do not describe `Later`/vision items as available.
