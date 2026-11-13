# Managed primaries UI mappings (#353)

Normative companions to [ADR 0035](../decisions/0035-color-workspace-contract.md)
and `studio_managed_primaries.py`. These mappings are versioned. UI and CPU
reference must share the same ids; inventing a frontend-only approximation is
forbidden.

## kelvin-tint-v1

| Input | Range | Neutral |
|---|---|---|
| Kelvin | 2000..15000 | 6500 |
| Tint | -100..100 | 0 |

Algorithm:

1. Sample Tanner Helland / FFmpeg-compatible blackbody RGB at Kelvin and at 6500 K.
2. Form channel ratios `sample / reference`.
3. Apply tint: `R' = R*(1-0.25*t)`, `G' = G*(1+0.5*t)`, `B' = B*(1-0.25*t)` with `t = tint/100`.
4. Clamp each channel to `[0.01, 100]`.
5. Exact `(6500, 0)` returns `(1,1,1)` before balance.
6. `primaries_balance` luma-normalizes the gains so gray keeps Y.

Golden vectors (pre-balance gains, 9 decimal places):

| Kelvin | Tint | R | G | B |
|---|---|---|---|---|
| 6500 | 0 | 1.000000000 | 1.000000000 | 1.000000000 |
| 5000 | 0 | 1.000000000 | 0.897298118 | 0.823583620 |
| 8000 | 0 | 0.867508429 | 0.904289926 | 1.019829043 |
| 6500 | 50 | 0.875000000 | 1.250000000 | 0.875000000 |
| 6500 | -50 | 1.125000000 | 0.750000000 | 1.125000000 |

Exact published floats are locked by `tests/test_studio_managed_primaries.py`.

## tone-controls-v1

| Input | Range | Neutral |
|---|---|---|
| blacks, shadows, highlights, whites | -100..100 | 0 |

Algorithm:

1. All-zero → identity curve `[(0,0),(1,1)]`.
2. Otherwise five knots at x = 0, 0.25, 0.5, 0.75, 1.0:
   - `y0 = clamp(blacks/100*0.25, -0.05, 0.35)`
   - `y1 = 0.25 + shadows/100*0.20`
   - `y2 = 0.5 + 0.5*(shadows/100*0.10) + 0.5*(highlights/100*0.10)`
   - `y3 = 0.75 + highlights/100*0.20`
   - `y4 = clamp(1 + whites/100*0.25, 0.65, 1.05)`
3. Enforce non-decreasing y by forward max.
4. Evaluate with `apply_tone_curve` (piecewise linear, endpoint extrapolation).

This is the only tone operator for managed primaries. There is no second hidden
tone map.
