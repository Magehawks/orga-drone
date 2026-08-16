"""Lightweight desktop shell via pywebview (Edge WebView2 on Windows)."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import uvicorn

from orga_drone.config import settings

_LOG = logging.getLogger("orga_drone.desktop")

# .NET Assembly.LoadFrom cannot resolve Python.Runtime.Loader.Initialize when
# the DLL path contains these characters. Windows "Copy (2)" of the GitHub zip
# is the usual trigger: …\orga-drone-windows-x64(2)\orga-drone\_internal\…
_UNSAFE_CLR_PATH_CHARS = frozenset("()[]#&")


def app_window_icon_path() -> Path | None:
    """Local ``.ico`` for the desktop window (packaged and unpackaged).

    pywebview 6.x has no ``icon=`` on ``create_window``. WinForms reads
    ``webview.start(icon=...)`` via ``_state['icon']``; if that is unset it
    extracts the first icon from ``sys.executable``.
    """
    path = Path(__file__).resolve().parent / "static" / "icons" / "orga-drone.ico"
    return path if path.is_file() else None


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


def clr_dll_path_is_unsafe(path: Path) -> bool:
    """True when pythonnet/CLR cannot load Python.Runtime.dll from ``path``."""
    return any(ch in str(path) for ch in _UNSAFE_CLR_PATH_CHARS)


def startup_crash_log_path() -> Path:
    settings.ensure_dirs()
    return settings.data_dir / "startup-crash.log"


def log_desktop_failure(exc: BaseException) -> Path:
    """Persist the desktop-shell exception so windowed EXEs are diagnosable."""
    configure_stdio_and_logging()
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _LOG.error("desktop shell failed:\n%s", tb)
    crash = startup_crash_log_path()
    crash.parent.mkdir(parents=True, exist_ok=True)
    crash.write_text(tb, encoding="utf-8")
    print(f"Desktop window unavailable ({exc})", file=sys.stderr)
    return crash


def pythonnet_runtime_dll(package_dir: Path) -> Path:
    """DLL path used by stock ``pythonnet.load()`` (no public override exists)."""
    return package_dir / "runtime" / "Python.Runtime.dll"


def _strip_zone_identifier(path: Path) -> None:
    """Remove NTFS Mark-of-the-Web so .NET Framework can LoadFrom the copy."""
    if sys.platform != "win32":
        return
    try:
        os.remove(f"{path}:Zone.Identifier")
    except OSError:
        pass


def _copy_file_without_zone(src: Path, dest: Path) -> None:
    """Byte-copy a file so Windows does not preserve Zone.Identifier ADS."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    _strip_zone_identifier(dest)


def _copy_pythonnet_package(src_pkg: Path, dest_pkg: Path) -> None:
    """Copy pythonnet + its full ``runtime/`` facade set (not just the one DLL)."""
    dest_pkg.mkdir(parents=True, exist_ok=True)
    runtime_src = src_pkg / "runtime"
    if runtime_src.is_dir():
        runtime_dest = dest_pkg / "runtime"
        runtime_dest.mkdir(parents=True, exist_ok=True)
        for item in runtime_src.iterdir():
            if item.is_file():
                _copy_file_without_zone(item, runtime_dest / item.name)
    for item in src_pkg.iterdir():
        if item.is_file() and (item.suffix == ".py" or item.name == "py.typed"):
            _copy_file_without_zone(item, dest_pkg / item.name)


def _find_pythonnet_package() -> Path | None:
    """Locate the installed pythonnet package without importing it."""
    import importlib.util

    spec = importlib.util.find_spec("pythonnet")
    if spec is None or not spec.origin:
        return None
    pkg = Path(spec.origin).resolve().parent
    if not pythonnet_runtime_dll(pkg).is_file():
        return None
    return pkg


def _clr_safe_home() -> Path:
    """Directory whose path is safe for .NET LoadFrom (no ``()[]#&``)."""
    local_app = os.environ.get("LOCALAPPDATA", "").strip()
    candidates = [
        settings.data_dir / "pythonnet-home",
        Path(local_app) / "orga-drone" / "pythonnet-home" if local_app else None,
        Path(tempfile.gettempdir()) / "orga-drone-pythonnet-home",
    ]
    for home in candidates:
        if home is not None and str(home) and not clr_dll_path_is_unsafe(home):
            return home
    raise RuntimeError(
        "No CLR-safe directory available for pythonnet "
        "(data dir, LOCALAPPDATA, and TEMP all contain ()[]#&)."
    )


