## Linked issue

Closes #

## Summary

<!-- What changed and why? Keep this tied to the approved issue. -->

## Scope check

- [ ] Implements the linked issue acceptance criteria
- [ ] No unrelated refactors / speculative scope
- [ ] Source media remains non-destructive where applicable
- [ ] Existing data/projects remain compatible, or migration is documented

## Test evidence

- [ ] `ruff check .` passes locally
- [ ] `mypy src` passes locally
- [ ] `pytest` passes locally
- [ ] Feature-specific regression tests added/updated

Details:

<!-- Commands, focused tests, relevant fixtures/synthetic media. -->

## Docs / i18n

- [ ] Product/architecture docs updated if shipping truth changed
- [ ] DE + EN strings updated if user-visible copy changed
- [ ] ADR added/updated only if a significant architectural decision was made

## Independent review

Reviewer verdict:

- [ ] `REVIEW_APPROVED`
- [ ] `REVIEW_CHANGES_REQUESTED`
- [ ] `REVIEW_ARCHITECTURE_CONCERN`

<!-- Reviewer findings belong in PR review/comments; the reviewer must not fix its own findings. -->

## Human test handoff

<!-- Concise real-world checks for the Product Owner before merge. For Studio features, prefer realistic drone media. -->

- [ ] Manual product test completed by human Product Owner

## Follow-ups (not part of this PR)

<!-- Performance improvements, future profiles, cleanup, etc. Keep them out of the current diff unless required for correctness. -->

<!-- CI on PRs runs Ruff lint, MyPy type check, pytest. See docs/AGENT_WORKFLOW.md. -->
