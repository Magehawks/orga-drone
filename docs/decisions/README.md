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
| [0002](0002-studio-order-and-duration.md) | Studio order and duration estimate | Accepted |
| [0003](0003-studio-video-cut-offsets.md) | Studio video cut via source in/out offsets | Accepted |
| [0004](0004-studio-project-clip-model.md) | Studio non-destructive project and clip model | Accepted |
| [0005](0005-studio-export-resolution.md) | Studio export resolution and encoder boundary | Accepted |
| [0006](0006-studio-project-browser.md) | Studio project browser and last-opened project | Proposed |
| [0007](0007-studio-export-open-reveal.md) | Studio export open / reveal after completion | Proposed |
| [0008](0008-studio-music-soundtrack.md) | Studio music as a read-only project soundtrack | Proposed |
| [0009](0009-studio-title-cards.md) | Studio Title Cards as generated timeline items | Proposed |
