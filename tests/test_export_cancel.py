"""Cancel a running Studio export (Issue #88)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.jobs import ExportJobStore
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import (
    ExportCancelled,
    FfmpegStudioEncoder,
    _run_ffmpeg,
    cancel_export_process,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from tests.test_studio_export import _seed_media


def test_cancel_frees_the_job_and_is_not_success() -> None:
    store = ExportJobStore()
    job = store.try_create()
    assert job is not None
    store.mark_running(job.id)
    event = store.request_cancel(job.id)
    assert event is not None
    assert event.is_set()
    assert store.get(job.id) is not None
    assert store.get(job.id).phase == "cancelling"  # type: ignore[union-attr]
    store.finish_cancelled(job.id)
    finished = store.get(job.id)
    assert finished is not None
    assert finished.state == "cancelled"
    assert finished.output_path is None
    assert store.get_last_success() is None
    assert store.try_create() is not None
    assert store.request_cancel("missing") is None


def test_ffmpeg_cancel_stops_quickly_and_keeps_existing_bytes(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    existing = tmp_path / "story.mp4"
    existing.write_bytes(b"original-export")
    event = threading.Event()
    started = time.monotonic()

    def trip() -> None:
        time.sleep(0.3)
        cancel_export_process(event)

    threading.Thread(target=trip, daemon=True).start()
    with pytest.raises(ExportCancelled):
        _run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x180:r=30:d=120",
                str(tmp_path / "long.mp4"),
            ],
            cancel_event=event,
        )
    assert time.monotonic() - started < 5
    assert existing.read_bytes() == b"original-export"
    assert list(tmp_path.glob("*.partial")) == []


def test_render_cancel_before_publish_leaves_destination(tmp_path: Path) -> None:
    still = tmp_path / "still.jpg"
    still.write_bytes(b"still")
    dest = tmp_path / "out" / "story.mp4"
    dest.parent.mkdir()
    dest.write_bytes(b"keep")
    event = threading.Event()
    event.set()
    clip = StudioExportClip(source_path=still, kind="photo", duration_s=30.0)
    config = StudioExportConfig(
        output_path=dest,
        width=320,
        height=180,
        clips=(clip,),
    )
    with pytest.raises(ExportCancelled):
        FfmpegStudioEncoder().render(config, cancel_event=event)
    assert dest.read_bytes() == b"keep"
    assert list(dest.parent.glob("*.partial")) == []


def test_http_cancel_then_export_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    calls = {"n": 0}

    class _SlowEncoder:
        def render(  # type: ignore[no-untyped-def]
            self,
            config: StudioExportConfig,
            *,
            on_progress=None,
            cancel_event=None,
        ) -> Path:
            calls["n"] += 1
            if calls["n"] == 1:
                while cancel_event is None or not cancel_event.is_set():
                    time.sleep(0.02)
                raise ExportCancelled()
            config.output_path.write_bytes(b"second")
            return config.output_path

    import orga_drone.studio_export as studio_export

    monkeypatch.setattr(studio_export, "get_default_encoder", lambda: _SlowEncoder())
    app = create_app()
    db: Database = app.state.db
    media_id = _seed_media(db, tmp_path / "lib")
    item = db.get_media(media_id)
    assert item is not None
    db.add_studio_item(
        item.path,
        identity_key=make_identity_key(
            item.filename, item.size_bytes, item.recorded_at
        ),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        source_media_id=media_id,
    )
    client = TestClient(app)
    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="studio-export-cancel"' in page.text
    assert 'type="button"' in page.text
    assert ("Export abbrechen" in page.text) or ("Cancel export" in page.text)
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "/cancel" in script
    assert "exportCancelBtn.disabled = running" not in script

    out = tmp_path / "Videos" / "story.mp4"
    out.parent.mkdir()
    out.write_bytes(b"already-there")
    started = client.post(
        "/api/studio/export",
        json={"height": 720, "output_path": str(out), "overwrite": True},
    )
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    cancelled = client.post(f"/api/studio/export/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    body = None
    for _ in range(50):
        job = client.get(f"/api/studio/export/jobs/{job_id}")
        body = job.json()
        if body["state"] == "cancelled":
            break
        time.sleep(0.05)
    assert body is not None
    assert body["state"] == "cancelled"
    assert body["output_path"] is None
    assert out.read_bytes() == b"already-there"
    assert db.list_studio_items()
    missing = client.post("/api/studio/export/jobs/nope/cancel")
    assert missing.status_code == 404

    again = client.post(
        "/api/studio/export",
        json={"height": 720, "output_path": str(out), "overwrite": True},
    )
    assert again.status_code == 200
    second = again.json()["job_id"]
    done = None
    for _ in range(50):
        job = client.get(f"/api/studio/export/jobs/{second}")
        done = job.json()
        if done["state"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.05)
    assert done is not None
    assert done["state"] == "completed"
    assert out.read_bytes() == b"second"
