"""Lightweight desktop shell via pywebview (Edge WebView2 on Windows)."""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import uvicorn

from orga_drone.config import settings

_LOG = logging.getLogger("orga_drone.desktop")


def startup_log_path() -> Path:
    settings.ensure_dirs()
    return settings.data_dir / "orga-drone.log"


def configure_stdio_and_logging() -> Path:
    """Ensure stdout/stderr exist (windowed EXE) and append logs to app data."""
    log_path = startup_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if sys.stdout is None or sys.stderr is None:
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        if sys.stdout is None:
            sys.stdout = log_file
        if sys.stderr is None:
            sys.stderr = log_file

    root = logging.getLogger()
    if not any(
        isinstance(h, logging.FileHandler)
        and Path(getattr(h, "baseFilename", "")).resolve() == log_path.resolve()
        for h in root.handlers
    ):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
        if root.level > logging.INFO:
            root.setLevel(logging.INFO)

    return log_path


def uvicorn_log_config() -> dict[str, Any]:
    """Uvicorn logging that never relies on a TTY (safe for console=False)."""
    log_path = str(startup_log_path())
    # Use uvicorn formatters: Config injects use_colors into these keys.
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": False,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "use_colors": False,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.FileHandler",
                "filename": log_path,
                "encoding": "utf-8",
            },
            "access": {
                "formatter": "access",
                "class": "logging.FileHandler",
                "filename": log_path,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }


def show_error_dialog(title: str, message: str) -> None:
    """Best-effort native error dialog (Windows MessageBox); else stderr."""
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
            return
    except Exception:  # noqa: BLE001
        pass
    print(f"{title}: {message}", file=sys.stderr)


def find_listen_port(host: str, preferred: int) -> int:
    """Prefer ``preferred`` if free; otherwise bind an ephemeral port."""
    # Avoid SO_REUSEADDR on Windows — it can report a busy port as free.
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                if port == preferred:
                    continue
                raise
            return int(sock.getsockname()[1])
    raise RuntimeError("no free TCP port for orga-drone")


def wait_tcp(host: str, port: int, timeout_s: float = 20.0) -> bool:
    """Poll until a TCP accept is possible on host:port."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def wait_http(url: str, timeout_s: float = 20.0) -> bool:
    """Poll until the local HTTP endpoint answers or timeout."""
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if 200 <= getattr(resp, "status", 200) < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            time.sleep(0.05)
    return False


def wait_server_ready(host: str, port: int, timeout_s: float = 25.0) -> bool:
    """Wait for TCP accept, then GET /health (or / as fallback)."""
    if not wait_tcp(host, port, timeout_s=timeout_s):
        return False
    remaining = max(2.0, timeout_s / 2)
    if wait_http(f"http://{host}:{port}/health", timeout_s=remaining):
        return True
    return wait_http(f"http://{host}:{port}/", timeout_s=2.0)


def run_desktop(
    app: Any,
    *,
    host: str,
    port: int,
    log_level: str = "warning",
    access_log: bool = False,
    width: int = 1280,
    height: int = 800,
) -> None:
    """Serve FastAPI in a background thread and open a native webview window."""
    import webview

    log_path = configure_stdio_and_logging()
    _LOG.info("desktop shell starting (host=%s preferred_port=%s)", host, port)

    listen_port = find_listen_port(host, port)
    url = f"http://{host}:{listen_port}/"
    if listen_port != port:
        _LOG.info("preferred port %s busy; using %s", port, listen_port)

    boot_error: list[BaseException] = []

    def _run_server() -> None:
        try:
            config = uvicorn.Config(
                app,
                host=host,
                port=listen_port,
                log_level=log_level,
                access_log=access_log,
                log_config=uvicorn_log_config(),
            )
            server_box[0] = uvicorn.Server(config)
            server_box[0].run()
        except BaseException as exc:  # noqa: BLE001 — surface to waiter
            boot_error.append(exc)
            _LOG.exception("uvicorn thread crashed: %s", exc)

    server_box: list[Any] = [None]
    thread = threading.Thread(target=_run_server, name="orga-drone-uvicorn", daemon=True)
    thread.start()

    ready = wait_server_ready(host, listen_port)
    if not ready or boot_error:
        detail = ""
        if boot_error:
            detail = f"\n\n{type(boot_error[0]).__name__}: {boot_error[0]}"
        msg = (
            f"orga-drone Server startete nicht unter {url}.{detail}\n\n"
            f"Details: {log_path}"
        )
        _LOG.error("server not ready at %s (errors=%s)", url, boot_error)
        _LOG.error("traceback:\n%s", "".join(traceback.format_stack()))
        if server_box[0] is not None:
            server_box[0].should_exit = True
        show_error_dialog("orga-drone", msg)
        raise RuntimeError(msg)

    # Open blank first, then navigate once the GUI loop is up — avoids WebView2 -102
    # if the native control races the first document load.
    window = webview.create_window(
        "orga-drone",
        "about:blank",
        width=width,
        height=height,
        min_size=(900, 600),
    )

    def _navigate() -> None:
        # Re-check readiness briefly in case the server died between wait and GUI start.
        if wait_server_ready(host, listen_port, timeout_s=5.0):
            window.load_url(url)
            _LOG.info("webview navigated to %s", url)
        else:
            msg = f"Server nicht erreichbar unter {url}.\n\nDetails: {log_path}"
            _LOG.error(msg)
            show_error_dialog("orga-drone", msg)
            window.destroy()

    try:
        webview.start(_navigate)
    finally:
        if server_box[0] is not None:
            server_box[0].should_exit = True
        thread.join(timeout=3.0)
        _ = window
