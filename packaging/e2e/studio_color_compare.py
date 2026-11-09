"""Focused Windows/WebView2 source-app journey for #322; synthetic media only.

Run with the repository's src on PYTHONPATH. This is not packaged/MOTW evidence.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

_spec = importlib.util.spec_from_file_location("compare_windows_e2e", Path(__file__).with_name("windows_e2e.py"))
assert _spec and _spec.loader
_harness: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)
free_port = _harness.free_port
wait_cdp, wait_page_target = _harness.wait_cdp, _harness.wait_page_target


class RecordingCDP(_harness.CDP):
    """Retain request notifications while using the existing synchronous client."""
    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.urls: list[str] = []

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self._next_id
        self._next_id += 1
        self._ws.send(json.dumps(dict(id=request_id, method=method, params=params or {})))
        while True:
            message = json.loads(self._ws.recv())
            if message.get("method") == "Network.requestWillBeSent":
                self.urls.append(message["params"]["request"]["url"])
            if message.get("id") != request_id:
                continue
            assert "error" not in message, message
            return message.get("result")


def run(out: Path) -> None:
    from orga_drone.config import Settings
    from orga_drone.db import Database
    from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
    from orga_drone.studio_lut import import_lut_from_path

    out.mkdir(parents=True, exist_ok=False)
    data, media = out / "data", out / "media"
    media.mkdir()
    ffmpeg = find_ffmpeg()
    assert ffmpeg
    for ext in ("jpg", "png"):
        Image.new("RGB", (640, 360), (64, 100, 150)).save(media / f"sample.{ext}")
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=0x406496:s=640x360:r=30:d=2", "-pix_fmt", "yuv420p",
                    str(media / "sample.mp4")], check=True, timeout=30,
                   **subprocess_no_window_kwargs())
    cube = out / "technical.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "\n".join(
        f"{r * .6 + .1} {g * .8} {b * .7}" for b in (0, 1) for g in (0, 1) for r in (0, 1)) + "\n")
    technical = import_lut_from_path(data, cube)
    cube.write_text(cube.read_text().replace("0.1", "0.25"))
    creative = import_lut_from_path(data, cube)
    db = Database(Settings(data_dir=data).db_path)
    root = db.add_root(media, label="Synthetic comparison")
    project = db.create_studio_project("Synthetic color comparison")
    ids = []
    originals = {}
    for source in sorted(media.iterdir()):
        kind = "video" if source.suffix == ".mp4" else "photo"
        originals[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        mid = db.upsert_media(dict(root_id=root, kind=kind, path=str(source), filename=source.name,
                                  size_bytes=source.stat().st_size, width=640, height=360,
                                  duration_s=2 if kind == "video" else None, has_srt=0, has_lrf=0))
        cid, _ = db.add_studio_item(str(source), identity_key=source.name, filename=source.name,
                                   kind=kind, recorded_at=None, project_id=project.id, source_media_id=mid)
        db.set_studio_color_look(cid, dict(input_profile="dlog_m", conversion_lut=technical,
                                         conversion_confirmed=True, creative_lut=creative, creative_strength=75))
        db.set_studio_image_adjust(cid, dict(exposure=35, contrast=20, saturation=15))
        if kind == "photo":
            db.set_studio_hsl(cid, {"range": "blue", "hue": 10})
        else:
            # Keep video WebGL-eligible: generated HSL would select another path.
            db.set_studio_masks(cid, {"masks": [
                dict(id="blur", effect="blur", x=.15, y=.25, w=.2, h=.3, strength=50),
                dict(id="pixel", effect="pixelate", x=.65, y=.25, w=.2, h=.3, strength=50),
            ]})
        ids.append((cid, source.suffix))
    port, debug = free_port(), free_port()
    repo = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(PYTHONPATH=str(repo / "src"), ORGA_DRONE_DATA_DIR=str(data), ORGA_DRONE_HOST="127.0.0.1",
               ORGA_DRONE_PORT=str(port), ORGA_DRONE_GEOCODE="off", ORGA_DRONE_E2E="1",
               ORGA_DRONE_CDP_PORT=str(debug))
    env.pop("ORGA_DRONE_BROWSER", None)
    base = f"http://127.0.0.1:{port}"
    cdp = None
    with (out / "app.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-m", "orga_drone"], cwd=repo, env=env,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    result: dict[str, Any] = {"status": "INCOMPLETE", "cases": []}
    def api(path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Origin": base})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    def ev(expression: str) -> Any:
        assert cdp
        return cdp.evaluate(expression, await_promise=True, user_gesture=True)
    def until(expression: str) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if ev(expression):
                return
            time.sleep(.05)
        raise AssertionError("Timed out: " + expression)
    def state() -> list[Any]:
        with db.connect() as conn:
            tables = [str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                      if str(r[0]).startswith("studio_")]
            return [[tuple(r) for r in conn.execute(f'SELECT * FROM "{t}"')] for t in sorted(tables)]
    def pixels() -> str:
        time.sleep(.15)
        return str(ev("document.getElementById('studio-preview-blit').toDataURL()"))
    def export(name: str) -> Path:
        destination = out / name
        job = api("/api/studio/export", dict(project_id=project.id, height=720, output_path=str(destination)))
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status = api("/api/studio/export/jobs/" + job["job_id"])
            if status["state"] in {"completed", "failed", "cancelled"}:
                assert status["state"] == "completed", status
                subprocess.run([ffmpeg, "-v", "error", "-i", str(destination), "-f", "null", "-"],
                               capture_output=True, check=True, timeout=90, **subprocess_no_window_kwargs())
                return destination
            time.sleep(.2)
        raise AssertionError("Export timed out")
    def key(kind: str, value: str = " ") -> None:
        assert cdp
        cdp.call("Input.dispatchKeyEvent", {"type": kind, "key": value,
                 "code": "Space" if value == " " else "Enter", "windowsVirtualKeyCode": 32 if value == " " else 13})
    def select(cid: int) -> None:
        ev(f"(()=>{{let e=document.querySelector('#studio-grid [data-select-clip=\"{cid}\"]');let r=e.getBoundingClientRect();e.dispatchEvent(new MouseEvent('click',{{bubbles:true,clientX:r.x+1}}));document.querySelector('[data-inspector-tab-button=image]').click();}})()")
        until("!document.getElementById('inspector-look-compare').disabled")
        # Keep the comparison surface fixed while focus scrolls the inspector.
        # Otherwise browser layout changes backing dimensions, not color pixels.
        ev("Object.assign(document.getElementById('studio-preview-frame').style,{width:'640px',height:'360px',maxWidth:'none',maxHeight:'none',flex:'none'})")
    def before_ready() -> None:
        until("document.getElementById('studio-color-compare-status').textContent === document.getElementById('studio-root').dataset.compareBefore")
    def mouse(kind: str, outside: bool = False) -> None:
        assert cdp
        rect = ev("(()=>{let e=document.getElementById('inspector-look-compare');e.scrollIntoView({block:'center'});let r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
        cdp.call("Input.dispatchMouseEvent", dict(type=kind, x=5 if outside else rect["x"],
                 y=5 if outside else rect["y"], button="left", clickCount=1))
    try:
        result["browser"] = wait_cdp(debug, 120)["Browser"]
        result["source_hashes"] = originals
        result["implementation_sha256"] = {
            path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in (
                "src/orga_drone/app.py", "src/orga_drone/studio_preview_frame.py",
                "src/orga_drone/static/js/studio.js", "src/orga_drone/static/js/studio/color-compare.js",
                "src/orga_drone/templates/studio.html", "src/orga_drone/static/css/app.css",
                "packaging/e2e/studio_color_compare.py")}
        cdp = RecordingCDP(wait_page_target(debug, 120)["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.call("Network.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", dict(width=1600, height=1000, deviceScaleFactor=1, mobile=False))
        cdp.call("Page.navigate", {"url": base + f"/studio?project_id={project.id}"})
        until("!!document.getElementById('studio-grid')")
        first = export("before-interaction.mp4")
        for cid, ext in ids:
            select(cid)
            time.sleep(2)
            saved, after = state(), pixels()
            ev("document.getElementById('inspector-look-compare').focus()")
            key("keyDown")
            before_ready()
            request_count = len([u for u in cdp.urls if "before=1" in u])
            time.sleep(.5)
            ev("1")
            assert len([u for u in cdp.urls if "before=1" in u]) == request_count, "held comparison must not poll"
            before = pixels()
            assert before != after, ext + " comparison must visibly change color"
            if ext == ".mp4":
                assert ev("document.getElementById('studio-preview-frame').dataset.lutWebgl === '1'"), "video must exercise WebGL"
                matched = ev("(()=>{let a=document.getElementById('studio-preview-blit'),b=document.getElementById('studio-preview-masks');return [.25,.75].every(x=>{let p=a.getContext('2d').getImageData(Math.floor(a.width*x),Math.floor(a.height*.4),1,1).data;let q=b.getContext('2d').getImageData(Math.floor(b.width*x),Math.floor(b.height*.4),1,1).data;return [...p].every((v,i)=>v===q[i]);});})()")
                assert matched, "blur and pixel masks must use the same Before color as the compositor"
                result["webgl_blur_and_pixel_masks_before"] = True
            (out / (ext[1:] + "-before.png")).write_bytes(base64.b64decode(before.split(",", 1)[1]))
            if ext == ".jpg":
                (out / "ui-before.png").write_bytes(base64.b64decode(cdp.call("Page.captureScreenshot", {"format": "png"})["data"]))
            key("keyUp")
            until("document.getElementById('inspector-look-compare').getAttribute('aria-pressed') === 'false'")
            assert pixels() == after, ext + " release must restore exact current pixels"
            assert state() == saved, "comparison wrote project/history"
            (out / (ext[1:] + "-after.png")).write_bytes(base64.b64decode(after.split(",", 1)[1]))
            if ext == ".jpg":
                (out / "ui-after.png").write_bytes(base64.b64decode(cdp.call("Page.captureScreenshot", {"format": "png"})["data"]))
            for _ in range(6):
                key("keyDown", "Enter")
                key("keyUp", "Enter")
            time.sleep(.5)
            rapid = pixels()
            if rapid != after:
                (out / "rapid-actual.png").write_bytes(base64.b64decode(rapid.split(",", 1)[1]))
                result["rapid_diagnostic"] = ev("({pressed:document.getElementById('inspector-look-compare').getAttribute('aria-pressed'),status:document.getElementById('studio-color-compare-status').textContent,time:document.getElementById('studio-playhead').getAttribute('aria-valuenow'),w:document.getElementById('studio-preview-blit').width,h:document.getElementById('studio-preview-blit').height})")
            assert rapid == after, "stale rapid-toggle frame"
            mouse("mousePressed")
            before_ready()
            mouse("mouseReleased", outside=True)
            assert pixels() == after, "outside-pointer release must restore After"
            result["cases"].append(dict(kind=ext, exact_restore=True, state_unchanged=True,
                                         rapid_toggle=True, mouse_outside_release=True, held_requests=0))
        select(ids[0][0])
        ev("document.getElementById('inspector-look-compare').focus()")
        key("keyDown")
        select(ids[1][0])
        key("keyUp")
        assert ev("document.getElementById('inspector-look-compare').getAttribute('aria-pressed')") == "false"
        result["clip_change_releases"] = True
        second = export("after-interaction.mp4")
        assert first.read_bytes() == second.read_bytes(), "comparison changed export bytes"
        result["export_bytes_identical"] = True
        result["export_sha256"] = hashlib.sha256(first.read_bytes()).hexdigest()
        result["source_hashes_unchanged"] = all(hashlib.sha256((media / n).read_bytes()).hexdigest() == h
                                                 for n, h in originals.items())
        assert result["source_hashes_unchanged"]
        assert cdp
        cdp.call("Page.reload")
        until("!!document.getElementById('inspector-look-compare')")
        assert ev("document.getElementById('inspector-look-compare').getAttribute('aria-pressed')") == "false"
        result["reload_after"] = True
        select(ids[0][0])
        ev("document.getElementById('inspector-look-compare').focus()")
        key("keyDown")
        before_ready()
        ev("(()=>{let e=document.getElementById('inspector-color-creative-select');e.value='';e.dispatchEvent(new Event('change',{bubbles:true}));})()")
        until("document.getElementById('inspector-look-compare').getAttribute('aria-pressed') === 'false'")
        key("keyUp")
        until(f"!JSON.parse(document.querySelector('#studio-grid [data-studio-id=\"{ids[0][0]}\"]').dataset.colorLook).creative_lut")
        result["lut_removal_releases"] = True
        # Baseline photo owners still do no per-tick preview-frame work during playback.
        select(ids[0][0])
        ev("document.querySelector('[data-transport=toggle]').click()")
        time.sleep(.3)
        ev("1")
        count = len([u for u in cdp.urls if "/preview-frame" in u])
        time.sleep(.5)
        ev("1")
        assert len([u for u in cdp.urls if "/preview-frame" in u]) == count
        assert ev("document.getElementById('inspector-look-compare').disabled")
        result["playback_interval_still_requests"] = 0
        ev("document.querySelector('[data-transport=toggle]').click()")
        result["status"] = "PASS"
    finally:
        (out / "evidence.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if cdp:
            cdp.close()
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    run(parser.parse_args().output_dir.resolve())
