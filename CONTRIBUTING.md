# Contributing to orga-drone

Thanks for helping improve this local drone media library. Contributions of code, docs, translations, and bug reports are welcome.

## Before you start

- Search [existing issues](https://github.com/Magehawks/orga-drone/issues) to avoid duplicates.
- For larger changes, open an issue first so we can align on scope.
- Keep changes focused — small PRs are easier to review.
- Never commit secrets, `.env` files, private media, SRT files, flight logs, or
  screenshots with people, homes, or precise locations. Tests and docs use
  synthetic fixtures or the existing sanitized samples.

## User needs

To describe a concrete problem — your own, or one you observed elsewhere — use the **User need** issue template.

- **Direct feedback** is about your use of Orga Drone.
- **External research** is evidence about someone else's pain point. It is not a feature request from that person.

Do not attach photos, videos, flight logs, or screenshots that show people, homes, or precise locations. Opening a user-need issue does not add a public roadmap item.

Labels, the monthly triage, and how accepted work is linked to release notes: [`docs/USER_NEEDS.md`](docs/USER_NEEDS.md).

## Development setup

Requirements: **Python 3.11+**. Node **22.13+** is optional for running the
application and required only for the JavaScript checks.

```bash
git clone https://github.com/Magehawks/orga-drone.git
cd orga-drone
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -e ".[dev]"
cp .env.example .env   # optional
python -m orga_drone
```

See [`docs/user/`](docs/user/) for usage, [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the current technical shape, and [`packaging/README.md`](packaging/README.md)
for Windows builds.

## Find your area

| Change | Start here |
|---|---|
| Library scan, metadata, flows, sessions | `scan/`, `parse/`, `group/`, `db/` |
| Browse, filters, detail page | `app.py`, `templates/`, `static/js/browse.js`, `static/js/detail-*.js` |
| Studio timing, cut, speed, repeat | `studio_cut.py`, `studio_speed.py`, `studio_transition.py`, `studio_estimate.py` |
| Studio color, LUT, HSL, wheels | `studio_image.py`, `studio_hsl.py`, `studio_color_wheels.py`, `studio_lut.py` |
| Studio preview and playback proxy | `studio_preview_frame.py`, `studio_playback_proxy.py` |
| Studio export | `studio_export.py`, `export/` |
| Studio frontend / inspector / timeline | `static/js/studio.js`, `templates/studio.html`, `docs/STUDIO_MODULES.md` |
| Desktop shell and Windows packaging | `desktop.py`, `packaging/` |
| UI strings | `src/orga_drone/locales/`, template `data-*` messages |
| Tests | `tests/`, `tests/js/` |

Coding agents should read [`AGENTS.md`](AGENTS.md) first. The Studio frontend
target modules and dependency rules are in
[`docs/STUDIO_MODULES.md`](docs/STUDIO_MODULES.md).

## Tests

Run the full Python suite from the repo root:

```bash
pytest
```

Add or update tests when you change parsing, indexing, search, API, or Studio
behavior. Python tests live under `tests/`; JavaScript module tests live under
`tests/js/` and are run by `npm run test:js`.

### Manual check: Browse memory (large libraries)

Browse paginates media cards (default 48 per page) and unloads off-screen
thumbnails in `static/js/thumbs.js`. After changing Browse DOM or thumbnail
loading, verify manually when possible:

1. Open a library with hundreds+ of items in the desktop WebView2 shell (or browser).
2. Open **Browse**, scroll the first page, then move through several pages.
3. In Task Manager, watch the **WebView2 / msedgewebview2** process (not only Python):
   memory should plateau near a page’s worth of decoded thumbs, not climb linearly
   through the whole library as you keep paging/scrolling.
4. Leave Browse for the Dashboard; DOM/images for that page should be released.
5. Confirm filters/sort still work and thumbs reappear when scrolling back into view.

This is best-effort (Chromium may keep HTTP cache entries); the hard guarantee is
bounded DOM size via pagination.

## Quality checks (local and CI)

Pull requests run GitHub Actions CI (`CI` workflow, Python 3.12 and Node 22) with three checks.

Python:

```bash
ruff check .
mypy src packaging/itch_channel.py packaging/windows_third_party.py
pytest --ignore=tests/test_pr_journey_smoke.py
pytest tests/test_pr_journey_smoke.py
```

The last Python command is the **App journey smoke** check (synthetic photo, temporary data directory). A local `pytest` runs that file together with the rest of the suite. What the check covers, and what a person still clicks, is in [`docs/PR_E2E.md`](docs/PR_E2E.md).

JavaScript (Node 22.13+):

```bash
npm ci
npm run lint:js
npm run format:check
npm run test:js
```

`npm run check:js` runs all three JavaScript checks. The current lint and format scope is new modules under `src/orga_drone/static/js/studio/` and `tests/js/**/*.test.js`. The legacy `studio.js` monolith stays out of scope until it is split. New modules use ES modules; no bundler is required.

`npm audit` may report moderate advisories in the dev-only ESLint dependency tree (currently `minimatch`). They do not affect the shipped application, which has no npm runtime dependencies. Do not run `npm audit fix --force`; it would downgrade ESLint across major versions.

Install the Python tooling locally via `pip install -e ".[dev]"` (configuration in `pyproject.toml`). Install the JavaScript tooling via `npm ci` (configuration in `eslint.config.js` and `.prettierrc.json`).

Windows build candidates come from a separate **Manual Windows build**
workflow (`workflow_dispatch` only). It does not run on pull requests, merges,
or tag pushes, and it never publishes a release, uploads to itch.io, or posts a
notification. Procedure, checksum, manual release, and rollback:
[`packaging/README.md`](packaging/README.md). Publication limits and required
repository settings: [`docs/RELEASE_SECURITY.md`](docs/RELEASE_SECURITY.md).

## Architecture and refactoring rules

- Prefer small modules in existing package areas. Do not add a generic
  `utils/` bucket or a new top-level framework.
- New Studio frontend modules use ES modules and follow
  [`docs/STUDIO_MODULES.md`](docs/STUDIO_MODULES.md): one responsibility per
  module, explicit imports, no cross-module DOM writes.
- Do not add a bundler, React/Vue/Svelte, or a TypeScript migration.
- Do not change the SQLite schema or `effect_settings` shape without an ADR and
  migration plan.
- Keep source media and existing projects compatible. Studio and exports are
  additive references.
- Do not mix refactoring with feature work. Behavior-neutral extraction PRs say
  so in the summary and name their regression checks.
- Playback, proxy/cache, audio sync, and export color-order code need a
  dedicated issue and a regression plan before structural changes.

## Pull requests

1. Branch from `main` (default branch).
2. Keep commits readable; squash locally if you prefer one commit per PR.
3. Update docs when behavior or setup changes.
4. Confirm `ruff check .`, `mypy src packaging/itch_channel.py packaging/windows_third_party.py`, `pytest`, and `npm run check:js` pass before opening the PR.
5. Fill in the PR template (summary, test plan).

**Style:** Match existing code in the touched files — naming, typing, and structure. No drive-by refactors in the same PR unless required.

**Refactoring / maintenance PRs:** state that the change is behavior-neutral,
name the public interface or module boundary being introduced, list the
regression tests, and describe how to roll the PR back. Do not mass-format
legacy files.

**i18n:** UI strings use JSON + `.po` locales under `src/orga_drone/locales/`. Add or update both DE and EN when you change user-visible text.

## What we are looking for

- DJI / generic media metadata parsers
- Bug fixes with a clear repro
- Tests and docs
- Translations (new locale files welcome)

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be respectful in issues and reviews.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).

**DRAFT — not in effect.** [ADR 0024](docs/decisions/0024-licensing-model-proposal.md) proposes a future model for official Windows builds. That proposal is not adopted. Contributions are still accepted under MIT. Published tags `v1.1.0` through `v2.0.0` stay MIT.
