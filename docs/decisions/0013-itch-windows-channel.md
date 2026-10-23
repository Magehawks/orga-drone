# ADR 0013: itch.io Windows channel via butler

- **Status:** Accepted
- **Date:** 2026-10-23
- **Deciders:** Issue #82

## Context

Windows users who install a convenience build need a way to receive a newer
build without a custom updater inside Orga Drone. The application already
keeps the library, Studio projects, and settings in `%APPDATA%\orga-drone`,
outside the PyInstaller onefolder. GitHub Release zips do not update those
installs in place.

The Windows release workflow (ADR 0012) builds a draft GitHub Release. The
manual Mark-of-the-Web smoke test in `packaging/README.md` is still the
publish gate.

## Decision

1. Publish the existing Windows x64 onefolder with [butler](https://itch.io/docs/butler/),
   not with an in-app downloader, patcher, or auto-updater.
2. The first uploads go to a Draft or Restricted itch.io project, on the
   channel `windows-x64-test`, and the first push uses `--hidden`. A public
   paid launch is refused by `packaging/itch_channel.py`. The tool prints a
   butler command and does not run it.
3. Version A is the known stable GitHub Release **1.9.0** (`9eb28b0`,
   recorded zip SHA256). Version B is userversion **1.10.0** and is only the
   later build that contains image correction and timed overlays. Current
   `main` still reports `1.9.0` and does not contain timed overlays, so it
   must not be uploaded as A or as B.
4. Ordering on a channel is upload order. Rolling back means pushing the
   previous onefolder to the same channel again. Copy
   `%APPDATA%\orga-drone\orga-drone.sqlite3` before an A→B test. SQLite
   upgrades are forward-only.
5. Customers who download a ZIP (itch.io website or GitHub) do not receive
   itch.io desktop-app updates. Say that on the itch.io page and in the README.
6. Do not skip the existing Windows smoke test. Do not add a CI job that
   runs butler.

## Alternatives considered

1. **Custom in-app updater** — rejected. It would duplicate the itch.io app
   and expand the update surface. Out of scope for #82.
2. **Steam or another store** — out of scope.
3. **Upload test builds to a public page** — rejected. If Draft/Restricted
   visibility is not available, stop. Do not publish the test channel publicly.
4. **Treat current `main` as Version B** — rejected. Image correction is on
   `main`, timed overlays (issue #78) are not, and the version string is still
   1.9.0, which collides with Version A.

## Consequences

- Positive: app installs can later update through itch.io; user data stays
  outside the install directory; the repo can show the exact command and
  refuse a public target.
- Negative: ZIP installs never auto-update; butler credentials stay with the
  maintainer; the live A→B install on a clean PC is still open; a forward-only
  migration in B means rollback of the app needs the copied database.
- Follow-up: run the restricted test before any public launch. The draft
  GitHub Release from ADR 0012 stays an additional gate and does not replace
  the smoke test.
