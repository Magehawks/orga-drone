"""Synthetic shared-library and authenticated read-action contracts (#277)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orga_drone.library_actions import LibraryActionError, read_media
from tests.test_control_api import action_command
from tests.test_search import _seed

pytest_plugins = ["tests.test_control_api"]


def read(client, headers, sid, action="library.media.list", params=None, target=None):
    return client.post(
        "/api/control/v1/read-actions",
        headers=headers,
        json={
            "session_id": sid,
            "action": action,
            "action_version": 1,
            "target": target or {},
            "params": params or {},
        },
    )


def test_list_search_metadata_parity_and_source_safety(control, tmp_path):
    client, db, service, sid, state, headers = control
    root = tmp_path / "media"
    ids = [
        _seed(db, root, filename=name, kind=kind, recorded_at="2025-11-05")
        for name, kind in [
            ("DJI_001.MP4", "video"),
            ("IMG_002.JPG", "photo"),
            ("IMG_003.PNG", "photo"),
        ]
    ]
    before = {p: p.read_bytes() for p in root.iterdir() if p.is_file()}
    filters = {"kind": "photo", "sort": "filename", "order": "asc"}
    result = read(client, headers, sid, params=filters).json()["result"]
    assert [item["id"] for item in result["items"]] == [
        row.id for row in db.list_media(**filters)
    ]
    assert result["total"] == 2
    assert result["items"][0]["duration_s"] is None
    assert all(item["available"] for item in result["items"])
    search = read(
        client, headers, sid, "library.media.search", {"ask": "photos November 2025"}
    ).json()["result"]
    ui = client.post(
        "/api/search", json={"ask": "photos November 2025"}, headers=headers
    ).json()
    assert {item["id"] for item in search["items"]} == {
        item["id"] for item in ui["items"]
    }
    for mid in ids:
        response = read(
            client, headers, sid, "library.media.get", target={"media_id": mid}
        )
        assert response.status_code == 200
        item = response.json()["result"]["item"]
        assert item["id"] == mid and item["drone_model"] == "Avata 2"
        assert not {"path", "root_id", "track_json", "place", "notes"} & item.keys()
        assert str(tmp_path) not in response.text
    assert {p: p.read_bytes() for p in before} == before
    assert not service.commands


@pytest.mark.parametrize(
    "media_id", [True, False, 0, -1, 1.2, "1", "../source", 2**53, None]
)
def test_invalid_ids(control, media_id):
    client, _, _, sid, _, headers = control
    response = read(
        client, headers, sid, "library.media.get", target={"media_id": media_id}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IDENTIFIER"


def test_missing_offline_and_outside_root(control, tmp_path):
    client, db, _, sid, _, headers = control
    absent = read(client, headers, sid, "library.media.get", target={"media_id": 99999})
    assert absent.status_code == 404
    item = db.list_media()[0]
    # Simulate an offline source by renaming only this test's synthetic file.
    Path(item.path).rename(tmp_path / "offline.fixture")
    listing = read(client, headers, sid).json()["result"]
    assert listing["items"][0]["available"] is False
    assert (
        read(
            client, headers, sid, "library.media.get", target={"media_id": item.id}
        ).json()["error"]["code"]
        == "MEDIA_UNAVAILABLE"
    )
    outside = tmp_path / "outside.MP4"
    outside.write_bytes(b"synthetic outside")
    with db.connect() as conn:
        conn.execute("UPDATE media SET path=? WHERE id=?", (str(outside), item.id))
    assert (
        read(
            client, headers, sid, "library.media.get", target={"media_id": item.id}
        ).status_code
        == 409
    )
    assert outside.read_bytes() == b"synthetic outside"


@pytest.mark.parametrize(
    "params",
    [
        {"path": "C:/private"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"limit": True},
        {"q": "x" * 513},
        {"kind": "audio"},
        {"favorite": "yes"},
        {"date_from": "2025-02-30"},
        {"date_from": "2025-12-01", "date_to": "2025-01-01"},
    ],
)
def test_strict_bounded_params(control, params):
    client, _, _, sid, _, headers = control
    response = read(client, headers, sid, params=params)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PARAMS"


def test_reads_require_credentials_live_session_and_origin(control):
    client, _, service, sid, state, headers = control
    assert read(client, {}, sid).status_code == 401
    assert (
        read(client, dict(headers, Authorization="Bearer wrong"), sid).status_code
        == 401
    )
    assert read(client, headers, "other-session").status_code == 409
    assert (
        read(client, dict(headers, Origin="http://untrusted.invalid"), sid).status_code
        == 403
    )
    # Read availability is independent of selected clip / color readiness.
    service.poll({"session_id": sid, "state": dict(state, clip_id=None, ready=False)})
    assert read(client, headers, sid).status_code == 200
    service.clock = lambda: float("inf")
    assert read(client, headers, sid).json()["error"]["code"] == "EDITOR_DISCONNECTED"


def test_reads_cannot_be_admitted_as_mutations(control):
    client, _, service, sid, state, headers = control
    cmd = action_command(service, sid, state, "library.media.list", {})
    response = client.post("/api/control/v1/commands", headers=headers, json=cmd)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ACTION_SCOPE"
    assert not service.commands


def test_corrupt_optional_metadata_and_bounded_pagination(control):
    client, db, _, sid, _, headers = control
    item = db.list_media()[0]
    with db.connect() as conn:
        conn.execute(
            "UPDATE media SET duration_s=?, place_json=?, auto_tags_json=?, track_json=? WHERE id=?",
            ("bad", "{", "{", "{", item.id),
        )
    response = read(
        client, headers, sid, "library.media.get", target={"media_id": item.id}
    )
    assert response.status_code == 200
    assert response.json()["result"]["item"]["duration_s"] is None
    result = read(client, headers, sid, params={"limit": 1, "offset": 1}).json()[
        "result"
    ]
    assert result["total"] == 1 and result["items"] == []
    assert "bad" not in json.dumps(response.json())


def test_shared_query_collapse_matches_browse(control):
    _, db, _, _, _, _ = control
    expected = db.list_media(sessions_only=False, flows_only=False)
    result = read_media(
        db, "library.media.list", {}, {"sessions_only": False, "flows_only": False}
    )
    assert [item["id"] for item in result["items"]] == [item.id for item in expected]
    with pytest.raises(LibraryActionError, match="INVALID_TARGET"):
        read_media(db, "library.media.list", {"media_id": 1}, {})
