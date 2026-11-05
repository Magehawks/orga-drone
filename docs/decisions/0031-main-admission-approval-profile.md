# ADR 0031: Main admission packaged E2E and owner authorization

- Status: Accepted
- Date: 2026-11-04
- Issue: #262
- Related: #261, #263, #265, `docs/BRANCH_MIGRATION.md`

## Context

PR #265 added a fail-closed Main admission policy. It verifies CI checks,
candidate movement, and independent human approval from the immutable PR base,
but deliberately denied every candidate until packaged Windows validation
existed.

The repository has one maintainer. GitHub does not let a PR author approve their
own review, so an independent-review-only rule cannot admit owner-authored
promotions. The policy also had to avoid trusting run names, labels, old green
runs, partial reruns, or PR-authored evidence.

## Decision

1. **Packaged Windows E2E is a required admission input.** Every PR to `main`
   builds the existing onefolder app once and tests the extracted ZIP with the
   real WebView2 runtime. The workflow uploads the candidate ZIP and a bounded
   `evidence.json` artifact. Admission verifies the newest run for the exact
   head, the current attempt/suite/job/check identity, both artifact names,
   run/head/expiry linkage, and the downloaded evidence artifact's digest. The
   evidence binds the tested ZIP SHA-256, the tested merge SHA and tree, the
   current PR head/base, the required journey set, and a pass result. Missing,
   failed, stale, expired, partial-rerun, older-green, or mismatched evidence
   denies admission.
2. **Merge commits are required for promotions.** Evidence is bound to the PR
   merge commit and its Git tree. A different merge method or a changed base
   invalidates the evidence and requires a fresh run.
3. **Approval supports independent review or explicit owner authorization.**
   Independent review remains the stronger option. For solo operation, a PR
   comment by a user with `admin` permission may authorize admission only when it
   contains the exact head/base and ZIP SHA-256 and was created after the E2E
   evidence. Labels, PR authorship, bot reviews, and non-admin comments grant
   nothing. This is owner authorization, not independent review.
4. **Workflow/harness content is compared across base and head.** Admission
   denies if the E2E workflow, harness, or evidence validator differs between the
   trusted base and candidate. Repository protection of those paths remains an
   administrator requirement before enforcing required checks.

## Consequences

- A candidate cannot pass admission with mocked or missing packaged evidence.
- The first PR adding this policy cannot certify itself because its trusted base
  has the previous policy. It lands under the current human process; subsequent
  candidates use the new gate.
- E2E artifacts expire after 30 days. A longer-lived candidate must rerun the
  workflow; the old artifact is not reused.
- Native dialogs, MOTW/SmartScreen, real-media visual review, and release
  publication remain manual. This ADR does not authorize release publication.
- Workflow definitions remain PR-controlled until an administrator protects
  them with CODEOWNERS/required-workflow enforcement or equivalent review. The
  base/head content comparison reduces candidate-side tampering but does not
  replace administrator enforcement.
