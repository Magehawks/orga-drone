"""HTTP / service tests for Studio export options and destination (Issue #17)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportConfig
from orga_drone.export.studio_encoder import StudioExportError
from orga_drone.studio_export import probe_video_dimensions, run_studio_export


_FFMPEG_I_STDERR = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Stream #0:0(und): Video: hevc (Main 10) (hvc1 / 0x31637668), yuv420p10le(tv, bt709), 3840x2160, 119896 kb/s, 59.94 fps
  Stream #0:1(und): Data: none (djmd / 0x646D6A64), 131 kb/s
  Stream #0:2: Video: mjpeg (Baseline), yuvj420p(pc, bt470bg/unknown/unknown), 1280x720 [SAR 1:1 DAR 16:9], 90k tbr (attached pic)
"""


def test_probe_video_dimensions_ffmpeg_fallback_skips_attached_pic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")

    monkeypatch.setattr("orga_drone.ffmpeg_bin.find_ffprobe", lambda: None)
    monkeypatch.setattr(
        "orga_drone.ffmpeg_bin.find_ffmpeg", lambda: "ffmpeg-fake"
    )

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[0] == "ffmpeg-fake"
        assert "-i" in cmd
        return SimpleNamespace(returncode=1, stdout="", stderr=_FFMPEG_I_STDERR)

    monkeypatch.setattr("subprocess.run", fake_run)
    assert probe_video_dimensions(media) == (3840, 2160)


def test_probe_video_dimensions_prefers_ffprobe_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")
    monkeypatch.setattr("orga_drone.ffmpeg_bin.find_ffprobe", lambda: "ffprobe-fake")

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[0] == "ffprobe-fake"
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"streams":[{"codec_type":"video","width":1920,"height":1080,'
                '"disposition":{"attached_pic":0}},'
                '{"codec_type":"video","width":320,"height":240,'
                '"disposition":{"attached_pic":1}}]}'
            ),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    assert probe_video_dimensions(media) == (1920, 1080)


def _seed_media(
    db: Database,
    root_path: Path,
    *,
    filename: str = "CLIP.MP4",
    kind: str = "video",
    duration_s: float | None = 5.0,
    width: int | None = 1920,
    height: int | None = 1080,
    content: bytes = b"fake",
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="lib")
    media_file = root_path / filename
    media_file.write_bytes(content)
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": len(content),
            "duration_s": duration_s,
            "width": width,
            "height": height,
            "recorded_at": "2024-01-02T10:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": "Avata 2",
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    return mid


class _FakeEncoder:
    def __init__(self) -> None:
        self.configs: list[StudioExportConfig] = []
        self.progress: list[dict] = []

    def render(self, config: StudioExportConfig, *, on_progress=None) -> Path:  # type: ignore[no-untyped-def]
        self.configs.append(config)
        total = len(config.clips)
        if on_progress is not None:
            for index, clip in enumerate(config.clips, start=1):
                label = clip.source_path.name
                for frac in (0.0, 0.5, 1.0):
                    evt = {
                        "phase": "rendering",
                        "clip_index": index,
                        "clip_total": total,
                        "percent": int(round(100 * ((index - 1) + frac) / (total + 1))),
                        "current_label": label,
                    }
                    self.progress.append(evt)
                    on_progress(evt)
            concat = {
                "phase": "concat",
                "clip_index": total,
                "clip_total": total,
                "percent": int(round(100 * total / (total + 1))),
                "current_label": None,
            }
            self.progress.append(concat)
            on_progress(concat)
            done = {
                "phase": "done",
                "clip_index": total,
                "clip_total": total,
                "percent": 100,
                "current_label": None,
            }
            self.progress.append(done)
            on_progress(done)
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_bytes(b"mp4-bytes")
        return config.output_path


def test_http_export_options_and_fake_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    mid = _seed_media(db, tmp_path / "lib", height=2160, width=3840)
    item = db.get_media(mid)
    assert item is not None
    db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        source_media_id=mid,
    )
    db.set_studio_project_title(db.ensure_default_studio_project().id, "Alps Cut")
    c = TestClient(app)

    opts = c.get("/api/studio/export/options")
    assert opts.status_code == 200
    body = opts.json()
    assert body["ok"] is True
    assert body["suggested_filename"] == "Alps Cut.mp4"
    assert body["default_height"] == 1080
    assert [o["height"] for o in body["options"]] == [720, 1080, 1440, 2160]
    assert any(o["recommended"] for o in body["options"] if o["height"] == 1080)

    out = tmp_path / "Videos" / "Alps Cut.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    fake = _FakeEncoder()
    import orga_drone.studio_export as se

    monkeypatch.setattr(se, "get_default_encoder", lambda: fake)

    export = c.post(
        "/api/studio/export",
        json={"height": 1080, "output_path": str(out), "overwrite": False},
    )
    assert export.status_code == 200
    started = export.json()
    assert started["ok"] is True
    assert started.get("job_id")

    job_body = None
    for _ in range(50):
        job = c.get(f"/api/studio/export/jobs/{started['job_id']}")
        assert job.status_code == 200
        job_body = job.json()
        if job_body["state"] in {"completed", "failed"}:
            break
        import time

        time.sleep(0.05)
    assert job_body is not None
    assert job_body["state"] == "completed"
    assert job_body["percent"] == 100
    assert job_body["output_path"] == str(out.resolve())
    assert "elapsed_s" in job_body
    assert fake.progress and fake.progress[0].get("current_label")
    assert out.is_file()
    assert fake.configs and fake.configs[0].height == 1080
    assert fake.configs[0].width == 1920
    assert fake.progress
    # Source media untouched
    assert (tmp_path / "lib" / "CLIP.MP4").read_bytes() == b"fake"


