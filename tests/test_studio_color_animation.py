"""Limited Studio color points (#211 PR2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.studio_color_animation import (
    ColorAnimation,
    ColorKey,
    apply_keyed_image,
    build_preset,
    color_animation_from_effect_settings,
    dump_color_animation,
    expand_export_clip_for_color,
    image_adjust_at,
    keyed_sliders_at,
    parse_color_animation_payload,
    shift_color_animation_settings,
)
from orga_drone.studio_image import ImageAdjust


def test_missing_settings_are_neutral() -> None:
    assert color_animation_from_effect_settings(None).is_active is False
    assert color_animation_from_effect_settings("{}").is_active is False
    assert image_adjust_at("{}", 1.0) == ImageAdjust()


def test_preset_warm_up_and_manual_keeps_keys() -> None:
    preset = build_preset("warm_up", bar_start_s=0.0, bar_end_s=4.0)
    assert preset.mode == "preset"
    assert len(preset.keys) == 2
    mid = keyed_sliders_at(preset, 2.0)
    assert mid is not None
    assert mid.warmth == 17 or mid.warmth == 18  # round half
    assert mid.exposure in {4, 5}
    manual = parse_color_animation_payload(
        {
            "mode": "manual",
            "bar": {"start_s": 0.0, "end_s": 4.0},
            "keys": [k.as_dict() for k in preset.keys],
        }
    )
    assert manual.mode == "manual"
    assert manual.preset_id is None
    assert len(manual.keys) == 2


def test_outside_bar_uses_static_image() -> None:
    blob = dump_color_animation(
        json.dumps({"image": {"exposure": 10, "warmth": 0}}),
        build_preset("brighten", bar_start_s=1.0, bar_end_s=3.0),
    )
    outside = image_adjust_at(blob, 0.2)
    assert outside.exposure == 10
    inside = image_adjust_at(blob, 2.0)
    assert inside.exposure > 10


def test_shift_on_cut() -> None:
    blob = dump_color_animation(
        "{}",
        build_preset("dim", bar_start_s=2.0, bar_end_s=6.0),
    )
    shifted = shift_color_animation_settings(blob, 2.0)
    anim = color_animation_from_effect_settings(shifted)
    assert anim.bar_start_s == pytest.approx(0.0)
    assert anim.bar_end_s == pytest.approx(4.0)
    assert anim.keys[0].t == pytest.approx(0.0)


def test_expand_export_clip_splits_grade() -> None:
    from orga_drone.export.studio_config import StudioExportClip

    anim = parse_color_animation_payload(
        {
            "mode": "manual",
            "bar": {"start_s": 0.0, "end_s": 2.0},
            "keys": [
                {"t": 0.0, "exposure": 0, "contrast": 0, "saturation": 0, "warmth": 0},
                {"t": 1.0, "exposure": 0, "contrast": 10, "saturation": 15, "warmth": 0},
                {"t": 2.0, "exposure": 0, "contrast": 10, "saturation": 30, "warmth": 0},
            ],
        }
    )
    clip = StudioExportClip(
        source_path=Path("x.mp4"),
        kind="video",
        duration_s=2.0,
        source_start_s=0.0,
        source_end_s=2.0,
        image=ImageAdjust(),
        color_animation=anim,
    )
    pieces = expand_export_clip_for_color(clip)
    assert len(pieces) >= 2
    assert pieces[0].image.saturation < pieces[-1].image.saturation
    assert pieces[-1].image.saturation >= 20
    assert all(piece.color_animation is None for piece in pieces)


def test_expand_untrimmed_clip_without_source_end() -> None:
    """Untrimmed Studio clips often leave source_end_s unset."""
    from orga_drone.export.studio_config import StudioExportClip

    anim = build_preset("warm_up", bar_start_s=0.0, bar_end_s=4.0)
    clip = StudioExportClip(
        source_path=Path("x.mp4"),
        kind="video",
        duration_s=4.0,
        source_start_s=0.0,
        source_end_s=None,
        image=ImageAdjust(),
        color_animation=anim,
    )
    pieces = expand_export_clip_for_color(clip)
    assert len(pieces) >= 2
    assert pieces[0].image.warmth < pieces[-1].image.warmth
    assert pieces[-1].image.warmth >= 20
    assert pieces[-1].source_end_s == pytest.approx(4.0)


def test_expand_two_key_preset_is_dense_and_monotonic() -> None:
    from orga_drone.export.studio_config import StudioExportClip

    anim = build_preset("warm_up", bar_start_s=0.0, bar_end_s=4.0)
    clip = StudioExportClip(
        source_path=Path("x.mp4"),
        kind="video",
        duration_s=4.0,
        source_start_s=10.0,
        source_end_s=14.0,
        image=ImageAdjust(),
        color_animation=anim,
    )
    pieces = expand_export_clip_for_color(clip)
    assert len(pieces) >= 4  # densified beyond the two key boundaries
    warmths = [piece.image.warmth for piece in pieces]
    assert warmths == sorted(warmths)
    assert warmths[0] < warmths[-1]


def test_expand_honors_color_local_origin_for_slow_piece() -> None:
    from orga_drone.export.studio_config import StudioExportClip

    anim = build_preset("warm_up", bar_start_s=0.0, bar_end_s=4.0)
    # Second half of the clip (slow piece), keys still relative to in-point 0.
    piece = StudioExportClip(
        source_path=Path("x.mp4"),
        kind="video",
        duration_s=2.0,
        source_start_s=12.0,
        source_end_s=14.0,
        image=ImageAdjust(),
        color_animation=anim,
    )
    object.__setattr__(piece, "color_local_origin", 2.0)
    pieces = expand_export_clip_for_color(piece)
    assert pieces
    # Mid of this piece is clip-local ~3.0 → near the warm end of warm_up.
    assert pieces[-1].image.warmth >= 25
    # Without origin the same absolute mid (~1s into the piece) would sample ~1.0.
    bare = StudioExportClip(
        source_path=Path("x.mp4"),
        kind="video",
        duration_s=2.0,
        source_start_s=12.0,
        source_end_s=14.0,
        image=ImageAdjust(),
        color_animation=anim,
    )
    wrong = expand_export_clip_for_color(bare)
    assert wrong[-1].image.warmth < pieces[-1].image.warmth


def test_apply_keyed_image_passthrough() -> None:
    base = ImageAdjust(exposure=5, highlights=10)
    anim = ColorAnimation(
        bar_start_s=0,
        bar_end_s=2,
        keys=(ColorKey(t=0), ColorKey(t=2, warmth=40)),
    )
    out = apply_keyed_image(base, anim, 2.0)
    assert out.warmth == 40
    assert out.highlights == 10


def test_color_animation_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.app import create_app
    from orga_drone.config import Settings
    from orga_drone.db import make_identity_key

    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    app = create_app()
    db = app.state.db
    root = tmp_path / "media"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    video = root / "clip.MP4"
    video.write_bytes(b"\x00\x00\x00\x14ftypmp42" + b"\x00" * 32)
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": video.name,
            "path": str(video.resolve()),
            "size_bytes": video.stat().st_size,
            "duration_s": 4.0,
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
    headers = {
        "Origin": "http://testserver",
        "Referer": "http://testserver/studio",
        "Sec-Fetch-Site": "same-origin",
    }
    client = TestClient(app)
    ok = client.patch(
        f"/api/studio/{clip_id}/color-animation",
        json={"preset_id": "warm_up", "bar": {"start_s": 0.0, "end_s": 3.0}},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["ok"] is True
    assert body["color_animation"]["preset_id"] == "warm_up"
    assert body["effect_lane"]["color_animation"]["mode"] == "preset"
    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="inspector-color-animation"' in page.text
    assert "data-color-animation-model=" in page.text
    moved = client.patch(
        f"/api/studio/{clip_id}/effect-lane",
        json={"kind": "color", "op": "update", "start_s": 0.5, "end_s": 2.5},
        headers=headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["effect_lane"]["color_animation"]["bar"]["start_s"] == 0.5
    deleted = client.patch(
        f"/api/studio/{clip_id}/effect-lane",
        json={"kind": "color", "op": "delete"},
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["effect_lane"]["color_animation"] is None
