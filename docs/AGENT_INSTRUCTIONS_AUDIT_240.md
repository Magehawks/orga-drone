# Agent instruction audit for the 2.4.0 cycle

Audit date: 2026-11-07. Baseline: `develop` at
`7dd593000844ab7b6832bb24608f2629ec515c1c`. GitHub repository metadata
confirmed `develop` is the default branch. Effective branch protection was not
verified and is not changed by this work.

## 1. Instruction sources and precedence

Explicit Product Owner decisions in the audit request supersede the old process.
Host/system safety and tool permissions still apply. Root `AGENTS.md` provides
repository constraints; a nested AGENTS file would narrow its directory scope.
Inventory found only the root AGENTS file and no tracked repository SKILL.md.
Untracked host configuration is not a repository policy source and is excluded.

`docs/AGENT_WORKFLOW.md` is the canonical process; `docs/PR_E2E.md` defines test
selection and CI evidence. Product vision, roadmap status, architecture, Studio
module rules and ADRs govern their respective subjects. `.cursor/rules/` has two
always-applied rules: project knowledge and agent roles. `.cursor/agents/` has
four read-only role prompts. These are specialized agents, not installed skills.
Contributor docs, issue forms and the PR template must reflect the canonical
process rather than create additional gates. Executable tooling/workflows define
what actually runs; prose cannot waive checks or install branch protection.

## 2. Contradictions and obsolete rules

- `AGENTS.md`, Workflow sections Roles/State flow/Issue contract, and
  `.cursor/rules/agent-roles.mdc` mandate PM, UX and CTO handoffs for already
  approved work. This conflicts with continuous implementation of approved issues.
- Workflow calls UX both required and not an implementation gate. The PM and UX
  prompts require concept selection and further handoffs even for settled scope.
- Workflow Human test gate and the PR template require Product Owner testing
  before every merge. This conflicts with separate periodic DJI/edit/export tests.
- Agent roles and Roadmap require pre-commit implementation review; Workflow
  describes branch/PR review. Independent ChatGPT review belongs on the actual PR.
- Workflow Developer contract, Contributing Tests/Pull requests and the PR
  template require full local checks regardless of risk, duplicating CI for tiny
  docs changes. AGENTS lists commands without distinguishing local selection.
- Contributing and Workflow call `main` the current development target. GitHub
  now reports `develop`. Branch migration's 2026-11-04 snapshot is historical.
- Branch migration Proposed branch rules permits merging failed informational
  develop checks. The current decision explicitly prohibits accepting failures.
- AGENTS and Contributing MyPy examples omit three packaging policy/harness
  targets that CI explicitly checks. `pyproject.toml` default files also omit
  those targets; retain tool configuration and document the exact CI command.
- Contributing says CI has three checks; PR_E2E's every-PR table includes Windows
  E2E, although its workflow targets only `main`. Distinguish the branch lanes.
- PR_E2E contains a dated “Tonight’s review pass” and obsolete stacked-PR advice.
  LUT packaged parity is described as deferred there; leave technical coverage
  claims outside this process audit unchanged pending a separate coverage audit.
- Roadmap intake, User needs and feature issue form repeat the superseded gates.
- AGENTS calls Studio a monolith without noting extracted ES modules. Studio
  module rules already describe incremental extraction; its 500–1,000-line
  entry target is an architectural aspiration, not a required size gate.
- No arbitrary Python file-size cap, Python formatter gate, blanket Python
  refactoring obligation or repository-local Python/JS skill was found. Do not
  invent one. Ruff currently selects E4/E7/E9/F; MyPy targets Python 3.12 while
  runtime supports 3.11+. Pytest has no project-wide marker/coverage threshold.

## 3. Recommended changes per file

- `AGENTS.md`: link canonical testing/workflow, summarize the new loop and
  optional advisors; preserve all product, security and compatibility limits.
- `docs/AGENT_WORKFLOW.md`: replace mandatory role chain with approved issue,
  implementation, focused checks, PR, independent ChatGPT review, correction,
  authorized develop merge. Separate periodic PO testing and human release signoff.
