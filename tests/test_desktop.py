"""Tests for desktop shell startup helpers (port pick + readiness wait)."""

from __future__ import annotations

import importlib.util
import os
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
    app_window_icon_path,
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


def _snapshot_pythonnet_modules() -> dict[str, object]:
    return {
        n: sys.modules[n]
        for n in list(sys.modules)
        if n == "pythonnet" or n.startswith("pythonnet.")
    }


def _restore_pythonnet_modules(saved: dict[str, object]) -> None:
    for name in [k for k in sys.modules if k == "pythonnet" or k.startswith("pythonnet.")]:
        del sys.modules[name]
    sys.modules.update(saved)  # type: ignore[arg-type]


def _fake_webview_lib(root: Path) -> Path:
    lib = root / "lib"
    (lib / "runtimes" / "win-x64" / "native").mkdir(parents=True)
    (lib / "Microsoft.Web.WebView2.Core.dll").write_bytes(b"core")
    (lib / "Microsoft.Web.WebView2.WinForms.dll").write_bytes(b"winforms")
    (lib / "WebBrowserInterop.x64.dll").write_bytes(b"interop")
    (lib / "runtimes" / "win-x64" / "native" / "WebView2Loader.dll").write_bytes(b"loader")
    return lib


def _fake_motw_stat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report a Zone.Identifier stream for every probed file (Explorer unzip)."""
    real_stat = os.stat

    def fake_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if str(path).endswith(":Zone.Identifier"):
            return os.stat_result((0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type, call-overload]

    monkeypatch.setattr("orga_drone.desktop.os.stat", fake_stat)


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


def test_app_window_icon_path_points_at_packaged_ico() -> None:
    path = app_window_icon_path()
    assert path is not None
    assert path.name == "orga-drone.ico"
    assert path.is_file()
    assert path.stat().st_size > 1000


def test_webview_start_accepts_icon_kwarg() -> None:
    """WinForms reads start(icon=); create_window has no icon parameter."""
    webview = pytest.importorskip("webview")
    import inspect

    start_params = inspect.signature(webview.start).parameters
    window_params = inspect.signature(webview.create_window).parameters
    assert "icon" in start_params
    assert "icon" not in window_params


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


def test_pythonnet_runtime_dll_matches_stock_load_formula() -> None:
    from orga_drone.desktop import pythonnet_runtime_dll

    pkg = Path("/tmp/pythonnet")
    assert pythonnet_runtime_dll(pkg) == pkg / "runtime" / "Python.Runtime.dll"


def test_prepare_pythonnet_copies_full_package_onto_sys_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stock pythonnet.load() uses Path(__file__).parent/runtime/*.dll — copy that tree."""
    from orga_drone.config import Settings
    from orga_drone.desktop import (
        prepare_pythonnet_runtime,
        pythonnet_runtime_dll,
    )

    src_pkg = tmp_path / "orga-drone-windows-x64(2)" / "pythonnet"
    runtime = src_pkg / "runtime"
    runtime.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text("# pythonnet stub\n", encoding="utf-8")
    (runtime / "Python.Runtime.dll").write_bytes(b"dll")
    (runtime / "Python.Runtime.deps.json").write_text("{}", encoding="utf-8")
    (runtime / "netstandard.dll").write_bytes(b"facade")

    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "orga_drone.desktop._find_pythonnet_package", lambda: src_pkg
    )
    monkeypatch.setattr("orga_drone.desktop.settings", Settings(data_dir=data_dir))
    monkeypatch.setattr(sys, "path", list(sys.path))
    saved = _snapshot_pythonnet_modules()

    dest = prepare_pythonnet_runtime()
    try:
        home = data_dir / "pythonnet-home"
        dest_pkg = home / "pythonnet"
        expected_dll = pythonnet_runtime_dll(dest_pkg)
        assert dest == expected_dll
        assert expected_dll.is_file()
        assert expected_dll.read_bytes() == b"dll"
        assert (dest_pkg / "runtime" / "netstandard.dll").read_bytes() == b"facade"
        assert (dest_pkg / "runtime" / "Python.Runtime.deps.json").read_text(
            encoding="utf-8"
        ) == "{}"
        assert (dest_pkg / "__init__.py").is_file()
        assert sys.path[0] == str(home)
        spec = importlib.util.find_spec("pythonnet")
        assert spec is not None and spec.origin is not None
        assert Path(spec.origin).resolve().parent == dest_pkg.resolve()
        import pythonnet

        assert Path(pythonnet.__file__).resolve() == (dest_pkg / "__init__.py").resolve()
        assert pythonnet_runtime_dll(Path(pythonnet.__file__).parent) == expected_dll
    finally:
        _restore_pythonnet_modules(saved)


