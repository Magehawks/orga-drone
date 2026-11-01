# Release Security and Repository Automation

This document records who may publish Orga Drone builds, which GitHub settings
must back that rule, and which automations are intentionally absent. It
complements [`packaging/README.md`](../packaging/README.md) and ADR
[0031](decisions/0031-manual-release-and-local-agent-config.md).

## Publication rule

Only a human repository maintainer may publish a release. Agents and normal
repository events must not publish.

- A GitHub Release is created and published manually in the GitHub UI, after
  the Mark-of-the-Web smoke test in [`packaging/README.md`](../packaging/README.md).
- Windows binaries are never attached to a GitHub Release. GitHub Releases stay
  notes-only; the Windows zip is an Actions artifact or a local build.
- itch.io uploads are a manual butler step run by the maintainer on the
  maintainer's machine. No workflow runs butler and no workflow holds an itch.io
  API key.
- Intended approver: a repository admin or a maintainer with write access and
  the protected `release` environment (when that environment is configured).
  For a single-maintainer repository, that is the repository owner.
- A collaborator with Actions write permission can start the manual Windows
  build. That only produces a non-publishing artifact; it does not publish.

## Automations in the repository

| Workflow | Trigger | What it can do |
|---|---|---|
| `ci.yml` | Pull request, manual dispatch, `workflow_call` from the manual Windows build | Runs Ruff, MyPy, pytest, JavaScript checks, and the App journey smoke. Read-only token. No secrets. No release, upload, or notification step. |
| `windows-release.yml` | `workflow_dispatch` only | Builds the onefolder zip and uploads it as a non-publishing Actions artifact for 30 days. It does not create or edit a GitHub Release, does not upload to itch.io, and does not post to Discord. |

Disabled or removed:

- Tag pushes (`v*.*.*`) no longer start a build or open a draft GitHub Release.
- The automatic draft-release job was removed from the Windows build workflow.
- The `release: published` Discord notice workflow
  (`itch-test-channel-notice.yml`) was deleted.
- No workflow runs butler, posts a webhook, or uses `workflow_run`,
  `repository_dispatch`, or a release-event trigger.

## Required GitHub repository settings

Repository files cannot restrict a maintainer who has write or admin access.
Configure these settings in addition to the files:

1. **Actions permissions** (Settings → Actions → General):
   - Set the default `GITHUB_TOKEN` permission to read-only repository
     contents.
   - Disable “Allow GitHub Actions to create and approve pull requests”.
   - Keep the workflow allow-list policy narrow if the repository uses one.
2. **Release and tag protection** (Settings → Rules or Rulesets):
   - Protect `main`: require a pull request and passing CI before merge.
   - Protect `v*` tags, or restrict tag creation to release maintainers. A tag
     must not build or publish anything on its own.
   - Restrict GitHub Release creation and editing to the release maintainer
     role where the plan supports it, or to repository admins.
3. **Protected `release` environment** (Settings → Environments), when a
   manual release job is ever added:
   - Require reviewers before deployment.
   - Limit deployment branches and tags to `main` and `v*`.
   - Store release credentials as environment secrets, never as repository
     secrets that every workflow can read.
4. **Secrets** (Settings → Secrets and variables):
   - Delete `DISCORD_RELEASE_WEBHOOK` after the Discord workflow is removed.
   - Do not store itch.io API keys, code-signing keys, or release tokens as
     repository or organization secrets for PR workflows. Keep local
     credentials on the maintainer machine.
   - Fork pull requests must not receive release secrets. Keep release secrets
     in a protected environment so they are unavailable to `pull_request`
     runs.
5. **Environment and branch rules for agents**: do not give automation tokens
   permission to create tags, publish releases, or approve deployments.

## What repository files can and cannot guarantee

The workflow changes remove accidental publication from pushes, pull requests,
merges, and tags. They do not stop a repository admin from running a manual
workflow, editing a workflow file on a branch, or publishing a release by
hand. That residual access is deliberate: a human maintainer must still be able
to release. Branch protection, tag protection, environment reviewers, and
scoped secrets are what keep that access limited to the intended maintainer.

## Verification

A reviewer can confirm the repository side of this policy:

```bash
git ls-files .cursor
git grep -n "DISCORD_RELEASE_WEBHOOK" -- .github
git grep -n "gh release" -- .github
git grep -n "^on:" -- .github/workflows
pytest tests/test_repository_automation.py
```

Expected: no tracked `.cursor` files, no Discord webhook use, no release
commands in workflows, and only the intended workflow triggers. The test
`tests/test_repository_automation.py` enforces the release and notification
guard.
