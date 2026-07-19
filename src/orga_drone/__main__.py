"""Application entrypoint: `python -m orga_drone` or `orga-drone`."""

from __future__ import annotations

import sys
import webbrowser
from threading import Timer

import uvicorn

from orga_drone.config import settings


def main() -> None:
    host = settings.host
    port = settings.port
    url = f"http://{host}:{port}/"

    def _open() -> None:
        webbrowser.open(url)

    Timer(1.0, _open).start()
    # PyInstaller frozen: import the app object directly (string factory fails when frozen).
    if getattr(sys, "frozen", False):
        from orga_drone.app import create_app

        uvicorn.run(create_app(), host=host, port=port, log_level="info")
    else:
        uvicorn.run(
            "orga_drone.app:create_app",
            factory=True,
            host=host,
            port=port,
            log_level="info",
        )


if __name__ == "__main__":
    main()