def test_bind_wins_over_meta_path_finder_claiming_pythonnet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PyInstaller FrozenImporter claims pythonnet before PathFinder; bind must win."""
    from orga_drone.config import Settings
    from orga_drone.desktop import prepare_pythonnet_runtime

    src_pkg = tmp_path / "orga-drone-windows-x64(2)" / "pythonnet"
    runtime = src_pkg / "runtime"
    runtime.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text("MARKER = 'copied'\n", encoding="utf-8")
    (runtime / "Python.Runtime.dll").write_bytes(b"dll")

    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "orga_drone.desktop._find_pythonnet_package", lambda: src_pkg
    )
    monkeypatch.setattr("orga_drone.desktop.settings", Settings(data_dir=data_dir))
    monkeypatch.setattr(sys, "path", list(sys.path))

    class ClaimPythonnet:
        def find_spec(self, fullname: str, path: object = None, target: object = None):
            if fullname != "pythonnet":
                return None
            return importlib.util.spec_from_file_location(
                "pythonnet",
                src_pkg / "__init__.py",
                submodule_search_locations=[str(src_pkg)],
            )

    monkeypatch.setattr(sys, "meta_path", [ClaimPythonnet(), *list(sys.meta_path)])
    saved = _snapshot_pythonnet_modules()
    for n in list(saved):
        del sys.modules[n]
    try:
        dest_pkg = data_dir / "pythonnet-home" / "pythonnet"
        prepare_pythonnet_runtime()
        import pythonnet

        assert Path(pythonnet.__file__).resolve() == (dest_pkg / "__init__.py").resolve()
        assert "orga-drone-windows-x64(2)" not in pythonnet.__file__
    finally:
        _restore_pythonnet_modules(saved)


def test_materialize_init_when_src_package_has_no_py(tmp_path: Path) -> None:
    """Need the real installed pythonnet; skip on Linux CI where it is absent."""
    saved = _snapshot_pythonnet_modules()
    _restore_pythonnet_modules({})
    spec = importlib.util.find_spec("pythonnet")
    origin = Path(spec.origin) if spec is not None and spec.origin else None
    if origin is None or not origin.is_file():
        pytest.skip("pythonnet not installed")
    source = origin.read_text(encoding="utf-8")
    if "def load(" not in source or "Python.Runtime.dll" not in source:
        pytest.skip("pythonnet package is not the installed runtime module")
    from orga_drone.desktop import _materialize_pythonnet_init

    src_pkg = tmp_path / "pythonnet"
    (src_pkg / "runtime").mkdir(parents=True)
    dest_pkg = tmp_path / "dest" / "pythonnet"
    dest_pkg.mkdir(parents=True)
    try:
        init = _materialize_pythonnet_init(src_pkg, dest_pkg)
        assert init.is_file()
        text = init.read_text(encoding="utf-8")
        assert "def load(" in text
        assert "Python.Runtime.dll" in text
    finally:
        _restore_pythonnet_modules(saved)


def test_frozen_zone_identifier_triggers_relocate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.config import Settings
    from orga_drone.desktop import (
        clr_dll_path_is_unsafe,
        prepare_pythonnet_runtime,
        pythonnet_runtime_dll,
    )

    src_pkg = tmp_path / "pythonnet"
    runtime = src_pkg / "runtime"
    runtime.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text("#\n", encoding="utf-8")
    (runtime / "Python.Runtime.dll").write_bytes(b"dll")
    src_dll = pythonnet_runtime_dll(src_pkg)
    assert clr_dll_path_is_unsafe(src_dll) is False

    monkeypatch.setattr("orga_drone.desktop._find_pythonnet_package", lambda: src_pkg)
    monkeypatch.setattr(
        "orga_drone.desktop.settings", Settings(data_dir=tmp_path / "data")
    )
    monkeypatch.setattr("orga_drone.desktop.sys.frozen", True, raising=False)
    monkeypatch.setattr("orga_drone.desktop.sys.platform", "win32")
    monkeypatch.setattr(sys, "path", list(sys.path))

    _fake_motw_stat(monkeypatch)
    saved = _snapshot_pythonnet_modules()
    try:
        dest = prepare_pythonnet_runtime()
        expected = pythonnet_runtime_dll(
            tmp_path / "data" / "pythonnet-home" / "pythonnet"
        )
        assert dest == expected
        assert expected.is_file()
    finally:
        _restore_pythonnet_modules(saved)


def test_frozen_motw_copies_webview_lib_and_patches_interop_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HRESULT 0x80131515: LoadFrom of MOTW-stamped WebView2.Core.dll."""
    pytest.importorskip("webview")
    import webview.util as util
    from orga_drone.config import Settings
    from orga_drone.desktop import prepare_webview_runtime

    src_lib = _fake_webview_lib(tmp_path / "unzipped" / "webview")
    dest_lib = tmp_path / "data" / "webview-lib"
    monkeypatch.setattr("orga_drone.desktop._webview_lib_dir", lambda: src_lib)
    monkeypatch.setattr(
        "orga_drone.desktop.settings", Settings(data_dir=tmp_path / "data")
    )
    monkeypatch.setattr("orga_drone.desktop.sys.frozen", True, raising=False)
    monkeypatch.setattr("orga_drone.desktop.sys.platform", "win32")
    _fake_motw_stat(monkeypatch)
    stripped: list[str] = []
    monkeypatch.setattr("orga_drone.desktop.os.remove", stripped.append)
    original = util.interop_dll_path
    try:
        result = prepare_webview_runtime()
        assert result == dest_lib
        assert (dest_lib / "Microsoft.Web.WebView2.Core.dll").read_bytes() == b"core"
        assert (dest_lib / "Microsoft.Web.WebView2.WinForms.dll").read_bytes() == b"winforms"
        assert (dest_lib / "WebBrowserInterop.x64.dll").read_bytes() == b"interop"
        native = dest_lib / "runtimes" / "win-x64" / "native" / "WebView2Loader.dll"
        assert native.read_bytes() == b"loader"
        assert f"{dest_lib / 'Microsoft.Web.WebView2.Core.dll'}:Zone.Identifier" in stripped
        assert util.interop_dll_path("Microsoft.Web.WebView2.Core.dll") == str(
            dest_lib / "Microsoft.Web.WebView2.Core.dll"
        )
        assert util.interop_dll_path("win-x64") == str(
            dest_lib / "runtimes" / "win-x64" / "native"
        )
    finally:
        util.interop_dll_path = original


