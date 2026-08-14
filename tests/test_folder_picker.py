"""Tests for native library folder picker (pywebview FileDialog.FOLDER)."""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orga_drone.desktop import FolderPickerError, pick_folder, pick_open_file


def _make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORGA_DRONE_DATA", str(tmp_path / "data"))
    from orga_drone.app import create_app

    return create_app()


def _install_fake_webview(
    monkeypatch: pytest.MonkeyPatch,
    *,
    windows: list | None = None,
    dialog_result=None,
) -> MagicMock:
    window = MagicMock()
    window.create_file_dialog.return_value = dialog_result
    fake_webview = MagicMock()
    fake_webview.windows = windows if windows is not None else [window]
    fake_webview.FileDialog.FOLDER = 20
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    return window


def test_pick_folder_returns_selected_path(monkeypatch: pytest.MonkeyPatch) -> None:
    window = _install_fake_webview(
        monkeypatch, dialog_result=(r"D:\DroneMedia",)
    )
    assert pick_folder() == r"D:\DroneMedia"
    window.create_file_dialog.assert_called_once_with(
        sys.modules["webview"].FileDialog.FOLDER,
        directory="",
    )


def test_pick_folder_decodes_bytes_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_webview(monkeypatch, dialog_result=(b"/tmp/drone",))
    assert pick_folder() == "/tmp/drone"


def test_pick_folder_cancel_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_webview(monkeypatch, dialog_result=None)
    assert pick_folder() is None


def test_pick_folder_unavailable_without_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_webview(monkeypatch, windows=[], dialog_result=None)
    with pytest.raises(FolderPickerError, match="desktop window"):
        pick_folder()


def test_pick_folder_unavailable_without_webview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "webview", raising=False)
    real_import = builtins.__import__

    def _import(name: str, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name == "webview":
            raise ImportError("no webview")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)
    with pytest.raises(FolderPickerError, match="pywebview"):
        pick_folder()


def test_library_page_shows_browse_button(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _make_app(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/library")
    assert resp.status_code == 200
    assert 'id="browse-folder"' in resp.text
    assert 'id="folder-path"' in resp.text
    assert 'name="path"' in resp.text
    assert "Browse" in resp.text or "Durchsuchen" in resp.text


def test_pick_folder_api_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.desktop.pick_folder",
        lambda *, directory="": r"/media/user/drone",
    )
    app = _make_app(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.post("/api/desktop/pick-folder")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "path": "/media/user/drone"}


def test_pick_folder_api_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.desktop.pick_folder",
        lambda *, directory="": None,
    )
    app = _make_app(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.post("/api/desktop/pick-folder")
    assert resp.status_code == 200
    assert resp.json() == {"status": "cancelled"}


def test_pick_folder_api_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*, directory: str = "") -> str | None:
        raise FolderPickerError("no window")

    monkeypatch.setattr("orga_drone.desktop.pick_folder", _raise)
    app = _make_app(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.post("/api/desktop/pick-folder")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["error"] == "folder_picker_unavailable"


def test_pick_open_file_returns_selected_path(monkeypatch: pytest.MonkeyPatch) -> None:
    window = _install_fake_webview(
        monkeypatch, dialog_result=(r"D:\Music\song.mp3",)
    )
    assert pick_open_file() == r"D:\Music\song.mp3"
    window.create_file_dialog.assert_called_once()
    args, kwargs = window.create_file_dialog.call_args
    assert args[0] == sys.modules["webview"].FileDialog.OPEN


def test_pick_open_file_api_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.desktop.pick_open_file",
        lambda *, directory="", file_types=(): r"C:\Music\a.mp3",
    )
    app = _make_app(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.post("/api/desktop/pick-open-file", json={})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "path": r"C:\Music\a.mp3"}
