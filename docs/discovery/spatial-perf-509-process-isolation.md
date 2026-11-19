# Spatial photo bake process isolation (#509) + in-flight dedupe (#510)

Date: 2026-11-19  
Parent: #506  
Base: `develop` @ `1e20899` (after #515/#516)

## Problem

Full-resolution spatial CPU bakes ran inside the desktop process (export job
thread / `asyncio.to_thread`). Pure-Python mask evaluation saturated the GIL;
HTTP status/cancel timed out while the process stayed alive (Neon Relic
incident protocol).

## Change

1. **Process isolation** (`studio_spatial_bake_process.py`): photo
   `_grade_rgb_image` runs in a `spawn` child when pixel count ≥ 96²
   (override with `ORGA_SPATIAL_BAKE_PROCESS` / `ORGA_SPATIAL_BAKE_INLINE`).
2. **Cancel**: parent polls `cancel_event`, terminates/kills the child, deletes
   temp output, never publishes `graded.png`.
3. **In-flight dedupe**: concurrent `materialize_spatial_managed_media` calls
   for the same work directory wait on one owner bake (#510).
4. Still export passes `cancel_event` into spatial materialize.
5. `multiprocessing.freeze_support()` in `__main__` for frozen Windows builds.

## Non-scope

- Video spatial bake process isolation (still uses existing ffmpeg cancel).
- GPU path (#511).
- Preview path already clamped to 512px (#508); remains in-thread.

## Tests

`tests/test_spatial_bake_process.py` — threshold, process publish, concurrent
dedupe, cancel-before-bake, fake-process terminate on cancel.
