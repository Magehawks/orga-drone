"""Process-isolated spatial photo bake (#509).

Runs ``_grade_rgb_image`` in a spawned child so the desktop FastAPI/UI process
keeps answering HTTP (status/cancel) under GIL-heavy mask evaluation.

Cancel: parent terminates the child and refuses to publish ``graded.png``.
Packaged EXEs need ``multiprocessing.freeze_support()`` in ``__main__``.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from orga_drone.studio_managed_apply import ManagedApplyError

# Below this pixel count, stay in-process (tests / tiny thumbs).
_PROCESS_MIN_PIXELS = 96 * 96


def _env_force_inline() -> bool:
    return os.getenv("ORGA_SPATIAL_BAKE_INLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_force_process() -> bool:
    return os.getenv("ORGA_SPATIAL_BAKE_PROCESS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def should_bake_photo_in_process(*, width: int, height: int) -> bool:
    if _env_force_inline():
        return False
    if _env_force_process():
        return True
    return int(width) * int(height) >= _PROCESS_MIN_PIXELS


def _photo_grade_worker(
    still_s: str,
    grade_json: str,
    tmp_s: str,
    result_s: str,
    meta: dict[str, Any],
) -> None:
    """Child entry: grade still → tmp PNG; write result JSON."""
    from orga_drone.studio_managed_spatial_export import _grade_rgb_image

    still = Path(still_s)
    tmp = Path(tmp_s)
    result = Path(result_s)
    try:
        grade = json.loads(grade_json)
        if not isinstance(grade, dict):
            raise ManagedApplyError("grade payload invalid", code="UNSUPPORTED_GRADE")
        _grade_rgb_image(
            still,
            grade,
            tmp,
            source_time_s=float(meta.get("source_time_s", 0.0)),
            source_in_s=float(meta.get("source_in_s", 0.0)),
            source_out_s=(
                None
                if meta.get("source_out_s") is None
                else float(meta["source_out_s"])
            ),
            story_anchor_s=(
                None
                if meta.get("story_anchor_s") is None
                else float(meta["story_anchor_s"])
            ),
            playback_speed=float(meta.get("playback_speed", 1.0)),
        )
        result.write_text(
            json.dumps({"ok": True, "tmp": str(tmp)}),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 — surface to parent via result file
        code = getattr(exc, "code", "UNSUPPORTED_GRADE")
        result.write_text(
            json.dumps({"ok": False, "error": str(exc), "code": str(code)}),
            encoding="utf-8",
        )


def run_photo_grade_process(
    still: Path,
    grade: Mapping[str, Any],
    tmp: Path,
    *,
    source_time_s: float = 0.0,
    source_in_s: float = 0.0,
    source_out_s: float | None = None,
    story_anchor_s: float | None = None,
    playback_speed: float = 1.0,
    cancel_event: threading.Event | None = None,
    poll_s: float = 0.2,
) -> Path:
    """Grade ``still`` into ``tmp`` in a child process; honor cancel_event."""
    if cancel_event is not None and cancel_event.is_set():
        raise ManagedApplyError(
            "Spatial managed photo grading was cancelled",
            code="CANCELLED",
        )
    if tmp.is_file():
        tmp.unlink(missing_ok=True)
    result = tmp.with_suffix(tmp.suffix + ".result.json")
    if result.is_file():
        result.unlink(missing_ok=True)

    meta = {
        "source_time_s": float(source_time_s),
        "source_in_s": float(source_in_s),
        "source_out_s": source_out_s,
        "story_anchor_s": story_anchor_s,
        "playback_speed": float(playback_speed),
    }
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(
        target=_photo_grade_worker,
        name="orga-spatial-photo-bake",
        args=(
            str(still),
            json.dumps(dict(grade), separators=(",", ":"), ensure_ascii=True),
            str(tmp),
            str(result),
            meta,
        ),
    )
    proc.start()
    try:
        while proc.is_alive():
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                proc.join(timeout=5.0)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=2.0)
                tmp.unlink(missing_ok=True)
                result.unlink(missing_ok=True)
                raise ManagedApplyError(
                    "Spatial managed photo grading was cancelled",
                    code="CANCELLED",
                )
            proc.join(timeout=poll_s)
        if proc.exitcode not in (0, None) and not result.is_file():
            tmp.unlink(missing_ok=True)
            raise ManagedApplyError(
                f"Spatial bake worker exited with code {proc.exitcode}",
                code="UNSUPPORTED_GRADE",
            )
        if not result.is_file():
            tmp.unlink(missing_ok=True)
            raise ManagedApplyError(
                "Spatial bake worker produced no result",
                code="UNSUPPORTED_GRADE",
            )
        payload = json.loads(result.read_text(encoding="utf-8"))
        if not payload.get("ok"):
            tmp.unlink(missing_ok=True)
            raise ManagedApplyError(
                str(payload.get("error") or "Spatial bake failed"),
                code=str(payload.get("code") or "UNSUPPORTED_GRADE"),
            )
        if not tmp.is_file() or tmp.stat().st_size <= 0:
            raise ManagedApplyError(
                "Spatial bake worker did not write output",
                code="UNSUPPORTED_GRADE",
            )
        return tmp
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2.0)
        result.unlink(missing_ok=True)


# In-flight dedupe for identical spatial work dirs (#510).
_inflight_lock = threading.Lock()
_inflight_waiters: dict[str, threading.Event] = {}
_inflight_errors: dict[str, BaseException] = {}


def inflight_begin(key: str) -> tuple[bool, threading.Event]:
    """Return (owner, waiter). Non-owners must wait then re-check cache."""
    with _inflight_lock:
        existing = _inflight_waiters.get(key)
        if existing is not None:
            return False, existing
        waiter = threading.Event()
        _inflight_waiters[key] = waiter
        _inflight_errors.pop(key, None)
        return True, waiter


def inflight_fail(key: str, exc: BaseException) -> None:
    with _inflight_lock:
        _inflight_errors[key] = exc
        waiter = _inflight_waiters.get(key)
    if waiter is not None:
        waiter.set()


def inflight_finish(key: str) -> None:
    with _inflight_lock:
        waiter = _inflight_waiters.pop(key, None)
        # Keep error until waiters observe it; clear after a short grace via pop on wait.
    if waiter is not None:
        waiter.set()
    # Delayed cleanup of error slot so waiters can read it.
    def _clear() -> None:
        time.sleep(0.05)
        with _inflight_lock:
            _inflight_errors.pop(key, None)

    threading.Thread(target=_clear, name="orga-inflight-clear", daemon=True).start()


def inflight_wait_error(key: str) -> BaseException | None:
    with _inflight_lock:
        return _inflight_errors.get(key)


__all__ = [
    "inflight_begin",
    "inflight_fail",
    "inflight_finish",
    "inflight_wait_error",
    "run_photo_grade_process",
    "should_bake_photo_in_process",
]
