"""Application entrypoint: `python -m orga_drone` or `orga-drone`."""

from __future__ import annotations

import os
import sys
import webbrowser
from threading import Timer


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _want_browser() -> bool:
    """Force system browser when ORGA_DRONE_BROWSER=1."""
    return _env_truthy("ORGA_DRONE_BROWSER")


def _webview_available() -> bool:
    try:
        import webview  # noqa: F401

        return True
    except ImportError:
        return False


def _prefer_desktop() -> bool:
    """Desktop window by default when pywebview is installed (packaged or not)."""
    if _want_browser():
        return False
    return _webview_available()


def _load_app():
    from orga_drone.app import create_app

    return create_app()


def _prepare_runtime() -> None:
    """Fix windowed-EXE stdio (None when console=False) before uvicorn touches isatty."""
    from orga_drone.desktop import configure_stdio_and_logging

    configure_stdio_and_logging()


def _run_browser(host: str, port: int, *, packaged: bool) -> None:
    import uvicorn

    from orga_drone.desktop import (
        find_listen_port,
        uvicorn_log_config,
        wait_server_ready,
    )

    listen_port = find_listen_port(host, port)
    url = f"http://{host}:{listen_port}/"

    def _open_when_ready() -> None:
        if wait_server_ready(host, listen_port, timeout_s=25.0):
            webbrowser.open(url)

    Timer(0.05, _open_when_ready).start()

    log_level = "warning" if packaged else "info"
    access_log = not packaged
    # log_config sets use_colors=False on DefaultFormatter (no isatty).
    common = {
        "host": host,
        "port": listen_port,
        "log_level": log_level,
        "access_log": access_log,
        "log_config": uvicorn_log_config(),
    }

    if getattr(sys, "frozen", False):
        uvicorn.run(_load_app(), **common)
    else:
        uvicorn.run(
            "orga_drone.app:create_app",
            factory=True,
            **common,
        )


def _run_desktop(host: str, port: int) -> None:
    from orga_drone.desktop import run_desktop

    # Quiet logs in the desktop shell (no console access-log spam).
    log_level = "warning"
    access_log = False
    run_desktop(
        _load_app(),
        host=host,
        port=port,
        log_level=log_level,
        access_log=access_log,
    )


def main() -> None:
    from orga_drone.config import is_packaged, settings

    # Must run before any uvicorn.Config / uvicorn.run (windowed EXE: stdout is None).
    _prepare_runtime()

    host = settings.host
    port = settings.port
    packaged = is_packaged()

    if packaged:
        # Signal to the rest of the app / docs that we are in a frozen build.
        os.environ.setdefault("ORGA_DRONE_PACKAGED", "1")

    if _prefer_desktop():
        try:
            _run_desktop(host, port)
            return
        except Exception as exc:  # noqa: BLE001 — fall back to browser UX
            print(f"Desktop window unavailable ({exc}); opening system browser.", file=sys.stderr)

    _run_browser(host, port, packaged=packaged)


if __name__ == "__main__":
    main()
