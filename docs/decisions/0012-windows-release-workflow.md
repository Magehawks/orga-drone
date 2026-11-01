# ADR 0012: Windows release workflow with a draft publish gate

- **Status:** Superseded by [ADR 0031](0031-manual-release-and-local-agent-config.md)
- **Date:** 2026-10-23
- **Deciders:** Issue #79

> Historical record. ADR 0031 removes the tag trigger and the automatic draft
> GitHub Release. The Windows workflow is now manual-only, builds an Actions
> artifact, and never publishes. See `docs/RELEASE_SECURITY.md`.

## Context

Windows builds were produced locally with PyInstaller and uploaded by hand as
`orga-drone-windows-x64.zip`. Pull-request CI ran Ruff, MyPy, and pytest, but
did not build a binary. A browser-downloaded zip also has to pass the
Mark-of-the-Web smoke test in `packaging/README.md` before it is safe to call
public; a green `dist/` launch does not carry that stamp.

The maintainer needs a repeatable GitHub Actions build of the existing
onefolder layout, downloadable before publication, with a human approval step.
This is not an in-app updater, an installer, or a store deploy.

## Decision

1. `.github/workflows/windows-release.yml` builds `packaging/orga-drone.spec`
   on `windows-latest` (Python 3.12, PyInstaller 6.22.3 pinned in the
   workflow). Output remains onefolder: `orga-drone.exe` + `_internal/`,
   zipped as `orga-drone-windows-x64.zip` with a SHA256 file.
2. The workflow runs only on `workflow_dispatch` and on `v*.*.*` tags. It does
   not run on pull-request merge. It calls `.github/workflows/ci.yml`
   (`workflow_call`) and packages only after Ruff, MyPy, and pytest pass.
3. `packaging/verify_release_version.py` fails the run unless `pyproject.toml`
   `project.version` is `X.Y.Z`, `__version__` matches it, and (on a tag) the
   tag is exactly `v{version}`. A mismatch skips packaging and release
   creation.
4. A matching tag opens a **draft** GitHub Release and attaches the zip and
   checksum. The job checks the release is still a draft. Re-runs may replace
   assets on an existing draft and must refuse an already public release.
   `workflow_dispatch` uploads the Actions artifact only.
5. Publishing the draft is a maintainer action after the MOTW checklist
   (browser download, Explorer extract into a parentheses path, native window,
   pickers, 1080p export, persistence), with SHA256, commit, date, and outcome
   recorded in the release notes. The local PyInstaller commands stay as a
   fallback. Workflow permissions stay read-only except `contents: write` on
   the draft job and `actions: write` on the upload job. Third-party actions
   are pinned to commit SHAs. Binaries are not committed.

## Alternatives considered

1. Publish the GitHub Release as soon as the tag build succeeds — rejected.
   The MOTW smoke test cannot be skipped, and a green Actions run is not that
   test.
2. Onetile / onefile PyInstaller, Electron, or Tauri — rejected. The shipping
   desktop layout is the onefolder zip.
3. Attach the zip from a pull-request workflow — rejected. Merging must not
   publish, and PR artifacts are the wrong publication gate.

## Consequences

- Positive: the maintainer can download a candidate built from a known commit
  and publish it without rebuilding the exe locally. A wrong tag cannot open
  a release.
- Negative / trade-offs: Actions artifact downloads are wrapped in an outer
  zip; the draft release asset is the file to smoke-test for publication.
  Draft assets need a signed-in browser session. The Windows runner build is
  slower than the Ubuntu quality job. PyInstaller is pinned only in the
  workflow; the local fallback still installs current PyInstaller.
- Follow-up work: code signing, MSIX, and macOS/Linux release builds stay out
  of scope.
