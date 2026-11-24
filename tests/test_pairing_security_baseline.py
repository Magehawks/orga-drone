"""Approved pairing security baseline for ADR 0032 (not production #273 pairing).

These tests lock the shipping Control API credential model: caller-supplied key,
in-memory digest only, disable/restart revocation, no key echo or generation.
They are mandatory CI gates. They do not authorize DPAPI, Settings Connect UX,
or app-generated credentials.
"""

from __future__ import annotations

import hashlib
import secrets

import pytest

from orga_drone.control import ControlError, ControlService
from orga_drone.db import Database


def _service(tmp_path) -> ControlService:
    return ControlService(Database(tmp_path / "orga-drone.sqlite3"), tmp_path)


def test_wrong_bearer_is_rejected(tmp_path) -> None:
    service = _service(tmp_path)
    key = "ab" * 32
    service.enable({"session_id": "editor-1", "pairing_key": key})
    with pytest.raises(ControlError) as caught:
        service.authenticate("Bearer " + ("cd" * 32))
    assert caught.value.code == "INVALID_CREDENTIAL"
    assert caught.value.status == 401


def test_missing_bearer_prefix_is_rejected(tmp_path) -> None:
    service = _service(tmp_path)
    key = "ab" * 32
    service.enable({"session_id": "editor-1", "pairing_key": key})
    with pytest.raises(ControlError) as caught:
        service.authenticate(key)
    assert caught.value.code == "INVALID_CREDENTIAL"


def test_disable_revokes_and_rejects_old_bearer(tmp_path) -> None:
    service = _service(tmp_path)
    key = "ab" * 32
    service.enable({"session_id": "editor-1", "pairing_key": key})
    service.disable()
    assert service.digest is None
    with pytest.raises(ControlError) as caught:
        service.authenticate("Bearer " + key)
    assert caught.value.code == "CONTROL_DISABLED"
    assert caught.value.status == 403


def test_reenable_with_new_key_invalidates_old_bearer(tmp_path) -> None:
    service = _service(tmp_path)
    old_key = "ab" * 32
    new_key = "cd" * 32
    service.enable({"session_id": "editor-1", "pairing_key": old_key})
    service.enable({"session_id": "editor-1", "pairing_key": new_key})
    assert service.digest == hashlib.sha256(new_key.encode()).digest()
    with pytest.raises(ControlError) as caught:
        service.authenticate("Bearer " + old_key)
    assert caught.value.code == "INVALID_CREDENTIAL"
    service.authenticate("Bearer " + new_key)


def test_fresh_service_after_restart_has_no_session(tmp_path) -> None:
    first = _service(tmp_path)
    key = "ab" * 32
    first.enable({"session_id": "editor-1", "pairing_key": key})
    restarted = ControlService(first.db, first.data_dir)
    assert not restarted.enabled
    assert restarted.digest is None
    assert restarted.instance != first.instance
    with pytest.raises(ControlError) as caught:
        restarted.authenticate("Bearer " + key)
    assert caught.value.code == "CONTROL_DISABLED"


def test_enable_requires_caller_pairing_key_and_does_not_echo_it(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path)
    with pytest.raises(ControlError) as missing:
        service.enable({"session_id": "editor-1"})
    assert missing.value.code == "INVALID_PAYLOAD"
    generated: list[int] = []

    def _forbid_token_hex(nbytes: int = 32) -> str:
        generated.append(nbytes)
        return "ff" * nbytes

    monkeypatch.setattr(secrets, "token_hex", _forbid_token_hex)
    key = "ab" * 32
    result = service.enable({"session_id": "editor-1", "pairing_key": key})
    assert result == {"enabled": True}
    assert list(result.keys()) == ["enabled"]
    assert key not in repr(result)
    assert key.encode() not in service.digest
    assert service.digest == hashlib.sha256(key.encode()).digest()
    # enable must use the caller key only; never invent credentials via secrets.
    assert generated == []
    service.authenticate("Bearer " + key)


def test_pairing_key_never_written_under_data_dir(tmp_path) -> None:
    service = _service(tmp_path)
    key = "ef" * 32
    service.enable({"session_id": "editor-1", "pairing_key": key})
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert key.encode() not in path.read_bytes()


def test_invalid_pairing_key_shapes_are_rejected(tmp_path) -> None:
    service = _service(tmp_path)
    for bad in ("", "ab" * 31, "AB" * 32, "gh" * 32, 123):
        with pytest.raises(ControlError) as caught:
            service.enable({"session_id": "editor-1", "pairing_key": bad})
        assert caught.value.code in {"INVALID_PAIRING_KEY", "INVALID_PAYLOAD"}
