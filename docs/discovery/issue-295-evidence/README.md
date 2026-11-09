# Issue #295 / ADR 0034 evidence

Synthetic source-app Windows/WebView2 journey only (`packaging/e2e/studio_speed_ramp.py`).
Not packaged/MOTW or real-footage visual-quality proof.

- `speed-curve.png` — Effect-lane curve + Speed inspector after presets/edit.
- `e2e-evidence.json` — PASS summary: four presets, pointer edit, undo/redo,
  relaunch restore, muted source audio, 1080p and 2160p export decode,
  unchanged originals. Measured playhead/music error stays within the harness
  tolerances used for Story clock work.

## Performance and known limits

- Preview uses the browser decoder and dynamic `playbackRate`; demanding 4K
  playback can drop frames. Export samples deterministically to 30 fps CFR.
- Slow regions hold source frames; fast regions drop frames. No optical flow.
- Source audio is muted for the whole ramped clip; soundtrack stays on Story time.
- Global frame boundaries are shared across ramp/color/loop pieces to avoid
  accumulated duration drift.
