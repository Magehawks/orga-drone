"""Remove a cut by joining adjacent source clips (Issue #160)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orga_drone.db import Database, StudioClip
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_image import SaturationRamp, dump_saturation_ramp, shift_saturation_ramp_settings
from orga_drone.studio_merge import MergeBlocked, plan_merge
from orga_drone.studio_overlay import split_overlay_settings
from tests.test_studio_history import _client, _seed


def _clip(
    clip_id: int,
    *,
    position: int,
    start: float,
    end: float,
    path: str = "C:/clips/A.MP4",
    identity: str = "same",
    speed: float = 1.0,
    volume: float = 1.0,
    transition: str = "cut",
    settings: str = "{}",
    kind: str = "video",
    duration: float = 20.0,
) -> StudioClip:
    return StudioClip(
        id=clip_id,
        project_id=1,
        media_path=path,
        identity_key=identity,
        position=position,
        filename_snapshot="A.MP4",
        recorded_at_snapshot=None,
        kind_snapshot=kind,
        photo_duration_s=None,
        added_at="2024-06-01T12:00:00",
        available=True,
        source_media_id=1,
        filename="A.MP4",
        recorded_at=None,
        kind=kind,
        duration_s=duration,
        source_start=start,
        source_end=end,
        playback_speed=speed,
        volume=volume,
        transition=transition,
        effect_settings=settings,
    )


def test_plan_refuses_gap_reverse_speed_and_mask_mismatch() -> None:
    left = _clip(1, position=0, start=0.0, end=4.0)
    gap = _clip(2, position=1, start=4.2, end=8.0)
    with pytest.raises(MergeBlocked) as gap_exc:
        plan_merge([left, gap], 2)
    assert gap_exc.value.code == "not_contiguous"

    reversed_clip = _clip(2, position=1, start=0.0, end=4.0)
    later = _clip(1, position=0, start=4.0, end=8.0)
    with pytest.raises(MergeBlocked) as order_exc:
        plan_merge([later, reversed_clip], 2)
    assert order_exc.value.code == "reversed"

    slower = _clip(2, position=1, start=4.0, end=8.0, speed=0.5)
    with pytest.raises(MergeBlocked) as speed_exc:
        plan_merge([left, slower], 2)
    assert speed_exc.value.code == "speed"

    other_file = _clip(2, position=1, start=4.0, end=8.0, path="C:/clips/B.MP4")
    with pytest.raises(MergeBlocked) as file_exc:
        plan_merge([left, other_file], 2)
    assert file_exc.value.code == "different_file"

    masked = '{"masks":[{"id":"m1","effect":"blur","strength":40,"x":0.1,"y":0.1,"w":0.2,"h":0.2}]}'
    with pytest.raises(MergeBlocked) as mask_exc:
        plan_merge([_clip(1, position=0, start=0.0, end=4.0, settings=masked), _clip(2, position=1, start=4.0, end=8.0)], 2)
    assert mask_exc.value.code == "masks"


def test_plan_rejoins_a_split_overlay_and_ramp() -> None:
    original = json.dumps(
        {
            "overlays": [
                {
                    "id": "ov1",
                    "kind": "text",
                    "start_s": 1.0,
                    "end_s": 8.0,
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.4,
                    "h": 0.16,
                    "text": "Hello",
                }
            ]
        }
    )
    left_settings, right_settings = split_overlay_settings(original, 4.0, left_s=4.0, right_s=6.0)
    ramp = SaturationRamp(
        enabled=True, start_s=1.0, end_s=7.0, start_saturation=100, end_saturation=0
    )
    left_ramp = dump_saturation_ramp(left_settings, ramp)
    right_ramp = shift_saturation_ramp_settings(dump_saturation_ramp(right_settings, ramp), 4.0)
    plan = plan_merge(
        [
            _clip(1, position=0, start=0.0, end=4.0, settings=left_ramp),
            _clip(2, position=1, start=4.0, end=10.0, settings=right_ramp),
        ],
        2,
    )
    stored = json.loads(plan.effect_settings)
    assert stored["saturation_ramp"]["start_s"] == pytest.approx(1.0)
    assert stored["saturation_ramp"]["end_s"] == pytest.approx(7.0)
    overlay = stored["overlays"][0]
    assert overlay["id"] == "ov1"
    assert overlay["start_s"] == pytest.approx(1.0)
    assert overlay["end_s"] == pytest.approx(8.0)
    assert overlay["text"] == "Hello"
    assert plan.source_end == pytest.approx(10.0)


def test_merge_keeps_the_file_and_undo_restores_the_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    clip_id = _seed(db, tmp_path / "a", "A.MP4", 12.0)
    opened = db.resolve_studio_page_project()
    assert opened is not None
    source = tmp_path / "a" / "A.MP4"
    before = source.read_bytes()
    cut = client.post(f"/api/studio/{clip_id}/cut", json={"local_s": 4.0})
    assert cut.status_code == 200
    right_id = int(cut.json()["right_id"])
    left_id = int(cut.json()["left_id"])

    status = client.get(f"/api/studio/{right_id}/merge-previous", cookies={"lang": "en"})
    assert status.status_code == 200
    assert status.json()["ok"] is True

    merged = client.post(f"/api/studio/{right_id}/merge-previous")
    assert merged.status_code == 200
    body = merged.json()
    assert body["id"] == left_id
    assert body["source_in_s"] == pytest.approx(0.0)
    assert body["source_out_s"] == pytest.approx(12.0)
    assert body["effective_duration_s"] == pytest.approx(12.0)
    stored = db.list_studio_items(opened.id)
    assert [item.id for item in stored] == [left_id]
    assert source.read_bytes() == before

    reopened = Database(db.path)
    again = reopened.list_studio_items(opened.id)
    assert [item.id for item in again] == [left_id]
    assert again[0].source_end == pytest.approx(12.0)

    exported = _clip_to_export_clip(db, again[0])
    assert exported is not None
    assert exported.source_start_s == pytest.approx(0.0)
    assert exported.source_end_s == pytest.approx(12.0)
    assert exported.duration_s == pytest.approx(12.0)
    assert exported.source_path == source.resolve()

    undo = client.post("/api/studio/history/undo")
    assert undo.status_code == 200
    restored = db.list_studio_items(opened.id)
    assert [item.id for item in restored] == [left_id, right_id]
    assert restored[0].source_end == pytest.approx(4.0)
    assert restored[1].source_start == pytest.approx(4.0)
    redo = client.post("/api/studio/history/redo")
    assert redo.status_code == 200
    assert [item.id for item in db.list_studio_items(opened.id)] == [left_id]
    assert source.read_bytes() == before


def test_merge_refuses_a_changed_mask_and_a_fade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    first = _seed(db, tmp_path / "a", "A.MP4", 12.0)
    db.resolve_studio_page_project()
    cut = client.post(f"/api/studio/{first}/cut", json={"local_s": 4.0})
    assert cut.status_code == 200
    right_id = int(cut.json()["right_id"])
    left_id = int(cut.json()["left_id"])
    masked = client.patch(
        f"/api/studio/{right_id}/masks",
        json={
            "masks": [
                {"id": "mask1", "effect": "blur", "strength": 40, "x": 0.2, "y": 0.2, "w": 0.3, "h": 0.2}
            ]
        },
    )
    assert masked.status_code == 200
    blocked = client.get(f"/api/studio/{right_id}/merge-previous", cookies={"lang": "en"})
    assert blocked.json()["ok"] is False
    assert blocked.json()["reason"] == "Privacy masks do not match."
    german = client.get(f"/api/studio/{right_id}/merge-previous", cookies={"lang": "de"})
    assert german.json()["reason"] == "Die Datenschutzmasken stimmen nicht überein."
    refused = client.post(f"/api/studio/{right_id}/merge-previous", cookies={"lang": "en"})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Privacy masks do not match."
    opened = db.resolve_studio_page_project()
    assert opened is not None
    assert [item.id for item in db.list_studio_items(opened.id)] == [left_id, right_id]

    client.patch(
        f"/api/studio/{right_id}/masks",
        json={"masks": []},
    )
    fade = client.patch(
        f"/api/studio/{left_id}/transition",
        json={"type": "crossfade", "duration_s": 0.5},
    )
    assert fade.status_code == 200
    still = client.post(f"/api/studio/{right_id}/merge-previous", cookies={"lang": "en"})
    assert still.status_code == 400
    assert still.json()["detail"] == "The transition between these clips is not a cut."
    assert [item.id for item in db.list_studio_items(opened.id)] == [left_id, right_id]


def test_merge_menu_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    _seed(db, tmp_path / "a", "A.MP4", 8.0)
    _seed(db, tmp_path / "a", "B.MP4", 6.0)
    page = client.get("/studio", cookies={"lang": "en"})
    assert 'id="studio-clip-menu-uncut"' in page.text
    assert "Remove cut" in page.text
    assert "Merge with previous" in page.text
    german = client.get("/studio", cookies={"lang": "de"})
    assert "Schnitt entfernen" in german.text
    assert "Mit vorherigem Clip verbinden" in german.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "function mergeWithPrevious" in script
    assert "/merge-previous" in script
    assert 'closest(".studio-transition")' in script
