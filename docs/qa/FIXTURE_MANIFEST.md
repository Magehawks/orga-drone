# Fixture manifest policy (#283)

Authoritative machine-readable pin:
[`../../tests/fixtures/regression_fixture_manifest.json`](../../tests/fixtures/regression_fixture_manifest.json).

Human summary only — do not invent a second competing JSON manifest.

## Rules

1. Prefer deterministic **synthetic** fixtures generated in-test (Pillow / FFmpeg lavfi).
2. In-repo samples must be privacy-safe (no people, homes, precise locations, private SRT).
3. Never fabricate DJI/Potensic coverage. Optional real footage stays **local opt-in**,
   referenced by hash in a private manifest, never committed if it contains private data.
4. Pin fixture schema version, build SHA under test, FFmpeg version, and WebView2
   version in evidence JSON when Layer 4/5 claims are made.
5. Do not regenerate reference outputs solely from a candidate implementation.

## Synthetic defaults

| Kind | How produced | Used by |
| --- | --- | --- |
| JPEG/PNG solids | Pillow in tests | journey smoke, HSL export, collage |
| Short MP4 | FFmpeg `lavfi` color source | creator journey, export decode |
| Sanitized SRT | `tests/fixtures/dji_srt_*.srt` | telemetry/HUD parsing |

## Optional real footage (local only)

Creators may point `ORGA_DRONE_REAL_FIXTURE_ROOT` at a private folder. Gate scripts
must refuse to upload those files as CI artifacts. Public evidence may include only
aggregate metrics and synthetic screenshots. Potensic / DJI representative slots in
the JSON stay `NOT_FABRICATED` until real local fixtures exist.
