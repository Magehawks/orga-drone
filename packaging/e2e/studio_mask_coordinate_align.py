#!/usr/bin/env python3
"""Native WebView2 E2E: mask overlay aligns with pointer on letterboxed photos (#561).

Launches packaged ``orga-drone.exe``, imports a portrait fixture, places polygon
points with real PointerEvents, and asserts overlay canvas bounds match the
painted picture (not the letterbox gutters).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(url: str, timeout: float = 5.0):
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


class CDP:
    def __init__(self, ws_url: str) -> None:
        import websocket

        self._id = 1
        self._ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self._ws.settimeout(180)

    def call(self, method: str, params=None):
        mid = self._id
        self._id += 1
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") != mid:
                continue
            if "error" in msg:
                raise RuntimeError(msg["error"])
            return msg.get("result")

    def evaluate(self, expression: str, await_promise: bool = False):
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": True,
            },
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def shot(self, path: Path) -> Path:
        data = self.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        path.write_bytes(base64.b64decode(data["data"]))
        return path

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


def wait_cdp(port: int, timeout_s: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        try:
            return http_json(f"http://127.0.0.1:{port}/json/version")
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(0.4)
    raise RuntimeError(f"CDP not ready: {last}")


def wait_page(port: int, timeout_s: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            targets = http_json(f"http://127.0.0.1:{port}/json/list")
        except Exception:
            time.sleep(0.4)
            continue
        for target in targets if isinstance(targets, list) else []:
            if (
                isinstance(target, dict)
                and target.get("type") == "page"
                and target.get("webSocketDebuggerUrl")
            ):
                return target
        time.sleep(0.4)
    raise RuntimeError("no CDP page target")


def fetch(cdp: CDP, path: str, method: str = "GET", body=None):
    headers = {}
    body_js = "null"
    if body is not None:
        headers["Content-Type"] = "application/json"
        body_js = f"JSON.stringify({json.dumps(body)})"
    return cdp.evaluate(
        "(async () => {"
        f"const res = await fetch({json.dumps(path)}, {{method:{json.dumps(method)},"
        f"headers:{json.dumps(headers)},body:{body_js}}});"
        "const ct = res.headers.get('content-type')||'';"
        "if (ct.includes('application/json')) {"
        "  return {ok: res.ok, status: res.status, data: await res.json()};"
        "}"
        "return {ok: res.ok, status: res.status, url: res.url};"
        "})()",
        await_promise=True,
    )


def make_portrait(path: Path) -> None:
    img = Image.new("RGB", (450, 800), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.ellipse((80, 220, 370, 620), fill=(40, 170, 60))
    img.save(path, quality=95)


def dispatch_pointer(cdp: CDP, client_x: float, client_y: float, typ: str) -> dict:
    return cdp.evaluate(
        f"""(() => {{
          const media = document.querySelector('img.studio-preview-media:not([hidden])')
            || document.querySelector('img.studio-preview');
          if (!media) return {{ok:false, reason:'no-media'}};
          const init = {{
            bubbles: true, cancelable: true, composed: true,
            clientX: {client_x}, clientY: {client_y},
            pointerId: 1, pointerType: 'mouse',
            button: 0, buttons: {1 if typ != "pointerup" else 0}
          }};
          media.dispatchEvent(new PointerEvent({json.dumps(typ)}, init));
          return {{ok:true}};
        }})()"""
    )


def measure_layout(cdp: CDP) -> dict:
    return cdp.evaluate(
        """(() => {
          const media = document.querySelector('img.studio-preview-media:not([hidden])')
            || document.querySelector('img.studio-preview');
          if (!media) return null;
          const rect = media.getBoundingClientRect();
          const nw = Number(media.naturalWidth || 0);
          const nh = Number(media.naturalHeight || 0);
          const scale = Math.min(rect.width / nw, rect.height / nh);
          const width = nw * scale;
          const height = nh * scale;
          const left = rect.left + (rect.width - width) / 2;
          const top = rect.top + (rect.height - height) / 2;
          const canvas = media.parentElement
            && media.parentElement.querySelector('[data-managed-brush-overlay]');
          const cRect = canvas ? canvas.getBoundingClientRect() : null;
          return {
            media: {left: rect.left, top: rect.top, width: rect.width, height: rect.height, nw, nh},
            content: {left, top, width, height},
            overlay: cRect ? {left: cRect.left, top: cRect.top, width: cRect.width, height: cRect.height} : null
          };
        })()"""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exe",
        type=Path,
        default=ROOT / "dist" / "orga-drone" / "orga-drone.exe",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "acceptance-evidence"
        / "masking-ux-e2e"
        / "runs"
        / f"mask-coord-{time.strftime('%Y%m%d-%H%M%S')}",
    )
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--cdp-port", type=int, default=0)
    args = parser.parse_args()
    if not args.exe.is_file():
        print(f"missing exe: {args.exe}", file=sys.stderr)
        return 2

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    app_port = args.port or free_port()
    cdp_port = args.cdp_port or free_port()
    data_dir = out / "data"
    lib = out / "lib"
    data_dir.mkdir(parents=True, exist_ok=True)
    lib.mkdir(parents=True, exist_ok=True)
    photo = lib / "portrait-leaf.jpg"
    make_portrait(photo)

    env = os.environ.copy()
    env["ORGA_DRONE_PORT"] = str(app_port)
    env["ORGA_DRONE_DATA_DIR"] = str(data_dir)
    env["ORGA_DRONE_GEOCODE"] = "off"
    env["ORGA_DRONE_E2E"] = "1"
    env["ORGA_DRONE_CDP_PORT"] = str(cdp_port)

    proc = subprocess.Popen(
        [str(args.exe)],
        cwd=str(args.exe.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    report: dict = {"exe": str(args.exe), "app_port": app_port, "cdp_port": cdp_port}
    cdp = None
    try:
        wait_cdp(cdp_port)
        page = wait_page(cdp_port)
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/"})
        time.sleep(1.5)

        added = cdp.evaluate(
            f"""(async () => {{
              const body = new URLSearchParams({{path:{json.dumps(str(lib))}, label:'MaskCoord'}});
              const res = await fetch('/library/add', {{method:'POST',
                headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body}});
              return {{ok:res.ok, url:res.url}};
            }})()""",
            await_promise=True,
        )
        import re

        m = re.search(r"scan_job=([^&]+)", str(added.get("url") or ""))
        if not m:
            raise RuntimeError(f"scan job missing: {added}")
        job = m.group(1)
        for _ in range(180):
            st = fetch(cdp, f"/api/scan-jobs/{job}")["data"]
            if st.get("state") in {"completed", "failed"}:
                break
            time.sleep(0.25)
        if st.get("state") != "completed":
            raise RuntimeError(f"scan failed: {st}")

        search = fetch(cdp, "/api/search", "POST", {"q": "portrait-leaf.jpg"})["data"]
        photo_id = int(search["items"][0]["id"])
        created = fetch(cdp, "/api/studio/projects", "POST", {"title": "Mask Coord #561"})["data"]
        project_id = int(created["id"])
        fetch(cdp, f"/api/studio/projects/{project_id}/open", "POST")
        cdp.evaluate(
            f"""(async () => {{
              const body = new URLSearchParams({{return_to:'studio'}});
              return await (await fetch('/media/{photo_id}/studio/add', {{method:'POST',
                headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body}})).status;
            }})()""",
            await_promise=True,
        )
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/studio"})
        time.sleep(2.0)
        cdp.evaluate(
            """(() => {
              const b=[...document.querySelectorAll('button')].find(x=>
                /Photo editing focus/i.test(x.getAttribute('title')||'')
                || /^\\s*Photo\\s*$/i.test(x.textContent||''));
              if (b) b.click();
              return !!b;
            })()"""
        )
        time.sleep(0.8)
        clip_id = cdp.evaluate(
            """(() => {
              const c=[...document.querySelectorAll('.studio-clip')].find(
                el=>(el.getAttribute('data-kind')||'')==='photo');
              return c?Number(c.getAttribute('data-studio-id')||c.getAttribute('data-id')):null;
            })()"""
        )
        assert clip_id, "no photo clip"
        g = fetch(cdp, f"/api/studio/{clip_id}/grade")["data"]
        if g.get("evaluator") != "managed-sdr-v1":
            fetch(cdp, f"/api/studio/{clip_id}/grade/wrap", "POST")
            fetch(
                cdp,
                f"/api/studio/{clip_id}/grade/convert-managed",
                "POST",
                {"acknowledge_appearance_change": True},
            )

        # Enable polygon tool.
        armed = cdp.evaluate(
            """(() => {
              const b=document.querySelector('[data-managed-polygon-draw]');
              if (b) { b.click(); return true; }
              return false;
            })()"""
        )
        assert armed, "polygon button missing"

        layout0 = measure_layout(cdp)
        report["layout_before"] = layout0
        content = layout0["content"]
        # Five distinct points on the green leaf (center region of portrait).
        uvs = [(0.35, 0.40), (0.55, 0.38), (0.62, 0.55), (0.48, 0.68), (0.32, 0.58)]
        clicked = []
        for u, v in uvs:
            cx = content["left"] + u * content["width"]
            cy = content["top"] + v * content["height"]
            dispatch_pointer(cdp, cx, cy, "pointerdown")
            dispatch_pointer(cdp, cx, cy, "pointerup")
            clicked.append({"u": u, "v": v, "clientX": cx, "clientY": cy})
            time.sleep(0.15)
        time.sleep(0.3)
        layout1 = measure_layout(cdp)
        report["layout_after"] = layout1
        report["clicked"] = clicked
        overlay = layout1.get("overlay")
        assert overlay, "overlay canvas missing after polygon clicks"
        # Overlay must match content rect (letterbox-aware), not full media box.
        media = layout1["media"]
        assert abs(overlay["width"] - content["width"]) < 3.0, (overlay, content)
        assert abs(overlay["height"] - content["height"]) < 3.0, (overlay, content)
        assert abs(overlay["left"] - content["left"]) < 3.0, (overlay, content)
        assert abs(overlay["top"] - content["top"]) < 3.0, (overlay, content)
        # And must NOT equal the full media element when letterboxed.
        letterboxed = abs(media["width"] - content["width"]) > 4.0
        report["letterboxed"] = letterboxed
        if letterboxed:
            assert abs(overlay["width"] - media["width"]) > 4.0

        shot = cdp.shot(out / "01-polygon-on-leaf.png")
        report["screenshot"] = str(shot)

        # Brush stroke across leaf center.
        cdp.evaluate(
            """(() => {
              const b=document.querySelector('[data-managed-brush-draw]');
              if (b) b.click();
              return !!b;
            })()"""
        )
        time.sleep(0.2)
        path = [(0.40, 0.45), (0.48, 0.50), (0.56, 0.55)]
        for i, (u, v) in enumerate(path):
            cx = content["left"] + u * content["width"]
            cy = content["top"] + v * content["height"]
            typ = "pointerdown" if i == 0 else ("pointerup" if i == len(path) - 1 else "pointermove")
            if i == len(path) - 1:
                dispatch_pointer(cdp, cx, cy, "pointermove")
                dispatch_pointer(cdp, cx, cy, "pointerup")
            elif i == 0:
                dispatch_pointer(cdp, cx, cy, "pointerdown")
            else:
                dispatch_pointer(cdp, cx, cy, "pointermove")
            time.sleep(0.05)
        time.sleep(0.2)
        report["screenshot_brush"] = str(cdp.shot(out / "02-brush-on-leaf.png"))
        layout2 = measure_layout(cdp)
        report["layout_brush"] = layout2
        if layout2.get("overlay"):
            assert abs(layout2["overlay"]["width"] - content["width"]) < 3.0

        report["ok"] = True
        (out / "e2e-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["error"] = str(exc)
        (out / "e2e-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), file=sys.stderr)
        return 1
    finally:
        if cdp is not None:
            cdp.close()
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
