"""Thin PyInstaller entrypoint that keeps the orga_drone package layout intact."""

from __future__ import annotations

import traceback
from pathlib import Path


def _log_crash(exc: BaseException) -> None:
    try:
        log = Path.home() / "AppData" / "Roaming" / "orga-drone" / "startup-crash.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    try:
        from orga_drone.__main__ import main

        main()
    except BaseException as exc:  # noqa: BLE001 — log then re-raise for PyInstaller dialog
        _log_crash(exc)
        raise
