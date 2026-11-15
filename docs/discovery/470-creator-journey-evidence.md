# Creator journey evidence (#470)

Synthetic fixtures only. Shares collage helpers with WP5–WP7 / #463.
Does not replace PO testing on real DJI media (#283).

## Automated journey (`tests/test_creator_journey.py`)

| Scenario | Command / coverage | Result |
| --- | --- | --- |
| Multi-select → new project → clips present | `test_browse_multiselect_new_project_opens_with_clips` | PASS (local) |
| Empty start panel + seeded collage leaves | `test_browse_seed_collage_and_empty_start_panel` | PASS (local) |
| Hold last frame clock contract | `test_hold_last_frame_helper_matches_export_clock` (+ `tests/js/collage_playback.test.js`) | PASS (local) |
| Per-leaf grade → PNG/JPEG still + MP4 Story with trailing clip | `test_per_leaf_grade_still_and_story_with_following_clip` | PASS (local) |
| Mixed photo/video collage + missing media still render | `test_mixed_photo_video_collage_and_missing_media` | PASS (local) |
| Incomplete existing-project choice fails closed | `test_bulk_add_cancel_without_project_id_fails_closed` | PASS (local) |

Local command:

```text
python -m pytest tests/test_creator_journey.py -q
```

## Related coverage (not duplicated here)

| Area | Where |
| --- | --- |
| Browse Edit-in-Studio chooser | `tests/test_studio_bulk_add.py` (#466) |
| Empty-project start | `tests/test_studio_empty_start.py` (#467) |
| Collage seed | `tests/test_studio_collage_seed.py` (#468) |
| Leaf grades | `tests/test_studio_collage_leaf_grade.py` (#469) |
| Collage still/MP4 integration | `tests/test_studio_collage_integration.py` (#463) |

## Desktop / packaged

| Check | Status |
| --- | --- |
| WebView2 creator journey (Browse → Studio → Collage → Export) | **NOT_RUN** |
| Packaged EXE E2E | **NOT_RUN** (out of scope; no EXE/release in this mandate) |

## Preview / export parity note

Still PNG/JPEG and Story MP4 reuse the collage compositor / existing encoder path
(ADR 0038). This gate asserts publish success and source-file preservation on
synthetic media. Strict pixel parity against WebView2 preview remains **NOT_RUN**.
