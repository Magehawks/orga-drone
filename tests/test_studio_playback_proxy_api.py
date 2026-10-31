"""Experimental single-clip LUT proxy playback API (Issue #223)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageStat

from orga_drone.config import Settings
from orga_drone.db import make_identity_key
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs


def _run(ffmpeg: str, *args: str) -> None:
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )


def _write_cube(path: Path) -> None:
    lines = ['TITLE "Synthetic channel transform"', "LUT_3D_SIZE 2"]
    for b in (0, 1):
        for g in (0, 1):
            for r in (0, 1):
                lines.append(f"{0.2 + r * 0.7} {g * 0.65} {b * 0.8}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _frame_mean(ffmpeg: str, video: Path, t_s: float, dest: Path) -> float:
    _run(ffmpeg, "-ss", str(t_s), "-i", str(video), "-frames:v", "1", str(dest))
    with Image.open(dest) as image:
        return ImageStat.Stat(image.convert("L")).mean[0]


def _first_silence_end(ffmpeg: str, video: Path) -> float:
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(video),
            "-af",
            "silencedetect=noise=-30dB:d=0.05",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        **subprocess_no_window_kwargs(),
    )
    for line in proc.stderr.splitlines():
        if "silence_end:" in line:
            return float(line.split("silence_end:")[1].split("|")[0].strip())
    raise AssertionError(proc.stderr)


def test_proxy_api_playback_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    from orga_drone.app import create_app

    data_dir = tmp_path / "data"
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=data_dir))
    app = create_app()
    db = app.state.db
    root = tmp_path / "media"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    video = root / "clip.mp4"
    _run(
        ffmpeg,
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x180:r=30:d=3,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='between(t,1,1.1)'",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=3",
        "-af",
        "volume=enable='not(between(t,1,1.2))':volume=0",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(video),
    )
    original_hash = hashlib.sha256(video.read_bytes()).hexdigest()
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": video.name,
            "path": str(video.resolve()),
            "size_bytes": video.stat().st_size,
            "duration_s": 3.0,
            "recorded_at": "2024-01-01T00:00:00",
            "sequence": None,
            "mode": None,
            "drone_model": None,
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    client = TestClient(app)
    cube = tmp_path / "boost.cube"
    _write_cube(cube)
    imported = client.post("/api/studio/luts", json={"path": str(cube)})
    assert imported.status_code == 200
    asset = imported.json()["asset_name"]
    colored = client.patch(
        f"/api/studio/{clip_id}/color",
        json={"creative_lut": asset, "creative_strength": 100},
    )
    assert colored.status_code == 200

    url = f"/api/studio/{clip_id}/playback-proxy?lut_proxy=1"
    assert client.get(url).status_code == 404
    assert client.get(url.replace("?lut_proxy=1", "")).status_code == 404
    assert client.post(url.replace("?lut_proxy=1", "")).status_code == 404
    built = client.post(url)
    assert built.status_code == 200, built.text
    payload = built.json()
    assert payload["bytes"] > 0
    assert payload["generation_s"] >= 0
    assert payload["url"] == url

    served = client.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("video/mp4")
    assert served.headers.get("x-orga-lut-proxy") == "1"
    assert served.headers["cache-control"] == "no-store"
    ranged = client.get(url, headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206
    assert len(ranged.content) == 100

    page = client.get("/studio?lut_proxy=1")
    assert page.status_code == 200
    assert 'data-lut-proxy-enabled="1"' in page.text
    assert f'data-lut-proxy-url="{url}"' in page.text
    disabled = client.get("/studio")
    assert 'data-lut-proxy-enabled="0"' in disabled.text
    assert f'data-lut-proxy-url="{url}"' not in disabled.text

    proxy_files = list((data_dir / "playback-proxies").glob("*.mp4"))
    assert len(proxy_files) == 1
    proxy = proxy_files[0]
    assert proxy.parent != video.parent
    assert hashlib.sha256(video.read_bytes()).hexdigest() == original_hash

    source_onset = _first_silence_end(ffmpeg, video)
    proxy_onset = _first_silence_end(ffmpeg, proxy)
    assert abs(proxy_onset - source_onset) < 0.1
    source_dark = _frame_mean(ffmpeg, video, 0.9, tmp_path / "source-dark.png")
    proxy_dark = _frame_mean(ffmpeg, proxy, 0.9, tmp_path / "dark.png")
    source_flash = _frame_mean(ffmpeg, video, 1.05, tmp_path / "source-flash.png")
    proxy_flash = _frame_mean(ffmpeg, proxy, 1.05, tmp_path / "flash.png")
    assert source_dark < 30 and proxy_dark < 30
    assert source_flash > 120 and proxy_flash > 120

    started = time.perf_counter()
    _run(ffmpeg, "-ss", "2", "-i", str(proxy), "-frames:v", "1", "-f", "null", "-")
    seek_s = time.perf_counter() - started
    assert seek_s < 2.0
    print(json.dumps({
        "generation_s": payload["generation_s"],
        "bytes": payload["bytes"],
        "seek_s": round(seek_s, 3),
        "audio_onset_delta_s": round(proxy_onset - source_onset, 3),
    }))

    changed = client.patch(
        f"/api/studio/{clip_id}/color",
        json={"creative_lut": asset, "creative_strength": 50},
    )
    assert changed.status_code == 200
    assert client.get(url).status_code == 404
