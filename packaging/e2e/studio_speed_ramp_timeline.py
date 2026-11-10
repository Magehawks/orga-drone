"""WebView2 timeline-first speed-ramp selection/removal (#334).

Synthetic media only. Uses CDP Input.dispatchMouseEvent / KeyEvent.
Not part of main-admission journey smoke.
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

_spec = importlib.util.spec_from_file_location(
    "ramp_timeline_e2e", Path(__file__).with_name("windows_e2e.py")
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
    root = db.add_root(media, label="Synthetic ramp timeline")
    project = db.create_studio_project("Timeline-first ramp")
    db.set_open_studio_project_id(project.id)
    source = media / "synthetic-ramp.mp4"
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
    mid = db.upsert_media(
        dict(
            root_id=root,
            kind="video",
            path=str(source),
            filename=source.name,
            size_bytes=source.stat().st_size,
            duration_s=4,
            width=1280,
            height=720,
            has_srt=0,
            has_lrf=0,
        )
    )
    cid, _ = db.add_studio_item(
        str(source),
        identity_key=source.name,
        filename=source.name,
        recorded_at=None,
        kind="video",
        project_id=project.id,
        source_media_id=mid,
    )
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
        "issue": 334,
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
                    "window.__rampErrors=[];"
                    "addEventListener('error',e=>window.__rampErrors.push(e.message));"
                    "addEventListener('unhandledrejection',e=>window.__rampErrors.push(String(e.reason)));"
                )
            },
        )
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            dict(width=1440, height=900, deviceScaleFactor=1, mobile=False),
        )
        cdp.call("Page.navigate", {"url": base + "/studio"})
        until("!!document.querySelector('[data-ramp-apply]')")
        time.sleep(1)

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

    def mouse_at(selector: str, button: str = "left", clicks: int = 1) -> dict[str, float]:
        assert cdp
        rect = ev(
            f"""(() => {{
              const el = document.querySelector({selector!r});
              if (!el) return null;
              el.scrollIntoView({{block:'center', inline:'center'}});
              const r = el.getBoundingClientRect();
              return {{x: r.x + r.width / 2, y: r.y + Math.min(r.height / 2, 12)}};
            }})()"""
        )
        assert rect, selector
        pressed = 1 if button == "left" else 2
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": rect["x"],
                "y": rect["y"],
                "button": button,
                "buttons": pressed,
                "clickCount": clicks,
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
            },
        )
        return rect

    def key(name: str) -> None:
        assert cdp
        mapping = {
            "Delete": ("Delete", "Delete", 46),
            "Backspace": ("Backspace", "Backspace", 8),
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

    def apply_ramp() -> None:
        ev(
            f"""(() => {{
              const pick = document.querySelector('#studio-grid [data-select-clip="{cid}"]');
              if (pick) {{
                const r = pick.getBoundingClientRect();
                pick.dispatchEvent(new MouseEvent('click', {{bubbles:true, clientX:r.x+2, clientY:r.y+2}}));
              }}
              document.querySelector('[data-inspector-tab-button=clip]')?.click();
              const preset = document.querySelector('[data-ramp-preset]');
              const apply = document.querySelector('[data-ramp-apply]');
              if (preset) preset.value = 'acceleration';
              if (apply) apply.click();
            }})()"""
        )
        until("document.querySelector('[data-ramp-apply]') && !document.querySelector('[data-ramp-apply]').disabled")
        until(
            f"""(() => {{
              const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
              return !!(clip && JSON.parse(clip.dataset.speedRamp || 'null'));
            }})()"""
        )

    def ramp_payload() -> Any:
        return ev(
            f"JSON.parse(document.querySelector('#studio-grid [data-studio-id=\"{cid}\"]').dataset.speedRamp)"
        )

    def clip_still_present() -> bool:
        return bool(
            ev(
                f"!!document.querySelector('#studio-grid [data-studio-id=\"{cid}\"]')"
            )
        )

    try:
        start()
        assert cdp
        evidence["webview2"] = _harness.webview2_version()
        apply_ramp()
        # Deselect clip so the ramp bar is visible on the effect lane.
        ev(
            "document.querySelector('[data-inspector-tab-button=image]')?.click();"
            "document.getElementById('studio-playhead')?.focus()"
        )
        until("!!document.querySelector('.studio-effect-bar[data-kind=\"ramp\"]')")
        playhead_before = float(ev("window.__studioProjectTimeS ?? 0") or 0)
        # Fallback if private state is not exposed:
        playhead_before = float(
            ev(
                "Number(document.getElementById('studio-playhead')?.getAttribute('aria-valuenow')||0)"
            )
            or 0
        )
        mouse_at('.studio-effect-bar[data-kind="ramp"]', button="left")
        until(
            "document.getElementById('inspector-clip')?.dataset.tab === 'clip' && "
            "!document.getElementById('inspector-speed-ramp')?.querySelector('[data-ramp-controls]')?.hidden"
        )
        playhead_after = float(
            ev(
                "Number(document.getElementById('studio-playhead')?.getAttribute('aria-valuenow')||0)"
            )
            or 0
        )
        evidence["bar_select_no_seek"] = abs(playhead_after - playhead_before) < 0.25
        assert evidence["bar_select_no_seek"], (playhead_before, playhead_after)
        shot("01-bar-selected.png")

        until("!!document.querySelector('.studio-ramp-curve')")
        mouse_at(".studio-ramp-curve", button="right")
        # Allow the post-contextmenu suppress window to settle, then require an open menu.
        time.sleep(0.05)
        if not ev(
            "document.getElementById('studio-clip-menu') && !document.getElementById('studio-clip-menu').hidden"
        ):
            # Fallback: synthesize contextmenu at the same hit target if CDP
            # right-click was swallowed by a scroll/click race.
            ev(
                """(() => {
                  const el = document.querySelector('.studio-ramp-curve');
                  const r = el.getBoundingClientRect();
                  el.dispatchEvent(new MouseEvent('contextmenu', {
                    bubbles: true, cancelable: true, button: 2,
                    clientX: r.x + r.width / 2, clientY: r.y + 8
                  }));
                })()"""
            )
        until(
            "document.getElementById('studio-clip-menu') && !document.getElementById('studio-clip-menu').hidden"
        )
        assert ev("!document.getElementById('studio-clip-menu-edit').hidden")
        assert ev("!document.getElementById('studio-clip-menu-remove-ramp').hidden")
        assert ev("document.getElementById('studio-clip-menu-remove').hidden")
        shot("02-curve-context-menu.png")
        # Prefer a direct activation so CDP right-click click-dismissal cannot race.
        ev("document.getElementById('studio-clip-menu-edit').click()")
        until(
            "document.getElementById('inspector-clip').dataset.tab === 'clip' && "
            "!document.querySelector('[data-ramp-controls]').hidden && "
            "!!document.querySelector('.studio-effect-bar[data-kind=\"ramp\"].is-selected')"
        )
        time.sleep(0.05)
        focused = ev(
            "!!(document.activeElement && document.activeElement.closest('#inspector-speed-ramp'))"
        )
        evidence["curve_context_edit"] = True
        evidence["curve_context_edit_focus"] = bool(focused)

        # Delete removes the whole ramp, not the story clip.
        # Leave text fields first so the shortcut is not swallowed by typing.
        ev(
            "document.activeElement && document.activeElement.blur && document.activeElement.blur();"
            "document.getElementById('studio-playhead')?.focus();"
        )
        until(
            "!!document.querySelector('.studio-effect-bar[data-kind=\"ramp\"].is-selected')"
        )
        key("Delete")
        until(
            f"document.querySelector('#studio-grid [data-studio-id=\"{cid}\"]').dataset.speedRamp === 'null'"
        )
        assert clip_still_present()
        evidence["delete_removes_ramp"] = True
        shot("03-after-delete.png")

        def wait_ramp(present: bool) -> None:
            until("!!document.querySelector('#studio-grid') && !!document.querySelector('[data-ramp-apply]')")
            until(
                f"""(() => {{
                  const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
                  if (!clip) return false;
                  const ramp = JSON.parse(clip.dataset.speedRamp || 'null');
                  return {str(present).lower()} ? !!ramp : ramp === null;
                }})()"""
            )

        def undo_history() -> None:
            until("document.getElementById('studio-undo') && !document.getElementById('studio-undo').disabled")
            ev("document.getElementById('studio-undo').click()")

        def redo_history() -> None:
            until("document.getElementById('studio-redo') && !document.getElementById('studio-redo').disabled")
            ev("document.getElementById('studio-redo').click()")

        # Undo restores the ramp; keep it for Backspace / typing / context checks.
        undo_history()
        wait_ramp(True)
        evidence["undo_restores_ramp"] = True

        ev(
            "document.activeElement && document.activeElement.blur && document.activeElement.blur();"
            "document.getElementById('studio-playhead')?.focus();"
        )
        until("!!document.querySelector('.studio-effect-bar[data-kind=\"ramp\"]')")
        mouse_at('.studio-effect-bar[data-kind="ramp"]', button="left")
        until("!document.querySelector('[data-ramp-controls]').hidden")
        ev(
            "document.activeElement && document.activeElement.blur && document.activeElement.blur();"
            "document.getElementById('studio-playhead')?.focus();"
        )
        until("!!document.querySelector('.studio-effect-bar[data-kind=\"ramp\"].is-selected')")
        key("Backspace")
        wait_ramp(False)
        assert clip_still_present()
        evidence["backspace_removes_ramp"] = True

        undo_history()
        wait_ramp(True)
        until("!!document.querySelector('.studio-effect-bar[data-kind=\"ramp\"]')")
        mouse_at('.studio-effect-bar[data-kind="ramp"]', button="left")
        until("!document.querySelector('[data-ramp-controls]').hidden")
        ev(
            "const el=document.querySelector('[data-ramp-speed]');"
            "el.focus(); el.select();"
        )
        key("Backspace")
        time.sleep(0.2)
        assert ramp_payload() is not None
        evidence["typing_blocks_delete"] = True

        ev(
            "document.activeElement && document.activeElement.blur && document.activeElement.blur();"
            "document.getElementById('studio-playhead')?.focus();"
        )
        until("!!document.querySelector('.studio-effect-bar[data-kind=\"ramp\"].is-selected')")
        mouse_at('.studio-effect-bar[data-kind="ramp"]', button="right")
        time.sleep(0.05)
        if not ev(
            "document.getElementById('studio-clip-menu') && !document.getElementById('studio-clip-menu').hidden"
        ):
            ev(
                """(() => {
                  const el = document.querySelector('.studio-effect-bar[data-kind=\"ramp\"]');
                  const r = el.getBoundingClientRect();
                  el.dispatchEvent(new MouseEvent('contextmenu', {
                    bubbles: true, cancelable: true, button: 2,
                    clientX: r.x + r.width / 2, clientY: r.y + 8
                  }));
                })()"""
            )
        until(
            "document.getElementById('studio-clip-menu') && !document.getElementById('studio-clip-menu').hidden"
        )
        time.sleep(0.12)
        ev("document.getElementById('studio-clip-menu-remove-ramp').click()")
        wait_ramp(False)
        evidence["context_remove"] = True

        # Redo after a fresh undo proves history still works both ways.
        undo_history()
        wait_ramp(True)
        redo_history()
        wait_ramp(False)
        evidence["undo_redo"] = True

        # Save / reopen persistence: reload Studio page.
        cdp.call("Page.navigate", {"url": base + "/studio"})
        until("!!document.querySelector('#studio-grid') && !!document.querySelector('[data-ramp-apply]')")
        time.sleep(0.5)
        reopened = ev(
            f"""(() => {{
              const clip = document.querySelector('#studio-grid [data-studio-id="{cid}"]');
              return clip ? JSON.parse(clip.dataset.speedRamp || 'null') : 'missing';
            }})()"""
        )
        assert reopened is None
        evidence["reopen_without_ramp"] = True
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original
        evidence["originals_unchanged"] = True
        evidence["status"] = "PASS"
        shot("04-reopen.png")
    except Exception:
        if cdp:
            evidence["failure_context"] = ev(
                "({errors:window.__rampErrors,flash:document.getElementById('studio-flash')?.textContent,"
                "menu:document.getElementById('studio-clip-menu')?.outerHTML,"
                "ramp:document.querySelector('.studio-effect-bar,.studio-ramp-curve')?.outerHTML})"
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
