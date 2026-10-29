# Discovery: DJI SRT telemetry coverage, sync, and HUD data

- **Issue:** [#188](https://github.com/Magehawks/orga-drone/issues/188)
- **Date:** 2026-10-29
- **Status:** Discovery only. Parser behavior unchanged in this note.
- **Tree checked:** `main` (Studio HUD from [#107](https://github.com/Magehawks/orga-drone/issues/107) / ADR 0022)

Related: [#137](https://github.com/Magehawks/orga-drone/issues/137) (time mapping),
[#174](https://github.com/Magehawks/orga-drone/issues/174) (D-Log M), existing
HUD / map overlay / SRT rescan paths.

## Question

Which fields from real DJI sibling `.SRT` files are parsed, stored, shown, and
exported today — and what is the smallest honest follow-up set for hobby
pilots who want trustworthy flight info without inventing speed or heading?

## Method

- Parser: `src/orga_drone/parse/__init__.py` (`parse_srt`, `SRT_GPS_RE`, `SRT_ALT_RE`)
- Scan token: `src/orga_drone/scan/__init__.py` (`srt_token` = sidecar size:mtime)
- Studio HUD: `src/orga_drone/studio_hud.py`, ADR `0022-studio-telemetry-hud.md`
- Library overlay: `static/js/overlay.js`, `track.js`
- Local read-only sample shape checked outside the repo (user test folder);
  **no real GPS coordinates are recorded in this document or in fixtures.**
- Sanitized fixture added: `tests/fixtures/dji_srt_camera_fields_sample.srt`

## Observed DJI cue shape (field names only)

A recent Avata-style cue typically contains:

- Subtitle clock `HH:MM:SS,mmm --> …`
- `FrameCnt` / `DiffTime` and a wall-clock line
- Camera tokens: `iso`, `shutter`, `fnum`, `ev`, `ct`, `color_md` (e.g. `dlog_m`),
  `ae_meter_md`
- `latitude` / `longitude`
- Combined altitude bracket: `[rel_alt: … abs_alt: …]`

This sample did **not** expose explicit speed, heading, gimbal, or gyro tokens.
Never infer reliable horizontal speed or heading from near-stationary GPS.

Not every recording has an SRT. JPG-only stills and some MP4s in mixed folders
have no sibling telemetry. LRF files are separate preview/proxy media and are
not SRT sources.

## Field coverage matrix

| Field | In typical SRT | Parsed | Stored | Library | Studio HUD preview/MP4 |
| --- | --- | --- | --- | --- | --- |
| Subtitle cue start → `t` | Yes | Yes | `track_json[].t` | Overlay/map timing | Elapsed source time |
| Cue end / duration | Yes | Duration only | `duration_s` (from last cue) | Info duration paths | Clip window uses media duration |
| latitude / longitude | Often | Yes | `track_json` + media start | Map + overlay | Flight map only (not HUD text) |
| rel_alt + abs_alt (combined bracket) | Often | Yes | `track_json`; media `abs_alt` from start | Overlay both; Info shows abs | **rel_alt only** |
| Separate `[rel_alt:]` / `[abs_alt:]` | Possible | **No** | — | Missing altitude | Missing altitude |
| FrameCnt / DiffTime | Often | **No** | — | — | — |
| iso / shutter / fnum / ev / ct | Often | **No** | — | — | — |
| color_md / dlog_m | Often | **No** | — | — | — |
| Speed token | Rare / absent in sample | **No** | — | Overlay **derives** from GPS Δ | Explicit **unavailable** |
| Home distance | Absent in sample | **No** | — | — | Explicit **unavailable** |

## Data flow (today)

```text
sibling .SRT/.srt
  → parse_srt / parse_media_file
  → media.track_json (+ lat/lon/abs_alt, has_srt, srt_token)
  → Library map / overlay / session heuristics
  → Studio flight map (stored GPS)

same sibling file (re-read, high cue limit)
  → studio_hud.cues_from_srt
  → preview + MP4 drawtext (elapsed + rel_alt)
```

Rescan: unchanged video size+mtime **and** unchanged `srt_token` skips
metadata extraction; a changed SRT forces re-parse even if the MP4 is
unchanged.

Index tracks are downsampled (default 200 points). HUD bypasses that by
re-reading the SRT with a very high cue limit.

## Time alignment

| Source | Role |
| --- | --- |
| Subtitle start time | Canonical `GpsPoint.t` and HUD cue times |
| FrameCnt / DiffTime | Ignored today |
| Studio cuts / speed / repeat | Shared story mapping from [#137](https://github.com/Magehawks/orga-drone/issues/137); HUD uses source window |
| Altitude hold | Nearest `rel_alt` within 1.0 s; gaps stay blank (honest empty) |

## User-facing terminology (recommended)

| Internal | Show users |
| --- | --- |
| `rel_alt` | Relative altitude (above takeoff / home reference in the file) |
| `abs_alt` | Absolute altitude (as written in the file; not a survey grade) |
| Derived GPS speed (Library overlay) | Estimated ground speed — not a speedometer |
| Studio HUD speed / home | “Not available” (keep; do not invent) |
| `color_md: dlog_m` | Color profile hint (D-Log M) — not an automatic look until [#174](https://github.com/Magehawks/orga-drone/issues/174) |

## Gaps and smallest follow-ups

1. **Parser: separate altitude brackets** — accept `[rel_alt: X]` and
   `[abs_alt: Y]` when the combined form is missing. Tiny regex change + tests
   against the new sanitized fixture section.
2. **Optional cue extras in track JSON** — store camera tokens (`iso`,
   `color_md`, …) when present, without HUD UI. Enables later D-Log hints.
3. **Do not** add Studio HUD speed/heading from sparse GPS.
4. **Do not** auto-apply D-Log conversion from `color_md` without an explicit
   user look ([#174](https://github.com/Magehawks/orga-drone/issues/174) /
   [#172](https://github.com/Magehawks/orga-drone/issues/172)).
5. Keep Library overlay’s derived speed labeled as estimated if copy is
   tightened under [#186](https://github.com/Magehawks/orga-drone/issues/186).

## Fixtures and test plan

| Asset | Purpose |
| --- | --- |
| `tests/fixtures/dji_srt_hud_sample.srt` | Existing HUD gap + combined alt |
| `tests/fixtures/dji_srt_camera_fields_sample.srt` | **New** anonymized cues with FrameCnt/DiffTime, camera tokens, `color_md: dlog_m`, combined alt, one GPS-only cue, synthetic coordinates far from real flights |

Parser/HUD test plan (implementation later):

- Combined alt still fills `rel_alt` / `abs_alt`
- Camera tokens ignored until extras land (document expected None)
- Separate-alt section expected fail → pass after follow-up 1
- `(0,0)` GPS still discarded
- Changed sidecar mtime invalidates `srt_token` (existing incremental test)

## Non-scope (honored)

Cloud processing, AI, full telemetry rewrite, gyro stabilization, invented
speed/heading, publishing private coordinates.

## Outcome

Acceptance for #188 is met: evidence-backed matrix, sanitized fixture, gaps,
and a short follow-up list without duplicating the shipping HUD. No runtime
change in this discovery PR beyond the fixture + this note.
