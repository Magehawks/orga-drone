"""One export-only frame projection for a Story containing variable speed."""

from __future__ import annotations

from dataclasses import replace

from orga_drone.export.studio_config import StudioExportClip


def frame_index(seconds: float) -> int:
    return int(seconds * 30 + 0.5 + 1e-8)


def plan_story_frames(
    clips: tuple[StudioExportClip, ...],
) -> tuple[tuple[StudioExportClip, ...], tuple[StudioExportClip, ...]]:
    if not any(clip.speed_ramp is not None for clip in clips):
        return clips, clips
    render, stitch = [], []
    cursor = 0.0
    for index, clip in enumerate(clips):
        end = cursor + clip.duration_s
        count = frame_index(end) - frame_index(cursor)
        overlap = (
            clip.transition_s
            if index + 1 < len(clips) and clip.transition_type == "crossfade"
            else 0.0
        )
        overlap_frames = frame_index(end) - frame_index(end - overlap)
        if count > 0:
            render.append(
                replace(clip, export_frame_origin_s=cursor, export_frame_count=count)
            )
            stitch.append(
                replace(
                    clip,
                    duration_s=count / 30,
                    transition_s=overlap_frames / 30,
                    export_frame_origin_s=cursor,
                    export_frame_count=count,
                )
            )
        cursor = end - overlap
    return tuple(render), tuple(stitch)
