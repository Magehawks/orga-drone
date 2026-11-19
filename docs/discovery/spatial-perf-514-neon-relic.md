# Neon Relic creative acceptance (#514 / #506)

Date: 2026-11-19  
Tree: `develop` @ `cb068da` (after #515–#517)  
Local assets: `acceptance-evidence/neon-relic/` (not committed)

## Goal

Magenta leaf / desaturated background look via **Orga-Drone** managed spatial
grade + still publish path — not an external Pillow-only pipeline presented as
Studio output.

## Method

`scripts/neon_relic_creative_acceptance.py`:

1. Load local BEFORE JPG (machine path via `--source` / env).
2. Apply managed-sdr-v1 grade: brush selection on leaf + inverted selection HSL
   desat on background; primaries tint/kelvin toward magenta on leaf.
3. Bake with `materialize_spatial_managed_media` (same CPU path as Studio still
   export; process worker via `ORGA_SPATIAL_BAKE_PROCESS=1`).
4. Write JPEG + metrics JSON next to local evidence (filenames
   `20-neon-relic-orga-export.jpg` / `.json`).

## Run (local)

Private BEFORE/TARGET stay under a local evidence directory (not in git).
Product Owner compares `20-neon-relic-orga-export.jpg` visually vs TARGET locally.

```text
set PYTHONPATH=src
set ORGA_SPATIAL_BAKE_PROCESS=1
set ORGA_NEON_RELIC_DIR=C:\path\to\acceptance-evidence\neon-relic
python scripts/neon_relic_creative_acceptance.py
```

Or with explicit paths:

```text
python scripts/neon_relic_creative_acceptance.py ^
  --source C:\path\to\00-before-original.jpg ^
  --target "C:\path\to\Magenta Blatt mit Regentropfen.png" ^
  --out-dir C:\path\to\acceptance-evidence\neon-relic
```

## Results (2026-11-19)

| Metric | Orga export | TARGET reference |
|---|---:|---:|
| bake_s (1125×1984) | 270.47 | — |
| mean R/G/B | 91.2 / 94.2 / 53.7 | 70.6 / 40.1 / 61.5 |
| chroma ratio | 0.2867 | 0.2879 |

Honest limitations:

- Brush mask approximates the leaf; edges are not AI freistellung.
- Channel means are not a pixel match to TARGET (export stays greener / less
  magenta-dominant than the reference look).
- Interactive Studio UI can refine strokes/feather further; this script locks a
  reproducible API-path grade for regression.

## Acceptance

- [x] Grade + JPEG via Orga materialize path
- [x] Metrics vs TARGET recorded
- [x] No private media committed to git
- [x] No cloud AI

## Non-scope

External “make it look like TARGET in Pillow” as product evidence.
