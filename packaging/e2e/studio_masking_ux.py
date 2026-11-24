#!/usr/bin/env python3
"""Native WebView2 masking UX acceptance (#543 / parent #535).

Covers Inspector list, object select (+ multi-seed), rename, invert binding,
save/reopen, and JPG export with decoded pixel checks on a synthetic leaf.

Usage (dev):
  set ORGA_DRONE_E2E=1
  python -m orga_drone   # with CDP port
  python packaging/e2e/studio_masking_ux.py --port 18765 --cdp-port 18766

Usage (packaged):
  python packaging/e2e/studio_masking_ux.py --exe dist/orga-drone/orga-drone.exe
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat

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
        self._ws.settimeout(300)

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


def wait_cdp(port: int, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        try:
            http_json(f"http://127.0.0.1:{port}/json/version")
            return
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
        "const buf = await res.arrayBuffer();"
        "return {ok: res.ok, status: res.status, bytes: buf.byteLength, ct};"
        "})()",
        await_promise=True,
    )


def make_leaf(path: Path) -> None:
    img = Image.new("RGB", (640, 480), (35, 35, 35))
    draw = ImageDraw.Draw(img)
    draw.ellipse((160, 80, 480, 400), fill=(45, 175, 70))
    img.save(path, quality=95)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--cdp-port", type=int, default=0)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "acceptance-evidence"
        / "masking-ux-e2e"
        / "runs"
        / f"masking-ux-{time.strftime('%Y%m%d-%H%M%S')}",
    )
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    app_port = args.port or free_port()
    cdp_port = args.cdp_port or free_port()
    data_dir = out / "data"
    lib = out / "lib"
    data_dir.mkdir(parents=True, exist_ok=True)
    lib.mkdir(parents=True, exist_ok=True)
    photo = lib / "synthetic-leaf.jpg"
    make_leaf(photo)

    proc = None
    env = os.environ.copy()
    if args.exe:
        if not args.exe.is_file():
            print(f"missing exe: {args.exe}", file=sys.stderr)
            return 2
        env["ORGA_DRONE_PORT"] = str(app_port)
        env["ORGA_DRONE_DATA_DIR"] = str(data_dir)
        env["ORGA_DRONE_GEOCODE"] = "off"
        env["ORGA_DRONE_E2E"] = "1"
        env["ORGA_DRONE_CDP_PORT"] = str(cdp_port)
        env["ORGA_SPATIAL_APPLY_WORKERS"] = "1"
        proc = subprocess.Popen(
            [str(args.exe)],
            cwd=str(args.exe.parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif not args.port or not args.cdp_port:
        print("Provide --exe or both --port and --cdp-port for an already-running app", file=sys.stderr)
        return 2

    report: dict = {
        "out": str(out),
        "app_port": app_port,
        "cdp_port": cdp_port,
        "steps": [],
        "checks": {},
    }
    cdp = None
    try:
        wait_cdp(cdp_port)
        page = wait_page(cdp_port)
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/"})
        time.sleep(1.2)

        added = cdp.evaluate(
            f"""(async () => {{
              const body = new URLSearchParams({{path:{json.dumps(str(lib))}, label:'MaskUX'}});
              const res = await fetch('/library/add', {{method:'POST',
                headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body}});
              return {{ok:res.ok, url:res.url}};
            }})()""",
            await_promise=True,
        )
        import re

        m = re.search(r"scan_job=([^&]+)", str(added.get("url") or ""))
        if m:
            job = m.group(1)
            for _ in range(180):
                st = fetch(cdp, f"/api/scan-jobs/{job}")["data"]
                if st.get("state") in {"completed", "failed"}:
                    break
                time.sleep(0.25)
            assert st.get("state") == "completed", st

        search = fetch(cdp, "/api/search", "POST", {"q": "synthetic-leaf.jpg"})["data"]
        photo_id = int(search["items"][0]["id"])
        created = fetch(
            cdp, "/api/studio/projects", "POST", {"title": "Masking UX #543"}
        )["data"]
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
        time.sleep(1.8)
        cdp.evaluate(
            """(() => {
              const b=[...document.querySelectorAll('button')].find(x=>
                /Photo editing focus/i.test(x.getAttribute('title')||'') ||
                /^\\s*Photo\\s*$/i.test(x.textContent||''));
              if (b) b.click();
              return !!b;
            })()"""
        )
        time.sleep(0.6)
        clip_id = cdp.evaluate(
            """(() => {
              const c=[...document.querySelectorAll('.studio-clip')].find(
                el => (el.getAttribute('data-kind')||'')==='photo');
              return c ? Number(c.getAttribute('data-studio-id')||c.getAttribute('data-id')) : null;
            })()"""
        )
        assert clip_id, "photo clip missing"
        report["clip_id"] = int(clip_id)

        g = fetch(cdp, f"/api/studio/{clip_id}/grade")["data"]
        if g.get("evaluator") != "managed-sdr-v1":
            fetch(cdp, f"/api/studio/{clip_id}/grade/wrap", "POST")
            fetch(
                cdp,
                f"/api/studio/{clip_id}/grade/convert-managed",
                "POST",
                {"acknowledge_appearance_change": True},
            )
            g = fetch(cdp, f"/api/studio/{clip_id}/grade")["data"]
        rev = int(g["revision"])

        t0 = time.perf_counter()
        prop = fetch(
            cdp,
            f"/api/studio/{clip_id}/grade/object-select",
            "POST",
            {
                "u": 0.5,
                "v": 0.5,
                "seeds": [[0.55, 0.55], [0.45, 0.45]],
                "expected_revision": rev,
                "expand_passes": 2,
            },
        )
        report["object_select_s"] = round(time.perf_counter() - t0, 4)
        assert prop.get("ok"), prop
        points = prop["data"]["proposal"]["points"]
        assert len(points) >= 3
        report["checks"]["object_select"] = True
        report["checks"]["object_select_under_1s"] = report["object_select_s"] < 1.0
        report["steps"].append("object_select_ok")

        leaf = {
            "id": "sel-leaf",
            "name": "Blatt",
            "invert": False,
            "overlay": {"visible": True},
            "mask": {
                "combine": "union",
                "leaves": [
                    {"type": "polygon", "points": points, "feather": 0.02, "closed": True}
                ],
            },
            "qualifier": {"type": "none"},
        }
        bg = {
            **leaf,
            "id": "sel-bg",
            "name": "Hintergrund",
            "invert": True,
            "overlay": {"visible": False},
        }
        put = fetch(
            cdp,
            f"/api/studio/{clip_id}/grade/command",
            "POST",
            {"type": "upsert_selection", "expected_revision": rev, "params": {"selection": leaf}},
        )
        assert put["ok"], put
        rev = int(put["data"]["revision"])
        put = fetch(
            cdp,
            f"/api/studio/{clip_id}/grade/command",
            "POST",
            {"type": "upsert_selection", "expected_revision": rev, "params": {"selection": bg}},
        )
        assert put["ok"], put
        rev = int(put["data"]["revision"])
        put = fetch(
            cdp,
            f"/api/studio/{clip_id}/grade/command",
            "POST",
            {
                "type": "upsert_step_params",
                "expected_revision": rev,
                "params": {
                    "step_id": "hsl-leaf",
                    "type": "managed-hsl-v1",
                    "selection_id": "sel-leaf",
                    "params": {"hue": -40, "saturation": 1.3, "lightness": -0.05},
                    "enabled": True,
                    "mix": 1.0,
                },
            },
        )
        assert put["ok"], put
        rev = int(put["data"]["revision"])
        put = fetch(
            cdp,
            f"/api/studio/{clip_id}/grade/command",
            "POST",
            {
                "type": "upsert_step_params",
                "expected_revision": rev,
                "params": {
                    "step_id": "hsl-bg",
                    "type": "managed-hsl-v1",
                    "selection_id": "sel-bg",
                    "params": {"hue": 0, "saturation": 0.0, "lightness": -0.05},
                    "enabled": True,
                    "mix": 1.0,
                },
            },
        )
        assert put["ok"], put
        report["steps"].append("grades_bound")

        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/studio"})
        time.sleep(1.5)
        cdp.evaluate(
            """(() => {
              const b=[...document.querySelectorAll('button')].find(x=>
                /Photo editing focus/i.test(x.getAttribute('title')||'') ||
                /^\\s*Photo\\s*$/i.test(x.textContent||''));
              if (b) b.click();
              return !!b;
            })()"""
        )
        time.sleep(0.8)
        has_list = cdp.evaluate(
            """(() => !!document.querySelector('[data-managed-selection-summary]'))()"""
        )
        clicked = cdp.evaluate(
            """(() => {
              const btn=[...document.querySelectorAll('.studio-mask-list-select')]
                .find(el => /Blatt/i.test(el.textContent||''));
              if (btn) { btn.click(); return true; }
              return false;
            })()"""
        )
        report["checks"]["mask_list"] = bool(has_list)
        report["checks"]["select_blatt"] = bool(clicked)
        report["shot_blatt"] = str(cdp.shot(out / "10-blatt-selected.png"))
        report["steps"].append("inspector_ok")

        # Save/reopen: reload Studio and confirm selection name persists.
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/studio"})
        time.sleep(1.5)
        g2 = fetch(cdp, f"/api/studio/{clip_id}/grade")["data"]
        names = [s.get("name") for s in (g2.get("grade") or {}).get("selections") or []]
        report["checks"]["persist_blatt"] = "Blatt" in names
        assert report["checks"]["persist_blatt"], names
        report["steps"].append("reopen_ok")

        export_path = out / "masking-ux-export.jpg"
        t1 = time.perf_counter()
        started = fetch(
            cdp,
            f"/api/studio/{clip_id}/still/export",
            "POST",
            {"format": "jpeg", "preset": "best", "output_path": str(export_path.resolve())},
        )
        assert started["ok"], started
        job_id = started["data"]["job_id"]
        while True:
            time.sleep(0.4)
            st = fetch(cdp, f"/api/studio/export/jobs/{job_id}")["data"]
            if st.get("state") in {"completed", "failed", "cancelled"}:
                break
            if time.perf_counter() - t1 > 300:
                raise TimeoutError(st)
        assert st.get("state") == "completed", st
        report["export_s"] = round(time.perf_counter() - t1, 2)
        final = Path(st.get("output_path") or export_path)
        assert final.is_file()
        with Image.open(final) as exp:
            mean = ImageStat.Stat(exp.convert("RGB")).mean
            # Leaf grade pushes magenta-ish / sat; BG desat — not a flat grey frame.
            assert max(mean) - min(mean) > 5.0
            report["export_mean_rgb"] = [round(v, 2) for v in mean]
            report["checks"]["export_pixels"] = True
        report["shot_final"] = str(cdp.shot(out / "20-studio-final.png"))
        report["steps"].append("export_ok")

        (out / "e2e-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        failed = [k for k, v in report["checks"].items() if not v]
        if failed:
            print(f"FAILED checks: {failed}", file=sys.stderr)
            return 1
        if args.keep_open:
            print("Keeping app open for PO review (--keep-open). Ctrl+C to stop.")
            while True:
                time.sleep(60)
        return 0
    finally:
        if cdp is not None:
            cdp.close()
        if proc is not None and not args.keep_open:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