def _drop_imported_pythonnet() -> None:
    for name in [n for n in sys.modules if n == "pythonnet" or n.startswith("pythonnet.")]:
        del sys.modules[name]


def _has_zone_identifier(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    try:
        os.stat(f"{path}:Zone.Identifier")
        return True
    except OSError:
        return False


def _materialize_pythonnet_init(src_pkg: Path, dest_pkg: Path) -> Path:
    """Ensure dest has ``__init__.py`` even if PyInstaller only stored it in the PYZ."""
    dest_init = dest_pkg / "__init__.py"
    src_init = src_pkg / "__init__.py"
    if src_init.is_file():
        _copy_file_without_zone(src_init, dest_init)
        return dest_init
    import inspect

    import pythonnet  # type: ignore[import-untyped]

    dest_init.write_text(inspect.getsource(pythonnet), encoding="utf-8")
    _strip_zone_identifier(dest_init)
    return dest_init


def _bind_pythonnet_from_path(dest_pkg: Path) -> None:
    """Load relocated pythonnet so stock ``load()`` uses dest ``__file__``.

    PyInstaller's FrozenImporter sits on ``sys.meta_path`` ahead of PathFinder,
    so ``sys.path.insert`` is not enough in a frozen EXE.
    """
    import importlib.util

    init_py = dest_pkg / "__init__.py"
    if not init_py.is_file():
        raise RuntimeError(f"relocated pythonnet package missing {init_py}")
    _drop_imported_pythonnet()
    spec = importlib.util.spec_from_file_location(
        "pythonnet",
        init_py,
        submodule_search_locations=[str(dest_pkg)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not create import spec for {init_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["pythonnet"] = module
    spec.loader.exec_module(module)
    _LOG.info("bound stock pythonnet from %s", init_py)


def prepare_pythonnet_runtime() -> Path | None:
    """Ensure stock ``pythonnet.load()`` sees a CLR-safe package path.

    Must run before ``import webview`` / ``import clr``. pythonnet 3.x
    ``load()`` always uses ``Path(__file__).parent / "runtime" / "Python.Runtime.dll"``
    and has no public DLL-path argument. Relocating only that DLL is not enough:
    ``runtime/`` also contains netstandard facade assemblies, and a downloaded zip
    copy may carry a ``Zone.Identifier`` stream that blocks LoadFrom.

    When the installed path is unsafe (or a frozen build carries Mark-of-the-Web),
    the whole package is copied to a CLR-safe home and bound with
    ``importlib.util.spec_from_file_location`` so PyInstaller's FrozenImporter
    cannot keep ``pythonnet.__file__`` on the unzip path. Stock ``pythonnet.load()``
    then uses the relocated ``runtime/`` tree.
    """
    src_pkg = _find_pythonnet_package()
    if src_pkg is None:
        return None

    src_dll = pythonnet_runtime_dll(src_pkg)
    need_relocate = clr_dll_path_is_unsafe(src_dll) or (
        bool(getattr(sys, "frozen", False)) and _has_zone_identifier(src_dll)
    )
    if not need_relocate:
        return src_dll

    home = _clr_safe_home()
    dest_pkg = home / "pythonnet"
    dest_dll = pythonnet_runtime_dll(dest_pkg)
    try:
        _copy_pythonnet_package(src_pkg, dest_pkg)
        _materialize_pythonnet_init(src_pkg, dest_pkg)
    except OSError as exc:
        dest_init = dest_pkg / "__init__.py"
        if not dest_dll.is_file() or not dest_init.is_file():
            raise
        _LOG.warning("could not refresh pythonnet copy at %s (%s)", dest_pkg, exc)
    else:
        _LOG.info("relocated pythonnet package for CLR: %s -> %s", src_pkg, dest_pkg)

    if not dest_dll.is_file():
        _LOG.warning("relocated Python.Runtime.dll missing at %s", dest_dll)
        return None
    if clr_dll_path_is_unsafe(dest_dll):
        _LOG.error("relocated pythonnet path is still CLR-unsafe: %s", dest_dll)
        return None

    sys.path.insert(0, str(home))
    _bind_pythonnet_from_path(dest_pkg)
    return dest_dll


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


class FolderPickerError(Exception):
    """Raised when a native folder dialog cannot be shown."""


class SaveFilePickerError(Exception):
    """Raised when a native save-file dialog cannot be shown."""


class DesktopActionUnavailable(Exception):
    """Raised when opening or revealing a local file is not supported."""


def can_open_local_file() -> bool:
    return sys.platform == "win32"


def can_reveal_local_file() -> bool:
    return sys.platform == "win32"


def open_local_file(path: Path) -> None:
    """Open ``path`` with the OS default application (Windows)."""
    if not can_open_local_file():
        raise DesktopActionUnavailable(
            "Opening local files is not available on this platform."
        )
    os.startfile(str(path))  # type: ignore[attr-defined]


def reveal_local_file(path: Path) -> None:
    """Reveal ``path`` in the file manager (Windows Explorer)."""
    if not can_reveal_local_file():
        raise DesktopActionUnavailable(
            "Revealing files in the folder is not available on this platform."
        )
    # Explorer often exits 1 even on success; do not treat that as failure.
    subprocess.Popen(
        ["explorer", "/select,", str(path.resolve())],
        shell=False,
    )


def pick_folder(*, directory: str = "") -> str | None:
    """Open the OS folder picker via the active pywebview window.

    Uses ``webview.FileDialog.FOLDER`` (cross-platform; no OS-specific APIs).

    Returns:
        Selected directory path, or ``None`` if the user cancelled.

    Raises:
        FolderPickerError: When pywebview is missing or no desktop window is open
            (e.g. browser-only mode).
    """
    try:
        import webview
    except ImportError as exc:
        raise FolderPickerError("pywebview is not available") from exc

    windows = list(getattr(webview, "windows", []) or [])
    if not windows:
        raise FolderPickerError(
            "Native folder picker requires the desktop window "
            "(not available in browser-only mode)"
        )

    result = windows[0].create_file_dialog(
        webview.FileDialog.FOLDER,
        directory=directory or "",
    )
    if not result:
        return None
    chosen = result[0]
    if isinstance(chosen, bytes):
        chosen = chosen.decode("utf-8")
    return str(chosen)


def pick_save_file(
    *,
    directory: str = "",
    save_filename: str = "export.mp4",
    file_types: tuple[str, ...] = ("MP4 Files (*.mp4)",),
) -> str | None:
    """Open the OS save-file dialog via the active pywebview window.

    Returns:
        Selected file path, or ``None`` if the user cancelled.

    Raises:
        SaveFilePickerError: When pywebview is missing or no desktop window is open.
    """
    try:
        import webview
    except ImportError as exc:
        raise SaveFilePickerError("pywebview is not available") from exc

    windows = list(getattr(webview, "windows", []) or [])
    if not windows:
        raise SaveFilePickerError(
            "Native save dialog requires the desktop window "
            "(not available in browser-only mode)"
        )

    result = windows[0].create_file_dialog(
        webview.FileDialog.SAVE,
        directory=directory or "",
        save_filename=save_filename or "export.mp4",
        file_types=file_types,
    )
    if not result:
        return None
    chosen = result[0] if isinstance(result, (list, tuple)) else result
    if isinstance(chosen, bytes):
        chosen = chosen.decode("utf-8")
    path = str(chosen)
    if path and not path.lower().endswith(".mp4"):
        path = f"{path}.mp4"
    return path


class OpenFilePickerError(Exception):
    """Raised when a native open-file dialog cannot be shown."""


def pick_open_file(
    *,
    directory: str = "",
    file_types: tuple[str, ...] = (
        "Audio Files (*.mp3;*.wav;*.m4a;*.aac;*.flac;*.ogg)",
    ),
) -> str | None:
    """Open the OS file-open dialog via the active pywebview window.

    Returns:
        Selected file path, or ``None`` if the user cancelled.

    Raises:
        OpenFilePickerError: When pywebview is missing or no desktop window is open.
    """
    try:
        import webview
    except ImportError as exc:
        raise OpenFilePickerError("pywebview is not available") from exc

    windows = list(getattr(webview, "windows", []) or [])
    if not windows:
        raise OpenFilePickerError(
            "Native file picker requires the desktop window "
            "(not available in browser-only mode)"
        )

    result = windows[0].create_file_dialog(
        webview.FileDialog.OPEN,
        directory=directory or "",
        file_types=file_types,
    )
    if not result:
        return None
    chosen = result[0] if isinstance(result, (list, tuple)) else result
    if isinstance(chosen, bytes):
        chosen = chosen.decode("utf-8")
    return str(chosen)


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
    if window is None:
        raise RuntimeError("webview.create_window returned None")

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
        icon = app_window_icon_path()
        if icon is not None:
            webview.start(_navigate, icon=str(icon))
        else:
            webview.start(_navigate)
    finally:
        if server_box[0] is not None:
            server_box[0].should_exit = True
        thread.join(timeout=3.0)
        _ = window
