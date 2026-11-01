# ADR 0031: Manual-only releases and local-only agent configuration

- **Status:** Accepted
- **Date:** 2026-11-01
- **Deciders:** Repository maintainer

## Context

The repository tracked Cursor agent prompts and rules under `.cursor/`. Those
files are private agent configuration and duplicated the public workflow in
`docs/AGENT_WORKFLOW.md`, `AGENTS.md`, and the architecture docs.

Two workflows could act on their own:

- `windows-release.yml` started on `v*.*.*` tag pushes and created a draft
  GitHub Release.
- `itch-test-channel-notice.yml` posted to a Discord webhook after a GitHub
  Release was published.

Normal pushes, pull requests, merges, or tags must not produce Windows
releases, itch.io uploads, or Discord messages. The product is local-first, and
publication stays a human decision after the Mark-of-the-Web smoke test.

## Decision

1. `.cursor/` is no longer tracked. Local Cursor files stay on disk and are
   ignored through `.cursor/` in `.gitignore`. Shared role and gate knowledge
   lives in `docs/AGENT_WORKFLOW.md`; canonical project knowledge stays in
   `AGENTS.md` and `docs/`.
2. The Windows build workflow is manual-only (`workflow_dispatch`). It builds
   the onefolder zip and uploads an Actions artifact. It does not create
   or edit a GitHub Release, does not upload to itch.io, and has read-only
   repository permissions.
3. The tag trigger and the automatic draft-release job were removed from the
   Windows build workflow.
4. The Discord notice workflow was deleted. The `DISCORD_RELEASE_WEBHOOK`
   secret should be deleted in GitHub repository settings.
5. GitHub Releases are manual, notes-only, and created by a maintainer after
   the smoke test. Butler uploads remain a manual maintainer step.
6. The required branch, tag, environment, and secret settings are documented in
   `docs/RELEASE_SECURITY.md`. Repository files alone cannot restrict a
   maintainer with write or admin access.
7. `tests/test_repository_automation.py` guards against reintroducing automatic
   release or notification triggers.

## Alternatives considered

1. Keep tag-triggered builds and only remove the draft-release job — rejected.
   A tag push would still start a Windows build, and the trigger would remain a
   misleading publication path.
2. Keep the Discord workflow behind an empty secret — rejected. An empty secret
   is an implicit switch, not a disabled automation, and it leaves the webhook
   path in the tree.
3. Delete all of `.github/` — rejected. CI and the issue/PR templates are
   required for contributors.
4. Keep `.cursor/` tracked as documentation — rejected. It is private agent
   configuration, and its project-level content is already public in `docs/`.

## Consequences

- Positive: pushes, pull requests, merges, and tags cannot publish a release,
  upload a build, or post a notification. CI stays unchanged. Local agent
  prompts remain available to the maintainer without being committed.
- Negative / trade-offs: a maintainer must start the Windows build manually and
  create any GitHub Release by hand after the smoke test. The release process
  depends on repository settings outside git; those settings are documented,
  not enforced by the workflow files.
- Follow-up work: if a release environment is added later, it must require
  reviewers and must not expose release secrets to `pull_request` workflows.
