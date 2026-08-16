"""Tests for desktop shell startup helpers (port pick + readiness wait)."""

from __future__ import annotations

import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import uvicorn

from orga_drone import desktop
from orga_drone.desktop import (
    DesktopActionUnavailable,
    can_open_local_file,
    can_reveal_local_file,
    configure_stdio_and_logging,
    find_listen_port,
    open_local_file,
    reveal_local_file,
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


def test_can_open_and_reveal_only_on_win32(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    assert can_open_local_file() is True
    assert can_reveal_local_file() is True
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    assert can_open_local_file() is False
    assert can_reveal_local_file() is False


def test_open_local_file_unavailable_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    with pytest.raises(DesktopActionUnavailable):
        open_local_file(Path("/tmp/a.mp4"))


def test_reveal_local_file_unavailable_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    with pytest.raises(DesktopActionUnavailable):
        reveal_local_file(Path("/tmp/a.mp4"))


def test_open_local_file_uses_startfile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    called: list[str] = []
    monkeypatch.setattr(
        desktop.os, "startfile", lambda path: called.append(path), raising=False
    )
    path = tmp_path / "story.mp4"
    open_local_file(path)
    assert called == [str(path)]


def test_reveal_local_file_explorer_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(args: list[str], **kwargs: object) -> object:
        calls.append((list(args), kwargs))
        return object()

    monkeypatch.setattr(desktop.subprocess, "Popen", fake_popen)
    path = tmp_path / "story.mp4"
    path.write_bytes(b"mp4")
    reveal_local_file(path)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["explorer", "/select,", str(path.resolve())]
    assert kwargs.get("shell") is False


def test_clr_dll_path_is_unsafe_for_windows_copy_suffix() -> None:
    from orga_drone.desktop import clr_dll_path_is_unsafe

    bad = Path(
        r"D:\downloads\orga-drone-windows-x64(2)\orga-drone"
        r"\_internal\pythonnet\runtime\Python.Runtime.dll"
    )
    good = Path(
        r"C:\Users\me\orga-drone\dist\orga-drone"
        r"\_internal\pythonnet\runtime\Python.Runtime.dll"
    )
    assert clr_dll_path_is_unsafe(bad) is True
    assert clr_dll_path_is_unsafe(good) is False


def test_prepare_pythonnet_relocates_parenthesized_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pythonnet
    from orga_drone.config import Settings
    from orga_drone.desktop import prepare_pythonnet_runtime

    pkg = tmp_path / "orga-drone-windows-x64(2)" / "pythonnet"
    runtime = pkg / "runtime"
    runtime.mkdir(parents=True)
    (pkg / "__init__.py").write_text("#", encoding="utf-8")
    (runtime / "Python.Runtime.dll").write_bytes(b"dll")
    (runtime / "Python.Runtime.deps.json").write_text("{}", encoding="utf-8")

    data_dir = tmp_path / "data"
    monkeypatch.setattr(pythonnet, "__file__", str(pkg / "__init__.py"))
    monkeypatch.setattr("orga_drone.desktop.settings", Settings(data_dir=data_dir))
    original_load = pythonnet.load
    try:
        dest = prepare_pythonnet_runtime()
        expected = data_dir / "clr-runtime" / "Python.Runtime.dll"
        assert dest == expected
        assert expected.is_file()
        assert expected.read_bytes() == b"dll"
        assert (data_dir / "clr-runtime" / "Python.Runtime.deps.json").read_text(
            encoding="utf-8"
        ) == "{}"
        assert pythonnet.load is not original_load
    finally:
        pythonnet.load = original_load


def test_log_desktop_failure_writes_startup_crash_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.config import Settings
    from orga_drone.desktop import log_desktop_failure

    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.desktop.settings", settings)
    path = log_desktop_failure(RuntimeError("clr boom"))
    assert path.name == "startup-crash.log"
    text = path.read_text(encoding="utf-8")
    assert "RuntimeError" in text
    assert "clr boom" in text


def test_packaged_desktop_failure_does_not_open_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone import __main__ as mainmod
    from orga_drone.config import Settings

    browser_calls: list[int] = []
    monkeypatch.setattr(mainmod, "_prefer_desktop", lambda: True)
    monkeypatch.setattr(
        mainmod,
        "_run_desktop",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("clr boom")),
    )
    monkeypatch.setattr(
        mainmod, "_run_browser", lambda *a, **k: browser_calls.append(1)
    )
    monkeypatch.setattr(mainmod, "_want_browser", lambda: False)
    monkeypatch.setattr(mainmod, "_prepare_runtime", lambda: None)
    monkeypatch.setattr(
        "orga_drone.desktop.show_error_dialog", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "orga_drone.desktop.settings", Settings(data_dir=tmp_path / "data")
    )
    monkeypatch.setattr("orga_drone.config.is_packaged", lambda: True)
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=tmp_path / "data"))

    mainmod.main()
    assert browser_calls == []


def test_packaged_missing_webview_does_not_open_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone import __main__ as mainmod
    from orga_drone.config import Settings

    browser_calls: list[int] = []
    monkeypatch.setattr(mainmod, "_prefer_desktop", lambda: False)
    monkeypatch.setattr(
        mainmod, "_run_browser", lambda *a, **k: browser_calls.append(1)
    )
    monkeypatch.setattr(mainmod, "_want_browser", lambda: False)
    monkeypatch.setattr(mainmod, "_prepare_runtime", lambda: None)
    monkeypatch.setattr(
        "orga_drone.desktop.show_error_dialog", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "orga_drone.desktop.settings", Settings(data_dir=tmp_path / "data")
    )
    monkeypatch.setattr("orga_drone.config.is_packaged", lambda: True)
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=tmp_path / "data"))

    mainmod.main()
    assert browser_calls == []


def test_unpackaged_desktop_failure_falls_back_to_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone import __main__ as mainmod
    from orga_drone.config import Settings

    browser_calls: list[int] = []
    monkeypatch.setattr(mainmod, "_prefer_desktop", lambda: True)
    monkeypatch.setattr(
        mainmod,
        "_run_desktop",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("clr boom")),
    )
    monkeypatch.setattr(
        mainmod, "_run_browser", lambda *a, **k: browser_calls.append(1)
    )
    monkeypatch.setattr(mainmod, "_want_browser", lambda: False)
    monkeypatch.setattr(mainmod, "_prepare_runtime", lambda: None)
    monkeypatch.setattr(
        "orga_drone.desktop.show_error_dialog", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "orga_drone.desktop.settings", Settings(data_dir=tmp_path / "data")
    )
    monkeypatch.setattr("orga_drone.config.is_packaged", lambda: False)

    mainmod.main()
    assert browser_calls == [1]

