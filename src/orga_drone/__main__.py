"""Application entrypoint: `python -m orga_drone` or `orga-drone`."""

from __future__ import annotations

import os
import sys
import webbrowser
from threading import Timer

import uvicorn

from orga_drone.config import is_packaged, settings


def main() -> None:
    host = settings.host
    port = settings.port
    url = f"http://{host}:{port}/"
    packaged = is_packaged()

    if packaged:
        # Signal to the rest of the app / docs that we are in a frozen build.
        os.environ.setdefault("ORGA_DRONE_PACKAGED", "1")

    def _open() -> None:
        webbrowser.open(url)

    Timer(1.0, _open).start()

    # Packaged: quiet access log (range requests flood the console + add IO).
    # Dev: keep default info logging.
    log_level = "warning" if packaged else "info"
    access_log = not packaged

    # PyInstaller frozen: import the app object directly (string factory fails when frozen).
    if getattr(sys, "frozen", False):
        from orga_drone.app import create_app

        uvicorn.run(
            create_app(),
            host=host,
            port=port,
            log_level=log_level,
            access_log=access_log,
        )
    else:
        uvicorn.run(
            "orga_drone.app:create_app",
            factory=True,
            host=host,
            port=port,
            log_level=log_level,
            access_log=access_log,
        )


if __name__ == "__main__":
    main()
