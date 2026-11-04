# Proposed develop/main strategy and migration runbook

**Status: branch cutover proposed; not activated.** PR A documented the strategy
for [#261](https://github.com/Magehawks/orga-drone/issues/261). PR B adds push CI
and the pre-cutover denial guard described below; neither completes that issue
or authorizes the operational steps. `main` remains the default branch and
current contribution target until a separately approved cutover.

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
  coverage is configured by PR B for both `main` and `develop`; it creates no branch.
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
- **Main admission policy** is the pre-cutover guard for promotion/hotfix
  prerequisites. It requires the three CI checks and the packaged **Windows
  packaged E2E** evidence implemented by #262. A release-candidate/MOTW gate
  still does not exist; manual release checks stay separate. Verify actual
  GitHub contexts and producing app before configuring required checks.

The aggregate gate must explicitly require successful component results. Missing,
skipped, cancelled, timed-out, expired, or failed evidence is not success. Do not
use a skipped conditional job as proof of validation. Changes to gate workflows
need independent review; gate code in a PR is not its own authorization.

The approval mechanism is either an independent qualified review or the explicit
owner-authorization comment profile adopted for the solo maintainer by #262.
Protect that mechanism from routine bypass. The packaged E2E check validates the
built Windows artifact, not the manual MOTW checklist or release approval.

### PR B: implemented pre-cutover guard and administrator configuration

[`main-admission.yml`](../.github/workflows/main-admission.yml) runs on ordinary
PR events targeting `main` (open, synchronize, reopen, edit, ready for review).
Label/unlabel events also request a fresh evaluation; labels never authorize it.
It uses read-only contents/PR/check/Actions/issue permissions, no persisted checkout
credential, and executes [`packaging/main_admission.py`](../packaging/main_admission.py) from
the event's immutable **base SHA**, never from PR-head code. No dependency install,
artifact execution, release credential, or publication is involved.
The existing CI quality job type-checks the policy and runs its regression tests
with the ordinary Python suite; the three existing PR check names are unchanged.

The script reads live GitHub metadata, rechecks the PR after evidence collection,
and compares event head/base to live PR and branch tips. It diagnoses invalid or
forked sources, missing emergency documentation, stale/missing human approval,
and unsuccessful/missing checks. It lists `ci.yml` workflow runs for the exact
head and PR event, selects the newest run for this PR before evaluating success,
and verifies repository, branch, and head/base linkage. It collects jobs from
that run's explicit current attempt, then verifies their actual check-run IDs,
suite, job/run linkage, producing app, and candidate. All three named checks must
be unique, completed with `success`, and from that same verified PR run/attempt.
Skipped/neutral results do not pass. A newer queued, failed, or stale-base run
cannot fall back to an older green run. A partial CI rerun missing jobs must be
replaced by a full CI rerun; successes from earlier attempts are not borrowed.
API, permission, malformed-data, and incomplete-pagination failures deny admission.
The run/attempt, newest run, PR, and reviews are rechecked after collection.
These prerequisites still do not certify a tested merge tree or packaged artifact.

#### Real metadata validation (2026-11-04)

The read-only audit inspected all **249 available workflow runs**. SHA
`48f7c13f7bb83115ea67df13d03ee806a81a840c` has both
[PR CI run 40593212015](https://github.com/Magehawks/orga-drone/actions/runs/40593212015)
and [tag-push Windows run 40592919043](https://github.com/Magehawks/orga-drone/actions/runs/40592919043).
The commit check-runs endpoint returned the same eight records with explicit
`filter=latest` and `filter=all`, spanning three suites. The nested release CI
names differ from ordinary PR names. No same-name push/PR run of `ci.yml` was
available: permanent-branch push CI has not landed yet. Do not describe that
specific overlap as live-tested; it has synthetic regression coverage.

For PR #265's original head `39d58883a3ce6eae97fbbf3c5dd7b15b2af2dc25`, both filters
returned five checks, including two separate **Main admission policy** runs.
Thus `latest` is not a guarantee of one check per name across all runs/suites.
The collector now avoids that endpoint and filter entirely. See
[GitHub's check-runs API](https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference).

The hardened collector was also executed against the live public API for #265:
it retrieved all three successful required checks from CI run **41916224480**,
attempt **1**, suite **113586341896**, and verified their job/check linkage.
The minimized public snapshot in
[`tests/fixtures/main_admission_github.json`](../tests/fixtures/main_admission_github.json)
supports offline replay. Historical run 40593212015 now has an empty PR linkage
array and only two old check names, so it cannot certify a current candidate.
These reads triggered no workflow, release, upload, or settings mutation.

For a future hotfix candidate, document these lines in its PR body, linking an
existing issue with a nonempty problem statement in the same repository:

```text
Emergency issue: #123
Emergency reason: Explain the urgent regression.
Emergency scope: Describe the narrow fix.
```

An independent human with write/maintain/admin access must submit an approving
review on the exact head, with this exact line using full SHAs:

```text
Main admission candidate: <head SHA> <base SHA>
```

The latest decisive review from that person must still approve; bots, self-review,
dismissals, changes requested, and old head/base approvals do not qualify. This
marker binds approval to a candidate; it is not MOTW/product evidence and does not
authorize merge or publication. The current two-human precondition is not a usable
solo-owner approval profile; the operational alternative below must be chosen
before activation.

#### Minimal explicit reevaluation

There is no privileged CI-completion listener or polling service. After **every**
CI completion/rerun and review submission, edit, dismissal, or revocation, a
maintainer must add or remove a dedicated `admission:recheck` label on the PR.
An administrator may create that label separately; this PR creates none.
Both `labeled` and `unlabeled` ordinary PR events run the unconditional job, with
fresh event head/base metadata and checkout of that immutable base policy.
Any label change triggers evaluation; there is no conditional skipped-job pass.
The label's name/value is never read as approval or packaged evidence.

Alternatively, use the PR's **Main admission** run → **Re-run failed jobs**, or:

```text
gh run rerun ADMISSION_RUN_ID --repo Magehawks/orga-drone --failed
```

Verify it is the admission PR run for the intended head/base, not Windows release.
[Native reruns retain the original event SHA/ref](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs).
A changed head/base must fail stale validation; update/synchronize the candidate
and use a fresh PR event, not an old run. If CI was only partially rerun, rerun
the entire **CI** run first, then request admission reevaluation. Do not dispatch
a Windows build or use `workflow_dispatch` to manufacture an admission context.

Manual reevaluation is an explicit pre-cutover procedure, not automatic review
revocation enforcement. Admission re-reads the PR, reviews, comments, workflow
runs, artifacts, and branch tips after collection; any movement fails closed.
A changed head/base invalidates the old evidence and approval.

#### Packaged Windows E2E gate (implemented by #262)

[`windows-e2e.yml`](../.github/workflows/windows-e2e.yml) runs on every
`opened`, `synchronize`, `reopened`, or `ready_for_review` PR to `main`,
including non-promotion PRs so a skipped E2E cannot satisfy a required check. It
checks out the PR merge commit, builds the existing onefolder app once, tests the
extracted ZIP with the real WebView2 runtime, and uploads the candidate ZIP plus
a small `evidence.json` artifact for 30 days. It has no release credentials and
never publishes.

The E2E job is named exactly **Windows packaged E2E**. Admission selects the
newest run for the exact head and PR, verifies its current attempt, suite, and
job/check identity, then verifies both artifact names
`orga-drone-windows-e2e-<attempt>-<head>` and
`windows-e2e-evidence-<attempt>-<head>`, GitHub's artifact digest, non-expiry,
and run/head linkage. It downloads only the bounded evidence artifact and checks
the exact head, base, merge SHA, Git tree, run/attempt, artifact name/size/digest,
required journey set, and pass result. The E2E workflow and harness files must be
byte-identical between the PR head and base. Missing, failed, cancelled,
skipped, expired, malformed, partial-rerun, older-green, or mismatched evidence
denies admission; there is no fallback run, label, or enable flag.

The automated evidence covers startup, synthetic media import, library
navigation, Studio open, WebView2 playback, edit persistence after reload and
relaunch, a 720p packaged export with MP4 decode/order checks, and source
integrity. It does not replace the manual MOTW/native-dialog checklist in
[`packaging/README.md`](../packaging/README.md#windows-pre-release-smoke-test-mandatory)
or release approval.

#### Safe bootstrap order

1. #265 is already merged and deliberately pre-cutover. `main` remains
   unprotected while #262 is reviewed.
2. Land #262 through a reviewed PR under the current human repository process.
   Its own admission job still uses the old base policy and therefore cannot
   certify itself; that is a bootstrap limitation, not a bypass.
3. Before any cutover, confirm a real main-targeted PR produces a successful
   **Windows packaged E2E** check and inspect both Actions artifacts. Use a
   separate test PR or the #262 PR itself, not a synthetic check.
4. Only then perform the separately authorized `develop` creation/default/rules
   cutover below. Do not enable required checks before the contexts and
   producing app are verified on a real PR.
5. Keep release/itch automation disabled until a separate explicit decision.
   No temporary passing check, synthetic approval, general admin bypass, or
   early required-rule activation is part of bootstrap.

#### Exact administrator enforcement (not active)

`main` is still unprotected and there is no CODEOWNERS enforcement established by
this PR. A required check name plus the GitHub Actions app does not authenticate
the workflow contents: a PR can replace its workflow despite the honest workflow's
base-SHA checkout. Before activation, the administrator must:

- Target explicit `refs/heads/main`; require PRs, latest-base validation, the three
  existing CI contexts, **Windows packaged E2E**, **Main admission policy**,
  with verified producing app. Require merge commits for promotions. Prevent
  deletion/force pushes and routine bypass.
- Protect `/.github/workflows/**`, `/packaging/main_admission.py`,
  `/packaging/packaged_e2e.py`, `/packaging/e2e/windows_e2e.py`,
  `/tests/test_main_admission.py`, `/tests/test_packaged_e2e.py`,
  `/tests/fixtures/main_admission_github.json`, and every future #262
  evidence/approval helper. Protect `/.github/CODEOWNERS` itself and any
  replacement ownership/protection configuration.
- With multiple eligible maintainers, install matching CODEOWNERS entries on both
  permanent branches, require code-owner approval in the base branch's rules,
  dismiss stale approvals, and require approval of the latest reviewable push.
  Resolve review conversations and ensure the author cannot satisfy their own
  required review. A CODEOWNERS file alone enforces nothing. See
  [GitHub's CODEOWNERS guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).
- Alternatively, verify availability of an organization/enterprise required
  workflow from a separately protected trusted source and mandate that exact
  workflow/ref. Do not assume this organization-level capability exists for this
  personal repository. See [ruleset workflow scope](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-workflows-to-pass-before-merging).
- Demonstrate rejection of a PR deleting the gate, replacing it with `exit 0`,
  weakening policy/tests, or changing its code ownership. An unauthorized change
  must remain blocked even if it reports a same-name successful check.

Keep auto-merge disabled; add no merge queue. Do not modify #256 or branch settings
as part of this draft. The administrator must confirm plan/permission support and
test enforcement rather than treating these instructions as installed rules.

#### Single-maintainer approval profile (adopted by #262)

GitHub does not let a PR author approve their own PR review. #262 therefore
adopts an explicit **owner-authorization** profile alongside independent review:
a PR comment by a user with `admin` permission containing these exact lines,
created after the packaged E2E evidence was generated:

```text
Main admission owner authorization: <head SHA> <base SHA>
Main admission artifact: sha256:<ZIP SHA-256>
```

Labels and PR authorship never grant authority. This is owner authorization, not
independent human review; the chosen profile must be stated when it is used.
Because issue comments do not trigger this workflow, add or remove
`admission:recheck` after posting the authorization comment. If a second
eligible maintainer is available, independent review remains the stronger option.
A protected `main-candidate` environment with required reviewers is a native
future alternative; it is not activated by this runbook.

Workflow-content provenance remains a separate requirement: verify trusted
workflow enforcement, or protected review by a second eligible maintainer, before
claiming tamper resistance. If neither can be enforced with the available
repository/plan, keep final cutover blocked and approve a supported trust-control
design. Do not use a blanket admin bypass.

The ordinary PR workflow is retained. The previous claim that `pull_request_target`
cannot satisfy required checks was incorrect: current
[GitHub guidance](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
lists it and `pull_request_review` as eligible, while `workflow_dispatch` is not.
No privileged event or new permission is needed for the explicit label recheck.

## Promotion and emergency hotfix process

1. Prepare a reviewable `develop` to `main` candidate PR. Record the intended
   release scope and freeze its candidate while validating; new integration
   commits require refreshed validation rather than silently joining the release.
2. Record the head and base SHAs, tested commit and tree, workflow run/attempt,
   artifact ID, ZIP SHA-256, version, automated coverage/results, and human smoke
   evidence. Any changed head/base invalidates approval for the old candidate.
3. #262 builds and tests the packaged ZIP automatically (see above). Complete
   the mandatory Windows/MOTW and remaining product checks on the same ZIP
   identity for release; those manual checks are not part of merge admission.
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
2. **PR B (#261):** minimal push CI/admission guard and focused tests, described
   above. Preserve existing checks and release behavior; the #262 packaged gate
   is implemented separately. GitHub enforcement/cutover remain separate.
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