def test_webview_lib_stays_in_place_without_motw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("webview")
    import webview.util as util
    from orga_drone.config import Settings
    from orga_drone.desktop import prepare_webview_runtime

    src_lib = _fake_webview_lib(tmp_path / "dist" / "webview")
    monkeypatch.setattr("orga_drone.desktop._webview_lib_dir", lambda: src_lib)
    monkeypatch.setattr(
        "orga_drone.desktop.settings", Settings(data_dir=tmp_path / "data")
    )
    monkeypatch.setattr("orga_drone.desktop.sys.frozen", True, raising=False)
    original = util.interop_dll_path
    try:
        assert prepare_webview_runtime() == src_lib
        assert not (tmp_path / "data" / "webview-lib").exists()
        assert util.interop_dll_path is original
    finally:
        util.interop_dll_path = original


def test_prepare_runtime_copies_webview_lib_before_desktop_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import orga_drone.__main__ as mainmod

    calls: list[str] = []
    monkeypatch.setattr(
        "orga_drone.desktop.configure_stdio_and_logging", lambda: calls.append("stdio")
    )
    monkeypatch.setattr(
        "orga_drone.desktop.prepare_pythonnet_runtime", lambda: calls.append("pythonnet")
    )
    monkeypatch.setattr(
        "orga_drone.desktop.prepare_webview_runtime", lambda: calls.append("webview")
    )

    mainmod._prepare_runtime()

    assert calls == ["stdio", "pythonnet", "webview"]


def test_copy_file_strips_zone_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.desktop import _copy_file_without_zone, _strip_zone_identifier

    src = tmp_path / "src.dll"
    dest = tmp_path / "dest.dll"
    src.write_bytes(b"payload")
    monkeypatch.setattr("orga_drone.desktop.sys.platform", "win32")
    removed: list[str] = []

    def fake_remove(path: str) -> None:
        removed.append(path)

    monkeypatch.setattr("orga_drone.desktop.os.remove", fake_remove)
    _copy_file_without_zone(src, dest)
    assert dest.read_bytes() == b"payload"
    assert removed == [f"{dest}:Zone.Identifier"]
    _strip_zone_identifier(dest)
    assert removed[-1] == f"{dest}:Zone.Identifier"


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

