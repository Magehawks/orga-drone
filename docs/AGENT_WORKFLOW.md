# Orga Drone development workflow

This is the canonical workflow for the 2.4.0 development cycle. The Product
Owner has scoped a substantial release covering fixes, modular refactoring, MCP,
and speed ramping/effects. This scope is planning context, not a shipping claim
or permission to implement unapproved features.

## Normal development loop

Approved issue → Implementation → Focused tests → PR to develop → Independent
ChatGPT GitHub PR review → Corrections and renewed review if needed → Develop merge.

Coding agents may continuously implement approved issues. An approved issue
records the problem, expected behavior, acceptance criteria, explicit non-scope
and relevant compatibility/security constraints. A clear Product Owner task may
supply the approval and scope; link that decision in the PR if no issue exists.
Do not manufacture PM/UX/CTO approvals for settled scope. Ask the Product Owner
about unresolved product decisions; investigate technical questions in place.

PM (`product-spec-reviewer`), UX (`product-ux-designer`) and engineering
(`engineering-planner`) are optional read-only advisors for unresolved scope,
interaction or architecture questions. Use them when explicitly requested.
Their status tokens are advisory and do not create an automatic handoff chain.
UX advice does not authorize unselected alternatives or create implementation issues.

## Developer responsibilities

- Read AGENTS.md, the approved scope, existing implementation and relevant docs.
- Implement the smallest complete slice; preserve source media, data and compatibility.
- Add meaningful regression tests where behavior changes. Select local checks by
  risk using [PR_E2E.md](PR_E2E.md); report commands, results, skips and limitations.
- Update docs when behavior/setup/architecture changes and DE/EN for UI text.
- Open a focused PR against latest develop using the template; avoid unrelated
  refactors, blanket abstraction requirements and legacy mass formatting.
- Resolve failures and review findings. Do not silently accept failing checks.

## Independent review and merge readiness

ChatGPT reviews the actual GitHub PR diff, approved scope, relevant implementation,
tests and CI evidence in an independent review context. The implementation agent
must not certify its own work as independently approved. The local
`implementation-reviewer` prompt is a reusable checklist or optional advisory
review, not a substitute for independent ChatGPT PR review.

Record a linked review with `REVIEW_APPROVED`, `REVIEW_CHANGES_REQUESTED` or
`REVIEW_ARCHITECTURE_CONCERN`, actionable findings and test limitations. The reviewer
stays read-only; developers make corrections. Material corrections require renewed
review. After three unresolved correction loops, escalate to the Product Owner.

Before develop merge: acceptance criteria met, independent review approved,
findings resolved, and all applicable CI checks successful for the current
candidate. Missing, failing, cancelled or skipped required checks are not success.
Do not bypass branch protection or reinterpret a failed check as informational.
Agents merge only with explicit human authorization; this workflow grants none.
A green CI run or ChatGPT review is not release approval and does not satisfy a
GitHub human-approval requirement or main-admission authorization by itself.

## Periodic Product Owner testing

The Product Owner periodically tests realistic DJI media, edits videos and checks
exports across integrated changes. Manual PO testing is not required before every
develop merge. Record tested commit/build, scenarios and outcomes; turn problems
into scoped bug issues with a safe reproduction. Never attach private media or
precise locations. PR authors may suggest scenarios for the next session.
A specific approved issue may require targeted manual evidence for a high-risk
change; identify that requirement explicitly rather than imposing it on every PR.

## Release candidates and release approval

Full validation belongs at the release-candidate stage: full automated checks,
appropriate packaged/integration evidence, realistic editing/export tests and the
Windows/MOTW checklist in [packaging/README.md](../packaging/README.md).
Record coverage gaps and failures; do not describe untested behavior as passed.
Main promotions remain subject to the existing admission policy, packaged evidence
and human authorization requirements. Release approval is explicitly human-controlled.
Do not tag, publish, attach binaries or dispatch release actions without the
applicable explicit authorization. No release workflow or security gate is changed.

## Tracking and intake

Issues and PRs carry scope, evidence and handoffs. Existing `status:ready-for-dev`,
`status:in-development`, `status:review-required` and `status:changes-requested`
labels may be used; labels are not approval or enforcement. Legacy PM/UX/CTO and
human-test labels are historical, not mandatory stages. No bulk relabeling is needed.
User-need intake remains evidence, not an approved implementation task or roadmap
promise; see [USER_NEEDS.md](USER_NEEDS.md).

Develop is the normal development base and PR target. Historical cutover details
in [BRANCH_MIGRATION.md](BRANCH_MIGRATION.md) do not override this process.
Effective GitHub protection must be verified by an administrator; documentation
alone does not install or prove protection.
