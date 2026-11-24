# Parallel integration ownership (#284)

Goal: keep concurrent feature workstreams from fighting over shared CI/docs while
the permanent regression system protects established creator journeys.

## Worktree rules

- One isolated worktree + branch per issue family.
- Do **not** reuse feature worktrees named `gy62`, `color-ws-*`, `scopes-*`,
  `collage-*`, `playback-*`, `tracking-*`, or `assistant-*` for integration gates.
- Integration / regression work uses a dedicated tree (example:
  `regression-275-283-284` / `feat/regression-gates-275-283-284`).
- Prefer additive CI jobs and documentation over rewriting sibling harnesses.

## Shared-file coordination

| Area | Owners | Coordination |
| --- | --- | --- |
| `.github/workflows/ci.yml` | regression gates + release maintainers | Additive jobs preferred; announce before renaming existing jobs |
| `packaging/e2e/windows_e2e.py` | packaging + journey owners | Extend journeys; do not drop REQUIRED_JOURNEYS without PO |
| `docs/REGRESSION_GATES.md` / `docs/qa/*` | regression gates | Single living matrix; feature PRs update status rows only |
| `static/js/studio.js` monolith | feature modules | Extract modules per `STUDIO_MODULES.md`; avoid drive-by growth |
| Control API v1 | API / MCP | No second editor; MCP adapter stays external |

## PR gate checklist (every feature PR)

1. Links the issue and states risk / rollback.
2. Names API/MCP contract impact (`none` is allowed when true).
3. Reports PASS / FAIL / NOT_RUN / PENDING honestly for affected journeys.
4. Includes focused tests for changed behavior; does not skip red mandatory tests.
5. Avoids mass formatting and unrelated refactors.
6. Leaves Windows packaged E2E as NOT_RUN when not executed; does not claim native pass from browser/HTTP.

## Merge order

1. Land independent domain PRs to `develop` after CI + independent review.
2. Re-run curated regression gates after each merge when Studio contracts moved.
3. Build a release candidate only after integration and real Windows creator validation.
4. No self-merge of conflicting refactors; no automatic release.

## Required checks vs settings

Workflow jobs can land in-repo without changing GitHub branch protection.
Making develop checks **required** needs Product Owner approval of repository
settings (see `docs/REGRESSION_GATES.md`).
