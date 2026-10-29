"""Per-clip Studio image adjustment (Issue #76)."""

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
    _segment_vf,
    _segment_vf_for_clip,
    build_stitch_filters,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_image import (
    ImageAdjust,
    blackbody_channel_gains,
    color_profile_hint_from_srt,
    dump_effect_settings,
    ffmpeg_grade_chain,
    image_adjust_from_effect_settings,
    kelvin_for_warmth,
    parse_image_adjust_patch,
    preview_css_functions,
)
from orga_drone.studio_transition import normalize_type


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


def _video_clip(**overrides: object) -> StudioExportClip:
    values: dict[str, object] = {
        "source_path": Path("clip.mp4"),
        "kind": "video",
        "duration_s": 4.0,
    }
    values.update(overrides)
    return StudioExportClip(**values)  # type: ignore[arg-type]


def test_missing_settings_are_neutral() -> None:
    for raw in (None, "", "{}", "{", "[]", '{"image":"nope"}'):
        assert image_adjust_from_effect_settings(raw).is_neutral
    corrupt = image_adjust_from_effect_settings(
        '{"image":{"exposure":900,"contrast":"eq=1","saturation":true}}'
    )
    assert corrupt.is_neutral
    partial = image_adjust_from_effect_settings('{"image":{"warmth":-15}}')
    assert partial.as_dict() == {
        "exposure": 0,
        "contrast": 0,
        "saturation": 0,
        "warmth": -15,
        "highlights": 0,
        "shadows": 0,
        "blacks": 0,
    }


def test_patch_rejects_injection_and_out_of_range() -> None:
    current = ImageAdjust(exposure=4)
    with pytest.raises(ValueError, match="exposure"):
        parse_image_adjust_patch({"exposure": "1;movie=/tmp/x"}, current)
    with pytest.raises(ValueError, match="warmth"):
        parse_image_adjust_patch({"warmth": 101}, current)
    with pytest.raises(ValueError, match="contrast"):
        parse_image_adjust_patch({"contrast": True}, current)
    with pytest.raises(ValueError, match="include an image adjustment"):
        parse_image_adjust_patch({"filter": "eq=brightness=1"}, current)
    updated = parse_image_adjust_patch({"saturation": 12.4}, current)
    assert updated.exposure == 4
    assert updated.saturation == 12
    blob = dump_effect_settings('{"legacy":1}', updated)
    stored = json.loads(blob)
    assert stored["legacy"] == 1
    assert "movie" not in blob
    assert stored["image"]["saturation"] == 12


def test_ffmpeg_and_preview_mapping() -> None:
    neutral = ffmpeg_grade_chain(ImageAdjust())
    assert neutral == ""
    assert preview_css_functions(ImageAdjust()) == ""
    full = ImageAdjust(exposure=100, contrast=100, saturation=100, warmth=100)
    assert kelvin_for_warmth(100) == 4676
    assert kelvin_for_warmth(-100) == 10656
    assert kelvin_for_warmth(0) == 6500
    chain = ffmpeg_grade_chain(full)
    assert chain == (
        "colortemperature=temperature=4676,"
        "exposure=exposure=1.0000,"
        "eq=contrast=1.5000:saturation=2.0000"
    )
    tonal = ffmpeg_grade_chain(ImageAdjust(highlights=50, shadows=40, blacks=20))
    assert "colorlevels=" in tonal
    assert "rimin=" in tonal
    assert "rimax=" in tonal
    assert ";" not in tonal
    assert ";" not in chain
    assert "[" not in chain
    assert preview_css_functions(ImageAdjust(exposure=100)) == "brightness(2.0000)"
    assert preview_css_functions(ImageAdjust(contrast=-100, saturation=-100)) == (
        "saturate(0.0000) contrast(0.5000)"
    )
    gains = blackbody_channel_gains(4800)
    sampled = tuple(round(channel * gain) for channel, gain in zip((127, 95, 63), gains))
    assert sampled == (127, 83, 49)


