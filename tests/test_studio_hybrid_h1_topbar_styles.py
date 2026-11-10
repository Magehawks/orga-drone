"""Hybrid Crystal H1: computed topbar styles via Chromium CDP.

Uses the real ``app.css`` stylesheet and a minimal Studio topbar fixture.
Browser launch reuses the same websocket CDP pattern as the packaged E2E
harness (``websocket-client``), without adding a new test framework.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "src" / "orga_drone" / "static" / "css" / "app.css"

_FIXTURE_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="/app.css?h1=1">
</head>
<body style="margin:0;background:var(--bg);">
  <div class="studio-creator" id="creator">
    <header class="studio-topbar" id="topbar">
      <a class="button ghost studio-back" id="nav-browse" href="#browse">Back to Browse</a>
      <div class="studio-topbar-title">
        <div class="studio-project-identity">
          <span class="studio-project-identity-label">Project</span>
          <input id="studio-project-title" class="studio-project-title" type="text"
                 value="Very Long Hybrid H1 Project Title For Narrow Export Reachability">
        </div>
        <a class="button ghost studio-icon-button" id="nav-projects" href="#projects">Back to projects</a>
      </div>
      <div class="studio-topbar-actions">
        <button type="button" class="button studio-icon-button studio-topbar-export" id="studio-export-open"
                title="Export" aria-label="Export">Export</button>
      </div>
      <button type="button" class="app-version-button" id="version">
        <span class="app-version studio-app-version">v0.0.0</span>
      </button>
    </header>
  </div>
</body>
</html>
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_json(url: str, timeout: float = 5.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _find_chrome() -> Path:
    env = os.environ.get("ORGA_DRONE_CHROME", "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            return path
    names = (
        "chrome",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "msedge",
        "chrome.exe",
        "msedge.exe",
    )
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft/Edge/Application/msedge.exe",
        Path.home()
        / "AppData/Local/ms-playwright/chromium_headless_shell-1208"
        / "chrome-headless-shell-win64/chrome-headless-shell.exe",
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/microsoft-edge"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    pytest.fail(
        "No Chromium/Chrome/Edge binary found for Hybrid H1 style regressions. "
        "Set ORGA_DRONE_CHROME to a browser executable."
    )


class _FixtureHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(CSS_PATH.parent), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html"}:
            body = _FIXTURE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/app.css":
            body = CSS_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


class _CDP:
    def __init__(self, websocket_url: str) -> None:
        import websocket  # type: ignore[import-untyped]

        self._next_id = 1
        self._ws = websocket.create_connection(
            websocket_url, timeout=20, suppress_origin=True
        )
        self._ws.settimeout(45)

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        message_id = self._next_id
        self._next_id += 1
        self._ws.send(
            json.dumps({"id": message_id, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(self._ws.recv())
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise AssertionError(f"CDP {method} failed: {message['error']}")
            return message.get("result")

    def evaluate(self, expression: str) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        if result.get("exceptionDetails"):
            raise AssertionError(f"JS exception: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def close(self) -> None:
        self._ws.close()


def _reload_fixture(cdp: _CDP, http_port: int) -> None:
    token = int(time.time() * 1000)
    cdp.call(
        "Page.navigate",
        {"url": f"http://127.0.0.1:{http_port}/?reload={token}"},
    )
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        ready = cdp.evaluate(
            "document.readyState === 'complete' && !!document.getElementById('topbar')"
        )
        if ready:
            return
        time.sleep(0.05)
    raise AssertionError("fixture topbar did not reload")


@pytest.fixture(scope="module")
def h1_browser() -> Any:
    assert CSS_PATH.is_file(), f"missing stylesheet: {CSS_PATH}"
    chrome = _find_chrome()
    http_port = _free_port()
    cdp_port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", http_port), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    cmd = [
        str(chrome),
        f"--remote-debugging-port={cdp_port}",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--user-data-dir=" + str(Path(os.environ.get("TMP", "/tmp")) / f"od-h1-{cdp_port}"),
        "about:blank",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cdp: _CDP | None = None
    try:
        deadline = time.monotonic() + 30.0
        version: dict[str, Any] | None = None
        last_error = ""
        while time.monotonic() < deadline:
            try:
                version = _http_json(f"http://127.0.0.1:{cdp_port}/json/version")
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = str(exc)
                time.sleep(0.2)
        if version is None:
            raise AssertionError(f"CDP never appeared on {cdp_port}: {last_error}")

        page = None
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            targets = _http_json(f"http://127.0.0.1:{cdp_port}/json/list")
            assert isinstance(targets, list)
            for target in targets:
                if (
                    isinstance(target, dict)
                    and target.get("type") == "page"
                    and target.get("webSocketDebuggerUrl")
                ):
                    page = target
                    break
            if page is not None:
                break
            time.sleep(0.2)
        assert page is not None, "no CDP page target"

        cdp = _CDP(str(page["webSocketDebuggerUrl"]))
        cdp.call("Page.enable")
        cdp.call("DOM.enable")
        cdp.call("CSS.enable")
        cdp.call("Runtime.enable")
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 1440,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        cdp.call(
            "Page.navigate",
            {"url": f"http://127.0.0.1:{http_port}/"},
        )
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            ready = cdp.evaluate(
                "document.readyState === 'complete' && !!document.getElementById('topbar')"
            )
            if ready:
                break
            time.sleep(0.05)
        assert cdp.evaluate(
            "document.readyState === 'complete' && !!document.getElementById('topbar')"
        ), "fixture topbar did not load"

        yield {"cdp": cdp, "http_port": http_port}
    finally:
        if cdp is not None:
            try:
                cdp.close()
            except Exception:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()


def _styles(cdp: _CDP, selector: str) -> dict[str, str]:
    value = cdp.evaluate(
        f"""(() => {{
          const el = document.querySelector({selector!r});
          if (!el) return null;
          const cs = getComputedStyle(el);
          return {{
            backgroundColor: cs.backgroundColor,
            color: cs.color,
            borderTopColor: cs.borderTopColor,
            boxShadow: cs.boxShadow,
            outlineStyle: cs.outlineStyle,
            outlineColor: cs.outlineColor,
            outlineWidth: cs.outlineWidth,
            backdropFilter: cs.backdropFilter || cs.webkitBackdropFilter || 'none',
            opacity: cs.opacity,
            visibility: cs.visibility,
            pointerEvents: cs.pointerEvents,
          }};
        }})()"""
    )
    assert isinstance(value, dict), f"missing element {selector}"
    return {str(k): str(v) for k, v in value.items()}


def _force_pseudo(cdp: _CDP, selector: str, classes: list[str]) -> None:
    doc = cdp.call("DOM.getDocument", {"depth": 0})
    node = cdp.call(
        "DOM.querySelector",
        {"nodeId": doc["root"]["nodeId"], "selector": selector},
    )
    node_id = int(node["nodeId"])
    assert node_id > 0, f"DOM node missing for {selector}"
    cdp.call(
        "CSS.forcePseudoState",
        {"nodeId": node_id, "forcedPseudoClasses": classes},
    )


def _clear_pseudo(cdp: _CDP, selector: str) -> None:
    _force_pseudo(cdp, selector, [])


def _mouse_hover(cdp: _CDP, selector: str) -> None:
    box = cdp.evaluate(
        f"""(() => {{
          const el = document.querySelector({selector!r});
          if (!el) return null;
          el.scrollIntoView({{block: 'nearest', inline: 'nearest'}});
          const r = el.getBoundingClientRect();
          return {{ x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height }};
        }})()"""
    )
    assert isinstance(box, dict), f"missing element {selector}"
    assert float(box["w"]) > 0 and float(box["h"]) > 0, f"{selector} has empty box"
    cdp.call(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseMoved",
            "x": float(box["x"]),
            "y": float(box["y"]),
        },
    )
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        hovered = cdp.evaluate(
            f"!!document.querySelector({selector!r}) && document.querySelector({selector!r}).matches(':hover')"
        )
        if hovered:
            return
        time.sleep(0.05)
    raise AssertionError(f"{selector} did not match :hover after mouse move")


def _mouse_leave_topbar(cdp: _CDP) -> None:
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 1, "y": 1})


def _parse_alpha(color: str) -> float:
    text = color.strip().lower()
    if text in {"transparent", "none"}:
        return 0.0
    if " / " in text:
        tail = text.rsplit(" / ", 1)[1].rstrip(")")
        return float(tail)
    if text.startswith("rgba("):
        return float(text[5:-1].split(",")[3])
    if text.startswith("rgb("):
        return 1.0
    if text.startswith("color(") and "/" in text:
        return float(text.rsplit("/", 1)[1].rstrip(")").strip())
    # oklab(...) / lab(...) without alpha component are opaque.
    if text.startswith(("oklab(", "oklch(", "lab(", "lch(", "color(")):
        return 1.0
    raise AssertionError(f"unexpected color: {color}")


def _rgba_channels(color: str) -> tuple[int, int, int, float]:
    text = color.replace(" ", "")
    if text.startswith("rgba("):
        parts = text[5:-1].split(",")
        return int(parts[0]), int(parts[1]), int(parts[2]), float(parts[3])
    if text.startswith("rgb("):
        parts = text[4:-1].split(",")
        return int(parts[0]), int(parts[1]), int(parts[2]), 1.0
    raise AssertionError(f"unexpected rgb color: {color}")


def _is_transparent(color: str) -> bool:
    return _parse_alpha(color) < 0.01


def _approx_accent(color: str) -> bool:
    if not color.startswith("rgb"):
        return False
    r, g, b, alpha = _rgba_channels(color)
    # Dark-theme --accent #ff9f0a
    return alpha > 0.5 and r > 200 and 100 < g < 200 and b < 80


def _approx_filled_accent(color: str) -> bool:
    """Solid Export CTA fill, not a light accent wash."""
    return _approx_accent(color) and _parse_alpha(color) > 0.9


def test_h1_secondary_nav_hover_and_focus(h1_browser: dict[str, Any]) -> None:
    cdp: _CDP = h1_browser["cdp"]
    _reload_fixture(cdp, int(h1_browser["http_port"]))
    for selector in ("#nav-browse", "#nav-projects"):
        _mouse_leave_topbar(cdp)
        resting = _styles(cdp, selector)
        assert _is_transparent(resting["backgroundColor"])
        assert not _approx_filled_accent(resting["backgroundColor"])
        assert resting["boxShadow"] in {"none", ""}

        try:
            _mouse_hover(cdp, selector)
            hovered = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                hovered = _styles(cdp, selector)
                if (
                    hovered["color"] != resting["color"]
                    and not _is_transparent(hovered["backgroundColor"])
                ):
                    break
                time.sleep(0.05)
            assert hovered is not None
            assert hovered["color"] != resting["color"]
            assert _approx_accent(hovered["color"])
            assert not _is_transparent(hovered["backgroundColor"]), hovered
            assert not _approx_filled_accent(hovered["backgroundColor"]), (
                "secondary hover must stay unfilled (wash, not accent CTA fill)"
            )
        finally:
            _mouse_leave_topbar(cdp)

        try:
            cdp.evaluate(
                f"document.querySelector({selector!r}).focus({{preventScroll:true}})"
            )
            _force_pseudo(cdp, selector, ["focus-visible"])
            focused = _styles(cdp, selector)
            assert focused["outlineStyle"] != "none"
            assert focused["boxShadow"] not in {"none", ""}
            assert any(
                token in focused["boxShadow"]
                for token in ("rgba", "rgb", "color(", "oklab")
            )
        finally:
            _clear_pseudo(cdp, selector)
            cdp.evaluate(
                f"document.querySelector({selector!r}) && document.querySelector({selector!r}).blur()"
            )


def test_h1_reduced_transparency_fallback(h1_browser: dict[str, Any]) -> None:
    cdp: _CDP = h1_browser["cdp"]
    _reload_fixture(cdp, int(h1_browser["http_port"]))
    cdp.evaluate(
        "document.getElementById('creator').removeAttribute('data-chrome')"
    )
    frost = _styles(cdp, "#topbar")
    assert "blur(" in frost["backdropFilter"]

    cdp.call(
        "Emulation.setEmulatedMedia",
        {
            "features": [
                {"name": "prefers-reduced-transparency", "value": "reduce"}
            ]
        },
    )
    try:
        reduced = _styles(cdp, "#topbar")
        assert reduced["backdropFilter"] in {"none", ""}
        # --panel #14181d
        r, g, b, a = _rgba_channels(reduced["backgroundColor"])
        assert a == 1.0
        assert (r, g, b) == (20, 24, 29)
        assert reduced["boxShadow"] in {"none", ""}
    finally:
        cdp.call(
            "Emulation.setEmulatedMedia",
            {
                "features": [
                    {
                        "name": "prefers-reduced-transparency",
                        "value": "no-preference",
                    }
                ]
            },
        )


def test_h1_data_chrome_opaque_fallback_independent(
    h1_browser: dict[str, Any],
) -> None:
    cdp: _CDP = h1_browser["cdp"]
    _reload_fixture(cdp, int(h1_browser["http_port"]))
    # Ensure media preference is not the source of opacity.
    cdp.call(
        "Emulation.setEmulatedMedia",
        {
            "features": [
                {
                    "name": "prefers-reduced-transparency",
                    "value": "no-preference",
                }
            ]
        },
    )
    cdp.evaluate(
        "document.getElementById('creator').setAttribute('data-chrome', 'opaque')"
    )
    try:
        opaque = _styles(cdp, "#topbar")
        assert opaque["backdropFilter"] in {"none", ""}
        r, g, b, a = _rgba_channels(opaque["backgroundColor"])
        assert a == 1.0
        assert (r, g, b) == (20, 24, 29)
        assert opaque["boxShadow"] in {"none", ""}
        frost_probe = cdp.evaluate(
            """(() => {
              const el = document.getElementById('topbar');
              return getComputedStyle(el).getPropertyValue('--studio-blur-top').trim();
            })()"""
        )
        assert frost_probe in {"0px", "0"}
    finally:
        cdp.evaluate(
            "document.getElementById('creator').removeAttribute('data-chrome')"
        )


def test_h1_export_accent_and_narrow_reachability(
    h1_browser: dict[str, Any],
) -> None:
    cdp: _CDP = h1_browser["cdp"]
    _reload_fixture(cdp, int(h1_browser["http_port"]))

    export_rest = _styles(cdp, "#studio-export-open")
    assert not _is_transparent(export_rest["backgroundColor"])
    assert _approx_filled_accent(export_rest["backgroundColor"])

    browse_rest = _styles(cdp, "#nav-browse")
    projects_rest = _styles(cdp, "#nav-projects")
    assert _is_transparent(browse_rest["backgroundColor"])
    assert _is_transparent(projects_rest["backgroundColor"])
    assert not _approx_filled_accent(browse_rest["backgroundColor"])
    assert not _approx_filled_accent(projects_rest["backgroundColor"])

    for width in (1920, 1440, 1100, 900):
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        metrics = cdp.evaluate(
            """(() => {
              const el = document.getElementById('studio-export-open');
              const r = el.getBoundingClientRect();
              const cs = getComputedStyle(el);
              return {
                width: r.width,
                height: r.height,
                left: r.left,
                right: r.right,
                top: r.top,
                bottom: r.bottom,
                viewW: window.innerWidth,
                viewH: window.innerHeight,
                visibility: cs.visibility,
                pointerEvents: cs.pointerEvents,
                opacity: Number(cs.opacity),
                disabled: !!el.disabled,
              };
            })()"""
        )
        assert isinstance(metrics, dict)
        assert metrics["width"] > 8
        assert metrics["height"] > 8
        assert metrics["left"] >= 0
        assert metrics["right"] <= metrics["viewW"] + 0.5
        assert metrics["top"] >= 0
        assert metrics["bottom"] <= metrics["viewH"] + 0.5
        assert metrics["visibility"] == "visible"
        assert metrics["pointerEvents"] != "none"
        assert metrics["opacity"] > 0.9
        assert metrics["disabled"] is False
