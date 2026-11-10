"""WebView2 timeline-first effect-bar selection/removal (#339 Phase 2).

Covers zoom, mask, slow-motion and color-change bars with real CDP mouse/key
input. Synthetic media only. Not part of main-admission journey smoke.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request

_spec = importlib.util.spec_from_file_location(
    "effect_bars_timeline_e2e", Path(__file__).with_name("windows_e2e.py")
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
    root = db.add_root(media, label="Synthetic effect bars")
    project = db.create_studio_project("Timeline-first effect bars")
    db.set_open_studio_project_id(project.id)
    source = media / "synthetic-effects.mp4"
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
    source_b = media / "synthetic-effects-b.mp4"
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
        "phase": 2,
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
                    "window.__effectErrors=[];"
                    "addEventListener('error',e=>window.__effectErrors.push(e.message));"
                    "addEventListener('unhandledrejection',e=>window.__effectErrors.push(String(e.reason)));"
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

    def http_json(method: str, path: str, body: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode("utf-8"),
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

    def wait_bar(kind: str, present: bool = True) -> None:
        until(
            f"""(() => {{
              const el = document.querySelector('.studio-effect-bar[data-kind="{kind}"]');
              return {str(present).lower()} ? !!el : !el;
            }})()"""
        )

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

    try:
        start()
        assert cdp
        evidence["webview2"] = _harness.webview2_version()

        # --- Zoom ---
        zoomed = http_json(
            "PATCH", f"/api/studio/{cid}/frame", {"zoom_start": 2.0, "zoom_end": 2.0}
        )
        assert zoomed and zoomed.get("ok"), zoomed
        reload_studio()
        wait_bar("zoom", True)
        ev(
            "document.querySelector('[data-inspector-tab-button=clip]')?.click();"
            "document.getElementById('studio-playhead')?.focus()"
        )
        before = playhead_now()
        mouse_at('.studio-effect-bar[data-kind="zoom"]', button="left")
        until(
            "document.getElementById('inspector-clip')?.dataset.tab === 'image' && "
            "!!document.querySelector('.studio-effect-bar[data-kind=\"zoom\"].is-selected')"
        )
        after = playhead_now()
        evidence["zoom_select_no_seek"] = abs(after - before) < 0.25
        assert evidence["zoom_select_no_seek"], (before, after)
        shot("01-zoom-selected.png")

        open_context_menu_cdp('.studio-effect-bar[data-kind="zoom"]', label="zoom")
        assert ev("!document.getElementById('studio-clip-menu-edit').hidden")
        assert ev("!document.getElementById('studio-clip-menu-remove-effect').hidden")
        assert ev("document.getElementById('studio-clip-menu-remove').hidden")
        shot("02-zoom-context-menu.png")
        ev("document.getElementById('studio-clip-menu-edit').click()")
        until("document.getElementById('inspector-clip')?.dataset.tab === 'image'")
        evidence["zoom_context_edit"] = True

        blur_focus()
        until("!!document.querySelector('.studio-effect-bar[data-kind=\"zoom\"].is-selected')")
        # Edge drag must remain functional.
        edge = ev(
            """(() => {
              const edge = document.querySelector(
                '.studio-effect-bar[data-kind="zoom"] .studio-effect-edge-out'
              );
              if (!edge) return null;
              edge.scrollIntoView({block:'center', inline:'nearest'});
              const r = edge.getBoundingClientRect();
              return {x: r.x + r.width / 2, y: r.y + r.height / 2};
            })()"""
        )
        assert edge
        width_before = float(
            ev(
                "Number.parseFloat(document.querySelector('.studio-effect-bar[data-kind=\"zoom\"]').style.width)||0"
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
        time.sleep(0.4)
        width_after = float(
            ev(
                "Number.parseFloat(document.querySelector('.studio-effect-bar[data-kind=\"zoom\"]').style.width)||0"
            )
        )
        evidence["zoom_edge_resize"] = width_after < width_before - 5
        assert evidence["zoom_edge_resize"], (width_before, width_after)
        shot("03-zoom-resized.png")

        blur_focus()
        mouse_at('.studio-effect-bar[data-kind="zoom"]', button="left")
        until("!!document.querySelector('.studio-effect-bar[data-kind=\"zoom\"].is-selected')")
        key("Delete")
        wait_bar("zoom", False)
        assert clip_present()
        # Zoom removal resets framing to neutral.
        frame = ev(
            f"JSON.parse(document.querySelector('#studio-grid [data-studio-id=\"{cid}\"]').dataset.frame||'{{}}')"
        )
        evidence["zoom_delete_resets_frame"] = (
            float(frame.get("zoom_start") or 1) <= 1.001
            and float(frame.get("zoom_end") or 1) <= 1.001
        )
        assert evidence["zoom_delete_resets_frame"], frame
        shot("04-zoom-removed.png")

        undo_history()
        wait_bar("zoom", True)
        evidence["zoom_undo"] = True
        blur_focus()
        mouse_at('.studio-effect-bar[data-kind="zoom"]', button="left")
        until("!!document.querySelector('.studio-effect-bar[data-kind=\"zoom\"].is-selected')")
        key("Backspace")
        wait_bar("zoom", False)
        assert clip_present()
        evidence["zoom_backspace"] = True
        undo_history()
        wait_bar("zoom", True)
        redo_history()
        wait_bar("zoom", False)
        evidence["zoom_redo"] = True

        # --- Stale selection across ordinary clip switch ---
        zoomed_again = http_json(
            "PATCH", f"/api/studio/{cid}/frame", {"zoom_start": 1.8, "zoom_end": 1.8}
        )
        assert zoomed_again and zoomed_again.get("ok"), zoomed_again
        reload_studio()
        wait_bar("zoom", True)
        mouse_at(
            f'.studio-effect-bar[data-kind="zoom"][data-studio-id="{cid}"]',
            button="left",
        )
        until(
            f'!!document.querySelector(\'.studio-effect-bar[data-kind="zoom"][data-studio-id="{cid}"].is-selected\')'
        )
        # Ordinary Story-Clip B selection must invalidate the timed effect on A.
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
            f'!document.querySelector(\'.studio-effect-bar[data-kind="zoom"][data-studio-id="{cid}"].is-selected\')'
        )
        # Focus outside story-delete context so Delete must not remove clip B either.
        ev("document.getElementById('inspector-tab-image')?.focus()")
        key("Delete")
        key("Backspace")
        time.sleep(0.25)
        assert ev(
            f'!!document.querySelector(\'.studio-effect-bar[data-kind="zoom"][data-studio-id="{cid}"]\')'
        )
        assert clip_present()
        assert bool(
            ev(f'!!document.querySelector(\'#studio-grid [data-studio-id="{cid_b}"]\')')
        )
        evidence["stale_selection_safe_after_clip_switch"] = True
        shot("04b-stale-selection-safe.png")

        # Correctly selected effects can still be deleted.
        mouse_at(
            f'.studio-effect-bar[data-kind="zoom"][data-studio-id="{cid}"]',
            button="left",
        )
        until(
            f'!!document.querySelector(\'.studio-effect-bar[data-kind="zoom"][data-studio-id="{cid}"].is-selected\')'
        )
        blur_focus()
        key("Delete")
        wait_bar("zoom", False)
        evidence["selected_effect_still_deletable"] = True

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

        # --- Mask ---
        masked = http_json(
            "PATCH",
            f"/api/studio/{cid}/masks",
            {
                "masks": [
                    {
                        "id": "mask-e2e",
                        "effect": "blur",
                        "strength": 40,
                        "x": 0.2,
                        "y": 0.2,
                        "w": 0.3,
                        "h": 0.25,
                        "start_s": 0.5,
                        "end_s": 3.0,
                    }
                ]
            },
        )
        assert masked and masked.get("ok"), masked
        reload_studio()
        wait_bar("mask", True)
        mouse_at('.studio-effect-bar[data-kind="mask"]', button="left")
        until(
            "document.getElementById('inspector-clip')?.dataset.tab === 'effects' && "
            "!!document.querySelector('.studio-effect-bar[data-kind=\"mask\"].is-selected')"
        )
        evidence["mask_select_tab"] = True
        shot("05-mask-selected.png")
        open_context_menu_cdp('.studio-effect-bar[data-kind="mask"]', label="mask")
        ev("document.getElementById('studio-clip-menu-remove-effect').click()")
        wait_bar("mask", False)
        assert clip_present()
        evidence["mask_context_remove"] = True

        # --- Slow motion ---
        slowed = http_json(
            "POST",
            f"/api/studio/{cid}/speed",
            {"speed": 0.5, "range_in_s": 0.5, "range_out_s": 2.5},
        )
        assert slowed and slowed.get("ok"), slowed
        reload_studio()
        wait_bar("slow", True)
        mouse_at('.studio-effect-bar[data-kind="slow"]', button="left")
        until(
            "document.getElementById('inspector-clip')?.dataset.tab === 'clip' && "
            "!!document.querySelector('.studio-effect-bar[data-kind=\"slow\"].is-selected')"
        )
        evidence["slow_select_tab"] = True
        shot("06-slow-selected.png")
        blur_focus()
        key("Delete")
        wait_bar("slow", False)
        assert clip_present()
        evidence["slow_delete"] = True

        # --- Color change ---
        colored = http_json(
            "PATCH",
            f"/api/studio/{cid}/color-animation",
            {"preset_id": "warm_up", "bar": {"start_s": 0.5, "end_s": 3.0}},
        )
        assert colored and colored.get("ok"), colored
        reload_studio()
        wait_bar("color", True)
        mouse_at('.studio-effect-bar[data-kind="color"]', button="left")
        until(
            "document.getElementById('inspector-clip')?.dataset.tab === 'effects' && "
            "!!document.querySelector('.studio-effect-bar[data-kind=\"color\"].is-selected')"
        )
        evidence["color_select_tab"] = True
        shot("07-color-selected.png")
        open_context_menu_cdp('.studio-effect-bar[data-kind="color"]', label="color")
        ev("document.getElementById('studio-clip-menu-remove-effect').click()")
        wait_bar("color", False)
        assert clip_present()
        evidence["color_context_remove"] = True

        reload_studio()
        assert not ev(
            "!!document.querySelector('.studio-effect-bar[data-kind=\"color\"],"
            ".studio-effect-bar[data-kind=\"zoom\"],.studio-effect-bar[data-kind=\"slow\"],"
            ".studio-effect-bar[data-kind=\"mask\"]')"
        )
        evidence["reopen_without_effect_bars"] = True
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original
        assert hashlib.sha256(source_b.read_bytes()).hexdigest() == original_b
        evidence["originals_unchanged"] = True
        evidence["status"] = "PASS"
        shot("08-reopen.png")
    except Exception:
        if cdp:
            evidence["failure_context"] = ev(
                "({errors:window.__effectErrors,flash:document.getElementById('studio-flash')?.textContent,"
                "menu:document.getElementById('studio-clip-menu')?.outerHTML,"
                "bars:[...document.querySelectorAll('.studio-effect-bar')].map(el=>el.outerHTML)})"
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
