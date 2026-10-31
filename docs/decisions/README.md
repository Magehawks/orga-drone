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
4. A record that says merging does not adopt it stays `Proposed` until the
   human accepts the decision itself. ADR 0024 is that kind of record: it
   documents a license proposal and does not change `LICENSE`.
5. Superseded decisions stay in place with a pointer to the replacement.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-studio-workspace-persistence.md) | Studio workspace persistence | Accepted |
| [0002](0002-studio-order-and-duration.md) | Studio order and duration estimate | Accepted |
| [0003](0003-studio-video-cut-offsets.md) | Studio video cut via source in/out offsets | Accepted |
| [0004](0004-studio-project-clip-model.md) | Studio non-destructive project and clip model | Accepted |
| [0005](0005-studio-export-resolution.md) | Studio export resolution and encoder boundary | Accepted |
| [0006](0006-studio-project-browser.md) | Studio project browser and last-opened project | Accepted |
| [0007](0007-studio-export-open-reveal.md) | Studio export open / reveal after completion | Accepted |
| [0008](0008-studio-music-soundtrack.md) | Studio music as a sequential soundtrack playlist | Accepted |
| [0009](0009-studio-title-cards.md) | Studio Title Cards as generated timeline items | Accepted |
| [0010](0010-studio-visual-transitions.md) | Studio visual transitions | Accepted |
| [0011](0011-studio-image-adjust.md) | Studio per-clip image adjustment | Accepted |
| [0012](0012-windows-release-workflow.md) | Windows release workflow with a draft publish gate | Accepted |
| [0013](0013-itch-windows-channel.md) | itch.io Windows channel via butler | Accepted |
| [0014](0014-studio-export-cancel.md) | Studio export cancellation | Accepted |
| [0015](0015-update-notice.md) | Optional published-release notice | Accepted |
| [0016](0016-studio-overlays.md) | Studio timed overlays | Accepted |
| [0017](0017-studio-privacy-masks.md) | Studio privacy masks | Accepted |
| [0018](0018-studio-framing.md) | Studio per-clip zoom and pan | Accepted |
| [0019](0019-studio-saturation-ramp.md) | Studio video saturation ramp | Accepted |
| [0020](0020-incremental-rescan-fingerprint.md) | Skip unchanged media on rescan | Accepted |
| [0021](0021-studio-section-repeat.md) | Studio video section repeat | Accepted |
| [0022](0022-studio-telemetry-hud.md) | Studio telemetry HUD | Accepted |
| [0023](0023-studio-flight-map.md) | Studio flight map without third-party tiles | Accepted |
| [0024](0024-licensing-model-proposal.md) | Licensing model for paid Windows builds | Proposed (not a license change) |
| [0025](0025-studio-reuse-source.md) | Another scene from the same Studio source | Accepted |
| [0026](0026-studio-soundtrack-lead-in.md) | Studio soundtrack lead-in | Accepted |
| [0027](0027-studio-lut-dlog-m.md) | Studio local `.cube` LUT and D-Log M conversion | Accepted |
| [0028](0028-studio-lut-preview-stills.md) | Studio LUT preview via shared FFmpeg stills | Accepted |
| [0029](0029-studio-hsl-color-mixer.md) | Studio HSL colour mixer as a generated 3D LUT | Accepted |
