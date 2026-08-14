"""Unit tests for Studio export job store and progress percent."""

from __future__ import annotations

from pathlib import Path

from orga_drone.export.jobs import ExportJobStore, estimate_eta_s
from orga_drone.export.studio_encoder import (
    export_progress_percent,
    parse_ffmpeg_out_time_seconds,
)


def test_x264_preset_is_veryfast() -> None:
    from orga_drone.export.studio_encoder import X264_PRESET, _x264_video_args

    assert X264_PRESET == "veryfast"
    args = _x264_video_args()
    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[args.index("-preset") + 1] == "veryfast"


def test_segment_vf_forces_cfr_and_yuv420p() -> None:
    from orga_drone.export.studio_encoder import EXPORT_FPS, _segment_vf

    vf = _segment_vf(1920, 1080)
    assert f"fps={EXPORT_FPS}" in vf
    assert "format=yuv420p" in vf
    assert "1920:1080" in vf


def test_export_progress_percent_steps() -> None:
    assert export_progress_percent(clip_index=0, clip_total=3, phase="preparing") == 0
    assert (
        export_progress_percent(
            clip_index=1, clip_total=3, phase="rendering", clip_fraction=0.0
        )
        == 0
    )
    assert (
        export_progress_percent(
            clip_index=1, clip_total=3, phase="rendering", clip_fraction=0.5
        )
        == 12
    )
    assert (
        export_progress_percent(
            clip_index=1, clip_total=3, phase="rendering", clip_fraction=1.0
        )
        == 25
    )
    assert (
        export_progress_percent(
            clip_index=3, clip_total=3, phase="rendering", clip_fraction=1.0
        )
        == 75
    )
    assert export_progress_percent(clip_index=3, clip_total=3, phase="concat") == 75
    assert export_progress_percent(clip_index=3, clip_total=3, phase="done") == 100


def test_estimate_eta_s() -> None:
    assert estimate_eta_s(10.0, 0) is None
    assert estimate_eta_s(10.0, 4) is None
    assert estimate_eta_s(10.0, 50) == 10.0
    assert estimate_eta_s(20.0, 25) == 60.0
    assert estimate_eta_s(30.0, 100) is None


def test_parse_ffmpeg_out_time_seconds() -> None:
    assert parse_ffmpeg_out_time_seconds("out_time_ms=2500000") == 2.5
    assert parse_ffmpeg_out_time_seconds("out_time_us=1500000") == 1.5
    assert parse_ffmpeg_out_time_seconds("out_time=00:00:03.500000") == 3.5
    assert parse_ffmpeg_out_time_seconds("frame=12") is None


def test_export_job_store_lifecycle() -> None:
    store = ExportJobStore()
    job = store.try_create()
    assert job is not None
    assert store.try_create() is None
    store.mark_running(job.id, clip_total=2)
    store.apply_progress(
        job.id,
        {
            "phase": "rendering",
            "clip_index": 1,
            "clip_total": 2,
            "percent": 33,
            "current_label": "CLIP.MP4",
        },
    )
    mid = store.get(job.id)
    assert mid is not None
    assert mid.state == "running"
    assert mid.percent == 33
    payload = mid.to_dict()
    assert payload["current_label"] == "CLIP.MP4"
    assert "elapsed_s" in payload
    assert "eta_s" in payload
    assert payload["started_at"] is not None
    store.complete(job.id, output_path="/tmp/a.mp4", directory="/tmp")
    done = store.get(job.id)
    assert done is not None
    assert done.state == "completed"
    assert done.percent == 100
    assert done.output_path == "/tmp/a.mp4"
    assert done.to_dict()["eta_s"] is None
    assert done.to_dict()["filename"] == "a.mp4"
    last = store.get_last_success()
    assert last is not None
    assert last.job_id == job.id
    assert last.filename == "a.mp4"
    assert store.try_create() is not None


def test_last_success_survives_job_ttl() -> None:
    store = ExportJobStore(finished_ttl_s=0.0, max_finished=0)
    job = store.try_create()
    assert job is not None
    store.complete(job.id, output_path="/tmp/story.mp4", directory="/tmp")
    assert store.get(job.id) is None
    last = store.get_last_success()
    assert last is not None
    assert last.job_id == job.id
    assert Path(last.output_path) == Path("/tmp/story.mp4")
    assert last.filename == "story.mp4"
    assert last.directory == "/tmp"


def test_fail_does_not_clear_last_success() -> None:
    store = ExportJobStore()
    first = store.try_create()
    assert first is not None
    store.complete(first.id, output_path="/tmp/ok.mp4", directory="/tmp")
    second = store.try_create()
    assert second is not None
    store.fail(second.id, "encoder failed")
    last = store.get_last_success()
    assert last is not None
    assert last.job_id == first.id
    assert last.filename == "ok.mp4"
    failed = store.get(second.id)
    assert failed is not None
    assert failed.state == "failed"
