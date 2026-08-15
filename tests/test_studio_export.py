"""HTTP / service tests for Studio export options and destination (Issue #17)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig, StudioExportMusic
from orga_drone.export.studio_encoder import (
    FfmpegStudioEncoder,
    StudioExportError,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_export import prepare_studio_export, probe_video_dimensions, run_studio_export


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
    assert job_body["filename"] == "Alps Cut.mp4"
    assert "open_available" in job_body
    assert "reveal_available" in job_body
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


def test_encoder_silent_video_fallback_preserves_source_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")

    source = tmp_path / "silent-source.mp4"
    generated = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x48:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x48:r=30:d=1",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stderr
    source_bytes = source.read_bytes()

    from orga_drone.export import studio_encoder as encoder_module

    commands: list[list[str]] = []
    real_run_ffmpeg = encoder_module._run_ffmpeg

    def recording_run_ffmpeg(cmd, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(cmd.copy())
        return real_run_ffmpeg(cmd, **kwargs)

    monkeypatch.setattr(encoder_module, "_run_ffmpeg", recording_run_ffmpeg)
    output = tmp_path / "trimmed.mp4"
    config = StudioExportConfig(
        output_path=output,
        width=64,
        height=48,
        clips=(
            StudioExportClip(
                source_path=source,
                kind="video",
                duration_s=2.0,
                source_start_s=1.0,
                source_end_s=1.6,
            ),
        ),
    )

    assert FfmpegStudioEncoder().render(config) == output
    assert source.read_bytes() == source_bytes
    assert any("0:a:0" in cmd for cmd in commands)
    silent_commands = [
        cmd
        for cmd in commands
        if "anullsrc=channel_layout=stereo:sample_rate=48000" in cmd
    ]
    assert len(silent_commands) == 1
    silent_cmd = silent_commands[0]
    assert silent_cmd.index("-ss") > silent_cmd.index(
        "anullsrc=channel_layout=stereo:sample_rate=48000"
    )

    probed = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert "Audio: aac" in probed.stderr
    duration_match = re.search(
        r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probed.stderr
    )
    assert duration_match is not None
    hours, minutes, seconds = duration_match.groups()
    duration_s = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    assert duration_s == pytest.approx(0.6, abs=0.15)

    first_frame = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(output),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=False,
        capture_output=True,
    )
    assert first_frame.returncode == 0, first_frame.stderr.decode(errors="replace")
    assert len(first_frame.stdout) == 64 * 48 * 3
    center = (24 * 64 + 32) * 3
    red, _green, blue = first_frame.stdout[center : center + 3]
    assert blue > red + 100


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


def test_ffmpeg_error_message_prefers_timebase_over_encoder_eof() -> None:
    from orga_drone.export.studio_encoder import _ffmpeg_error_message

    stderr = (
        "[Parsed_xfade_8 @ 0] First input link main timebase (1/1000000) "
        "do not match the corresponding second input link xfade timebase (1/15360)\n"
        "[Parsed_xfade_8 @ 0] Failed to configure output pad on Parsed_xfade_8\n"
        "[aost#0:1/aac @ 0] Could not open encoder before EOF\n"
        "Conversion failed!\n"
    )
    msg = _ffmpeg_error_message(stderr)
    assert "timebase" in msg.lower()
    assert "aost#0:1" not in msg


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


def _studio_export_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    return app, TestClient(app)


def test_export_open_uses_last_success_not_client_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client = _studio_export_app(tmp_path, monkeypatch)
    opened: list[Path] = []
    monkeypatch.setattr("orga_drone.desktop.can_open_local_file", lambda: True)
    monkeypatch.setattr(
        "orga_drone.desktop.open_local_file", lambda path: opened.append(path)
    )

    exported = tmp_path / "Videos" / "story.mp4"
    exported.parent.mkdir(parents=True)
    exported.write_bytes(b"mp4-bytes")
    decoy = tmp_path / "Videos" / "evil.mp4"
    decoy.write_bytes(b"nope")

    job = app.state.export_jobs.try_create()
    assert job is not None
    app.state.export_jobs.complete(
        job.id,
        output_path=str(exported.resolve()),
        directory=str(exported.parent.resolve()),
    )

    res = client.post(
        "/api/studio/export/open",
        json={"path": str(decoy.resolve())},
    )
    assert res.status_code == 200
    assert res.json() == {
        "ok": True,
        "action": "open",
        "filename": "story.mp4",
    }
    assert opened == [Path(str(exported.resolve()))]


def test_export_reveal_uses_last_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client = _studio_export_app(tmp_path, monkeypatch)
    revealed: list[Path] = []
    monkeypatch.setattr("orga_drone.desktop.can_reveal_local_file", lambda: True)
    monkeypatch.setattr(
        "orga_drone.desktop.reveal_local_file", lambda path: revealed.append(path)
    )

    exported = tmp_path / "story.mp4"
    exported.write_bytes(b"mp4-bytes")
    job = app.state.export_jobs.try_create()
    assert job is not None
    app.state.export_jobs.complete(
        job.id,
        output_path=str(exported.resolve()),
        directory=str(exported.parent.resolve()),
    )

    res = client.post("/api/studio/export/reveal")
    assert res.status_code == 200
    assert res.json() == {
        "ok": True,
        "action": "reveal",
        "filename": "story.mp4",
    }
    assert revealed == [Path(str(exported.resolve()))]


def test_export_open_404_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client = _studio_export_app(tmp_path, monkeypatch)
    monkeypatch.setattr("orga_drone.desktop.can_open_local_file", lambda: True)
    opened: list[Path] = []
    monkeypatch.setattr(
        "orga_drone.desktop.open_local_file", lambda path: opened.append(path)
    )

    exported = tmp_path / "gone.mp4"
    exported.write_bytes(b"mp4-bytes")
    job = app.state.export_jobs.try_create()
    assert job is not None
    app.state.export_jobs.complete(
        job.id,
        output_path=str(exported.resolve()),
        directory=str(exported.parent.resolve()),
    )
    exported.unlink()

    res = client.post("/api/studio/export/open")
    assert res.status_code == 404
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "missing_file"
    assert opened == []


def test_export_open_404_without_last_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, client = _studio_export_app(tmp_path, monkeypatch)
    monkeypatch.setattr("orga_drone.desktop.can_open_local_file", lambda: True)
    res = client.post("/api/studio/export/open")
    assert res.status_code == 404
    assert res.json()["error"] == "missing_file"


def test_export_open_503_when_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client = _studio_export_app(tmp_path, monkeypatch)
    monkeypatch.setattr("orga_drone.desktop.can_open_local_file", lambda: False)
    exported = tmp_path / "story.mp4"
    exported.write_bytes(b"mp4")
    job = app.state.export_jobs.try_create()
    assert job is not None
    app.state.export_jobs.complete(
        job.id,
        output_path=str(exported.resolve()),
        directory=str(exported.parent.resolve()),
    )
    res = client.post("/api/studio/export/open")
    assert res.status_code == 503
    assert res.json() == {"status": "unavailable", "error": "open_unavailable"}


def test_export_reveal_503_when_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, client = _studio_export_app(tmp_path, monkeypatch)
    monkeypatch.setattr("orga_drone.desktop.can_reveal_local_file", lambda: False)
    res = client.post("/api/studio/export/reveal")
    assert res.status_code == 503
    assert res.json() == {"status": "unavailable", "error": "reveal_unavailable"}


def test_prepare_export_without_music_skips_mix(
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
    config = prepare_studio_export(db, height=720, output_path=out, overwrite=True)
    assert config.music is None


def test_prepare_export_missing_music_fails(
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
    song = tmp_path / "gone.mp3"
    song.write_bytes(b"ID3")
    project = db.ensure_default_studio_project()
    db.set_studio_music(project.id, str(song.resolve()))
    song.unlink()
    with pytest.raises(StudioExportError) as exc:
        prepare_studio_export(
            db, height=720, output_path=tmp_path / "out.mp4", overwrite=True
        )
    assert exc.value.code == "music_missing"


def test_fake_encoder_receives_music_config(
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
    source_bytes = Path(item.path).read_bytes()
    db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        source_media_id=mid,
    )
    song = tmp_path / "bed.mp3"
    song.write_bytes(b"ID3music")
    project = db.ensure_default_studio_project()
    db.set_studio_music(project.id, str(song.resolve()))
    monkeypatch.setattr(
        "orga_drone.export.music_mix.require_readable_music",
        lambda path: 4.0,
    )
    monkeypatch.setattr(
        "orga_drone.studio_export.require_readable_music",
        lambda path: 4.0,
        raising=False,
    )
    from orga_drone.export import music_mix as mix_mod

    monkeypatch.setattr(mix_mod, "require_readable_music", lambda path: 4.0)

    out = tmp_path / "out.mp4"
    fake = _FakeEncoder()
    result = run_studio_export(
        db, height=720, output_path=out, overwrite=True, encoder=fake
    )
    assert result == out
    assert fake.configs and fake.configs[0].music is not None
    assert fake.configs[0].music.source_path == song.resolve()
    assert fake.configs[0].music.volume == 0.8
    assert Path(item.path).read_bytes() == source_bytes
    assert song.read_bytes() == b"ID3music"


def test_encoder_records_amix_when_music_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")

    video = tmp_path / "clip.mp4"
    made_video = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x48:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(video),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert made_video.returncode == 0, made_video.stderr
    music = tmp_path / "bed.wav"
    made_music = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=0.4",
            str(music),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert made_music.returncode == 0, made_music.stderr
    source_bytes = video.read_bytes()
    music_bytes = music.read_bytes()

    from orga_drone.export import studio_encoder as encoder_module

    commands: list[list[str]] = []
    real_run = encoder_module._run_ffmpeg

    def recording_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(cmd.copy())
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(encoder_module, "_run_ffmpeg", recording_run)
    output = tmp_path / "mixed.mp4"
    config = StudioExportConfig(
        output_path=output,
        width=64,
        height=48,
        clips=(
            StudioExportClip(
                source_path=video,
                kind="video",
                duration_s=1.0,
                source_start_s=0.0,
                source_end_s=1.0,
            ),
        ),
        music=StudioExportMusic(
            source_path=music,
            volume=0.5,
            fade_in_s=0.1,
            fade_out_s=0.1,
            loop=False,
            duration_s=0.4,
        ),
    )
    assert FfmpegStudioEncoder().render(config) == output
    assert video.read_bytes() == source_bytes
    assert music.read_bytes() == music_bytes
    mix_cmds = [cmd for cmd in commands if "-filter_complex" in cmd]
    assert mix_cmds
    graph = mix_cmds[-1][mix_cmds[-1].index("-filter_complex") + 1]
    assert "volume=0.5" in graph
    assert "afade=" in graph
    assert "amix=" in graph
    assert "-c:v" in mix_cmds[-1]
    assert mix_cmds[-1][mix_cmds[-1].index("-c:v") + 1] == "copy"

    looped = tmp_path / "looped.mp4"
    loop_config = StudioExportConfig(
        output_path=looped,
        width=64,
        height=48,
        clips=config.clips,
        music=StudioExportMusic(
            source_path=music,
            volume=0.5,
            fade_in_s=0.0,
            fade_out_s=0.0,
            loop=True,
            duration_s=0.4,
        ),
    )
    assert FfmpegStudioEncoder().render(loop_config) == looped
    loop_cmds = [cmd for cmd in commands if "-stream_loop" in cmd]
    assert loop_cmds
    assert loop_cmds[-1][loop_cmds[-1].index("-stream_loop") + 1] == "-1"