def test_run_studio_export_refuses_missing_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_media(db, tmp_path / "lib", height=720, width=1280)
    item = db.get_media(mid)
    assert item is not None
    db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        source_media_id=mid,
    )
    out = tmp_path / "out.mp4"
    out.write_bytes(b"old")
    fake = _FakeEncoder()
    with pytest.raises(StudioExportError, match="already exists"):
        run_studio_export(
            db,
            height=720,
            output_path=out,
            overwrite=False,
            encoder=fake,
        )
    assert out.read_bytes() == b"old"
    run_studio_export(
        db,
        height=720,
        output_path=out,
        overwrite=True,
        encoder=fake,
    )
    assert out.read_bytes() == b"mp4-bytes"


def test_materialize_photo_still_heic_like(tmp_path: Path) -> None:
    from PIL import Image

    from orga_drone.export.studio_encoder import _materialize_photo_still

    src = tmp_path / "shot.HEIC"
    # Write a real JPEG with HEIC suffix — Pillow opens by content; production
    # HEIC uses pillow-heif. This asserts the export still path works.
    Image.new("RGB", (64, 48), (10, 20, 30)).save(src, "JPEG")
    dest = tmp_path / "still.jpg"
    out = _materialize_photo_still(src, dest)
    assert out.is_file()
    with Image.open(out) as img:
        assert img.size == (64, 48)


def test_run_ffmpeg_progress_does_not_pipe_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: piping stderr+stdout deadlocks ffmpeg on Windows."""
    from orga_drone.export import studio_encoder as se

    out = tmp_path / "seg.mp4"
    captured: dict = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):  # type: ignore[no-untyped-def]
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            self.stdout = iter(
                [
                    "out_time_ms=500000\n",
                    "progress=end\n",
                ]
            )
            self.stderr = None
            self.returncode = 0

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr(se.subprocess, "Popen", _FakePopen)
    times: list[float] = []
    se._run_ffmpeg(
        ["ffmpeg", "-y", "-i", "in.mp4", str(out)],
        on_time=times.append,
        duration_s=2.0,
    )
    assert times and times[0] == 0.5
    assert captured["kwargs"]["stdout"] is se.subprocess.PIPE
    # stderr must be a file object, never PIPE
    assert captured["kwargs"]["stderr"] is not se.subprocess.PIPE
    assert hasattr(captured["kwargs"]["stderr"], "write")


def test_ffmpeg_error_message_strips_banner() -> None:
    from orga_drone.export.studio_encoder import _ffmpeg_error_message

    banner = (
        "ffmpeg version 7.1 Copyright\n"
        "libavformat 61. 7.100 / 61. 7.100\n"
        "Option loop not found.\n"
        "Error opening input file IMG_9323.HEIC.\n"
        "Error opening input files: Option not found\n"
    )
    msg = _ffmpeg_error_message(banner)
    assert "libavformat" not in msg
    assert "Option loop not found" in msg
    assert "IMG_9323.HEIC" in msg


def test_export_options_without_video_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    mid = _seed_media(
        db,
        tmp_path / "lib",
        filename="P.JPG",
        kind="photo",
        duration_s=None,
        width=None,
        height=None,
        content=b"jpg",
    )
    item = db.get_media(mid)
    assert item is not None
    db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        source_media_id=mid,
    )
    c = TestClient(app)
    body = c.get("/api/studio/export/options").json()
    assert body["options"] == []
    assert body["default_height"] is None
    assert body["has_video_resolution"] is False
