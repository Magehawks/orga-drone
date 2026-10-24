"""Pull-request journey smoke for the local HTTP app.

Uses a temporary data directory and one generated JPEG. It does not open the
desktop window, read a private library, or call the network.

CI runs this file as the **App journey smoke** check. A normal local ``pytest``
includes it as well. See ``docs/PR_E2E.md``.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings

_FILENAME = "pr-journey-smoke.jpg"
_LABEL = "PR journey"
_PROJECT_TITLE = "Journey smoke"


def _write_jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (12, 80, 140)).save(path, format="JPEG")


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """App bound to a temp data dir so the smoke cannot touch the real library."""
    isolated = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.config.settings", isolated)
    monkeypatch.setattr("orga_drone.app.settings", isolated)
    monkeypatch.setattr("orga_drone.auto_tags.settings", isolated)
    from orga_drone.app import create_app

    return TestClient(create_app())


def _wait_scan(client: TestClient, job_id: str, *, timeout_s: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/scan-jobs/{job_id}")
        assert resp.status_code == 200
        payload = resp.json()
        assert isinstance(payload, dict)
        last = payload
        if last["state"] in {"completed", "failed"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"scan job {job_id} did not finish: {last}")


def test_pr_journey_import_browse_and_studio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import a synthetic photo, find it, add it to Studio, then clear the Story."""
    client = _client(tmp_path, monkeypatch)

    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["version"]

    lang = client.get("/lang/en")
    assert lang.status_code == 200

    library = client.get("/library")
    assert library.status_code == 200
    assert "Manage libraries" in library.text
    assert 'name="path"' in library.text
    assert _LABEL not in library.text

    lib = tmp_path / "library"
    photo = lib / _FILENAME
    _write_jpg(photo)

    started = client.post(
        "/library/add",
        data={"path": str(lib), "label": _LABEL},
        follow_redirects=False,
    )
    assert started.status_code == 303
    location = started.headers["location"]
    assert "scan_job=" in location
    job_id = location.split("scan_job=", 1)[1].split("&", 1)[0]

    finished = _wait_scan(client, job_id)
    assert finished["state"] == "completed"
    assert finished["phase"] == "done"
    counts = finished.get("counts") or {}
    assert isinstance(counts, dict)
    assert counts.get("photos") == 1

    library_after = client.get("/library")
    assert library_after.status_code == 200
    assert _LABEL in library_after.text

    browse = client.get("/browse")
    assert browse.status_code == 200
    assert _FILENAME in browse.text
    match = re.search(r'href="/media/(\d+)', browse.text)
    assert match is not None
    media_id = int(match.group(1))

    detail = client.get(f"/media/{media_id}")
    assert detail.status_code == 200
    assert _FILENAME in detail.text
    assert "Add to Studio" in detail.text

    asked = client.get("/browse", params={"ask": "photos"})
    assert asked.status_code == 200
    assert _FILENAME in asked.text

    found = client.post("/api/search", json={"q": _FILENAME})
    assert found.status_code == 200
    found_body = found.json()
    assert found_body["count"] == 1
    assert found_body["items"][0]["filename"] == _FILENAME
    assert found_body["items"][0]["id"] == media_id

    created = client.post("/api/studio/projects", json={"title": _PROJECT_TITLE})
    assert created.status_code == 201
    project_id = created.json()["id"]
    opened = client.post(f"/api/studio/projects/{project_id}/open")
    assert opened.status_code == 200
    assert opened.json()["title"] == _PROJECT_TITLE

    studio_empty = client.get("/studio")
    assert studio_empty.status_code == 200
    assert f'value="{_PROJECT_TITLE}"' in studio_empty.text
    assert "studio-story-empty-track" in studio_empty.text
    assert _FILENAME not in studio_empty.text

    added = client.post(
        f"/media/{media_id}/studio/add",
        data={"return_to": "studio"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    assert added.headers["location"].startswith("/studio")

    studio = client.get("/studio")
    assert studio.status_code == 200
    assert f'data-filename="{_FILENAME}"' in studio.text
    assert "studio-story-empty-track" not in studio.text

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert _FILENAME in dashboard.text

    map_page = client.get("/map")
    assert map_page.status_code == 200
    duplicates = client.get("/duplicates")
    assert duplicates.status_code == 200

    cleared = client.post("/studio/clear", follow_redirects=False)
    assert cleared.status_code == 303
    studio_cleared = client.get("/studio")
    assert "studio-story-empty-track" in studio_cleared.text
    assert _FILENAME not in studio_cleared.text

    still_indexed = client.get("/browse")
    assert _FILENAME in still_indexed.text
    assert photo.is_file()