def test_neutral_segment_matches_existing_chain_and_grade_precedes_fades() -> None:
    plain = _video_clip()
    assert _segment_vf_for_clip(1920, 1080, plain) == _segment_vf(1920, 1080)
    graded = _video_clip(
        image=ImageAdjust(contrast=20),
        fade_in_s=0.25,
        fade_out_s=0.4,
    )
    vf = _segment_vf_for_clip(1920, 1080, graded)
    assert vf.startswith("eq=contrast=1.1000,")
    assert vf.index("eq=") < vf.index("scale=")
    assert vf.index("scale=") < vf.index("fade=t=in")
    assert "fade=t=out" in vf
    photo = StudioExportClip(
        source_path=Path("still.jpg"),
        kind="photo",
        duration_s=3.0,
        image=ImageAdjust(exposure=100),
    )
    photo_vf = _segment_vf_for_clip(1280, 720, photo)
    assert photo_vf.startswith("exposure=exposure=1.0000,")
    assert photo_vf.index("exposure=") < photo_vf.index("scale=")
    card = StudioExportClip(
        source_path=None,
        kind="title_card",
        duration_s=3.0,
        image=ImageAdjust(exposure=100),
    )
    assert "exposure=" not in _segment_vf_for_clip(1280, 720, card)


def test_crossfade_keeps_grade_on_each_segment() -> None:
    left = _video_clip(
        source_path=Path("left.mp4"),
        image=ImageAdjust(exposure=40, warmth=-20),
        transition_type="crossfade",
        transition_s=0.5,
    )
    right = _video_clip(
        source_path=Path("right.mp4"),
        duration_s=3.0,
        image=ImageAdjust(saturation=30),
    )
    left_vf = _segment_vf_for_clip(1280, 720, left)
    right_vf = _segment_vf_for_clip(1280, 720, right)
    assert "colortemperature=" in left_vf
    assert "exposure=exposure=0.4000" in left_vf
    assert left_vf.index("colortemperature=") < left_vf.index("scale=")
    assert "eq=saturation=1.3000" in right_vf
    stitch = ";".join(build_stitch_filters((left, right)))
    assert "xfade=transition=fade:" in stitch
    assert "exposure=" not in stitch
    assert "colortemperature=" not in stitch
    assert "saturation=" not in stitch


def test_ffmpeg_accepts_grade_chain() -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    chain = ffmpeg_grade_chain(
        ImageAdjust(exposure=-30, contrast=25, saturation=15, warmth=40)
    )
    vf = f"{chain},{_segment_vf(320, 180)}"
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x806040:s=320x180:r=30:d=0.1",
            "-vf",
            vf,
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")


def test_settings_persist_per_clip_and_survive_cut(tmp_path: Path) -> None:
    path = tmp_path / "studio.sqlite3"
    db = Database(path)
    media_id = _seed_media(
        db, tmp_path / "lib", filename="cloud.MP4", kind="video", duration_s=8.0
    )
    first = _add(db, media_id)
    second = _add(db, media_id)
    db.set_studio_image_adjust(first, {"exposure": 25, "warmth": -10})
    db.set_studio_image_adjust(second, {"contrast": -20})
    db.set_studio_transition(first, "fade_black", 0.6)
    reopened = Database(path)
    by_id = {item.id: item for item in reopened.list_studio_items()}
    assert image_adjust_from_effect_settings(by_id[first].effect_settings).as_dict() == {
        "exposure": 25,
        "contrast": 0,
        "saturation": 0,
        "warmth": -10,
        "highlights": 0,
        "shadows": 0,
        "blacks": 0,
    }
    assert image_adjust_from_effect_settings(by_id[second].effect_settings).contrast == -20
    assert normalize_type(by_id[first].transition) == "fade_black"
    exported = _clip_to_export_clip(reopened, by_id[first])
    assert exported is not None
    assert exported.image.exposure == 25
    assert exported.image.warmth == -10
    reopened.set_studio_transition(first, "crossfade", 0.4)
    kept = {item.id: item for item in reopened.list_studio_items()}[first]
    assert image_adjust_from_effect_settings(kept.effect_settings).exposure == 25
    left, right = reopened.cut_studio_video_item(first, 2.0)
    assert image_adjust_from_effect_settings(left.effect_settings).warmth == -10
    assert image_adjust_from_effect_settings(right.effect_settings).warmth == -10
    photo_id = _add(
        reopened,
        _seed_media(
            reopened, tmp_path / "lib", filename="still.JPG", kind="photo", duration_s=None
        ),
    )
    photo_item = reopened.set_studio_image_adjust(photo_id, {"exposure": 10, "warmth": 20})
    assert image_adjust_from_effect_settings(photo_item.effect_settings).exposure == 10
    photo_export = _clip_to_export_clip(reopened, photo_item)
    assert photo_export is not None
    assert photo_export.image.warmth == 20
    card = reopened.add_studio_title_card(reopened.list_studio_projects()[0].id, title_text="Hi")
    with pytest.raises(ValueError, match="photos and videos"):
        reopened.set_studio_image_adjust(card.id, {"exposure": 10})


