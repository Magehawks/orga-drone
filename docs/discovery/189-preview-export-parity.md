# Quality: Studio preview vs MP4 export parity

- **Issue:** [#189](https://github.com/Magehawks/orga-drone/issues/189)
- **Date:** 2026-10-29
- **Status:** Parity contract and regression matrix. No rendering rewrite.
- **Tree:** `main` after [#137](https://github.com/Magehawks/orga-drone/issues/137) time unification

Preview: `src/orga_drone/static/js/studio.js`, `templates/studio.html`.  
Export: `src/orga_drone/studio_export.py`, `export/studio_encoder.py` (`EXPORT_FPS = 30`).

## Parity contract

1. **Story clock is shared.** Clip occupancy, transitions, speed, slow bars,
   section repeat, and forward loop use the same duration rules on server
   (`item_effective_seconds`, `story_length_s`, `resolve_story_time`) and in
   preview (`resolveAt`, `totalDuration`). Export stitch uses the same
   applied boundaries.
2. **Supported adjustments are never silently dropped.** If a control is
   enabled in the Story, export must apply it or show a clear failure /
   unsupported message. Missing keys on old projects mean neutral.
3. **Visual layers may approximate.** Grade, overlays, masks, title cards,
   and fades use CSS/canvas/HTML in preview and FFmpeg/Pillow in export.
   Product copy already says “preview approximates export” for those.
4. **Encoder and color-space differences are not bugs** when timing and
   placement match. BT.709 limited YUV vs sRGB CSS will not match pixel hashes.
5. **Third-party re-encode** (WhatsApp/Instagram/TikTok after upload) is
   out of scope for this contract.
6. **Source media is never modified.**

## Cross-cutting timing

| Layer | Location |
| --- | --- |
| Per-clip story duration | `studio_transition.item_effective_seconds` / `studio_estimate.effective_seconds` |
| Multi-clip length + crossfade | `studio_transition.story_length_s`, `resolve_story_time` |
| Preview project time | `studio.js` `state.projectTimeS`, `resolveAt` |
| Export segments | `prepare_studio_export` → `FfmpegStudioEncoder` @ 30 fps CFR |

## Feature matrix

| Feature | Timing | Preview | Export | Parity | Tests | Manual tip |
| --- | --- | --- | --- | --- | --- | --- |
| Trim / edge drag | `studio_cut` + JS `edgeSourceAfterDrag` | Seek + handles | `-ss` / `-t` | **match** | `test_studio_cut.py`, `test_studio_edge.py` | First frame after trim matches scrub at clip start |
| Speed / slow bar | `studio_speed`, `studio_effect_lane` | `playbackRate`; mute in bar | Frame hold + mute | **match** time; **approx** motion | `test_studio_speed.py` | Story lengthens; audio silent in bar |
| Section repeat 1–8× | `section_playback_point` | Wrap seek | Slice joins | **match** hard cuts | `test_studio_section_repeat.py` | Count hard jumps |
| Loop to soundtrack | `studio_forward_loop` | Forward spans | Slices + one music bed | **match** length | `test_studio_forward_loop.py` | Music does not restart at joins |
| Loop crossfade / cinematic | Forward overlap | Dual-layer opacity | `xfade` | **approx** | `test_studio_forward_loop.py` | Ghosting possible both sides |
| Story transitions | `apply_boundaries` | Dual preview + black fade | `fade` / `xfade` | **match** timing; **approx** look | `test_studio_transition.py`, `test_studio_export_transitions.py` | Mid-crossfade both clips visible |
| Image grade | `studio_image` | CSS + SVG warmth | FFmpeg grade chain | **approx** | `test_studio_image.py` | Direction similar, not hex-equal |
| Saturation ramp | Same module | Extra `saturate()` | `hue=s` after grade | **approx** | `test_studio_saturation_ramp.py` | Mid-ramp less color |
| Overlays | Clip-relative times | DOM annotations | Pillow + overlay | **approx** | `test_studio_overlay.py` | In/out windows align |
| Privacy masks | Zoom-aware rects | Canvas (pixelate sharp) | `boxblur` / pixelate | **approx** | `test_studio_mask.py`, `test_studio_preview_blit.py` | Block size similar |
| Zoom / pan | `studio_frame` | `applyFrameToElement` | Crop before overlays | **match** framing | `test_studio_frame.py` | Same crop region |
| Flight map | Stored GPS + tiles | SVG + `/map-tiles/` | PIL + tile cache | **approx** tiles; plain fallback both | `test_studio_map.py` | Marker follows playhead |
| Telemetry HUD | `studio_hud` | `#studio-preview-hud` | `drawtext` | **match** fields/windows | `test_studio_hud.py` | Gaps stay blank |
| Soundtrack playlist | `music_mix` | `syncMusicAudio` | amix / concat | **match** length; **approx** fades | `test_studio_music.py` | Coverage tiles vs export audio |
| Title cards | Duration clamp | HTML card | Pillow still | **approx** | `test_studio_title_card.py` | Layout close |
| Clip audio lane | `studio_audio` | Detached `<audio>` | `atrim` / `adelay` | **match** | `test_studio_clip_audio.py` | Offset sound, picture unchanged |
| Export resolution / quality | `studio_export_resolution`, CRF presets | Source pane; no CRF sim | Scale + x264 CRF | **known gap** | `test_studio_export_resolution.py` | Preview size unchanged |

## Intentional approximations

| Area | Why different |
| --- | --- |
| Grade / ramp | sRGB CSS vs YUV FFmpeg filters (ADR 0011 / 0019) |
| Overlays / masks / titles | DOM/canvas vs Pillow/FFmpeg |
| Crossfades | Linear opacity vs `xfade` |
| Slow motion | Browser native fps vs 30 fps frame hold (no optical flow) |
| Map tiles | Fetch moment / cache may differ; plain panel when offline |

## Known gaps / asymmetries (not silent feature drops)

| Situation | Notes | Follow-up |
| --- | --- | --- |
| Proxy preview vs full-res export | Preview may look softer | Keep; document for users under [#186](https://github.com/Magehawks/orga-drone/issues/186) |
| Export WxH / CRF | Not simulated in preview | Expected; quality presets [#149](https://github.com/Magehawks/orga-drone/issues/149) |
| LUT / sharpen / denoise | Not shipping yet | Gate with [#172](https://github.com/Magehawks/orga-drone/issues/172) / [#174](https://github.com/Magehawks/orga-drone/issues/174)–[#177](https://github.com/Magehawks/orga-drone/issues/177) |
| Mask drag UX | Parity of placement covered by mask/zoom fixes; drag UX is [#179](https://github.com/Magehawks/orga-drone/issues/179) | Separate bug |
| Pixel A/B suite | No automated preview-frame vs MP4 frame diff in CI | Future optional; this issue ships the contract + matrix |

No reproducible timing/placement mismatch requiring a new fix ticket was found
beyond the intentional approximations above. Reuse existing issues for visual
follow-ups; do not open a rewrite.

## Regression matrix (manual Windows)

Use local media outside the repo (read-only). Export to a folder under the
user profile, never into the source library.

| # | Setup | Check at | Expect |
| --- | --- | --- | --- |
| 1 | Two clips, 1 s crossfade | Mid-boundary | Both visible; no black flash |
| 2 | Video trim via edges | Clip start / end | Matches preview scrub |
| 3 | Slow 0.5× bar mid-clip | Inside bar | Longer story; source audio muted |
| 4 | Section repeat 3× hard | Each join | Hard cut, same count |
| 5 | Grade + warmth + ramp | Mid-ramp | Direction matches export |
| 6 | Pixelate mask + 2× zoom | Mask center | Mask on zoomed window |
| 7 | Overlay text fade-in | Overlay start | Appears in both |
| 8 | HUD + SRT gaps | Gap time | Altitude blank both |
| 9 | Map with GPS | Mid-flight | Marker moves; offline plain both |
| 10 | Music playlist 2 songs | Song boundary | Audio switches once |
| 11 | Detached audio bar | Offset | Sound late, picture same |
| 12 | Title card only @ 1080 | Full card | Readable; layout close |
| 13 | Save / reopen project | After restart | Settings still applied in export |
| 14 | Cancel mid-export | During encode | Stops; no half-written replace of an existing good file |

## Automated coverage kept green

Run focused suites when touching render paths:

```text
pytest tests/test_studio_image.py tests/test_studio_mask.py tests/test_studio_frame.py tests/test_studio_hud.py tests/test_studio_transition.py tests/test_studio_export_transitions.py tests/test_studio_clip_audio.py tests/test_studio_forward_loop.py tests/test_studio_preview_blit.py -q
```

A small contract test asserts the shared story clock and documented
approximation markers stay present (`tests/test_studio_parity_contract.py`).

## Interaction with closed quality issues

| Issue | Role for #189 |
| --- | --- |
| [#137](https://github.com/Magehawks/orga-drone/issues/137) | Shared time mapping — prerequisite, closed |
| [#149](https://github.com/Magehawks/orga-drone/issues/149) | Quality presets — export-only; preview gap expected |
| [#150](https://github.com/Magehawks/orga-drone/issues/150) | Reimport/playability — keep regression if encoder flags change |
| [#168](https://github.com/Magehawks/orga-drone/issues/168) | Photo detail grade — separate from Studio Story MP4; still uses same `studio_image` math |

## Outcome

Acceptance for #189: documented parity contract, feature matrix with match /
approximate / known-gap, manual regression checklist, and an automated
contract smoke test. No silent omission of shipping adjustments. No render
engine rewrite.
