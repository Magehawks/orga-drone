# Proposed develop/main strategy and migration runbook

**Status: proposed; not activated.** This is the documentation-only PR A for
[#261](https://github.com/Magehawks/orga-drone/issues/261). It does not complete
that issue or authorize the operational steps below. `main` remains the default
branch and current contribution target until a separately approved cutover.

The goal is rapid integration without treating unverified changes as release-ready.
No application architecture, source media, project format, or database changes
are required. Keep the existing workflows and human review roles; introduce no
merge queue, generalized release framework, or automatic publication on merge.

## Current-state audit

Snapshot: **2026-11-04**, remote `main` at
`8c2f78302f669208fb1f50d934de292b51ae819b`. Recheck settings and SHAs at cutover;
this snapshot is evidence, not a permanent assertion about live GitHub settings.

- The repository is public; `main` is the default and `develop` does not exist.
- The [main branch API](https://api.github.com/repos/Magehawks/orga-drone/branches/main)
  reports `protected: false`, protection disabled, and no required checks.
- The active [Protect master ruleset](https://github.com/Magehawks/orga-drone/rules/19249114)
  targets only `refs/heads/master`. Its deletion, non-fast-forward, and update
  restrictions do not protect `main`. It includes an always-on administrator bypass.
- Repository auto-merge is disabled. Merge commits, squash merges, and rebase
  merges are enabled. No merge-queue rule appeared in the returned rulesets.
- The detailed classic branch-protection endpoint returned `403: Resource not
  accessible by integration`. An administrator must verify effective rules,
  bypasses, and merge settings in GitHub; absence of accessible admin data is not
  proof that every possible setting was audited.

Workflow references below are pinned to the audited commit:

- [CI, lines 3-6](https://github.com/Magehawks/orga-drone/blob/8c2f78302f669208fb1f50d934de292b51ae819b/.github/workflows/ci.yml#L3):
  `pull_request` without a base-branch filter, `workflow_dispatch`, and
  `workflow_call`. No push trigger. Jobs are **Ruff, MyPy and unit tests**,
  **JavaScript lint, format and tests**, and **App journey smoke**. Permissions
  are `contents: read`. It does not hardcode `main` as a development target.
- [Windows release, lines 10-16](https://github.com/Magehawks/orga-drone/blob/8c2f78302f669208fb1f50d934de292b51ae819b/.github/workflows/windows-release.yml#L10):
  manual dispatch or a push of a `v*.*.*` tag. Version verification and reusable CI
  precede Windows packaging. The ZIP, checksum, and `release-build.txt` are Actions
  artifacts retained for 30 days. A tag build creates notes-only draft release
  notes; it does not publish or attach Windows binaries. Only the draft job has
  `contents: write`. There is no validated-main ancestry/approval gate: version
  matching alone does not establish release readiness.
- [itch.io test channel notice, lines 9-11](https://github.com/Magehawks/orga-drone/blob/8c2f78302f669208fb1f50d934de292b51ae819b/.github/workflows/itch-test-channel-notice.yml#L9):
  `release: published` can send a Discord notice using a configured webhook.
  It does not run Butler or upload to itch.io. Its `blob/main/README.md` fallback
  is a release-documentation link, not a development trigger.

Ordinary branch creation and merges do not trigger Windows packaging or release
publication in these workflows. Manual dispatch, version tags, and publishing an
existing draft are separate actions with side effects and must be frozen during
cutover. Changing the default also affects workflow discovery/manual dispatch and
default-dependent integrations; verify these rather than assuming branch filters
are the only dependency.

Development assumptions to update at cutover:

- [CONTRIBUTING.md](../CONTRIBUTING.md#pull-requests) explicitly says to branch
  from `main`; retain that instruction until cutover.
- [PR_E2E.md](PR_E2E.md) describes stacked PRs inheriting CI from `main`.
- [packaging/README.md](../packaging/README.md#version-and-tag-procedure) needs
  the validated-promotion step before tagging, once that step exists.
- Preserve historical `main` references in release reports and ADRs. Do not
  replace release links with `develop` merely because it becomes the default.

## Proposed branch rules

### develop: rapid integration

- Become the default branch and normal feature/fix PR target after cutover.
- Require PRs and human merge decisions; prohibit deletion and force pushes.
- Run the three existing CI checks on PRs and pushes to `develop`. This push
  coverage is a later workflow change, not behavior implemented by this document.
- Treat those checks as informational for integration. A maintainer may merge
  failing checks with an explicit reason and linked repair issue. `develop` may
  temporarily be broken and must not be described as release-ready.
- Preserve the [PM/CTO, independent review, and human gates](AGENT_WORKFLOW.md).
  Informational CI is not a waiver of review or the human merge decision.
- Do not expose publication credentials or add publication jobs to this lane.

### main: validated release candidates

- Use an explicit `refs/heads/main` rule, not a default-branch selector that
  would move to `develop`. Block direct pushes, deletion, and force pushes.
- Require PRs, resolved review conversations, approval applicable to the current
  candidate, and validation against the latest base. No routine admin/bot bypass.
- Admit only same-repository `develop` promotions or explicitly documented
  emergency hotfixes. A branch name or label alone is not authorization.
- Keep auto-merge disabled and do not enable a merge queue. Use merge commits
  for permanent-branch promotions to retain ancestry; avoid squash/rebase
  promotions. Normal feature PR merge style need not change.
- Require the existing check names exactly: **Ruff, MyPy and unit tests**,
  **JavaScript lint, format and tests**, and **App journey smoke**.
- Also require two **proposed, not yet available** check contracts:
  **Main admission policy** for promotion/hotfix eligibility and human evidence;
  **Release candidate gate** for packaged validation and remaining manual checks.
  Later implementation must verify their actual GitHub contexts and producing
  app before configuring required checks.

The aggregate gate must explicitly require successful component results. Missing,
skipped, cancelled, timed-out, expired, or failed evidence is not success. Do not
use a skipped conditional job as proof of validation. Changes to gate workflows
need independent review; gate code in a PR is not its own authorization.

The maintainer must select an enforceable human approval mechanism and confirm
an eligible independent approver or explicitly approved alternative exists.
Protect that mechanism from routine bypass. Until #262 delivers and demonstrates
the gate, **keep promotions blocked**; do not substitute the current journey
smoke or claim that copying `main` to `develop` validates the starting baseline.

## Promotion and emergency hotfix process

1. Prepare a reviewable `develop` to `main` candidate PR. Record the intended
   release scope and freeze its candidate while validating; new integration
   commits require refreshed validation rather than silently joining the release.
2. Record the head and base SHAs, tested commit and tree, workflow run/attempt,
   artifact ID, ZIP SHA-256, version, automated coverage/results, and human smoke
   evidence. Any changed head/base invalidates approval for the old candidate.
3. Under #262, build the packaged app once and test that artifact. Complete the
   mandatory Windows/MOTW and remaining product checks on the same ZIP identity.
   The human Product Owner still decides whether to merge.
4. Use a merge commit. GitHub's temporary PR merge SHA may differ from the final
   `main` SHA: #262 must verify and record their exact tree/commit mapping. A tree
   mismatch invalidates evidence. #263 must reject missing mappings and reuse
   the original validated artifact, never silently rebuild it for distribution.
5. Merging is not publication. Only a separately approved release procedure may
   authorize a version tag and distribution under the policy below.

For an emergency hotfix, branch from `main`, link an emergency issue documenting
urgency, narrow scope, and human authorization, then use a reviewed PR to `main`.
Require the same checks, packaged validation, and manual gates; emergency status
does not waive them. Back-merge `main` into `develop` promptly through a PR,
resolve any conflicts explicitly, and rerun affected checks. Do not release from
an unvalidated hotfix branch or treat merge approval as release approval.

## Existing PR #256

At the audit, [#256](https://github.com/Magehawks/orga-drone/pull/256) was the only
open PR. It targets `main`, has auto-merge off, and its head is
`df86d2a157a6baef85de0451da48b4726426eccc`. All three CI checks passed on that head;
GitHub reported merge conflicts. [#255](https://github.com/Magehawks/orga-drone/issues/255)
records independent approval; the human product test is still pending. Its
reported WebView2 smoke is feature-specific evidence, not certification of a
packaged release artifact or MOTW behavior.

Leave #256 targeted at `main` in this PR. At cutover, record an explicit
maintainer/author decision before any retarget to `develop`; changing the default
is not consent to retarget. The normal proposed destination is `develop`, not an
exception allowing an ordinary feature to bypass the new `main` policy.
After an authorized retarget or base update, inspect the new diff, resolve conflicts
in separate implementation work, rerun checks, renew affected independent review,
and complete the pending human product test. Previous green checks and approval
do not certify the changed candidate. If no decision exists, keep it pending.

## Test and release dependencies

**Existing App journey smoke:** `tests/test_pr_journey_smoke.py` uses FastAPI
`TestClient`, temporary data, and a generated JPEG. It exercises routes, scanning,
Browse/search/detail, basic Studio create/add/clear, and other app pages. It also
includes `test_scan_story_export_real_mp4`: a synthetic JPEG/PNG HTTP journey
with actual FFmpeg MP4 export, full decode, and source-integrity/source-loss
checks. That test skips when FFmpeg is unavailable. Neither path launches the
packaged EXE or WebView2, operates native dialogs, or proves desktop playback,
rendered LUT fidelity, packaged export, or MOTW behavior. See [PR_E2E.md](PR_E2E.md).

**#262: packaged Windows validation** owns a demonstrably executed packaged-app
E2E path, wider import/edit/persistence/preview/export coverage, fail-closed
results, artifact identity/retention, diagnosis/reruns, and runner feasibility.
Verify public-repository runner availability/billing; do not assume paid minutes
or introduce a self-hosted runner without a security assessment. Explicitly list
coverage gaps. The mandatory [MOTW checklist](../packaging/README.md#why-motw-matters)
and human product decisions remain; mocks and TestClient passes cannot replace
them. #261 defines the admission contract; it does not implement #262.

**#263: deliberate release routing** depends on #261 and #262. It owns tag
authorization, validated artifact lookup/reuse, checksum/version verification,
dry-run, retries, partial-failure recovery, and approved distribution routing.
An approved tag must identify a validated `main` commit; tag/version matching
alone must not bypass approval. Expired or missing artifacts require a newly
validated candidate, not a silent rebuild. No release on develop integration or
ordinary main merge. No publication implementation belongs in PR A.

### Unresolved publication-policy conflict

Current binding policy in [AGENTS.md](../AGENTS.md#security-privacy-and-release-safety)
and [packaging/README.md](../packaging/README.md) retains notes-only GitHub Releases,
no Windows binary attachments, maintainer MOTW approval, and no agent release
publication. [The itch.io procedure](../packaging/itch/README.md) requires
Draft/Restricted visibility; `packaging/itch_channel.py` only prints commands.

Historical [ADR 0012](decisions/0012-windows-release-workflow.md) and #79 mention
attached draft ZIP assets, unlike the current workflow and packaging policy.
[ADR 0013](decisions/0013-itch-windows-channel.md) excludes CI Butler execution.
#263 requests GitHub/Butler publication automation, potentially conflicting with
these limits. Do not interpret it as approval to attach binaries, enable CI
Butler, make itch.io public, or let agents publish. Preserve current policy until
the maintainer explicitly approves and documents any change, including updated
decision records. This runbook records the conflict; it does not resolve it.

## Ordered implementation boundaries

1. **PR A (#261):** this proposed policy, dated audit, and migration/rollback
   runbook, with links from existing contributor/workflow docs. Documentation only.
2. **Later #261 PR:** minimal CI/admission safeguards and their focused tests.
   Preserve existing checks and release behavior; deny promotions until #262 is
   available. Do not rewrite all workflows in the same PR.
3. **#262 PR(s):** packaged validation, evidence, and an enforceable main gate,
   without release creation or distribution uploads. Demonstrate actual execution.
4. **Separate maintainer-approved cutover:** perform and record the runbook below.
5. **#263 PR(s):** first a no-publication/no-upload dry-run, then only publication
   behavior explicitly allowed by an approved policy decision. Reuse the artifact.

Each implementation PR follows the existing PM/CTO and independent review rules;
CI/tooling needs no UX gate. This document supplies no blanket approval for later
PRs, GitHub administration, product tests, merges, tags, or publication.

## Migration runbook (future authorized action only)

1. Announce a short merge, tag, manual-dispatch, publication, and Butler freeze.
   Capture branch SHAs, effective rules/bypasses, default/merge settings,
   workflow enabled states, active runs, artifacts/drafts, and every open PR's
   target. Resolve or stop active release jobs explicitly before cutover.
2. Temporarily disable Windows release and release-notice workflows in GitHub
   settings; leave CI enabled. Do not publish a draft, dispatch a build, push a
   version tag, or execute Butler as a migration test. Preserve recorded states.
3. Complete the preparatory PRs through normal review. Re-read remote `main`;
   create `develop` at that exact current HEAD and record the SHA. Preserve history.
4. Install explicit main/develop rules before changing the default. Correct the
   ineffective master-only protection deliberately; do not copy its update block
   and always-on bypass blindly. Keep main closed until #262 gates are proven.
5. Change the default to `develop`. Update current contribution/stack instructions
   and verify PR defaults, default-dependent rules, workflow discovery/dispatch,
   and external integrations. Inventory integrations inaccessible to this audit.
6. Record the decision for #256 and every other open PR; retarget none silently.
7. Demonstrate that ordinary feature-to-main PRs and failed, missing, skipped,
   stale, or bypassed evidence cannot enter main. Verify develop integration is
   informational and produces no release, upload, or Discord notice. Record the
   configuration and check contexts; do not weaken rules to get a green demo.
8. Re-enable release workflows only after an explicit review confirms their
   retained triggers and safeguards are safe. Record who approved resumption;
   no version tags or publication are part of cutover verification.

### Rollback

- Freeze publication first; inspect active jobs and drafts before changing settings.
- Restore `main` as default if necessary, retaining explicit main protection.
  Do not restore the unprotected baseline or reopen bypasses merely for convenience.
- Revert migration code/docs through reviewed PRs. Preserve `develop` and its
  integrated commits; never reset, force-push, or delete branch history.
- Reverse any authorized PR retarget only with another explicit agreement and
  diff/check review. Do not discard work or assume old approvals remain current.
- Restore recorded workflow/settings states deliberately after safety review.
  Do not move or reuse version tags. Accidental publication is a separate
  maintainer incident using existing release recovery procedures, not branch rollback.

## Maintainer decisions before activation

- Approve cutover timing, effective rules/bypasses, exact required check contexts,
  and the human approval mechanism/eligible approver. Confirm admin-only settings
  and external/default-dependent integrations that this audit could not inspect.
- Approve any #256 retarget and renewed review/test handoff.
- Accept demonstrated #262 coverage, artifact retention, identity mapping, and
  explicitly remaining manual checks before admitting promotions.
- Resolve #263's publication-policy conflict explicitly before changing routing,
  credentials, tag permissions, attachment policy, Butler automation, or visibility.
- Keep auto-merge disabled and do not introduce a merge queue in this migration.
