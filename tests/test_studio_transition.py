"""Studio visual transitions: math, persist, HTTP (Issue #27)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_estimate import summarize_studio_items
from orga_drone.studio_transition import (
    DEFAULT_DURATION_S,
    TYPE_CROSSFADE,
    TYPE_CUT,
    TYPE_FADE_BLACK,
    apply_boundaries,
    apply_one_boundary,
    clamp_user_duration,
    clip_flex_s,
    fade_in_s,
    fade_out_s,
    normalize_type,
    occupancy_s,
    resolve_story_time,
    story_length_s,
    story_starts_s,
)


def test_normalize_legacy_and_unknown() -> None:
    assert normalize_type(None) == TYPE_CUT
    assert normalize_type("none") == TYPE_CUT
    assert normalize_type("fade") == TYPE_CUT
    assert normalize_type("slide") == TYPE_CUT
    assert normalize_type("fade=t=in") == TYPE_CUT
    assert normalize_type("fade_black") == TYPE_FADE_BLACK
    assert normalize_type("CROSSFADE") == TYPE_CROSSFADE
    assert normalize_type("cut") == TYPE_CUT


def test_clamp_user_duration_steps() -> None:
    assert clamp_user_duration(0.05) == 0.1
    assert clamp_user_duration(2.4) == 2.0
    assert clamp_user_duration(0.54) == 0.5
    assert clamp_user_duration(0.56) == 0.6


def test_cut_and_fade_black_keep_story_length() -> None:
    durs = [3.0, 4.0, 5.0]
    types = [TYPE_FADE_BLACK, TYPE_CUT, TYPE_CUT]
    stored = [0.5, None, None]
    applied = apply_boundaries(durs, types, stored)
    assert applied[0].type == TYPE_FADE_BLACK
    assert applied[0].duration_s == pytest.approx(0.5)
    assert applied[1].type == TYPE_CUT
    assert story_length_s(durs, applied) == pytest.approx(12.0)
    assert fade_out_s(applied[0]) == pytest.approx(0.25)
    assert fade_in_s(applied[0]) == pytest.approx(0.25)


def test_crossfade_subtracts_overlap() -> None:
    durs = [3.0, 4.0]
    types = [TYPE_CROSSFADE, TYPE_CUT]
    stored = [0.5, None]
    applied = apply_boundaries(durs, types, stored)
    assert applied[0].is_crossfade
    assert story_length_s(durs, applied) == pytest.approx(6.5)
    starts = story_starts_s(durs, applied)
    assert starts == [pytest.approx(0.0), pytest.approx(2.5)]
    assert clip_flex_s(3.0, applied[0]) == pytest.approx(2.5)
    assert clip_flex_s(4.0, None) == pytest.approx(4.0)


def test_default_duration_when_none_stored() -> None:
    applied = apply_one_boundary(TYPE_CROSSFADE, None, 3.0, 3.0)
    assert applied.duration_s == pytest.approx(DEFAULT_DURATION_S)


def test_clamp_short_photo_default_crossfade() -> None:
    """0.5 s photo, default 0.5 s crossfade → applied 0.4 s."""
    applied = apply_one_boundary(TYPE_CROSSFADE, 0.5, 0.5, 3.0)
    assert applied.type == TYPE_CROSSFADE
    assert applied.duration_s == pytest.approx(0.4)
    assert applied.clamped is True
    assert applied.fallback_cut is False


def test_neighbor_too_short_falls_back_to_cut() -> None:
    applied = apply_one_boundary(TYPE_FADE_BLACK, 0.5, 0.15, 3.0)
    assert applied.type == TYPE_CUT
    assert applied.fallback_cut is True
    assert applied.duration_s == 0.0


def test_two_sided_occupancy_falls_back_outgoing() -> None:
    # 0.5s clip with incoming and outgoing 0.4s crossfades cannot fit both.
    durs = [3.0, 0.5, 3.0]
    types = [TYPE_CROSSFADE, TYPE_CROSSFADE, TYPE_CUT]
    stored = [0.4, 0.4, None]
    applied = apply_boundaries(durs, types, stored)
    assert applied[0].type == TYPE_CROSSFADE
    assert applied[1].type == TYPE_CUT
    assert applied[1].fallback_cut is True


def test_last_clip_stored_value_ignored() -> None:
    durs = [2.0, 2.0]
    types = [TYPE_CUT, TYPE_CROSSFADE]
    stored = [None, 0.8]
    applied = apply_boundaries(durs, types, stored)
    assert len(applied) == 1
    assert applied[0].type == TYPE_CUT


def test_resolve_story_time_crossfade_shows_both() -> None:
    durs = [2.0, 2.0]
    applied = apply_boundaries(durs, [TYPE_CROSSFADE, TYPE_CUT], [0.5, None])
    during = resolve_story_time(durs, applied, 1.7)
    assert during is not None
    assert during.overlap_index is not None
    assert {during.index, during.overlap_index} == {0, 1}
    assert during.crossfade_progress is not None
    assert 0.0 < during.crossfade_progress < 1.0
    after = resolve_story_time(durs, applied, 2.2)
    assert after is not None
    assert after.index == 1
    assert after.overlap_index is None


def test_resolve_story_time_fade_black_overlay() -> None:
    durs = [2.0, 2.0]
    applied = apply_boundaries(durs, [TYPE_FADE_BLACK, TYPE_CUT], [0.5, None])
    late_a = resolve_story_time(durs, applied, 1.9)
    assert late_a is not None
    assert late_a.index == 0
    assert late_a.overlap_index is None
    assert late_a.fade_black_opacity == pytest.approx(0.6, abs=0.05)
    early_b = resolve_story_time(durs, applied, 2.1)
    assert early_b is not None
    assert early_b.index == 1
    assert early_b.fade_black_opacity == pytest.approx(0.6, abs=0.05)
    assert story_length_s(durs, applied) == pytest.approx(4.0)


def test_occupancy_values() -> None:
    assert occupancy_s(TYPE_CUT, 0.5) == 0.0
    assert occupancy_s(TYPE_FADE_BLACK, 0.5) == pytest.approx(0.25)
    assert occupancy_s(TYPE_CROSSFADE, 0.5) == pytest.approx(0.5)


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed_video(db: Database, root_path: Path, name: str = "DJI_0001.MP4") -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / name
    media_file.write_bytes(b"fake-video")
    path = str(media_file.resolve())
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": name,
            "path": path,
            "size_bytes": 10,
            "duration_s": 12.0,
            "recorded_at": "2024-01-02T10:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": "Avata 2",
            "camera_model": None,
            "source_type": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": False,
            "has_lrf": False,
            "track_json": None,
        }
    )


def _add_video(db: Database, project_id: int, root: Path, name: str) -> int:
    media_id = _seed_video(db, root, name)
    media = db.get_media(media_id)
    assert media is not None
    clip_id, _ = db.add_studio_item(
        media.path,
        identity_key=make_identity_key(media.filename, media.size_bytes, media.recorded_at),
        filename=media.filename,
        recorded_at=media.recorded_at,
        kind="video",
        project_id=project_id,
        source_media_id=media.id,
    )
    return clip_id


def test_cut_only_estimate_matches_sum(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Cuts")
    _add_video(db, project.id, tmp_path / "m1", "A.MP4")
    _add_video(db, project.id, tmp_path / "m2", "B.MP4")
    items = db.list_studio_items(project.id)
    summary = summarize_studio_items(items)
    assert summary.estimated_total_s == pytest.approx(24.0)


def test_persist_isolate_and_http_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    a = db.create_studio_project("A")
    b = db.create_studio_project("B")
    db.set_open_studio_project_id(a.id)
    id1 = _add_video(db, a.id, tmp_path / "a1", "A1.MP4")
    id2 = _add_video(db, a.id, tmp_path / "a2", "A2.MP4")
    _add_video(db, b.id, tmp_path / "b1", "B1.MP4")
    _add_video(db, b.id, tmp_path / "b2", "B2.MP4")

    patched = client.patch(
        f"/api/studio/{id1}/transition",
        json={"type": "crossfade", "duration_s": 0.8},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["type"] == TYPE_CROSSFADE
    assert body["duration_s"] == pytest.approx(0.8)
    assert body["applied_type"] == TYPE_CROSSFADE
    assert body["summary"]["estimated_total_s"] == pytest.approx(23.2)

    page = client.get("/studio")
    assert page.status_code == 200
    html = page.text
    assert 'data-transition-type="crossfade"' in html
    assert "slide" not in html.lower() or "value=\"slide\"" not in html
    assert "Placeholder" not in html
    assert "None" not in html.split('id="inspector-transition"', 1)[-1].split("</div>", 1)[0]
    inspector = html.split('id="inspector-transition"', 1)[1].split('id="inspector-music"', 1)[0]
    assert 'value="slide"' not in inspector
    assert 'value="none"' not in inspector
    assert "Cut" in inspector or "Schnitt" in inspector

    other = db.list_studio_items(b.id)
    assert all(normalize_type(i.transition) == TYPE_CUT for i in other)

    reopened = Database(db.path)
    stored = {i.id: i for i in reopened.list_studio_items(a.id)}
    assert stored[id1].transition == TYPE_CROSSFADE
    assert stored[id1].transition_duration_s == pytest.approx(0.8)
    assert stored[id2].transition in {None, TYPE_CUT}

    too_small = client.patch(
        f"/api/studio/{id1}/transition",
        json={"type": "fade_black", "duration_s": 0.05},
    )
    assert too_small.status_code == 200
    assert too_small.json()["duration_s"] == pytest.approx(0.1)


def test_video_cut_left_is_cut_right_inherits(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Split")
    clip_id = _add_video(db, project.id, tmp_path / "m", "A.MP4")
    _add_video(db, project.id, tmp_path / "n", "B.MP4")
    db.set_studio_transition(clip_id, TYPE_CROSSFADE, 0.5)
    left, right = db.cut_studio_video_item(clip_id, 4.0)
    assert normalize_type(left.transition) == TYPE_CUT
    assert right.transition == TYPE_CROSSFADE
    assert right.transition_duration_s == pytest.approx(0.5)


def test_reorder_keeps_outgoing_on_clip(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Order")
    a = _add_video(db, project.id, tmp_path / "a", "A.MP4")
    b = _add_video(db, project.id, tmp_path / "b", "B.MP4")
    c = _add_video(db, project.id, tmp_path / "c", "C.MP4")
    db.set_studio_transition(a, TYPE_FADE_BLACK, 0.5)
    db.reorder_studio_items([c, a, b], project_id=project.id)
    items = {i.id: i for i in db.list_studio_items(project.id)}
    assert items[a].transition == TYPE_FADE_BLACK
    summary = summarize_studio_items(db.list_studio_items(project.id))
    assert summary.estimated_total_s == pytest.approx(36.0)


def test_prepare_export_attaches_fade_and_crossfade(tmp_path: Path) -> None:
    from orga_drone.studio_export import prepare_studio_export

    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Cards")
    first = db.add_studio_title_card(project.id, title_text="A", card_duration_s=3.0)
    db.add_studio_title_card(project.id, title_text="B", card_duration_s=3.0)
    db.set_studio_transition(first.id, TYPE_FADE_BLACK, 0.5)
    dest = tmp_path / "out.mp4"
    cfg = prepare_studio_export(
        db, height=1080, output_path=dest, overwrite=True, project_id=project.id
    )
    assert cfg.clips[0].transition_type == TYPE_FADE_BLACK
    assert cfg.clips[0].fade_out_s == pytest.approx(0.25)
    assert cfg.clips[1].fade_in_s == pytest.approx(0.25)
    db.set_studio_transition(first.id, TYPE_CROSSFADE, 0.5)
    cfg = prepare_studio_export(
        db, height=1080, output_path=dest, overwrite=True, project_id=project.id
    )
    assert cfg.clips[0].transition_type == TYPE_CROSSFADE
    assert cfg.clips[0].transition_s == pytest.approx(0.5)
    assert cfg.clips[0].fade_out_s == pytest.approx(0.0)


def test_preview_css_keeps_outgoing_layer_below_incoming() -> None:
    css = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "orga_drone"
        / "static"
        / "css"
        / "app.css"
    ).read_text(encoding="utf-8")
    assert "img.studio-preview-media.studio-preview-layer-b" in css
    assert "video.studio-preview-media.studio-preview-layer-b" in css


def test_stitch_filters_use_xfade_fade_and_audio_hardcut() -> None:
    from orga_drone.export.studio_config import StudioExportClip
    from orga_drone.export.studio_encoder import build_stitch_filters

    clips = (
        StudioExportClip(
            source_path=None,
            kind="title_card",
            duration_s=3.0,
            transition_type=TYPE_CROSSFADE,
            transition_s=0.5,
        ),
        StudioExportClip(
            source_path=None,
            kind="title_card",
            duration_s=3.0,
        ),
    )
    filters = build_stitch_filters(clips)
    joined = ";".join(filters)
    assert "xfade=transition=fade" in joined
    assert "fadeblack" not in joined
    assert "acrossfade" not in joined
    assert "atrim=0:2.7500" in joined
    assert "atrim=0.2500" in joined
    assert "settb=1/30" in joined


def test_stitch_filters_normalize_timebase_before_second_xfade() -> None:
    """Chained xfade after concat must reset timebase (FFmpeg 7 encoder-EOF)."""
    from orga_drone.export.studio_config import StudioExportClip
    from orga_drone.export.studio_encoder import build_stitch_filters

    clips = (
        StudioExportClip(
            source_path=None,
            kind="video",
            duration_s=3.0,
            transition_type=TYPE_CROSSFADE,
            transition_s=1.2,
        ),
        StudioExportClip(source_path=None, kind="video", duration_s=3.0),
        StudioExportClip(
            source_path=None,
            kind="video",
            duration_s=3.0,
            transition_type=TYPE_CROSSFADE,
            transition_s=0.5,
        ),
        StudioExportClip(source_path=None, kind="video", duration_s=3.0),
    )
    joined = ";".join(build_stitch_filters(clips))
    assert joined.count("xfade=transition=fade") == 2
    assert "offset=7.3000" in joined
    assert joined.count("settb=1/30") >= 6
    # Pre-fix graph fed the concat pad straight into the second xfade.
    assert "[xv1][3:v]xfade" not in joined
    assert "[xv1]fps=30,format=yuv420p,settb=1/30[vl2]" in joined
    assert "[vl2][vr2]xfade=transition=fade:duration=0.5000:offset=7.3000[xv2]" in joined
