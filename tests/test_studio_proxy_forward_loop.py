"""Forward-loop playback proxy parity (issue #294 Phase B).

Phase A kept looped clips proxy-ineligible. Phase B reuses one graded proxy
cycle and maps wraps/overlaps in proxy-local time so HSL/LUT stay visible
during forward-loop and section-repeat playback.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _run(*args: str) -> None:
    subprocess.run(
        [find_ffmpeg() or "ffmpeg", "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )


def _seed_video(db: Database, root: Path, filename: str, *, duration_s: float = 3.0) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    _run(
        "-f", "lavfi", "-i", f"color=c=red:s=320x180:r=30:d={duration_s:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(media_file),
    )
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": float(duration_s),
            "recorded_at": "2024-06-01T12:00:00",
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
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    return clip_id


def _seed_soundtrack(db: Database, tmp_path: Path, *, duration_s: float = 30.0) -> None:
    project = db.resolve_studio_page_project()
    assert project is not None
    music = tmp_path / "music"
    music.mkdir(exist_ok=True)
    song = music / "bed.mp3"
    song.write_bytes(b"ID3fake")
    original = db._probe_music_duration_s
    db._probe_music_duration_s = lambda _path: float(duration_s)  # type: ignore[method-assign,assignment]
    try:
        db.append_studio_music(project.id, str(song.resolve()))
    finally:
        db._probe_music_duration_s = original  # type: ignore[method-assign]


def _apply_lut(client: TestClient, tmp_path: Path, clip_id: int) -> str:
    cube = tmp_path / "boost.cube"
    lines = ['TITLE "Boost"', "LUT_3D_SIZE 2"] + ["0.2 0.5 0.8"] * 7 + ["1 1 1"]
    cube.write_text("\n".join(lines) + "\n", encoding="utf-8")
    imported = client.post("/api/studio/luts", json={"path": str(cube)})
    assert imported.status_code == 200
    asset = imported.json()["asset_name"]
    colored = client.patch(
        f"/api/studio/{clip_id}/color",
        json={"input_profile": "rec709", "creative_lut": asset, "creative_strength": 80},
    )
    assert colored.status_code == 200
    return asset


def test_forward_loop_clip_builds_and_advertises_a_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A forward-loop clip with a LUT is proxy-eligible: build succeeds and the
    Studio page advertises the same single-cycle proxy URL."""
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_video(db, tmp_path / "videos", "LOOP.MP4")
    _apply_lut(client, tmp_path, clip_id)
    _seed_soundtrack(db, tmp_path)
    url = f"/api/studio/{clip_id}/playback-proxy"

    looped = client.patch(f"/api/studio/{clip_id}/forward-loop", json={"enabled": True})
    assert looped.status_code == 200
    built = client.post(url)
    assert built.status_code == 200, built.text
    page = client.get("/studio")
    assert f'data-lut-proxy-url="{url}"' in page.text
    proxies = list((tmp_path / "data" / "playback-proxies").glob("*.mp4"))
    assert len(proxies) == 1
    assert proxies[0].stat().st_size > 0


def test_manual_section_repeats_build_and_advertise_a_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_video(db, tmp_path / "videos", "REPEAT.MP4")
    _apply_lut(client, tmp_path, clip_id)
    url = f"/api/studio/{clip_id}/playback-proxy"
    repeated = client.patch(
        f"/api/studio/{clip_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 2.0, "repeats": 3},
    )
    assert repeated.status_code == 200
    assert client.post(url).status_code == 200
    assert f'data-lut-proxy-url="{url}"' in client.get("/studio").text


def test_loop_cause_chip_messages_remain_for_proxy_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Truthful loop-cause chips still ship for the rare case where a loop
    plays without a ready proxy (preparing / animated color / etc.)."""
    client, db = _client(tmp_path, monkeypatch)
    _seed_video(db, tmp_path / "videos", "CHIPS.MP4")
    english = client.get("/studio", cookies={"lang": "en"})
    german = client.get("/studio", cookies={"lang": "de"})
    assert english.status_code == 200 and german.status_code == 200
    assert 'data-lut-chip-loop-playing="Playing looped; color file preview appears on pause"' in english.text
    assert 'data-hsl-chip-loop-playing="Playing looped; HSL preview appears on pause"' in english.text
    assert "Loop-Wiedergabe; Farbdatei-Vorschau erscheint bei Pause" in german.text

    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "proxyRelativeMediaTime" in script
    assert "playEndMediaTime" in script
    assert "forwardLoopActive(clip) || sectionRepeats(clip) > 1" in script


def test_proxy_policy_allows_loops_and_rejects_animated_color() -> None:
    policy = Path("src/orga_drone/static/js/studio/proxy-policy.js").read_text(encoding="utf-8")
    assert "Number(sectionRepeats) > 1 || forwardLoopActive" not in policy
    assert "colorAnimationKeys" in policy
    mapper = Path("src/orga_drone/static/js/studio/proxy-loop-map.js").read_text(encoding="utf-8")
    assert "proxyRelativeMediaTime" in mapper


def test_forward_loop_proxy_decoded_frame_matches_preview_still(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decoded proxy midpoint RGB stays within tolerance of the pause still.

    A saved eligibility flag alone is not enough: the graded pixels must be
    present in the proxy file used for looped playback.
    """
    from PIL import Image

    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed_video(db, tmp_path / "videos", "PARITY.MP4", duration_s=2.0)
    _apply_lut(client, tmp_path, clip_id)
    _seed_soundtrack(db, tmp_path, duration_s=8.0)
    assert client.patch(f"/api/studio/{clip_id}/forward-loop", json={"enabled": True}).status_code == 200

    proxy = client.post(f"/api/studio/{clip_id}/playback-proxy")
    assert proxy.status_code == 200
    proxy_path = tmp_path / "data" / "playback-proxies"
    files = list(proxy_path.glob("*.mp4"))
    assert files, "proxy mp4 missing"
    proxy_file = files[0]

    still = client.get(f"/api/studio/{clip_id}/preview-frame", params={"t_s": 0.5})
    assert still.status_code == 200
    still_img = tmp_path / "still.jpg"
    still_img.write_bytes(still.content)

    frame = tmp_path / "proxy_frame.png"
    _run(
        "-ss", "0.5", "-i", str(proxy_file), "-frames:v", "1", str(frame),
    )

    def mean_rgb(path: Path) -> tuple[float, float, float]:
        im = Image.open(path).convert("RGB")
        pixels = list(im.getdata())
        n = max(1, len(pixels))
        r = sum(p[0] for p in pixels) / n
        g = sum(p[1] for p in pixels) / n
        b = sum(p[2] for p in pixels) / n
        return r, g, b

    still_rgb = mean_rgb(still_img)
    proxy_rgb = mean_rgb(frame)
    # Documented preview tolerance: keep mean channel error well under 8/255.
    for a, b in zip(still_rgb, proxy_rgb, strict=True):
        assert abs(a - b) < 8.0, (still_rgb, proxy_rgb)

