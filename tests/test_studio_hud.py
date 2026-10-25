"""Optional Studio telemetry HUD (Issue #107)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip
from orga_drone.export.studio_encoder import (
    _segment_filter_invocation,
    _segment_vf,
    _segment_vf_for_clip,
    build_stitch_filters,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_hud import (
    FILTER_INLINE_LIMIT,
    altitude_at,
    cues_from_srt,
    dump_hud,
    empty_hud_state,
    ffmpeg_hud_chain,
    format_elapsed,
    hud_client_state,
    hud_enabled_from_effect_settings,
    hud_reading,
    insert_hud_chain,
    parse_hud_enabled,
    video_filter_args,
)
from orga_drone.studio_image import image_adjust_from_effect_settings

FIXTURE = Path("tests/fixtures/dji_srt_hud_sample.srt")


def _seed_media(
    db: Database,
    root_path: Path,
    *,
    filename: str,
    kind: str,
    duration_s: float | None,
    srt: str | None = None,
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / filename
    if not media_file.exists():
        media_file.write_bytes(b"media")
    if srt is not None:
        media_file.with_suffix(".SRT").write_text(srt, encoding="utf-8")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": duration_s,
            "recorded_at": "2024-06-15T12:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": "DJI Avata 2",
            "camera_model": None,
            "latitude": 47.3769,
            "longitude": 8.5417,
            "abs_alt": 408.0,
            "has_srt": 1 if srt is not None else 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )


def _add(db: Database, media_id: int) -> int:
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(
            item.filename, item.size_bytes, item.recorded_at
        ),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    return clip_id


def test_fixture_fields_gaps_and_cut_clock() -> None:
    from orga_drone.studio_hud import altitude_intervals

    cues = cues_from_srt(FIXTURE)
    assert [cue.t for cue in cues] == [0.0, 1.0, 2.0, 5.0]
    assert cues[0].rel_alt == 1.2
    assert cues[2].rel_alt is None
    assert altitude_at(cues, 2.0) == 3.4
    assert altitude_at(cues, 3.5) is None
    assert altitude_at(cues, 4.0) == 8.0
    state = hud_client_state(
        FIXTURE.with_suffix(".MP4"),
        effect_settings='{"hud":{"enabled":true}}',
        source_start_s=0.0,
        source_end_s=6.0,
        media_duration_s=None,
        fallback_duration_s=6,
    )
    assert state["available"] is True
    assert state["enabled"] is True
    assert state["elapsed"] == "available"
    assert state["altitude"] == "available"
    assert state["speed"] == "unavailable"
    assert state["home_distance"] == "unavailable"
    rows = state["intervals"]
    assert isinstance(rows, list)
    assert rows
    assert all(not (float(row["start"]) <= 3.5 < float(row["end"])) for row in rows)
    windows = altitude_intervals(cues, 0.0, 6.0)
    assert hud_reading(windows, 3.5) == ("00:00:03", None)
    assert hud_reading(windows, 1.0) == ("00:00:01", "3.4 m")
    cut = altitude_intervals(cues, 4.0, 6.0)
    assert cut[0].start_s >= 4.0
    assert hud_reading(cut, 4.0) == ("00:00:04", "8.0 m")
    assert format_elapsed(3661) == "01:01:01"
    assert empty_hud_state()["available"] is False


def test_srt_sibling_availability_and_skipped_fields(tmp_path: Path) -> None:
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"media")
    video.with_suffix(".SRT").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    state = hud_client_state(
        video,
        effect_settings='{"hud":{"enabled":"drawtext=text=owned"}}',
        source_start_s=0,
        source_end_s=6,
        media_duration_s=None,
        fallback_duration_s=6,
    )
    assert state["available"] is True
    assert state["enabled"] is False
    assert state["elapsed"] == "available"
    assert state["altitude"] == "available"
    assert state["speed"] == "unavailable"
    assert state["home_distance"] == "unavailable"
    assert state["intervals"]
    rows = state["intervals"]
    assert isinstance(rows, list)
    assert all(not (float(row["start"]) <= 3.5 < float(row["end"])) for row in rows)
    bare = tmp_path / "bare.MP4"
    bare.write_bytes(b"media")
    bare.with_suffix(".srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n[latitude: 47.1] [longitude: 8.2]\n",
        encoding="utf-8",
    )
    gps_only = hud_client_state(
        bare,
        effect_settings="{}",
        source_start_s=0,
        source_end_s=1,
        media_duration_s=None,
        fallback_duration_s=1,
    )
    assert gps_only["available"] is True
    assert gps_only["altitude"] == "unavailable"
    assert gps_only["intervals"] == []
    missing = hud_client_state(
        tmp_path / "none.MP4",
        effect_settings='{"hud":{"enabled":true}}',
        source_start_s=0,
        source_end_s=1,
        media_duration_s=None,
        fallback_duration_s=1,
    )
    assert missing["available"] is False
    assert missing["enabled"] is True


def test_settings_roundtrip_and_filter_text_cannot_be_stored() -> None:
    with pytest.raises(ValueError, match="true or false"):
        parse_hud_enabled({"enabled": "true;drawtext=text=owned"})
    with pytest.raises(ValueError, match="enabled"):
        parse_hud_enabled({})
    blob = dump_hud('{"image":{"exposure":4},"frame":{"zoom_start":1}}', True)
    stored = json.loads(blob)
    assert stored["hud"] == {"enabled": True}
    assert stored["image"]["exposure"] == 4
    assert image_adjust_from_effect_settings(blob).exposure == 4
    assert hud_enabled_from_effect_settings(blob) is True
    assert hud_enabled_from_effect_settings('{"hud":{"enabled":1}}') is False


def test_export_chain_uses_source_clock_and_hides_the_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.studio_title_card.resolve_title_card_font",
        lambda: tmp_path / "font.ttf",
    )
    cues = cues_from_srt(FIXTURE)
    from orga_drone.studio_hud import altitude_intervals

    windows = altitude_intervals(cues, 4.0, 6.0)
    plain = StudioExportClip(source_path=tmp_path / "clip.mp4", kind="video", duration_s=2)
    assert _segment_vf_for_clip(1280, 720, plain) == _segment_vf(1280, 720)
    extra, filters = _segment_filter_invocation(plain, 320, 180, tmp_path)
    assert extra == []
    assert filters[0] == "-vf"
    assert "drawtext=" not in filters[1]
    clip = StudioExportClip(
        source_path=tmp_path / "clip.mp4",
        kind="video",
        duration_s=2,
        source_start_s=4,
        source_end_s=6,
        fade_in_s=0.2,
        hud_enabled=True,
        hud_intervals=windows,
    )
    extra, filters = _segment_filter_invocation(clip, 320, 180, tmp_path)
    assert filters[0] == "-vf"
    body = filters[1]
    assert body.index("drawtext=") < body.index("fade=t=in")
    assert "floor(t/3600)" in body
    assert "t-4" not in body
    assert "between(t\\,4.0000\\," in body or any(
        f"between(t\\,{window.start_s:.4f}\\," in body for window in windows
    )
    assert "between(t\\,0.0000\\," not in body
    assert "3.5" not in body
    assert "speed" not in body.lower()
    assert "home" not in body.lower()
    chain = ffmpeg_hud_chain(
        fontfile=tmp_path / "font.ttf",
        height=180,
        intervals=(),
    )
    assert chain.count("drawtext=") == 1
    mask_graph = "[mbase1]fade=t=in:st=0:d=0.4000,format=yuv420p[vout]"
    burned = insert_hud_chain(mask_graph, "drawtext=text='00'")
    assert burned.index("drawtext=") < burned.index("fade=t=in")
    overlay_graph = "[ovl0]format=yuv420p[fmt];[fmt]fade=t=in:st=0:d=0.2000[vout]"
    over = insert_hud_chain(overlay_graph, "drawtext=text='00'")
    assert over.index("drawtext=") < over.index("format=yuv420p")
    assert over.index("format=yuv420p") < over.index("fade=t=in")
    script = tmp_path / "long.txt"
    args = video_filter_args("x" * (FILTER_INLINE_LIMIT + 1), script_path=script, complex_graph=False)
    assert args[0] == "-filter_script:v"
    assert script.read_text(encoding="utf-8").startswith("x")
    stitch = build_stitch_filters(
        (
            clip,
            StudioExportClip(source_path=tmp_path / "b.mp4", kind="video", duration_s=2),
        )
    )
    assert all("drawtext=" not in step for step in stitch)


def test_persisted_hud_follows_cuts_and_leaves_the_file(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "studio.sqlite3")
    media_id = _seed_media(
        db,
        tmp_path / "lib",
        filename="DJI_0001.MP4",
        kind="video",
        duration_s=6.0,
        srt=FIXTURE.read_text(encoding="utf-8"),
    )
    clip_id = _add(db, media_id)
    media = db.get_media(media_id)
    assert media is not None
    before = Path(media.path).read_bytes()
    stored = db.set_studio_hud(clip_id, {"enabled": True})
    assert hud_enabled_from_effect_settings(stored.effect_settings) is True
    assert Path(media.path).read_bytes() == before
    exported = _clip_to_export_clip(db, stored)
    assert exported is not None
    assert exported.hud_enabled is True
    assert exported.hud_intervals
    assert "drawtext=" not in Path(media.path).read_text(encoding="utf-8", errors="ignore")
    left, right = db.cut_studio_video_item(clip_id, 3.0)
    assert hud_enabled_from_effect_settings(left.effect_settings) is True
    assert hud_enabled_from_effect_settings(right.effect_settings) is True
    left_export = _clip_to_export_clip(db, left)
    right_export = _clip_to_export_clip(db, right)
    assert left_export is not None and right_export is not None
    assert left_export.hud_intervals[0].start_s < right_export.hud_intervals[0].start_s
    card = db.add_studio_title_card(db.list_studio_projects()[0].id, title_text="Hi")
    with pytest.raises(ValueError, match="videos"):
        db.set_studio_hud(card.id, {"enabled": True})


def test_http_hud_inspector_and_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    video_id = _add(
        db,
        _seed_media(
            db,
            tmp_path / "lib",
            filename="V.MP4",
            kind="video",
            duration_s=6.0,
            srt=FIXTURE.read_text(encoding="utf-8"),
        ),
    )
    plain_id = _add(
        db,
        _seed_media(
            db,
            tmp_path / "lib2",
            filename="PLAIN.MP4",
            kind="video",
            duration_s=4.0,
        ),
    )
    client = TestClient(app)
    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="inspector-hud" data-inspector-tab="effects" hidden' in page.text
    assert 'id="studio-preview-hud"' in page.text
    assert ("Telemetrie-HUD" in page.text) or ("Telemetry HUD" in page.text)
    assert '"available": true' in page.text
    assert '"speed": "unavailable"' in page.text
    assert '"home_distance": "unavailable"' in page.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "hudWrap.hidden = !isVideo" in script
    assert "formatHudElapsed" in script
    rejected = client.patch(f"/api/studio/{video_id}/hud", json={"enabled": "yes"})
    assert rejected.status_code == 400
    missing = client.patch(f"/api/studio/{plain_id}/hud", json={"enabled": True})
    assert missing.status_code == 400
    saved = client.patch(f"/api/studio/{video_id}/hud", json={"enabled": True})
    assert saved.status_code == 200
    assert saved.json()["enabled"] is True
    off = client.patch(f"/api/studio/{video_id}/hud", json={"enabled": False})
    assert off.status_code == 200
    assert off.json()["enabled"] is False


def _ffmpeg_has_filter(ffmpeg: str, name: str) -> bool:
    listed = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
    )
    return any(part == name for line in listed.stdout.splitlines() for part in line.split())


def test_ffmpeg_accepts_the_hud_chain(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    if not _ffmpeg_has_filter(ffmpeg, "drawtext"):
        pytest.skip("ffmpeg has no drawtext filter")
    from orga_drone.export.studio_config import StudioExportConfig
    from orga_drone.export.studio_encoder import FfmpegStudioEncoder
    from orga_drone.studio_hud import HudInterval

    source = tmp_path / "color.mp4"
    made = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        capture_output=True,
        check=False,
    )
    assert made.returncode == 0, made.stderr.decode("utf-8", errors="replace")
    original = source.read_bytes()
    dest = tmp_path / "hud.mp4"
    FfmpegStudioEncoder().render(
        StudioExportConfig(
            output_path=dest,
            width=320,
            height=180,
            clips=(
                StudioExportClip(
                    source_path=source,
                    kind="video",
                    duration_s=1.0,
                    hud_enabled=True,
                    hud_intervals=(
                        HudInterval(start_s=0.0, end_s=1.0, altitude_m=3.4),
                    ),
                ),
            ),
        )
    )
    assert dest.is_file()
    assert dest.stat().st_size > 0
    assert source.read_bytes() == original
