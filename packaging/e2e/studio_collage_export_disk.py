#!/usr/bin/env python3
"""Native WebView2 E2E: collage export disk safety (#487 / #489).

Creates a multi-cell collage, previews, exports, cancels an active export,
triggers a TEST-ONLY low-space failure, retries successfully, and verifies
cleanup. Never fills a real disk.
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


def http_fetch(base: str, path: str, method: str = "GET", body=None, timeout: float = 30.0):
    import urllib.request

    data = None
    headers = {"Origin": base.rstrip("/"), "Referer": base.rstrip("/") + "/"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base.rstrip("/") + path, data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return {"ok": 200 <= response.status < 300, "status": response.status, "data": parsed}


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
            pages = http_json(f"http://127.0.0.1:{port}/json/list")
            for page in pages:
                if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
                    return page
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError("CDP page target missing")


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
        "return {ok: res.ok, status: res.status, url: res.url, data: null};"
        "})()",
        await_promise=True,
    )


def make_fixtures(lib: Path) -> dict[str, Path]:
    lib.mkdir(parents=True, exist_ok=True)
    photos = {}
    for name, color in (("left.jpg", (220, 40, 40)), ("right.jpg", (40, 40, 220))):
        path = lib / name
        img = Image.new("RGB", (640, 360), color)
        draw = ImageDraw.Draw(img)
        draw.rectangle((40, 40, 600, 320), outline=(255, 255, 255), width=8)
        img.save(path, format="JPEG", quality=90)
        photos[name] = path
    # Short synthetic videos for collage cells.
    from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs

    ffmpeg = find_ffmpeg()
    assert ffmpeg
    for index, name in enumerate(("cella.mp4", "cellb.mp4")):
        path = lib / name
        pattern = "testsrc2" if index == 0 else "smptehdbars"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"{pattern}=size=640x360:rate=30:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            capture_output=True,
            **subprocess_no_window_kwargs(),
        )
        photos[name] = path
    return photos


def wait_job(base: str, job_id: str, timeout_s: float = 300.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last = {}
    while time.monotonic() < deadline:
        try:
            last = http_fetch(base, f"/api/studio/export/jobs/{job_id}")["data"]
        except Exception as exc:  # noqa: BLE001
            last = {"error": str(exc)}
            time.sleep(1.0)
            continue
        if isinstance(last, dict) and last.get("state") in {"completed", "failed", "cancelled"}:
            return last
        time.sleep(0.5)
    raise RuntimeError(f"export job timeout: {last}")


def temp_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for base in (root / "tmp", root / "scratch"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                found.append(path)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exe",
        type=Path,
        default=None,
        help="Packaged orga-drone.exe (optional; defaults to python -m orga_drone)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "acceptance-evidence"
        / "collage-export-disk-e2e"
        / "runs"
        / time.strftime("%Y%m%d-%H%M%S"),
    )
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--cdp-port", type=int, default=0)
    args = parser.parse_args()

    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    app_port = args.port or free_port()
    cdp_port = args.cdp_port or free_port()
    data_dir = out / "data"
    lib = out / "lib"
    exports = out / "exports"
    data_dir.mkdir(parents=True, exist_ok=True)
    exports.mkdir(parents=True, exist_ok=True)
    make_fixtures(lib)
    # Stagger mtimes so Browse/search session collapse does not hide a video.
    import os as _os
    base = time.time() - 86400
    for index, name in enumerate(["left.jpg", "cella.mp4", "cellb.mp4", "right.jpg"]):
        path = lib / name
        ts = base + index * 3600
        _os.utime(path, (ts, ts))

    env = os.environ.copy()
    env["ORGA_DRONE_PORT"] = str(app_port)
    env["ORGA_DRONE_DATA_DIR"] = str(data_dir)
    env["ORGA_DRONE_GEOCODE"] = "off"
    env["ORGA_DRONE_E2E"] = "1"
    env["ORGA_DRONE_CDP_PORT"] = str(cdp_port)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    if args.exe is not None:
        if not args.exe.is_file():
            print(f"missing exe: {args.exe}", file=sys.stderr)
            return 2
        cmd = [str(args.exe)]
        cwd = str(args.exe.parent)
    else:
        cmd = [sys.executable, "-m", "orga_drone"]
        cwd = str(ROOT)

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{app_port}"
    report: dict = {
        "cmd": cmd,
        "app_port": app_port,
        "cdp_port": cdp_port,
        "screenshots": [],
    }
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
              const body = new URLSearchParams({{path:{json.dumps(str(lib))}, label:'CollageDisk'}});
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
        report["scan"] = st

        def require_media(query: str) -> int:
            res = fetch(cdp, "/api/search", "POST", {"q": query})
            data = res.get("data") or {}
            items = data.get("items") or []
            if not items:
                raise RuntimeError(f"search empty for {query}: {res}")
            return int(items[0]["id"])

        left_id = require_media("left.jpg")
        video_a = require_media("cella.mp4")
        video_b = require_media("cellb.mp4")
        right_id = require_media("right.jpg")

        created = fetch(cdp, "/api/studio/projects", "POST", {"title": "Collage Disk #487/#489"})["data"]
        project_id = int(created["id"])
        fetch(cdp, f"/api/studio/projects/{project_id}/open", "POST")

        collage = fetch(
            cdp,
            "/api/studio/collages",
            "POST",
            {"project_id": project_id, "preset": "2x2", "duration_s": 0.5},
        )["data"]
        collage_id = int(collage["id"])
        def walk_leaves(node, acc):
            if not isinstance(node, dict):
                return
            if node.get("type") == "leaf" and node.get("id"):
                acc.append(node["id"])
                return
            for key in ("a", "b", "children"):
                child = node.get(key)
                if isinstance(child, list):
                    for item in child:
                        walk_leaves(item, acc)
                else:
                    walk_leaves(child, acc)

        leaves: list[str] = []
        walk_leaves((collage.get("collage_spec") or {}).get("root"), leaves)
        report["leaf_ids"] = leaves
        if len(leaves) < 4:
            raise RuntimeError(f"expected 4 leaves, got {leaves}; collage={collage}")

        media_assigns = [
            {"source": "library", "media_id": left_id, "kind": "photo"},
            {"source": "library", "media_id": video_a, "kind": "video"},
            {"source": "library", "media_id": video_b, "kind": "video"},
            {"source": "library", "media_id": right_id, "kind": "photo"},
        ]
        for leaf_id, media in zip(leaves[:4], media_assigns, strict=True):
            media_body = dict(media)
            media_body["fit"] = "fill"
            patched = fetch(
                cdp,
                f"/api/studio/{collage_id}/collage",
                "PATCH",
                {"op": "assign_media", "leaf_id": leaf_id, "media": media_body},
            )
            if not patched.get("ok"):
                raise RuntimeError(f"assign failed: {patched}")

        # Preview still
        # Open Studio collage page then capture preview UI.
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/studio"})
        time.sleep(1.5)
        leaf_preview = fetch(
            cdp,
            f"/api/studio/{collage_id}/collage/leaves/{leaves[0]}/preview-frame?t_s=0.1",
        )
        report["preview_status"] = leaf_preview.get("status")
        shot = cdp.shot(out / "01-collage-preview.png")
        report["screenshots"].append(str(shot))

        # Successful export with enough space
        dest_ok = exports / "story-ok.mp4"
        started = http_fetch(
            base_url,
            "/api/studio/export",
            "POST",
            {
                "project_id": project_id,
                "height": 720,
                "quality": "standard",
                "output_path": str(dest_ok),
            },
        )["data"]
        job_ok = wait_job(base_url, started["job_id"])
        report["export_ok"] = job_ok
        if job_ok.get("state") != "completed" or not dest_ok.is_file():
            raise RuntimeError(f"successful export failed: {job_ok}")
        shot = cdp.shot(out / "02-export-complete.png")
        report["screenshots"].append(str(shot))

        # Cancel during a longer export
        fetch(
            cdp,
            f"/api/studio/{collage_id}/collage",
            "PATCH",
            {"duration_s": 3.0},
        )
        dest_cancel = exports / "story-cancel.mp4"
        sentinel = b"pre-existing-cancel"
        dest_cancel.write_bytes(sentinel)
        started = http_fetch(
            base_url,
            "/api/studio/export",
            "POST",
            {
                "project_id": project_id,
                "height": 720,
                "quality": "standard",
                "output_path": str(dest_cancel),
                "overwrite": True,
            },
        )["data"]
        time.sleep(0.8)
        http_fetch(base_url, f"/api/studio/export/jobs/{started['job_id']}/cancel", "POST")
        job_cancel = wait_job(base_url, started["job_id"])
        report["export_cancel"] = job_cancel
        if dest_cancel.read_bytes() != sentinel:
            raise RuntimeError("cancel published or replaced destination")
        shot = cdp.shot(out / "03-export-cancelled.png")
        report["screenshots"].append(str(shot))

        # Controlled low-space failure via TEST-ONLY env on a new process is hard;
        # instead call the export API after setting the override through a small
        # evaluate that hits a debug path is unavailable. Re-launch is heavy.
        # Use an in-process API: set env for the running server via a side channel
        # is not supported. Simulate by spawning a second export worker path:
        # write a tiny helper file the server reads? Not present.
        # Practical approach for this E2E: invoke export while ORGA_DRONE_COLLAGE_STAGING_FREE_BYTES
        # is set on the process — set it before launch for a dedicated low-space run.
        # Controlled low-space failure via TEST-ONLY env in a sidecar (never fills disk).
        sidecar = subprocess.run(
            [
                sys.executable,
                str(ROOT / "packaging" / "e2e" / "collage_low_space_sidecar.py"),
                str(out / "sidecar-work"),
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        report["low_space_sidecar"] = {
            "returncode": sidecar.returncode,
            "stdout": sidecar.stdout[-2000:],
            "stderr": sidecar.stderr[-2000:],
        }
        if "ERR:Not enough temporary disk space" not in sidecar.stdout:
            raise RuntimeError(f"low-space sidecar failed: {sidecar.stdout} {sidecar.stderr}")
        if "PRESERVED:True" not in sidecar.stdout:
            raise RuntimeError("low-space sidecar did not preserve destination")

        # Successful retry after clearing the simulated budget (already enough on main app)
        dest_retry = exports / "story-retry.mp4"
        started = http_fetch(
            base_url,
            "/api/studio/export",
            "POST",
            {
                "project_id": project_id,
                "height": 720,
                "quality": "standard",
                "output_path": str(dest_retry),
            },
        )["data"]
        job_retry = wait_job(base_url, started["job_id"])
        report["export_retry"] = job_retry
        if job_retry.get("state") != "completed" or not dest_retry.is_file():
            raise RuntimeError(f"retry export failed: {job_retry}")
        shot = cdp.shot(out / "04-export-retry.png")
        report["screenshots"].append(str(shot))

        # Decode final video
        from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs

        ffmpeg = find_ffmpeg()
        decode = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(dest_retry), "-f", "null", "-"],
            capture_output=True,
            text=True,
            **subprocess_no_window_kwargs(),
        )
        report["decode_ok"] = decode.returncode == 0
        if decode.returncode != 0:
            raise RuntimeError(f"decode failed: {decode.stderr[-500:]}")

        leftovers = [str(p) for p in temp_files(data_dir) if "collage" in str(p).lower()]
        report["temp_leftovers"] = leftovers
        if leftovers:
            raise RuntimeError(f"temp leftovers: {leftovers}")

        report["ok"] = True
        (out / "e2e-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["error"] = str(exc)
        if cdp is not None:
            try:
                report["screenshots"].append(str(cdp.shot(out / "99-error.png")))
            except Exception:
                pass
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