- `docs/PR_E2E.md`: add risk tiers, exact CI MyPy targets, branch-specific evidence,
  and distinguish routine local selection from unchanged full CI/RC validation.
- `CONTRIBUTING.md`: use develop, remove blanket local full-suite obligation,
  document Python formatting baseline and avoid mandatory abstraction/refactors.
- `.cursor/rules/agent-roles.mdc`: keep optional advisors and independent review;
  delegate only when explicitly requested, without mandatory sequential handoffs.
- `.cursor/agents/{product-spec-reviewer,product-ux-designer,engineering-planner}.md`:
  advisory roles for unresolved questions, no automatic downstream gate.
- `.cursor/agents/implementation-reviewer.md`: reusable read-only review checklist;
  local advisory review cannot replace independent ChatGPT GitHub PR review.
- `.github/PULL_REQUEST_TEMPLATE.md`: risk, commands/results/limitations, CI and
  independent review evidence; periodic PO checks are not per-merge checkboxes.
- `.github/ISSUE_TEMPLATE/feature.yml`: approved scope/readiness and optional
  advice instead of mandatory role approvals; bug form accepts develop SHA.
- `docs/ROADMAP.md`, `docs/USER_NEEDS.md`: link canonical intake/workflow without
  changing feature status or roadmap priorities.
- `docs/BRANCH_MIGRATION.md`: label historical content, add current policy and
  supersede failing-CI permission; do not execute administrator operations.
- `docs/STUDIO_MODULES.md`: clarify incremental extraction and no size quota;
  preserve boundaries, direct module tests and sensitive-pipeline safeguards.
- Leave `pyproject.toml`, npm/ESLint/Prettier config, CI/release workflows,
  packaging/security code, existing validation reports and ADR history unchanged.

## 4. Specialized skills and agents

Update the four repository agent prompts and the role rule above. There are no
tracked local skills to update. Host-installed skills are outside this PR.
The product, UX and engineering advisors remain available on request; their
status tokens are advisory, not prerequisites for an already-approved issue.

## 5. Rules that remain unchanged

Local-first operation; read-only source media; confined paths and soundtrack
exception; loopback Host/Origin checks; privacy and synthetic fixtures; rescan
preservation; existing data/project compatibility; ADR/migration requirement for
schema or effect_settings changes; DE/EN user-facing text; truthful shipped/later
claims; no new framework/bundler/platform; focused approved scope; no unrelated
refactors or legacy mass formatting; independent read-only review; existing CI,
main admission and packaged evidence validation; human release approval and MOTW
checks; no automatic merge/publication authority.

## 6. Risks, migration and remaining decisions

Risk: agents may mistake lighter local checks for weaker merge requirements.
Mitigation: record risk and actual results, keep all CI unchanged, block on
failures/missing evidence, and never treat skipped coverage as a pass.
Risk: historical main-admission/branch runbooks could override current process.
Mitigation: explicit precedence note while retaining historical technical detail.
Risk: self-review could masquerade as independence. Mitigation: separate ChatGPT
PR review of the current diff, linked verdict/findings and renewed review after
material corrections. A bot/text review does not satisfy GitHub's human approval
or main-admission authorization requirements by itself.

Migration: deliver this report first, then update the listed policy surfaces in
one docs/configuration PR against develop. The Product Owner's explicit decisions
authorize replacing the old mandatory role and per-merge product-test gates.
Review the diff, run document/link/template checks, await unchanged CI and
independent ChatGPT review. Do not relabel historical issues, modify protection,
merge, tag, dispatch a release workflow or publish. Revert this single PR if the
policy needs rollback; no data or runtime migration is involved.

No additional Product Owner policy decision blocks this documentation PR.
The cadence/media selection for periodic testing and the 2.4.0 RC acceptance
record remain Product Owner choices; this PR sets no arbitrary schedule and
claims no release readiness. Merge execution, branch-protection administration,
release-candidate promotion and release approval still require explicit human
authorization. The existing main admission/human authorization mechanism stays
unchanged; this policy does not resolve or bypass its administrator requirements.
