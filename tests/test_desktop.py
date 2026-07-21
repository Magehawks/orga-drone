"""Tests for desktop shell startup helpers (port pick + readiness wait)."""

from __future__ import annotations

import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import uvicorn

from orga_drone.desktop import (
    configure_stdio_and_logging,
    find_listen_port,
    uvicorn_log_config,
    wait_http,
    wait_server_ready,
    wait_tcp,
)


def test_windowed_stdio_uvicorn_logging(monkeypatch, tmp_path) -> None:
    """console=False leaves stdout/stderr as None — logging must still configure."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    log_file = tmp_path / "orga-drone.log"
    monkeypatch.setattr(
        "orga_drone.desktop.startup_log_path",
        lambda: log_file,
    )

    configure_stdio_and_logging()
    assert sys.stdout is not None
    assert sys.stderr is not None
    assert sys.stdout.isatty() is False

    config = uvicorn.Config(
        lambda: None,
        host="127.0.0.1",
        port=0,
        log_config=uvicorn_log_config(),
        log_level="warning",
        access_log=False,
    )
    config.configure_logging()  # must not raise AttributeError/ValueError



def test_find_listen_port_prefers_free_preferred() -> None:
    preferred = find_listen_port("127.0.0.1", 0)
    assert preferred > 0
    # Preferred is free again after probe — should get same when asking for it.
    assert find_listen_port("127.0.0.1", preferred) == preferred


def test_find_listen_port_skips_busy() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        busy = int(holder.getsockname()[1])
        alt = find_listen_port("127.0.0.1", busy)
        assert alt != busy
        assert alt > 0


def test_wait_tcp_and_health() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert wait_tcp(host, port, timeout_s=5.0)
        assert wait_http(f"http://{host}:{port}/health", timeout_s=5.0)
        assert wait_server_ready(host, port, timeout_s=5.0)
    finally:
        server.shutdown()
        thread.join(timeout=2.0)


def test_wait_tcp_times_out_on_closed_port() -> None:
    port = find_listen_port("127.0.0.1", 0)
    started = time.monotonic()
    assert wait_tcp("127.0.0.1", port, timeout_s=0.3) is False
    assert time.monotonic() - started >= 0.25
