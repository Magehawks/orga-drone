# Packaged Windows WebView2 E2E — develop `708bdd5`

Status: **PASS** (local maintainer machine, 2026-11-13).

Candidate: `708bdd52bdb6f21b06b31fc6185042090a08f2df`  
Artifact SHA-256: `5e16c04851c8ab0874a016113a656df8c1a3bac7e5e027051a99ac74a14a00c3`  
App version: `2.3.3`  
WebView2: `157.0.4341.46`  
Runner: local Windows 11 build of `dist/orga-drone` (PyInstaller onefolder + GPL ffmpeg overlay when present).

Evidence directory (not committed; regenerable): `tmp-packaged-e2e-extended/`.

## Journeys

| Journey | Result | Notes |
|---|---|---|
| startup | PASS | Health ok, no startup-crash.log |
| media_import | PASS | 1 photo + 1 video synthetic fixtures |
| library_navigation | PASS | Browse lists both assets |
| studio_open | PASS | Project create/open + both clips |
| playback | PASS | Video advanced past 0.2 s; screenshot saved |
| edit_persistence | PASS | Photo exposure=20 survives reload |
| timeline_transitions | PASS | crossfade, blur_dissolve, soft_wipe_left applied 0.5 s |
| speed_and_timelapse | PASS | Bounded ramp then flat 2× Timelapse; cleared before export |
| undo_redo_timeline | PASS | exposure 20→35 undo→20 redo→35; restored to 20 |
| export_1080p | PASS | 1920×1080 MP4 published |
| sfx_lane | PASS | Music + 2 SFX, drag, trim, undo/redo |
| sfx_control | PASS | Control API volume update |
| export | PASS | 720p MP4 with audible audio peak |
| image_export | PASS | Instagram preset JPEG |
| lut_parity | PASS | Preview vs export max RGB error ≤0.91 (tol 8.0) |
| source_integrity | PASS | Source hashes unchanged |
| relaunch_persistence | PASS | Exposure 20 after process restart |
| shutdown | PASS | No leftover packaged process; no crash log |

## Artifacts produced

- `e2e-export.mp4` (720p)
- `e2e-export-1080p.mp4` (1080p)
- `e2e-image.jpg`
- `e2e-lut-parity.mp4`, `e2e-lut-preview.jpg`, `e2e-lut-export-frame.png`
- `studio-playback.png`, `studio-transitions.png`, `studio-timelapse-inspector.png`
- `evidence.json`

## Limitations

- MOTW / Defender exclusion checks were **not** claimed (`manual_checks_claimed: false`).
- This is a local packaged run, not the GitHub Actions `windows-e2e.yml` artifact binding for a PR to `main`.
- Color Workspace managed-SDR operators were **not** exercised here; that coverage belongs to Phase 2–3 after canonical writes are enabled.
