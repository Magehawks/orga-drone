"""Application entrypoint: `python -m orga_drone` or `orga-drone`."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer
from typing import Any


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
    """Fix windowed-EXE stdio and CLR assembly paths before pywebview imports."""
    from orga_drone.desktop import (
        configure_stdio_and_logging,
        prepare_pythonnet_runtime,
        prepare_webview_runtime,
    )

    configure_stdio_and_logging()
    # Must run before import webview: pythonnet.load() uses
    # Path(__file__).parent/runtime/Python.Runtime.dll with no public override.
    # Unsafe unzip paths and Mark-of-the-Web copies need a full package relocate.
    prepare_pythonnet_runtime()
    # GitHub zip + Explorer extract stamps WebView2 DLLs with Mark-of-the-Web;
    # .NET LoadFrom then fails with HRESULT 0x80131515. Copy + patch before start.
    prepare_webview_runtime()


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
    common: dict[str, Any] = {
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


def _report_desktop_failure(exc: BaseException) -> None:
    from orga_drone.desktop import log_desktop_failure, show_error_dialog

    crash = log_desktop_failure(exc)
    show_error_dialog(
        "orga-drone",
        "The desktop window could not start. Native file dialogs "
        "(library folder, soundtrack, export) need this window.\n\n"
        f"{type(exc).__name__}: {exc}\n\nDetails: {crash}",
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


def _geocode_probe() -> None:
    """Write one offline lookup. Used to show the frozen LGPL modules are the ones that run."""
    import reverse_geocoder

    from orga_drone.geocode import lookup_offline

    place = lookup_offline(48.137154, 11.576124)
    lines = [
        f"module {reverse_geocoder.__file__}",
        f"author {reverse_geocoder.__author__}",
        f"city {place.city if place else ''}",
        f"region {place.region if place else ''}",
        f"cc {place.country_code if place else ''}",
    ]
    text = "\n".join(lines) + "\n"
    if getattr(sys, "frozen", False):
        dest = Path(sys.executable).resolve().parent / "geocode-probe.txt"
    else:
        dest = Path.cwd() / "geocode-probe.txt"
    dest.write_text(text, encoding="utf-8")


def main() -> None:
    from orga_drone.config import is_packaged, settings

    if _env_truthy("ORGA_DRONE_GEOCODE_PROBE"):
        _geocode_probe()
        return

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
        except Exception as exc:  # noqa: BLE001 — log; packaged EXE must not hide this
            _report_desktop_failure(exc)
            if packaged and not _want_browser():
                return
    elif packaged and not _want_browser():
        _report_desktop_failure(
            RuntimeError("pywebview is not available in this packaged build")
        )
        return

    _run_browser(host, port, packaged=packaged)


if __name__ == "__main__":
    main()