def test_http_image_adjust_validation_and_inspector(
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
    assert 'id="inspector-image-panel"' in page.text
    assert 'data-inspector-tab="image"' in page.text
    assert 'id="inspector-image-section-basic"' in page.text
    assert 'id="inspector-image-section-profile"' in page.text
    assert 'id="inspector-image-section-advanced"' in page.text
    assert 'id="inspector-image-adjust"' in page.text
    assert 'id="inspector-image-exposure"' in page.text
    assert 'id="inspector-image-contrast"' in page.text
    assert 'id="inspector-image-saturation"' in page.text
    assert 'id="inspector-image-warmth"' in page.text
    assert ("Grundkorrektur" in page.text) or ("Basic correction" in page.text)
    assert ("Farbprofil" in page.text) or ("Color profile" in page.text)
    assert 'data-image-adjust=' in page.text
    assert 'data-color-profile=' in page.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "imagePanel.hidden = !canImage" in script
    assert "fillImageInspectorSections" in script

    rejected = client.patch(
        f"/api/studio/{video_id}/image",
        json={"exposure": "0;eq=brightness=1"},
    )
    assert rejected.status_code == 400
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    assert image_adjust_from_effect_settings(stored.effect_settings).is_neutral

    out_of_range = client.patch(f"/api/studio/{video_id}/image", json={"warmth": -150})
    assert out_of_range.status_code == 400
    photo = client.patch(f"/api/studio/{photo_id}/image", json={"exposure": 10, "saturation": -5})
    assert photo.status_code == 200
    assert photo.json()["image"]["exposure"] == 10
    assert photo.json()["image"]["saturation"] == -5
    missing = client.patch("/api/studio/999999/image", json={"exposure": 1})
    assert missing.status_code == 404

    saved = client.patch(
        f"/api/studio/{video_id}/image",
        json={"exposure": 12.4, "warmth": -8},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["image"]["exposure"] == 12
    assert body["image"]["warmth"] == -8
    again = client.patch(f"/api/studio/{video_id}/image", json={"saturation": 6})
    assert again.status_code == 200
    assert again.json()["image"] == {
        "exposure": 12,
        "contrast": 0,
        "saturation": 6,
        "warmth": -8,
        "highlights": 0,
        "shadows": 0,
        "blacks": 0,
    }
    reset = client.patch(
        f"/api/studio/{video_id}/image",
        json={"exposure": 0, "contrast": 0, "saturation": 0, "warmth": 0},
    )
    assert reset.status_code == 200
    assert reset.json()["image"]["exposure"] == 0


def test_color_profile_hint_reads_sibling_srt(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/dji_srt_camera_fields_sample.srt").read_text(
        encoding="utf-8"
    )
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"fake")
    (tmp_path / "clip.SRT").write_text(fixture, encoding="utf-8")
    assert color_profile_hint_from_srt(video) == "dlog_m"
    assert color_profile_hint_from_srt(tmp_path / "missing.MP4") is None
