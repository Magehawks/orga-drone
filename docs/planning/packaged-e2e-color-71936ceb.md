# Packaged Windows WebView2 E2E — develop `71936ceb`

Status: **PASS** (local maintainer machine, 2026-11-13).

Candidate: `71936cebac9db4dab850c053bc82aeecfbd640fa`  
App version: `2.3.3`  
Evidence directory (not committed): `tmp-packaged-e2e-color/run-71936ceb/`.

## Journeys

All harness journeys reported `ok: true`, including startup, media import,
library, studio open, playback, edit persistence, timeline transitions
(crossfade / blur dissolve / soft wipe), speed/timelapse, undo/redo, 720p and
1080p export, image export, legacy LUT parity, SFX, relaunch persistence,
source integrity, shutdown.

## Color Workspace note

This run proves the packaged app on the Color Workspace tip does not regress
the existing journey set. It does **not** yet drive managed-sdr convert,
curve editor, selection masks, or creative-lut-v1 through CDP. Source-app
Creative/Pro smoke (`packaging/e2e/studio_color_workspace.py`) also **PASS**.

## Limitations

- Local packaged run, not GitHub Actions `windows-e2e.yml` admission for `main`.
- Managed Color Workspace UI operators remain a separate CDP extension.
