"""Home hero: full-frame contain rendering via Chromium CDP (#338).

Uses the real ``app.css`` stylesheet and synthetic portrait / square /
landscape fixtures. Browser launch reuses the websocket CDP pattern from
``test_studio_hybrid_h1_topbar_styles`` (no new test framework).
"""

from __future__ import annotations

import base64
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
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "src" / "orga_drone" / "static" / "css" / "app.css"
EVIDENCE_DIR = ROOT / "tmp-hero-contain-evidence" / "screenshots"

_FIXTURE_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="/app.css?hero-contain=1">
  <style>
    body { margin: 0; background: var(--bg); color: var(--text); }
    .shell { display: flex; min-height: 100vh; }
    .sidebar {
      width: 15rem; flex: 0 0 15rem; border-right: 1px solid var(--border);
      padding: 1rem; background: var(--panel);
    }
    .main { flex: 1; min-width: 0; padding: 1rem 1.5rem 3rem; }
    .badge {
      display: inline-block; margin: 0 0 0.75rem; padding: 0.2rem 0.5rem;
      border: 1px solid var(--border); border-radius: 999px; color: var(--muted);
      font-size: 0.75rem;
    }
    .label { margin: 0 0 0.35rem; color: var(--muted); font-size: 0.8rem; }
    .meta { color: var(--muted); font-size: 0.8rem; margin-top: 0.4rem; }
    @media (max-width: 900px) {
      .sidebar { display: none; }
      .main { padding: 0.85rem 1rem 2rem; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">Sidebar 15rem</aside>
    <main class="main">
      <div class="badge" id="viewport-badge">viewport</div>
      <section class="home-welcome">
        <div class="home-hero-copy">
          <h1>Welcome to orga-drone</h1>
          <p>Your local drone media hub — browse the library or explore the world map.</p>
        </div>
        <p class="label" id="case-label">case</p>
        <div class="home-hero has-photo" id="hero">
          <img id="hero-img" class="home-hero-media" src="/portrait.jpg" alt="">
        </div>
        <p class="meta" id="measure"></p>
      </section>
    </main>
  </div>
  <script>
    const params = new URLSearchParams(location.search);
    const caseId = params.get("case") || "portrait";
    const files = {
      portrait: ["/portrait.jpg", "PORTRAIT 720×1280"],
      square: ["/square.jpg", "SQUARE 900×900"],
      landscape: ["/landscape.jpg", "LANDSCAPE 1280×720"],
    };
    const [src, label] = files[caseId] || files.portrait;
    const img = document.getElementById("hero-img");
    img.src = src;
    document.getElementById("case-label").textContent = label;
    function report() {
      const hero = document.getElementById("hero");
      const rect = hero.getBoundingClientRect();
      const fit = getComputedStyle(img).objectFit;
      document.getElementById("viewport-badge").textContent =
        window.innerWidth + "×" + window.innerHeight;
      document.getElementById("measure").textContent =
        "hero box " + Math.round(rect.width) + "×" + Math.round(rect.height) +
        " · object-fit=" + fit;
    }
    img.addEventListener("load", report);
    window.addEventListener("resize", report);
    report();
  </script>
</body>
</html>
"""

_CASES = (
    ("portrait", 720, 1280, (40, 110, 200)),
    ("square", 900, 900, (30, 140, 90)),
    ("landscape", 1280, 720, (170, 90, 40)),
)

_VIEWPORTS = (900, 1440, 1920)


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
        "No Chromium/Chrome/Edge binary found for Home hero contain regressions. "
        "Set ORGA_DRONE_CHROME to a browser executable."
    )


def _write_fixture_jpeg(path: Path, width: int, height: int, color: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(image)
    inset = max(8, min(width, height) // 40)
    draw.rectangle(
        [inset, inset, width - inset - 1, height - inset - 1],
        outline=(245, 245, 245),
        width=max(2, inset // 2),
    )
    for x, y in (
        (inset * 2, inset * 2),
        (width - inset * 2, inset * 2),
        (inset * 2, height - inset * 2),
        (width - inset * 2, height - inset * 2),
    ):
        r = max(4, inset)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 210, 40))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=92)


class _FixtureHandler(SimpleHTTPRequestHandler):
    fixture_dir: Path = Path(".")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(self.fixture_dir), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html", "/preview.html"}:
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
        super().do_GET()

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


@pytest.fixture(scope="module")
def hero_contain_browser(tmp_path_factory: pytest.TempPathFactory) -> Any:
    assert CSS_PATH.is_file(), f"missing stylesheet: {CSS_PATH}"
    fixture_root = tmp_path_factory.mktemp("hero-contain-fixtures")
    for name, width, height, color in _CASES:
        _write_fixture_jpeg(fixture_root / f"{name}.jpg", width, height, color)

    chrome = _find_chrome()
    http_port = _free_port()
    cdp_port = _free_port()

    handler = type(
        "HeroContainHandler",
        (_FixtureHandler,),
        {"fixture_dir": fixture_root},
    )
    server = ThreadingHTTPServer(("127.0.0.1", http_port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    profile = Path(
        os.environ.get("TMPDIR")
        or os.environ.get("TEMP")
        or os.environ.get("TMP")
        or "/tmp"
    ) / f"od-hero-contain-{cdp_port}"
    profile.mkdir(parents=True, exist_ok=True)
    stderr_path = profile / "chrome.stderr"
    cmd = [
        str(chrome),
        f"--remote-debugging-port={cdp_port}",
        "--remote-debugging-address=127.0.0.1",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        f"--user-data-dir={profile}",
        "about:blank",
    ]
    stderr_file = stderr_path.open("wb")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
    )
    cdp: _CDP | None = None
    try:
        deadline = time.monotonic() + 30.0
        version: dict[str, Any] | None = None
        last_error = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                version = _http_json(f"http://127.0.0.1:{cdp_port}/json/version")
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = str(exc)
                time.sleep(0.2)
        if version is None:
            stderr_file.flush()
            detail = ""
            try:
                detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            except OSError:
                detail = ""
            raise AssertionError(
                f"CDP never appeared on {cdp_port}: {last_error}; "
                f"chrome_exit={proc.poll()}; stderr={detail!r}"
            )

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
        cdp.call("Runtime.enable")
        yield {"cdp": cdp, "http_port": http_port, "fixture_root": fixture_root}
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
        try:
            stderr_file.close()
        except Exception:
            pass
        server.shutdown()


def _load_case(cdp: _CDP, http_port: int, case: str, width: int) -> None:
    cdp.call(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": 1000,
            "deviceScaleFactor": 1,
            "mobile": False,
        },
    )
    token = int(time.time() * 1000)
    cdp.call(
        "Page.navigate",
        {"url": f"http://127.0.0.1:{http_port}/preview.html?case={case}&t={token}"},
    )
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        ready = cdp.evaluate(
            """(() => {
              const img = document.getElementById('hero-img');
              return document.readyState === 'complete'
                && !!img
                && img.complete
                && img.naturalWidth > 0;
            })()"""
        )
        if ready:
            return
        time.sleep(0.05)
    raise AssertionError(f"hero fixture did not load for {case}@{width}")


def _metrics(cdp: _CDP) -> dict[str, Any]:
    value = cdp.evaluate(
        """(() => {
          const hero = document.getElementById('hero');
          const img = document.getElementById('hero-img');
          const copy = document.querySelector('.home-hero-copy');
          const hcs = getComputedStyle(hero);
          const ics = getComputedStyle(img);
          const hr = hero.getBoundingClientRect();
          const ir = img.getBoundingClientRect();
          const cr = copy.getBoundingClientRect();
          const nw = img.naturalWidth;
          const nh = img.naturalHeight;
          const scale = Math.min(ir.width / nw, ir.height / nh);
          const drawnW = nw * scale;
          const drawnH = nh * scale;
          const left = (ir.width - drawnW) / 2;
          const top = (ir.height - drawnH) / 2;
          return {
            objectFit: ics.objectFit,
            objectPosition: ics.objectPosition,
            heroBg: hcs.backgroundColor,
            hero: { w: hr.width, h: hr.height, top: hr.top },
            copyBottom: cr.bottom,
            natural: { w: nw, h: nh },
            drawn: { w: drawnW, h: drawnH, left, top },
            imgBox: { w: ir.width, h: ir.height },
            viewport: { w: window.innerWidth, h: window.innerHeight },
          };
        })()"""
    )
    assert isinstance(value, dict), "missing hero metrics"
    return value


def _save_screenshot(cdp: _CDP, path: Path) -> None:
    result = cdp.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    data = result.get("data")
    assert isinstance(data, str) and data, "empty screenshot"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data))


@pytest.mark.parametrize("case, naturally_w, naturally_h, _color", _CASES)
@pytest.mark.parametrize("viewport", _VIEWPORTS)
def test_home_hero_contain_keeps_full_frame_centered(
    hero_contain_browser: dict[str, Any],
    case: str,
    naturally_w: int,
    naturally_h: int,
    _color: tuple[int, int, int],
    viewport: int,
) -> None:
    cdp: _CDP = hero_contain_browser["cdp"]
    http_port = int(hero_contain_browser["http_port"])
    _load_case(cdp, http_port, case, viewport)
    metrics = _metrics(cdp)

    assert metrics["objectFit"] == "contain"
    assert "cover" not in str(metrics["objectFit"])
    assert metrics["objectPosition"] in {"50% 50%", "center center", "center"}
    assert metrics["natural"]["w"] == naturally_w
    assert metrics["natural"]["h"] == naturally_h

    # Welcome copy stays outside / above the media well.
    assert metrics["copyBottom"] <= metrics["hero"]["top"] + 1.0

    hero_h = float(metrics["hero"]["h"])
    # Keep hero compact: max-height clamps should stay well below a full viewport.
    assert hero_h <= 480.0
    assert hero_h >= 160.0

    drawn_w = float(metrics["drawn"]["w"])
    drawn_h = float(metrics["drawn"]["h"])
    box_w = float(metrics["imgBox"]["w"])
    box_h = float(metrics["imgBox"]["h"])
    left = float(metrics["drawn"]["left"])
    top = float(metrics["drawn"]["top"])

    # Full frame is visible inside the well (no crop), aspect preserved.
    assert drawn_w <= box_w + 0.5
    assert drawn_h <= box_h + 0.5
    assert abs((drawn_w / drawn_h) - (naturally_w / naturally_h)) < 0.02
    # One axis should nearly fill the well under contain.
    assert max(drawn_w / box_w, drawn_h / box_h) > 0.92
    # Centered with letter/pillar boxing for non-matching aspect ratios.
    assert abs(left - (box_w - drawn_w) / 2) < 1.0
    assert abs(top - (box_h - drawn_h) / 2) < 1.0
    if case == "portrait":
        assert left > 8.0
        assert drawn_h / box_h > 0.95
    if case == "landscape":
        # Height-clamped wide wells are flatter than 16:9, so landscape
        # fills the height and leaves dark side pillars — not a crop.
        assert drawn_h / box_h > 0.95
        assert left > 1.0

    # Dark hero well (rgb(18, 22, 28) == #12161c).
    assert "18,22,28" in str(metrics["heroBg"]).replace(" ", "")

    shot = EVIDENCE_DIR / f"{case}-{viewport}.png"
    _save_screenshot(cdp, shot)
    assert shot.is_file() and shot.stat().st_size > 1000


def test_home_css_declares_contain_not_cover() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    media_rule = css.split(".home-hero-media", 1)[1].split("}", 1)[0]
    assert "object-fit: contain" in media_rule
    assert "object-fit: cover" not in media_rule
    assert "object-position: center" in media_rule
    hero_rule = css.split(".home-hero {", 1)[1].split("}", 1)[0]
    assert "background: #12161c" in hero_rule
    assert "@media (max-width: 900px)" in css
    assert "@media (min-width: 1440px)" in css
    assert "@media (min-width: 1920px)" in css
