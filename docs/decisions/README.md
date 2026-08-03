# Architecture Decision Records (ADRs)

Record significant technical decisions here so agents and humans share the
same rationale.

## When to write an ADR

Write one when a change:

- introduces a new persistence model or schema strategy
- changes scan/index semantics (e.g. incremental vs full rescan)
- adds a dependency with lasting impact
- chooses between non-obvious implementation approaches
- affects security, privacy, or path confinement

Skip ADRs for routine bugfixes and small UI tweaks.

## Process

1. Copy `0000-template.md` to `NNNN-short-title.md` (next free number).
2. Fill Context / Decision / Consequences.
3. Status starts as `Proposed`; set to `Accepted` when merged.
4. Superseded decisions stay in place with a pointer to the replacement.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-studio-workspace-persistence.md) | Studio workspace persistence | Accepted |
