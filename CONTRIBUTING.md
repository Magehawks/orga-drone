# Contributing to orga-drone

Thanks for helping improve this local drone media library. Contributions of code, docs, translations, and bug reports are welcome.

## Before you start

- Search [existing issues](https://github.com/Magehawks/orga-drone/issues) to avoid duplicates.
- For larger changes, open an issue first so we can align on scope.
- Keep changes focused — small PRs are easier to review.

## Development setup

Requirements: **Python 3.11+**

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

See [README.md](README.md) for runtime options, packaging notes, and feature overview.

## Tests

Run the full suite from the repo root:

```bash
pytest
```

Add or update tests when you change parsing, indexing, search, or API behavior. Tests live under `tests/`.

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

Pull requests run GitHub Actions CI (`CI` workflow, Python 3.12) with:

```bash
ruff check .
mypy src
pytest
```

Install the same tooling locally via `pip install -e ".[dev]"`. Configuration lives in `pyproject.toml`.

## Pull requests

1. Branch from `master` (default branch).
2. Keep commits readable; squash locally if you prefer one commit per PR.
3. Update docs when behavior or setup changes.
4. Confirm `ruff check .`, `mypy src`, and `pytest` pass before opening the PR.
5. Fill in the PR template (summary, test plan).

**Style:** Match existing code in the touched files — naming, typing, and structure. No drive-by refactors in the same PR unless required.

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
