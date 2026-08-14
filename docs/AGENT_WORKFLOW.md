# Orga Drone Agentic Development Workflow

This document defines the human-gated development loop used for Orga Drone.
GitHub issues and pull requests are the source of truth between roles.

## Principle

**Limit the current scope, not the long-term vision.**

Agents may consider future professional creator workflows when judging architecture,
but they must not implement speculative platform scope unless the current issue requires it.

## Roles

| Role | Cursor role | Responsibility | May change application code? |
|---|---|---|---|
| Product Owner | Human | Idea, product judgment, real-world test, merge decision | Yes, manually |
| PM | `product-spec-reviewer` | User problem, target user, milestone fit, simplest slice, acceptance criteria, non-scope | No |
| CTO | `engineering-planner` | Architecture, compatibility, performance, security, test strategy, technical AC | No |
| Developer | Main Cursor agent | Implement only the approved issue and run required checks | Yes |
| Reviewer | `implementation-reviewer` | Independent adversarial review of the completed branch/PR | No |

## State flow

```text
idea
  ↓
pm-review
  ↓
cto-review
  ↓
ready-for-dev
  ↓
in-development
  ↓
review-required
  ↓
┌───────────────────────────┐
│ REVIEW_CHANGES_REQUESTED  │──→ developer fix ──→ review-required
└───────────────────────────┘
  ↓ REVIEW_APPROVED
human-test
  ↓
merge / done
```

A maximum of three developer ↔ reviewer correction loops is recommended. After that,
a human should decide whether the issue/spec or architecture needs to change.

## GitHub workflow labels

Recommended labels:

- `status:idea`
- `status:pm-review`
- `status:cto-review`
- `status:ready-for-dev`
- `status:in-development`
- `status:review-required`
- `status:changes-requested`
- `status:human-test`

Classification labels may be added independently, for example:

- `area:studio`, `area:library`, `area:telemetry`
- `priority:p0`, `priority:p1`, `priority:p2`, `priority:p3`
- GitHub's existing `enhancement`, `bug`, `documentation`

Exactly one `status:*` label should describe the current workflow state.

## Issue contract

An issue is `ready-for-dev` only when PM and CTO gates are complete.
The issue must contain or link to:

- concrete user problem
- target user
- why this belongs in the current slice
- proposed behavior
- acceptance criteria
- explicit non-scope
- relevant technical constraints
- automated and manual test expectations

The developer must not infer missing product decisions by silently expanding scope.
If a missing decision materially changes behavior, return the issue to the appropriate gate.

## Developer contract

The main implementation agent must:

1. Read the issue and `AGENTS.md` before changing code.
2. Inspect the existing implementation before choosing a design.
3. Implement the smallest complete slice that meets the acceptance criteria.
4. Preserve source media and compatibility unless the issue explicitly says otherwise.
5. Avoid unrelated refactors and speculative architecture.
6. Add/update tests and DE/EN strings where needed.
7. Update product/architecture docs only when product truth actually changes.
8. Run Ruff, MyPy and pytest (or explain any test that cannot run).
9. Open/update a PR that links the issue and reports test evidence.
10. Hand the PR to the independent reviewer.

## Review contract

The reviewer evaluates the linked issue and the actual diff, not the developer's intent.
It returns one of:

- `REVIEW_APPROVED`
- `REVIEW_CHANGES_REQUESTED`
- `REVIEW_ARCHITECTURE_CONCERN`

The reviewer does not fix its own findings. This keeps implementation and review contexts independent.

## Human test gate

Automated approval is not merge approval.

After `REVIEW_APPROVED`, the Product Owner performs the real workflow using realistic drone media where relevant. The PR should provide a short manual checklist tailored to the feature.

Examples for Studio work:

- preview and trim behavior feels correct
- exported media plays continuously
- visual/audio result is acceptable
- 4K input does not produce surprising behavior
- original media is unchanged
- failure/cancel/retry UX is understandable

Only the human Product Owner decides whether the feature is merged.

## Phase 1 vs automation

Phase 1 is intentionally semi-manual: roles and states are explicit, but agents are started by a human.

Only after several successful real issues should automation trigger Developer or Reviewer agents from GitHub state changes. The human test and merge gates remain manual.
