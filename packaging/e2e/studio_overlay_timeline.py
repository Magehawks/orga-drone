"""WebView2 timeline-first overlay selection/removal (#339 Phase 3).

Covers text, image and shape overlay bars with real CDP mouse/key input.
Synthetic media only. Not part of main-admission journey smoke.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request

from PIL import Image

_spec = importlib.util.spec_from_file_location(
    "overlay_timeline_e2e", Path(__file__).with_name("windows_e2e.py")
)
assert _spec and _spec.loader
_harness: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)


def run(out: Path) -> None:
    from orga_drone.config import Settings
    from orga_drone.db import Database
    from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs

    out.mkdir(parents=True, exist_ok=False)
    media = out / "media"
    media.mkdir()
    ffmpeg = find_ffmpeg()
    assert ffmpeg
    db = Database(Settings(data_dir=out / "data").db_path)
    root = db.add_root(media, label="Synthetic overlay bars")
    project = db.create_studio_project("Timeline-first overlay bars")
    db.set_open_studio_project_id(project.id)
    source = media / "synthetic-overlays.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1280x720:r=30:d=4",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    source_b = media / "synthetic-overlays-b.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1280x720:r=30:d=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(source_b),
        ],
        check=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )
    original_b = hashlib.sha256(source_b.read_bytes()).hexdigest()

    def _add_video(path: Path, duration: int) -> int:
        mid = db.upsert_media(
            dict(
                root_id=root,
                kind="video",
                path=str(path),
                filename=path.name,
                size_bytes=path.stat().st_size,
                duration_s=duration,
                width=1280,
                height=720,
                has_srt=0,
                has_lrf=0,
            )
        )
        item_id, _ = db.add_studio_item(
            str(path),
            identity_key=path.name,
            filename=path.name,
            recorded_at=None,
            kind="video",
            project_id=project.id,
            source_media_id=mid,
        )
        return int(item_id)

    cid = _add_video(source, 4)
    cid_b = _add_video(source_b, 3)
    port, debug = _harness.free_port(), _harness.free_port()
    repo = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(repo / "src"),
        ORGA_DRONE_DATA_DIR=str(out / "data"),
        ORGA_DRONE_HOST="127.0.0.1",
        ORGA_DRONE_PORT=str(port),
        ORGA_DRONE_GEOCODE="off",
        ORGA_DRONE_E2E="1",
        ORGA_DRONE_CDP_PORT=str(debug),
    )
    env.pop("ORGA_DRONE_BROWSER", None)
    base = f"http://127.0.0.1:{port}"
    process = None
    cdp = None
    evidence: dict[str, Any] = {
        "status": "INCOMPLETE",
        "issue": 339,
        "phase": 3,
        "source_app": True,
        "synthetic_only": True,
    }

    def start() -> None:
        nonlocal process, cdp
        with (out / "app.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "orga_drone"],
                cwd=repo,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        _harness.wait_cdp(debug, 45)
        target = _harness.wait_page_target(debug, 30)
        cdp = _harness.CDP(target["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "window.__overlayErrors=[];"
                    "addEventListener('error',e=>window.__overlayErrors.push(e.message));"
                    "addEventListener('unhandledrejection',e=>window.__overlayErrors.push(String(e.reason)));"
                )
            },
        )
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            dict(width=1440, height=900, deviceScaleFactor=1, mobile=False),
        )
        cdp.call("Page.navigate", {"url": base + "/studio"})
        until("!!document.querySelector('#studio-grid [data-studio-id]')")
        time.sleep(0.8)

    def stop() -> None:
        nonlocal cdp, process
        if cdp:
            cdp.close()
            cdp = None
        if process:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            process.wait(timeout=15)
            process = None

    def ev(js: str) -> Any:
        assert cdp
        return cdp.evaluate(js, await_promise=True, user_gesture=True)

    def until(js: str, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ev(js):
                return
            time.sleep(0.05)
        raise AssertionError("Timed out: " + js)

    def shot(name: str) -> None:
        assert cdp
        data = cdp.call("Page.captureScreenshot", {"format": "png"})["data"]
        (out / name).write_bytes(base64.b64decode(data))

    def _target_point(selector: str) -> dict[str, float]:
        rect = ev(
            f"""(() => {{
              const el = document.querySelector({selector!r});
              if (!el) return null;
              el.scrollIntoView({{block:'center', inline:'nearest'}});
              const r = el.getBoundingClientRect();
              return {{
                x: r.x + r.width / 2,
                y: r.y + Math.min(Math.max(r.height / 2, 4), 12),
                width: r.width,
                height: r.height
              }};
            }})()"""
        )
        assert rect, selector
        return rect

    def mouse_at(selector: str, button: str = "left", clicks: int = 1) -> dict[str, float]:
        assert cdp
        _target_point(selector)
        time.sleep(0.08)
        rect = _target_point(selector)
        pressed = 1 if button == "left" else 2
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": rect["x"],
                "y": rect["y"],
                "button": "none",
                "buttons": 0,
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": rect["x"],
                "y": rect["y"],
                "button": button,
                "buttons": pressed,
                "clickCount": clicks,
                "pointerType": "mouse",
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": rect["x"],
                "y": rect["y"],
                "button": button,
                "buttons": 0,
                "clickCount": clicks,
                "pointerType": "mouse",
            },
        )
        return rect

    def menu_open() -> bool:
        return bool(
            ev(
                "document.getElementById('studio-clip-menu') && "
                "!document.getElementById('studio-clip-menu').hidden"
            )
        )

    def key(name: str) -> None:
        assert cdp
        mapping = {
            "Delete": ("Delete", "Delete", 46),
            "Backspace": ("Backspace", "Backspace", 8),
            "Escape": ("Escape", "Escape", 27),
        }
        key_name, code, vk = mapping[name]
        for kind in ("keyDown", "keyUp"):
            cdp.call(
                "Input.dispatchKeyEvent",
                {
                    "type": kind,
                    "key": key_name,
                    "code": code,
                    "windowsVirtualKeyCode": vk,
                    "nativeVirtualKeyCode": vk,
                },
            )

    def open_context_menu_cdp(selector: str, *, label: str) -> None:
        assert cdp
        if menu_open():
            key("Escape")
            time.sleep(0.05)
        last_hit = None
        for attempt in range(1, 4):
            mouse_at(selector, button="right")
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                if menu_open():
                    evidence[f"cdp_contextmenu_{label}"] = True
                    evidence[f"cdp_contextmenu_{label}_attempt"] = attempt
                    return
                time.sleep(0.05)
            cdp.call(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": 8, "y": 8, "button": "none", "buttons": 0},
            )
            time.sleep(0.08)
            last_hit = attempt
        evidence[f"cdp_contextmenu_{label}"] = False
        evidence[f"cdp_contextmenu_{label}_debug"] = last_hit
        raise AssertionError(f"CDP right-click did not open context menu for {label}")

    def http_json(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            base + path,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": base,
                "Referer": base + "/studio",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AssertionError(f"{method} {path} -> {exc.code}: {detail}") from exc

    def http_multipart(path: str, filename: str, payload: bytes, content_type: str) -> Any:
        boundary = "----orgaoverlaye2e"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = urllib.request.Request(
            base + path,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
                "Origin": base,
                "Referer": base + "/studio",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AssertionError(f"POST {path} -> {exc.code}: {detail}") from exc

    def reload_studio() -> None:
        assert cdp
        cdp.call("Page.navigate", {"url": base + "/studio"})
        until("!!document.querySelector('#studio-grid [data-studio-id]')")
        time.sleep(0.5)

    def blur_focus() -> None:
        ev(
            "document.activeElement && document.activeElement.blur && document.activeElement.blur();"
            "document.getElementById('studio-playhead')?.focus();"
        )

    def clip_present() -> bool:
        return bool(ev(f"!!document.querySelector('#studio-grid [data-studio-id=\"{cid}\"]')"))

    def wait_overlay(overlay_id: str, present: bool = True) -> None:
        until(
            f"""(() => {{
              const el = document.querySelector(
                '.studio-effect-bar[data-kind="overlay"][data-mask-id="{overlay_id}"]'
              );
              return {str(present).lower()} ? !!el : !el;
            }})()"""
        )

    def overlay_selector(overlay_id: str) -> str:
        return f'.studio-effect-bar[data-kind="overlay"][data-mask-id="{overlay_id}"]'

    def undo_history() -> None:
        until("document.getElementById('studio-undo') && !document.getElementById('studio-undo').disabled")
        ev("document.getElementById('studio-undo').click()")

    def redo_history() -> None:
        until("document.getElementById('studio-redo') && !document.getElementById('studio-redo').disabled")
        ev("document.getElementById('studio-redo').click()")

    def playhead_now() -> float:
        return float(
            ev(
                "Number(document.getElementById('studio-playhead')?.getAttribute('aria-valuenow')||0)"
            )
            or 0
        )

    def _base_overlay(
        overlay_id: str,
        kind: str,
        *,
        start_s: float = 0.5,
        end_s: float = 2.5,
        text: str = "",
        asset_name: str = "",
    ) -> dict[str, Any]:
        return {
            "id": overlay_id,
            "kind": kind,
            "start_s": start_s,
            "end_s": end_s,
            "x": 0.1,
            "y": 0.1,
            "w": 0.3 if kind != "text" else 0.4,
            "h": 0.2 if kind != "text" else 0.16,
            "rotation": 0,
            "text": text,
            "font_size": 0.06,
            "color": "#ffffff",
            "fill": "#00000066" if kind in {"circle", "rectangle"} else "#00000000",
            "stroke": "#ffffff",
            "stroke_width": 0.012,
            "asset_name": asset_name,
            "animation": "none",
            "animation_s": 0.4,
            "slide_from": "left",
        }

    try:
        start()
        assert cdp
        evidence["webview2"] = _harness.webview2_version()

        # --- Text overlay ---
        texted = http_json(
            "PATCH",
            f"/api/studio/{cid}/overlays",
            {"overlays": [_base_overlay("ovtexte2e01", "text", text="Hello Overlay")]},
        )
        assert texted and texted.get("ok"), texted
        reload_studio()
        wait_overlay("ovtexte2e01", True)
        ev(
            "document.querySelector('[data-inspector-tab-button=clip]')?.click();"
            "document.getElementById('studio-playhead')?.focus()"
        )
        before = playhead_now()
        mouse_at(overlay_selector("ovtexte2e01"), button="left")
        until(
            "document.getElementById('inspector-clip')?.dataset.tab === 'overlays' && "
            f'!!document.querySelector(\'{overlay_selector("ovtexte2e01")}.is-selected\')'
        )
        after = playhead_now()
        evidence["text_select_no_seek"] = abs(after - before) < 0.25
        assert evidence["text_select_no_seek"], (before, after)
        shot("01-text-selected.png")

        open_context_menu_cdp(overlay_selector("ovtexte2e01"), label="text")
        assert ev("!document.getElementById('studio-clip-menu-edit').hidden")
        assert ev("!document.getElementById('studio-clip-menu-remove-effect').hidden")
        assert ev("document.getElementById('studio-clip-menu-remove').hidden")
        shot("02-text-context-menu.png")
        ev("document.getElementById('studio-clip-menu-edit').click()")
        until("document.getElementById('inspector-clip')?.dataset.tab === 'overlays'")
        evidence["text_context_edit"] = True

        blur_focus()
        until(f'!!document.querySelector(\'{overlay_selector("ovtexte2e01")}.is-selected\')')
        edge = ev(
            f"""(() => {{
              const edge = document.querySelector(
                '{overlay_selector("ovtexte2e01")} .studio-effect-edge-out'
              );
              if (!edge) return null;
              edge.scrollIntoView({{block:'center', inline:'nearest'}});
              const r = edge.getBoundingClientRect();
              return {{x: r.x + r.width / 2, y: r.y + r.height / 2}};
            }})()"""
        )
        assert edge
        width_before = float(
            ev(
                f"Number.parseFloat(document.querySelector('{overlay_selector('ovtexte2e01')}').style.width)||0"
            )
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": edge["x"],
                "y": edge["y"],
                "button": "none",
                "buttons": 0,
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": edge["x"],
                "y": edge["y"],
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
                "pointerType": "mouse",
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": edge["x"] - 40,
                "y": edge["y"],
                "button": "left",
                "buttons": 1,
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": edge["x"] - 40,
                "y": edge["y"],
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
                "pointerType": "mouse",
            },
        )
        time.sleep(0.5)
        width_after = float(
            ev(
                f"Number.parseFloat(document.querySelector('{overlay_selector('ovtexte2e01')}').style.width)||0"
            )
        )
        evidence["text_edge_resize"] = width_after < width_before - 5
        assert evidence["text_edge_resize"], (width_before, width_after)
        shot("03-text-resized.png")

        # Move drag keeps duration.
        mouse_at(overlay_selector("ovtexte2e01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovtexte2e01")}.is-selected\')')
        bar = _target_point(overlay_selector("ovtexte2e01"))
        start_before = float(
            ev(
                f"""(() => {{
                  const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
                  const ov = JSON.parse(clip.dataset.overlays||'[]').find(o => o.id === 'ovtexte2e01');
                  return ov ? Number(ov.start_s) : -1;
                }})()"""
            )
        )
        dur_before = float(
            ev(
                f"""(() => {{
                  const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
                  const ov = JSON.parse(clip.dataset.overlays||'[]').find(o => o.id === 'ovtexte2e01');
                  return ov ? Number(ov.end_s) - Number(ov.start_s) : -1;
                }})()"""
            )
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": bar["x"],
                "y": bar["y"],
                "button": "none",
                "buttons": 0,
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": bar["x"],
                "y": bar["y"],
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
                "pointerType": "mouse",
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": bar["x"] + 50,
                "y": bar["y"],
                "button": "left",
                "buttons": 1,
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": bar["x"] + 50,
                "y": bar["y"],
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
                "pointerType": "mouse",
            },
        )
        time.sleep(0.5)
        start_after = float(
            ev(
                f"""(() => {{
                  const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
                  const ov = JSON.parse(clip.dataset.overlays||'[]').find(o => o.id === 'ovtexte2e01');
                  return ov ? Number(ov.start_s) : -1;
                }})()"""
            )
        )
        dur_after = float(
            ev(
                f"""(() => {{
                  const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
                  const ov = JSON.parse(clip.dataset.overlays||'[]').find(o => o.id === 'ovtexte2e01');
                  return ov ? Number(ov.end_s) - Number(ov.start_s) : -1;
                }})()"""
            )
        )
        evidence["text_move_preserves_duration"] = (
            start_after > start_before + 0.05 and abs(dur_after - dur_before) < 0.05
        )
        assert evidence["text_move_preserves_duration"], (
            start_before,
            start_after,
            dur_before,
            dur_after,
        )
        shot("04-text-moved.png")

        blur_focus()
        mouse_at(overlay_selector("ovtexte2e01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovtexte2e01")}.is-selected\')')
        key("Delete")
        wait_overlay("ovtexte2e01", False)
        assert clip_present()
        evidence["text_delete"] = True
        shot("05-text-removed.png")

        undo_history()
        wait_overlay("ovtexte2e01", True)
        evidence["text_undo"] = True
        blur_focus()
        mouse_at(overlay_selector("ovtexte2e01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovtexte2e01")}.is-selected\')')
        key("Backspace")
        wait_overlay("ovtexte2e01", False)
        assert clip_present()
        evidence["text_backspace"] = True
        undo_history()
        wait_overlay("ovtexte2e01", True)
        redo_history()
        wait_overlay("ovtexte2e01", False)
        evidence["text_redo"] = True

        # --- Stale selection across ordinary clip switch ---
        texted_again = http_json(
            "PATCH",
            f"/api/studio/{cid}/overlays",
            {"overlays": [_base_overlay("ovtexte2e01", "text", text="Keep me")]},
        )
        assert texted_again and texted_again.get("ok"), texted_again
        reload_studio()
        wait_overlay("ovtexte2e01", True)
        mouse_at(overlay_selector("ovtexte2e01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovtexte2e01")}.is-selected\')')
        ev(
            f"""(() => {{
              const pick = document.querySelector('#studio-grid [data-select-clip="{cid_b}"]');
              if (!pick) return false;
              const r = pick.getBoundingClientRect();
              pick.dispatchEvent(new MouseEvent('click', {{bubbles:true, clientX:r.x+2, clientY:r.y+2}}));
              return true;
            }})()"""
        )
        until(
            f'document.querySelector(\'#studio-grid [data-studio-id="{cid_b}"]\')?.classList.contains("is-selected")'
        )
        until(
            f'!document.querySelector(\'{overlay_selector("ovtexte2e01")}.is-selected\')'
        )
        ev("document.getElementById('inspector-tab-image')?.focus()")
        key("Delete")
        key("Backspace")
        time.sleep(0.25)
        assert ev(f'!!document.querySelector(\'{overlay_selector("ovtexte2e01")}\')')
        assert clip_present()
        assert bool(
            ev(f'!!document.querySelector(\'#studio-grid [data-studio-id="{cid_b}"]\')')
        )
        evidence["stale_selection_safe_after_clip_switch"] = True
        shot("06-stale-selection-safe.png")

        # Selected overlay still deletable after reselect.
        mouse_at(overlay_selector("ovtexte2e01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovtexte2e01")}.is-selected\')')
        blur_focus()
        key("Delete")
        wait_overlay("ovtexte2e01", False)
        evidence["selected_overlay_still_deletable"] = True

        # Story-clip focus rules: Backspace must not remove the selected clip.
        ev(
            f"""(() => {{
              const pick = document.querySelector('#studio-grid [data-select-clip="{cid_b}"]');
              const r = pick.getBoundingClientRect();
              pick.dispatchEvent(new MouseEvent('click', {{bubbles:true, clientX:r.x+2, clientY:r.y+2}}));
              document.getElementById('studio-playhead')?.focus();
              return true;
            }})()"""
        )
        key("Backspace")
        time.sleep(0.2)
        assert bool(
            ev(f'!!document.querySelector(\'#studio-grid [data-studio-id="{cid_b}"]\')')
        )
        evidence["story_backspace_keeps_clip"] = True

        # --- Shape overlay ---
        shaped = http_json(
            "PATCH",
            f"/api/studio/{cid}/overlays",
            {"overlays": [_base_overlay("ovshapee2e1", "arrow", start_s=0.4, end_s=2.8)]},
        )
        assert shaped and shaped.get("ok"), shaped
        reload_studio()
        wait_overlay("ovshapee2e1", True)
        mouse_at(overlay_selector("ovshapee2e1"), button="left")
        until(
            "document.getElementById('inspector-clip')?.dataset.tab === 'overlays' && "
            f'!!document.querySelector(\'{overlay_selector("ovshapee2e1")}.is-selected\')'
        )
        evidence["shape_select_tab"] = True
        shot("07-shape-selected.png")
        open_context_menu_cdp(overlay_selector("ovshapee2e1"), label="shape")
        ev("document.getElementById('studio-clip-menu-remove-effect').click()")
        wait_overlay("ovshapee2e1", False)
        assert clip_present()
        evidence["shape_context_remove"] = True

        # --- Image overlay ---
        png = io.BytesIO()
        Image.new("RGBA", (64, 64), (255, 40, 40, 200)).save(png, format="PNG")
        uploaded = http_multipart(
            "/api/studio/overlay-assets",
            "badge.png",
            png.getvalue(),
            "image/png",
        )
        assert uploaded and uploaded.get("asset_name"), uploaded
        imaged = http_json(
            "PATCH",
            f"/api/studio/{cid}/overlays",
            {
                "overlays": [
                    _base_overlay(
                        "ovimagee2e1",
                        "image",
                        start_s=0.3,
                        end_s=2.2,
                        asset_name=uploaded["asset_name"],
                    )
                ]
            },
        )
        assert imaged and imaged.get("ok"), imaged
        reload_studio()
        wait_overlay("ovimagee2e1", True)
        mouse_at(overlay_selector("ovimagee2e1"), button="left")
        until(
            "document.getElementById('inspector-clip')?.dataset.tab === 'overlays' && "
            f'!!document.querySelector(\'{overlay_selector("ovimagee2e1")}.is-selected\')'
        )
        evidence["image_select_tab"] = True
        shot("08-image-selected.png")
        open_context_menu_cdp(overlay_selector("ovimagee2e1"), label="image")
        ev("document.getElementById('studio-clip-menu-remove-effect').click()")
        wait_overlay("ovimagee2e1", False)
        assert clip_present()
        evidence["image_context_remove"] = True

        # --- Persistence races: clip revisions + serialized saves ---
        dual = http_json(
            "PATCH",
            f"/api/studio/{cid}/overlays",
            {
                "overlays": [
                    _base_overlay("ovpersista01", "text", text="Persist-A", start_s=0.2, end_s=1.8),
                    _base_overlay("ovpersistb01", "circle", start_s=1.0, end_s=3.0),
                ]
            },
        )
        assert dual and dual.get("ok") and len(dual.get("overlays") or []) == 2, dual
        reload_studio()
        until(
            f"""(() => {{
              const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
              if (!clip) return false;
              const list = JSON.parse(clip.dataset.overlays || '[]');
              return list.some((o) => o.id === 'ovpersista01') &&
                list.some((o) => o.id === 'ovpersistb01');
            }})()"""
        )
        wait_overlay("ovpersista01", True)
        wait_overlay("ovpersistb01", True)
        evidence["two_overlay_seed"] = True

        # Install PATCH failure helper (optional delay) for /overlays.
        ev(
            """(() => {
              if (window.__overlayFetchWrapped) return true;
              const orig = window.fetch.bind(window);
              window.__overlayFailRemaining = 0;
              window.__overlayFailDelayMs = 0;
              window.__overlayFailHits = 0;
              window.fetch = async (input, init = {}) => {
                const url = String(typeof input === 'string' ? input : (input && input.url) || '');
                const method = String((init && init.method) || 'GET').toUpperCase();
                if (
                  window.__overlayFailRemaining > 0 &&
                  method === 'PATCH' &&
                  url.includes('/overlays')
                ) {
                  window.__overlayFailRemaining -= 1;
                  window.__overlayFailHits += 1;
                  const delay = Number(window.__overlayFailDelayMs) || 0;
                  if (delay > 0) {
                    await new Promise((resolve) => setTimeout(resolve, delay));
                  }
                  return new Response(
                    JSON.stringify({ ok: false, detail: 'forced overlay fail' }),
                    { status: 500, headers: { 'Content-Type': 'application/json' } }
                  );
                }
                return orig(input, init);
              };
              window.__overlayFetchWrapped = true;
              return true;
            })()"""
        )

        # Failed removal keeps selection and can be retried; sibling overlay survives.
        mouse_at(overlay_selector("ovpersista01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovpersista01")}.is-selected\')')
        blur_focus()
        ev("window.__overlayFailRemaining = 1")
        key("Delete")
        until(
            "!!document.getElementById('studio-flash')?.textContent && "
            f'!!document.querySelector(\'{overlay_selector("ovpersista01")}\')'
        )
        assert ev(f'!!document.querySelector(\'{overlay_selector("ovpersistb01")}\')')
        evidence["failed_remove_restored"] = True
        shot("09-failed-remove.png")
        blur_focus()
        mouse_at(overlay_selector("ovpersista01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovpersista01")}.is-selected\')')
        key("Delete")
        wait_overlay("ovpersista01", False)
        assert ev(f'!!document.querySelector(\'{overlay_selector("ovpersistb01")}\')')
        evidence["failed_remove_retry"] = True

        # Delayed failed delete A while B is selected/edited — A must return, focus stays on B.
        delayed = http_json(
            "PATCH",
            f"/api/studio/{cid}/overlays",
            {
                "overlays": [
                    _base_overlay("ovpersista01", "text", text="Persist-A", start_s=0.2, end_s=1.8),
                    _base_overlay("ovpersistb01", "circle", start_s=1.0, end_s=3.0),
                ]
            },
        )
        assert delayed and delayed.get("ok"), delayed
        reload_studio()
        wait_overlay("ovpersista01", True)
        wait_overlay("ovpersistb01", True)
        ev(
            """(() => {
              if (window.__overlayFetchWrapped) return true;
              const orig = window.fetch.bind(window);
              window.__overlayFailRemaining = 0;
              window.__overlayFailDelayMs = 0;
              window.__overlayFailHits = 0;
              window.fetch = async (input, init = {}) => {
                const url = String(typeof input === 'string' ? input : (input && input.url) || '');
                const method = String((init && init.method) || 'GET').toUpperCase();
                if (
                  window.__overlayFailRemaining > 0 &&
                  method === 'PATCH' &&
                  url.includes('/overlays')
                ) {
                  window.__overlayFailRemaining -= 1;
                  window.__overlayFailHits += 1;
                  const delay = Number(window.__overlayFailDelayMs) || 0;
                  if (delay > 0) {
                    await new Promise((resolve) => setTimeout(resolve, delay));
                  }
                  return new Response(
                    JSON.stringify({ ok: false, detail: 'forced overlay fail' }),
                    { status: 500, headers: { 'Content-Type': 'application/json' } }
                  );
                }
                return orig(input, init);
              };
              window.__overlayFetchWrapped = true;
              return true;
            })()"""
        )
        mouse_at(overlay_selector("ovpersista01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovpersista01")}.is-selected\')')
        blur_focus()
        ev("window.__overlayFailDelayMs = 900; window.__overlayFailRemaining = 1")
        key("Delete")
        # While A's PATCH is still delayed, select and edit B.
        until(f'!document.querySelector(\'{overlay_selector("ovpersista01")}\')', timeout=5)
        mouse_at(overlay_selector("ovpersistb01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovpersistb01")}.is-selected\')')
        ev(
            """(() => {
              const input = document.getElementById('overlay-end');
              if (!input) return false;
              input.value = '3.5';
              input.dispatchEvent(new Event('change', { bubbles: true }));
              return true;
            })()"""
        )
        until(
            f"""(() => {{
              const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
              const ov = JSON.parse(clip.dataset.overlays||'[]').find(o => o.id === 'ovpersistb01');
              return ov && Number(ov.end_s) >= 3.4;
            }})()"""
        )
        # After delayed failure, A returns and B's edit + selection remain.
        until(
            "!!document.getElementById('studio-flash')?.textContent && "
            f'!!document.querySelector(\'{overlay_selector("ovpersista01")}\')'
        )
        until(
            f"""(() => {{
              const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
              const list = JSON.parse(clip.dataset.overlays||'[]');
              const a = list.find(o => o.id === 'ovpersista01');
              const b = list.find(o => o.id === 'ovpersistb01');
              const selected = document.querySelector(
                '{overlay_selector("ovpersistb01")}.is-selected'
              );
              return !!a && !!b && Number(b.end_s) >= 3.4 && !!selected;
            }})()"""
        )
        evidence["delayed_remove_a_restored_while_b_focused"] = True
        shot("09b-delayed-remove-overlap.png")
        # Settled save/reopen must keep both overlays (A restored + B edit).
        time.sleep(1.0)
        reload_studio()
        wait_overlay("ovpersista01", True)
        wait_overlay("ovpersistb01", True)
        b_reopen = float(
            ev(
                f"""(() => {{
                  const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
                  const ov = JSON.parse(clip.dataset.overlays||'[]').find(o => o.id === 'ovpersistb01');
                  return ov ? Number(ov.end_s) : -1;
                }})()"""
            )
        )
        evidence["delayed_remove_reopen_keeps_both"] = b_reopen >= 3.4
        assert evidence["delayed_remove_reopen_keeps_both"], b_reopen
        shot("09c-delayed-remove-reopen.png")

        # Recreate A; fail A's timing save while B is edited — B must not roll back.
        restored = http_json(
            "PATCH",
            f"/api/studio/{cid}/overlays",
            {
                "overlays": [
                    _base_overlay("ovpersista01", "text", text="Persist-A", start_s=0.2, end_s=1.8),
                    _base_overlay("ovpersistb01", "circle", start_s=1.0, end_s=3.0),
                ]
            },
        )
        assert restored and restored.get("ok"), restored
        reload_studio()
        wait_overlay("ovpersista01", True)
        wait_overlay("ovpersistb01", True)
        # Re-wrap fetch after reload.
        ev(
            """(() => {
              if (window.__overlayFetchWrapped) return true;
              const orig = window.fetch.bind(window);
              window.__overlayFailRemaining = 0;
              window.__overlayFailDelayMs = 0;
              window.__overlayFailHits = 0;
              window.fetch = async (input, init = {}) => {
                const url = String(typeof input === 'string' ? input : (input && input.url) || '');
                const method = String((init && init.method) || 'GET').toUpperCase();
                if (
                  window.__overlayFailRemaining > 0 &&
                  method === 'PATCH' &&
                  url.includes('/overlays')
                ) {
                  window.__overlayFailRemaining -= 1;
                  window.__overlayFailHits += 1;
                  const delay = Number(window.__overlayFailDelayMs) || 0;
                  if (delay > 0) {
                    await new Promise((resolve) => setTimeout(resolve, delay));
                  }
                  return new Response(
                    JSON.stringify({ ok: false, detail: 'forced overlay fail' }),
                    { status: 500, headers: { 'Content-Type': 'application/json' } }
                  );
                }
                return orig(input, init);
              };
              window.__overlayFetchWrapped = true;
              return true;
            })()"""
        )
        ev("window.__overlayFailRemaining = 1")
        mouse_at(overlay_selector("ovpersista01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovpersista01")}.is-selected\')')
        edge = ev(
            f"""(() => {{
              const edge = document.querySelector(
                '{overlay_selector("ovpersista01")} .studio-effect-edge-out'
              );
              if (!edge) return null;
              edge.scrollIntoView({{block:'center', inline:'nearest'}});
              const r = edge.getBoundingClientRect();
              return {{x: r.x + r.width / 2, y: r.y + r.height / 2}};
            }})()"""
        )
        assert edge
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": edge["x"],
                "y": edge["y"],
                "button": "none",
                "buttons": 0,
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": edge["x"],
                "y": edge["y"],
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
                "pointerType": "mouse",
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": edge["x"] - 35,
                "y": edge["y"],
                "button": "left",
                "buttons": 1,
            },
        )
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": edge["x"] - 35,
                "y": edge["y"],
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
                "pointerType": "mouse",
            },
        )
        # Immediately edit sibling B so a newer clip revision exists before rollback.
        mouse_at(overlay_selector("ovpersistb01"), button="left")
        until(f'!!document.querySelector(\'{overlay_selector("ovpersistb01")}.is-selected\')')
        ev(
            """(() => {
              const input = document.getElementById('overlay-end');
              if (!input) return false;
              input.value = '3.5';
              input.dispatchEvent(new Event('change', { bubbles: true }));
              return true;
            })()"""
        )
        until(
            f"""(() => {{
              const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
              const ov = JSON.parse(clip.dataset.overlays||'[]').find(o => o.id === 'ovpersistb01');
              return ov && Number(ov.end_s) >= 3.4;
            }})()"""
        )
        time.sleep(0.8)
        b_end = float(
            ev(
                f"""(() => {{
                  const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
                  const ov = JSON.parse(clip.dataset.overlays||'[]').find(o => o.id === 'ovpersistb01');
                  return ov ? Number(ov.end_s) : -1;
                }})()"""
            )
        )
        a_present = bool(ev(f'!!document.querySelector(\'{overlay_selector("ovpersista01")}\')'))
        evidence["sibling_edit_survives_failed_drag"] = b_end >= 3.4 and a_present
        assert evidence["sibling_edit_survives_failed_drag"], (b_end, a_present)
        evidence["overlay_fail_hits"] = int(ev("Number(window.__overlayFailHits||0)") or 0)
        shot("10-sibling-survives-failed-drag.png")

        # Two-overlay Save/Reopen persistence.
        settled = http_json(
            "PATCH",
            f"/api/studio/{cid}/overlays",
            {
                "overlays": [
                    _base_overlay("ovpersista01", "text", text="Persist-A", start_s=0.2, end_s=1.5),
                    _base_overlay("ovpersistb01", "circle", start_s=1.0, end_s=2.8),
                ]
            },
        )
        assert settled and settled.get("ok"), settled
        reload_studio()
        wait_overlay("ovpersista01", True)
        wait_overlay("ovpersistb01", True)
        ids = ev(
            f"""(() => {{
              const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
              return JSON.parse(clip.dataset.overlays||'[]').map(o => o.id);
            }})()"""
        )
        evidence["two_overlay_reopen"] = ids == ["ovpersista01", "ovpersistb01"] or set(ids) == {
            "ovpersista01",
            "ovpersistb01",
        }
        assert evidence["two_overlay_reopen"], ids
        shot("11-two-overlay-reopen.png")

        cleared = http_json("PATCH", f"/api/studio/{cid}/overlays", {"overlays": []})
        assert cleared and cleared.get("ok"), cleared
        reload_studio()
        assert not ev('!!document.querySelector(\'.studio-effect-bar[data-kind="overlay"]\')')
        evidence["reopen_without_overlay_bars"] = True
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original
        assert hashlib.sha256(source_b.read_bytes()).hexdigest() == original_b
        evidence["originals_unchanged"] = True
        evidence["status"] = "PASS"
        shot("12-cleared-reopen.png")
    except Exception:
        if cdp:
            evidence["failure_context"] = ev(
                f"""({{
                  errors: window.__overlayErrors,
                  flash: document.getElementById('studio-flash')?.textContent,
                  menu: document.getElementById('studio-clip-menu')?.outerHTML,
                  bars: [...document.querySelectorAll('.studio-effect-bar')].map((el) => el.outerHTML),
                  tab: document.getElementById('inspector-clip')?.dataset.tab,
                  overlays: JSON.parse(
                    document.querySelector('#studio-grid [data-studio-id="{cid}"]')?.dataset.overlays || '[]'
                  ),
                  clipCount: document.querySelectorAll('#studio-grid [data-studio-id]').length
                }})"""
            )
            shot("failure.png")
        raise
    finally:
        (out / "evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        stop()
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    run(args.output_dir.resolve())
