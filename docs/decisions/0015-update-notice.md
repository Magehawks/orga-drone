# ADR 0015: Optional published-release notice

- **Status:** Accepted
- **Date:** 2026-10-23
- **Deciders:** Issue #90

## Context

People who unzip the Windows build do not get itch.io-app updates. They still
need to see which version is installed and, if they ask, whether a newer
published Windows build exists. The app must stay fully usable offline. A
check must not download, install, poll in the background, or send library data.

The itch.io Windows channel is a draft/restricted butler process and does not
publish a comparable stable version. GitHub `releases/latest` is the public
list of non-draft, non-prerelease releases. Draft assets are absent from that
URL (`packaging/README.md`).

## Decision

1. About shows `installed_version()`, which is the package `__version__`
   already checked against `pyproject.toml`. The dialog does not keep a second
   copy of the number.
2. `check_updates` in `app_prefs.json` defaults off. Startup runs no request
   while it is off. Turning it on allows one lookup per process, on a worker
   thread, with a 4 second timeout.
3. The lookup is `GET https://api.github.com/repos/Magehawks/orga-drone/releases/latest`
   with a static `User-Agent: orga-drone`, no query string, and no body.
4. A notice appears only when that document is a stable release, its tag is
   `X.Y.Z` / `vX.Y.Z` newer than the installed version, and it contains
   `orga-drone-windows-x64.zip`. Drafts, prereleases, older tags, and a
   missing Windows zip produce no notice. Network and parse failures do the
   same. A manual check may say up to date, a new version, or that the check
   was not possible.
5. The notice and About link open
   `https://github.com/Magehawks/orga-drone/releases/latest` in the system
   browser. The client cannot supply a different URL. Nothing is downloaded
   or installed.

## Alternatives considered

1. itch.io channel API — rejected until a public channel exposes a comparable
   stable version without an API key. A draft channel must not be treated as
   a public update.
2. In-app download and replace — rejected. Out of scope, and it would be an
   updater.
3. Check on every startup by default — rejected. Offline use stays the
   default, and the request is opt-in.

## Consequences

- Positive: a ZIP install can show its version and a newer published Windows
  release without leaving the machine's library. The same GitHub publish gate
  that hides drafts also hides them from this check.
- Negative / trade-offs: the download page is the GitHub Release, not an
  itch.io page, until that page is public. GitHub may rate-limit the
  anonymous request; the app then stays quiet. One startup check is remembered
  for the process, not across restarts.
