"""Current pairing stays in memory. This is not a new credential store."""

from __future__ import annotations

import hashlib

import pytest

from orga_drone.control import ControlError, ControlService
from orga_drone.db import Database


def test_enable_keeps_a_digest_and_disable_drops_it(tmp_path) -> None:
    service = ControlService(Database(tmp_path / "orga-drone.sqlite3"), tmp_path)
    key = "ab" * 32
    service.enable({"session_id": "editor-1", "pairing_key": key})
    assert service.digest == hashlib.sha256(key.encode()).digest()
    assert key.encode() not in service.digest
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert key.encode() not in path.read_bytes()
    service.disable()
    assert service.digest is None
    with pytest.raises(ControlError) as caught:
        service.authenticate("Bearer " + key)
    assert caught.value.code == "CONTROL_DISABLED"
