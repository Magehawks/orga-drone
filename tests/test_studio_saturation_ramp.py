"""Video saturation ramp inside one Studio clip (Issue #109)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip
from orga_drone.export.studio_encoder import _segment_vf_for_clip, build_stitch_filters
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_image import (
    ImageAdjust,
    SaturationRamp,
    dump_effect_settings,
    dump_saturation_ramp,
    ffmpeg_grade_chain,
    ffmpeg_saturation_ramp,
    image_adjust_from_effect_settings,
    parse_saturation_ramp_payload,
    saturation_factor,
    saturation_multiplier,
    saturation_ramp_from_effect_settings,
    shift_saturation_ramp_settings,
)


def _seed_media(
    db: Database,
    root_path: Path,
    *,
    filename: str,
    kind: str,
    duration_s: float | None,
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / filename
    media_file.write_bytes(b"media")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": 5,
            "duration_s": duration_s,
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


def _add(db: Database, media_id: int) -> int:
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


def _ramp(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "enabled": True,
        "start_s": 1.0,
        "end_s": 4.0,
        "start_saturation": 100,
        "end_saturation": 0,
    }
    body.update(overrides)
    return body


def test_missing_ramp_leaves_the_grade_alone() -> None:
    for raw in (None, "", "{}", "{", "[]", '{"saturation_ramp":"nope"}'):
        ramp = saturation_ramp_from_effect_settings(raw)
        assert ramp.enabled is False
        assert saturation_multiplier(ramp, 2.0) == 1.0
        assert ffmpeg_saturation_ramp(ramp, origin_s=1.5) == ""
    grade = ffmpeg_grade_chain(ImageAdjust(saturation=30, contrast=20))
    assert grade == "eq=contrast=1.1000:saturation=1.3000"
    assert "hue=" not in grade


def test_linear_multiplier_holds_the_ends_and_composes_with_the_grade() -> None:
    ramp = SaturationRamp(
        enabled=True, start_s=2.0, end_s=6.0, start_saturation=100, end_saturation=0
    )
    assert saturation_multiplier(ramp, 0.0) == 1.0
    assert saturation_multiplier(ramp, 2.0) == 1.0
    assert saturation_multiplier(ramp, 4.0) == 0.5
    assert saturation_multiplier(ramp, 9.0) == 0.0
    graded = ImageAdjust(saturation=50)
    assert saturation_factor(graded) * saturation_multiplier(ramp, 4.0) == pytest.approx(0.75)
    flat = SaturationRamp(
        enabled=True, start_s=0.0, end_s=0.0, start_saturation=40, end_saturation=0
    )
    assert saturation_multiplier(flat, 1.0) == 1.0
    held = SaturationRamp(
        enabled=True, start_s=0.0, end_s=3.0, start_saturation=25, end_saturation=25
    )
    assert saturation_multiplier(held, 0.0) == 0.25
    assert saturation_multiplier(held, 9.0) == 0.25


def test_split_shift_keeps_the_same_picture_at_the_cut() -> None:
    ramp = SaturationRamp(
        enabled=True, start_s=2.0, end_s=6.0, start_saturation=100, end_saturation=0
    )
    raw = dump_saturation_ramp(
        dump_effect_settings(None, ImageAdjust(exposure=12)),
        ramp,
    )
    assert shift_saturation_ramp_settings(raw, 3.0) != raw
    unchanged = dump_effect_settings(None, ImageAdjust(exposure=12))
    assert shift_saturation_ramp_settings(unchanged, 3.0) == unchanged
    right = saturation_ramp_from_effect_settings(shift_saturation_ramp_settings(raw, 3.0))
    assert right.start_s == -1.0
    assert right.end_s == 3.0
    assert image_adjust_from_effect_settings(
        shift_saturation_ramp_settings(raw, 3.0)
    ).exposure == 12
    assert saturation_multiplier(ramp, 3.0) == pytest.approx(
        saturation_multiplier(right, 0.0)
    )


def test_parser_rejects_injection_and_zero_length_ranges() -> None:
    with pytest.raises(ValueError, match="saturation ramp"):
        parse_saturation_ramp_payload({"filter": "hue=s=0"})
    with pytest.raises(ValueError, match="enabled"):
        parse_saturation_ramp_payload({"enabled": "true", "start_s": 0, "end_s": 1})
    with pytest.raises(ValueError, match="start_s"):
        parse_saturation_ramp_payload(_ramp(start_s="0;movie=/tmp/x"))
    with pytest.raises(ValueError, match="end_saturation"):
        parse_saturation_ramp_payload(_ramp(end_saturation=140))
    with pytest.raises(ValueError, match="longer range"):
        parse_saturation_ramp_payload(_ramp(start_s=2, end_s=2))
    off = parse_saturation_ramp_payload(
        {"enabled": False, "start_s": 2, "end_s": 2, "start_saturation": 80, "end_saturation": 10}
    )
    assert off.enabled is False
    assert off.start_saturation == 80
    stored = json.loads(dump_saturation_ramp('{"image":{"exposure":4}}', off))
    assert stored["image"]["exposure"] == 4
    assert "hue" not in json.dumps(stored)


def test_export_chain_ramps_after_the_grade_and_respects_trim() -> None:
    ramp = SaturationRamp(
        enabled=True, start_s=1.0, end_s=3.0, start_saturation=100, end_saturation=0
    )
    graded = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=8.0,
        source_start_s=2.5,
        image=ImageAdjust(exposure=-20, contrast=20, saturation=30, warmth=15),
        saturation_ramp=ramp,
    )
    vf = _segment_vf_for_clip(1280, 720, graded)
    assert "colortemperature=" in vf
    assert "exposure=exposure=-0.2000" in vf
    assert "eq=contrast=1.1000:saturation=1.3000" in vf
    assert "hue=s='" in vf
    assert "t-0.0000" in vf
    assert vf.index("colortemperature=") < vf.index("eq=") < vf.index("hue=s=")
    assert vf.index("hue=s=") < vf.index("scale=")
    plain = _segment_vf_for_clip(
        1280,
        720,
        StudioExportClip(
            source_path=Path("clip.mp4"),
            kind="video",
            duration_s=4.0,
            image=ImageAdjust(saturation=30),
        ),
    )
    assert "eq=saturation=1.3000" in plain
    assert "hue=" not in plain
    photo = _segment_vf_for_clip(
        640,
        360,
        StudioExportClip(
            source_path=Path("still.jpg"),
            kind="photo",
            duration_s=3.0,
            saturation_ramp=ramp,
        ),
    )
    assert "hue=" not in photo
    stitch = ";".join(
        build_stitch_filters(
            (
                StudioExportClip(
                    source_path=Path("clip.mp4"),
                    kind="video",
                    duration_s=8.0,
                    source_start_s=2.5,
                    image=graded.image,
                    saturation_ramp=ramp,
                    transition_type="crossfade",
                    transition_s=0.4,
                ),
                StudioExportClip(
                    source_path=Path("next.mp4"),
                    kind="video",
                    duration_s=3.0,
                ),
            )
        )
    )
    assert "hue=" not in stitch
    assert "saturation=" not in stitch


def test_full_strength_ramp_is_desaturated() -> None:
    """Strength all the way to black and white is a flat hue of 0, not a color fade."""
    ramp = SaturationRamp(
        enabled=True, start_s=0.0, end_s=4.0, start_saturation=0, end_saturation=0
    )
    chain = ffmpeg_saturation_ramp(ramp, origin_s=0.0)
    assert chain == "hue=s=0.0000"
    vf = _segment_vf_for_clip(
        1280,
        720,
        StudioExportClip(
            source_path=Path("clip.mp4"),
            kind="video",
            duration_s=4.0,
            saturation_ramp=ramp,
        ),
    )
    assert "hue=s=0.0000" in vf
    off = SaturationRamp(
        enabled=False, start_s=0.0, end_s=4.0, start_saturation=0, end_saturation=0
    )
    assert ffmpeg_saturation_ramp(off, origin_s=0.0) == ""
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    controls = script.split("function saturationRampFromControls", 1)[1].split(
        "function queueSaturationRampSave", 1
    )[0]
    assert "partialOn ? 100 : level" in controls
    assert "ramp.end_saturation = level" in controls
    preview = script.split("function cssFilterFor", 1)[1].split("function setGradeMatrix", 1)[0]
    assert "saturate(" in preview
    blit = script.split("function drawPreviewLayer", 1)[1].split("function ensurePreviewBlit", 1)[0]
    assert "previewGradeSource" in blit
    assert "ctx.filter = filter" in blit


def test_ffmpeg_ramps_a_red_frame_toward_gray() -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    ramp = SaturationRamp(
        enabled=True, start_s=0.0, end_s=0.5, start_saturation=100, end_saturation=0
    )
    chain = ffmpeg_saturation_ramp(ramp, origin_s=0.0)
    assert chain
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=16x16:r=30:d=1",
            "-vf",
            chain,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    frame = 16 * 16 * 3
    assert len(proc.stdout) >= frame * 20

    def chroma(index: int) -> int:
        pixel = proc.stdout[index * frame : index * frame + 3]
        return max(pixel) - min(pixel)

    assert chroma(0) > 100
    assert chroma(20) < 20


def test_settings_persist_reload_seek_and_survive_cut(tmp_path: Path) -> None:
    path = tmp_path / "studio.sqlite3"
    db = Database(path)
    media_id = _seed_media(db, tmp_path / "lib", filename="cloud.MP4", kind="video", duration_s=8.0)
    first = _add(db, media_id)
    second = _add(db, media_id)
    db.set_studio_image_adjust(first, {"exposure": 18, "saturation": 20, "warmth": -6})
    saved = db.set_studio_saturation_ramp(first, {"saturation_ramp": _ramp()})
    assert image_adjust_from_effect_settings(saved.effect_settings).as_dict() == {
        "exposure": 18,
        "contrast": 0,
        "saturation": 20,
        "warmth": -6,
    }
    stored = saturation_ramp_from_effect_settings(saved.effect_settings)
    assert stored.enabled is True
    assert stored.start_s == 1.0
    assert stored.end_s == 4.0
    assert saturation_multiplier(stored, 2.5) == pytest.approx(0.5)
    reopened = Database(path)
    kept = {item.id: item for item in reopened.list_studio_items()}[first]
    assert saturation_ramp_from_effect_settings(kept.effect_settings).end_saturation == 0
    other = {item.id: item for item in reopened.list_studio_items()}[second]
    assert saturation_ramp_from_effect_settings(other.effect_settings).enabled is False
    exported = _clip_to_export_clip(reopened, kept)
    assert exported is not None
    assert exported.image.warmth == -6
    assert exported.saturation_ramp.start_s == 1.0
    assert "t-0.0000" in _segment_vf_for_clip(320, 180, exported)
    left, right = reopened.cut_studio_video_item(first, 2.0)
    assert saturation_ramp_from_effect_settings(left.effect_settings).start_s == 1.0
    assert saturation_ramp_from_effect_settings(right.effect_settings).start_s == -1.0
    assert saturation_ramp_from_effect_settings(right.effect_settings).end_s == 2.0
    assert image_adjust_from_effect_settings(right.effect_settings).exposure == 18
    assert saturation_multiplier(
        saturation_ramp_from_effect_settings(left.effect_settings), 2.0
    ) == pytest.approx(
        saturation_multiplier(
            saturation_ramp_from_effect_settings(right.effect_settings), 0.0
        )
    )
    photo_id = _add(
        reopened,
        _seed_media(reopened, tmp_path / "lib", filename="still.JPG", kind="photo", duration_s=None),
    )
    with pytest.raises(ValueError, match="video"):
        reopened.set_studio_saturation_ramp(photo_id, {"saturation_ramp": _ramp()})
    card = reopened.add_studio_title_card(reopened.list_studio_projects()[0].id, title_text="Hi")
    with pytest.raises(ValueError, match="video"):
        reopened.set_studio_saturation_ramp(card.id, {"saturation_ramp": _ramp()})


def test_http_saturation_ramp_validation_and_inspector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    video_id = _add(
        db,
        _seed_media(db, tmp_path / "lib", filename="V.MP4", kind="video", duration_s=6.0),
    )
    photo_id = _add(
        db,
        _seed_media(db, tmp_path / "lib", filename="P.JPG", kind="photo", duration_s=None),
    )
    client = TestClient(app)
    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="inspector-saturation-ramp"' in page.text
    assert 'id="inspector-image-section-advanced"' in page.text
    assert 'id="inspector-bw-enabled"' in page.text
    assert 'id="inspector-bw-start"' in page.text
    assert 'id="inspector-bw-end"' in page.text
    assert 'id="inspector-image-saturation"' in page.text
    assert ("Zu Schwarzweiß" in page.text) or ("To black and white" in page.text)
    assert 'id="inspector-bw-strength"' in page.text
    assert "data-saturation-ramp=" in page.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "advancedSection.hidden = !isVideo" in script
    assert "saturationRampMultiplier" in script

    rejected = client.patch(
        f"/api/studio/{video_id}/saturation-ramp",
        json={"enabled": True, "start_s": "1;hue=s=0", "end_s": 2},
    )
    assert rejected.status_code == 400
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    assert saturation_ramp_from_effect_settings(stored.effect_settings).enabled is False

    zero = client.patch(
        f"/api/studio/{video_id}/saturation-ramp",
        json={"saturation_ramp": _ramp(start_s=1, end_s=1)},
    )
    assert zero.status_code == 400
    photo = client.patch(
        f"/api/studio/{photo_id}/saturation-ramp",
        json={"saturation_ramp": _ramp()},
    )
    assert photo.status_code == 400
    missing = client.patch(
        "/api/studio/999999/saturation-ramp",
        json={"saturation_ramp": _ramp()},
    )
    assert missing.status_code == 404

    db.set_studio_image_adjust(video_id, {"contrast": 12, "warmth": 4})
    saved = client.patch(
        f"/api/studio/{video_id}/saturation-ramp",
        json={"saturation_ramp": _ramp(start_s=0.2, end_s=2.8, end_saturation=0)},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["saturation_ramp"]["enabled"] is True
    assert body["saturation_ramp"]["start_s"] == 0.2
    assert body["saturation_ramp"]["end_saturation"] == 0
    again = {item.id: item for item in db.list_studio_items()}[video_id]
    assert image_adjust_from_effect_settings(again.effect_settings).as_dict() == {
        "exposure": 0,
        "contrast": 12,
        "saturation": 0,
        "warmth": 4,
    }
    off = client.patch(
        f"/api/studio/{video_id}/saturation-ramp",
        json={"enabled": False, "start_s": 0.2, "end_s": 2.8, "start_saturation": 100, "end_saturation": 0},
    )
    assert off.status_code == 200
    assert off.json()["saturation_ramp"]["enabled"] is False
    kept = {item.id: item for item in db.list_studio_items()}[video_id]
    assert image_adjust_from_effect_settings(kept.effect_settings).contrast == 12
