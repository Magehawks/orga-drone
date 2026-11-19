"""Process-isolated spatial photo bake + in-flight dedupe (#509/#510)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from orga_drone.studio_managed_apply import ManagedApplyError
from orga_drone.studio_managed_spatial_export import materialize_spatial_managed_media
from orga_drone.studio_spatial_bake_process import (
    should_bake_photo_in_process,
)


def _grade() -> dict:
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": "sel-1",
                "params": {
                    "exposure": 0.2,
                    "kelvin": 6500,
                    "tint": 0,
                    "contrast": 1.0,
                    "pivot": 0.18,
                    "saturation": 0.0,
                    "blacks": 0,
                    "shadows": 0,
                    "highlights": 0,
                    "whites": 0,
                },
            }
        ],
        "selections": [
            {
                "id": "sel-1",
                "invert": False,
                "mask": {
                    "combine": "union",
                    "leaves": [
                        {
                            "type": "radial",
                            "center": [0.5, 0.5],
                            "axes": [0.35, 0.35],
                            "feather": 0.05,
                        }
                    ],
                },
                "qualifier": {"type": "none"},
            }
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def _write(path: Path, size: tuple[int, int] = (128, 128)) -> Path:
    Image.new("RGB", size, (90, 40, 30)).save(path, format="JPEG", quality=90)
    return path


def test_should_bake_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORGA_SPATIAL_BAKE_INLINE", raising=False)
    monkeypatch.delenv("ORGA_SPATIAL_BAKE_PROCESS", raising=False)
    assert should_bake_photo_in_process(width=32, height=32) is False
    assert should_bake_photo_in_process(width=128, height=128) is True
    monkeypatch.setenv("ORGA_SPATIAL_BAKE_INLINE", "1")
    assert should_bake_photo_in_process(width=512, height=512) is False


def test_process_bake_publishes_graded_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORGA_SPATIAL_BAKE_PROCESS", "1")
    source = _write(tmp_path / "src.jpg", (128, 96))
    graded = materialize_spatial_managed_media(
        source,
        _grade(),
        tmp_path / "work",
        kind="photo",
        grade_digest="procbake01deadbeef",
    )
    assert graded.name == "graded.png"
    assert graded.is_file() and graded.stat().st_size > 0
    with Image.open(graded) as img:
        assert img.size == (128, 96)


def test_inflight_dedupe_single_bake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORGA_SPATIAL_BAKE_PROCESS", "1")
    source = _write(tmp_path / "src.jpg", (160, 120))
    work = tmp_path / "work"
    digest = "dedupe01cafebabe"
    results: list[Path] = []
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            results.append(
                materialize_spatial_managed_media(
                    source,
                    _grade(),
                    work,
                    kind="photo",
                    grade_digest=digest,
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not errors, errors
    assert len(results) == 3
    assert len({p.resolve() for p in results}) == 1
    # Exactly one published artifact under the digest work dir.
    published = list(work.rglob("graded.png"))
    assert len(published) == 1


def test_cancel_before_bake_refuses_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORGA_SPATIAL_BAKE_PROCESS", "1")
    source = _write(tmp_path / "src.jpg", (128, 96))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ManagedApplyError) as excinfo:
        materialize_spatial_managed_media(
            source,
            _grade(),
            tmp_path / "work",
            kind="photo",
            grade_digest="cancel01deadbeef",
            cancel_event=cancel,
        )
    assert excinfo.value.code == "CANCELLED"
    assert not list((tmp_path / "work").rglob("graded.png"))


def test_run_photo_grade_process_terminates_on_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone import studio_spatial_bake_process as bake_mod

    class _FakeProc:
        def __init__(self, *args, **kwargs) -> None:
            self._alive = True
            self.exitcode: int | None = None
            self.terminated = False

        def start(self) -> None:
            return None

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout: float | None = None) -> None:
            time.sleep(min(0.05, float(timeout or 0.05)))

        def terminate(self) -> None:
            self.terminated = True
            self._alive = False
            self.exitcode = -15

        def kill(self) -> None:
            self._alive = False
            self.exitcode = -9

    class _FakeCtx:
        def Process(self, **kwargs):  # noqa: N802
            return _FakeProc(**kwargs)

    monkeypatch.setattr(
        bake_mod.multiprocessing, "get_context", lambda _method="spawn": _FakeCtx()
    )
    cancel = threading.Event()
    still = _write(tmp_path / "still.jpg", (64, 64))
    tmp = tmp_path / "out.tmp.png"

    def _set_cancel() -> None:
        time.sleep(0.05)
        cancel.set()

    threading.Thread(target=_set_cancel, daemon=True).start()
    with pytest.raises(ManagedApplyError) as excinfo:
        bake_mod.run_photo_grade_process(still, _grade(), tmp, cancel_event=cancel, poll_s=0.05)
    assert excinfo.value.code == "CANCELLED"
    assert not tmp.is_file()
