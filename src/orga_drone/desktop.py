"""Lightweight desktop shell via pywebview (Edge WebView2 on Windows)."""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import uvicorn


def find_listen_port(host: str, preferred: int) -> int:
    """Prefer ``preferred`` if free; otherwise bind an ephemeral port."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                if port == preferred:
                    continue
                raise
            return int(sock.getsockname()[1])
    raise RuntimeError("no free TCP port for orga-drone")


def wait_http(url: str, timeout_s: float = 20.0) -> bool:
    """Poll until the local server answers or timeout."""
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

    listen_port = find_listen_port(host, port)
    url = f"http://{host}:{listen_port}/"

    config = uvicorn.Config(
        app,
        host=host,
        port=listen_port,
        log_level=log_level,
        access_log=access_log,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, name="orga-drone-uvicorn", daemon=True)
    thread.start()

    if not wait_http(url):
        server.should_exit = True
        raise RuntimeError(f"orga-drone server did not start at {url}")

    window = webview.create_window(
        "orga-drone",
        url,
        width=width,
        height=height,
        min_size=(900, 600),
    )

    try:
        webview.start()
    finally:
        server.should_exit = True
        # Give uvicorn a moment to unwind; daemon thread exits with process anyway.
        thread.join(timeout=3.0)
        _ = window  # keep reference until start() returns
