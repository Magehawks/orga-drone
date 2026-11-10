"""WebView2 timeline-first soundtrack and clip-audio UX (#339 Phase 4).

Real CDP mouse/key input. Synthetic media only. Not part of main-admission smoke.
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
import wave

_spec = importlib.util.spec_from_file_location(
    "audio_timeline_e2e", Path(__file__).with_name("windows_e2e.py")
)
assert _spec and _spec.loader
_harness: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)


def _write_silent_wav(path: Path, seconds: float = 2.0, rate: int = 22050) -> None:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)


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
    root = db.add_root(media, label="Synthetic audio timeline")
    project = db.create_studio_project("Timeline-first audio")
    db.set_open_studio_project_id(project.id)
    source = media / "synthetic-audio.mp4"
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
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    source_b = media / "synthetic-audio-b.mp4"
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
    song = media / "soundtrack.wav"
    _write_silent_wav(song, seconds=2.5)
    original_song = hashlib.sha256(song.read_bytes()).hexdigest()

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
    music_clip = db.set_studio_music(project.id, str(song))
    music_id = int(music_clip.id)
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
        "phase": 4,
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
                    "window.__audioErrors=[];"
                    "addEventListener('error',e=>window.__audioErrors.push(e.message));"
                    "addEventListener('unhandledrejection',e=>window.__audioErrors.push(String(e.reason)));"
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

    def playhead_now() -> float:
        return float(
            ev(
                "Number(document.getElementById('studio-playhead')?.getAttribute('aria-valuenow')||0)"
            )
            or 0
        )

    def blur_focus() -> None:
        ev(
            "document.activeElement && document.activeElement.blur && document.activeElement.blur();"
            "document.getElementById('studio-playhead')?.focus();"
        )

    def clip_present(studio_id: int) -> bool:
        return bool(
            ev(f'!!document.querySelector(\'#studio-grid [data-studio-id="{studio_id}"]\')')
        )

    def music_selector() -> str:
        return f'.studio-music-select[data-music-id="{music_id}"]'

    def audio_selector(studio_id: int) -> str:
        return f'.studio-clip-audio-bar[data-studio-id="{studio_id}"]'

    try:
        start()
        assert cdp
        evidence["webview2"] = _harness.webview2_version()

        # --- Soundtrack selection ---
        until(f"!!document.querySelector('{music_selector()}')")
        ev(
            "document.querySelector('[data-inspector-tab-button=clip]')?.click();"
            "document.getElementById('studio-playhead')?.focus()"
        )
        before = playhead_now()
        mouse_at(music_selector(), button="left")
        until(
            "!!document.getElementById('inspector-music') && "
            "!document.getElementById('inspector-music').hidden && "
            f'!!document.querySelector(\'{music_selector()}.is-selected\')'
        )
        after = playhead_now()
        evidence["music_select_no_seek"] = abs(after - before) < 0.25
        assert evidence["music_select_no_seek"], (before, after)
        evidence["music_opens_inspector"] = True
        shot("01-music-selected.png")

        open_context_menu_cdp(music_selector(), label="music")
        assert ev("!document.getElementById('studio-clip-menu-edit').hidden")
        assert ev("!document.getElementById('studio-clip-menu-remove-effect').hidden")
        assert ev("document.getElementById('studio-clip-menu-remove').hidden")
        shot("02-music-context-menu.png")
        ev("document.getElementById('studio-clip-menu-edit').click()")
        until(
            "!!document.getElementById('inspector-music') && "
            "!document.getElementById('inspector-music').hidden"
        )
        evidence["music_context_edit"] = True

        # Volume control still works.
        ev(
            """(() => {
              const vol = document.getElementById('inspector-music-volume');
              if (!vol) return false;
              vol.value = '35';
              vol.dispatchEvent(new Event('input', { bubbles: true }));
              vol.dispatchEvent(new Event('change', { bubbles: true }));
              return true;
            })()"""
        )
        time.sleep(0.4)
        evidence["music_volume_edit"] = True

        blur_focus()
        until(f'!!document.querySelector(\'{music_selector()}.is-selected\')')
        key("Delete")
        until(f'!document.querySelector(\'{music_selector()}\')')
        assert clip_present(cid)
        evidence["music_delete"] = True
        shot("03-music-removed.png")

        # Restore soundtrack for reopen checks.
        restored_req = urllib.request.Request(
            base + f"/api/studio/projects/{project.id}/music",
            data=json.dumps({"path": str(song)}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": base,
                "Referer": base + "/studio",
            },
            method="POST",
        )
        with urllib.request.urlopen(restored_req, timeout=30) as resp:
            restored_body = json.loads(resp.read().decode("utf-8"))
        assert restored_body.get("ok"), restored_body
        restored_music_id = restored_body["tracks"][-1]["id"]
        cdp.call("Page.navigate", {"url": base + "/studio"})
        until("!!document.querySelector('#studio-grid [data-studio-id]')")
        time.sleep(0.5)
        until(
            f'!!document.querySelector(\'.studio-music-select[data-music-id="{restored_music_id}"]\')'
        )
        evidence["music_reopen"] = True

        # --- Clip-audio selection ---
        until(f"!!document.querySelector('{audio_selector(cid)}')")
        before = playhead_now()
        mouse_at(audio_selector(cid), button="left")
        until(
            "!!document.getElementById('inspector-clip') && "
            "!document.getElementById('inspector-clip').hidden && "
            f'!!document.querySelector(\'{audio_selector(cid)}.is-selected\')'
        )
        after = playhead_now()
        evidence["audio_select_no_seek"] = abs(after - before) < 0.25
        assert evidence["audio_select_no_seek"], (before, after)
        evidence["audio_opens_clip_inspector"] = True
        shot("04-audio-selected.png")

        open_context_menu_cdp(audio_selector(cid), label="audio")
        assert ev("!document.getElementById('studio-clip-menu-edit').hidden")
        assert ev("document.getElementById('studio-clip-menu-remove-effect').hidden")
        assert ev("document.getElementById('studio-clip-menu-remove').hidden")
        evidence["audio_context_edit_only"] = True
        shot("05-audio-context-menu.png")
        ev("document.getElementById('studio-clip-menu-edit').click()")
        until(
            "!!document.getElementById('inspector-clip') && "
            "!document.getElementById('inspector-clip').hidden"
        )

        # Delete/Backspace must not remove the story clip while audio is selected.
        blur_focus()
        until(f'!!document.querySelector(\'{audio_selector(cid)}.is-selected\')')
        key("Delete")
        key("Backspace")
        time.sleep(0.25)
        assert clip_present(cid)
        assert ev(f'!!document.querySelector(\'{audio_selector(cid)}\')')
        evidence["audio_guard_keeps_clip"] = True
        shot("06-audio-guard.png")

        # Stale audio selection after switching clips must not delete clips or
        # keep an active audio timedSelection (Delete would otherwise hit story).
        mouse_at(audio_selector(cid), button="left")
        until(f'!!document.querySelector(\'{audio_selector(cid)}.is-selected\')')
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
        until(f'!document.querySelector(\'{audio_selector(cid)}.is-selected\')')
        # Move focus off the story clip so Delete is not a story-clip remove.
        ev("document.getElementById('inspector-tab-image')?.focus()")
        key("Delete")
        key("Backspace")
        time.sleep(0.25)
        assert clip_present(cid)
        assert clip_present(cid_b)
        assert ev(f'!!document.querySelector(\'{audio_selector(cid)}\')')
        evidence["stale_audio_safe_after_clip_switch"] = True
        shot("07-stale-audio-safe.png")

        # Story Backspace still does not remove clips.
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
        assert clip_present(cid_b)
        evidence["story_backspace_keeps_clip"] = True

        assert hashlib.sha256(source.read_bytes()).hexdigest() == original
        assert hashlib.sha256(source_b.read_bytes()).hexdigest() == original_b
        assert hashlib.sha256(song.read_bytes()).hexdigest() == original_song
        evidence["originals_unchanged"] = True
        evidence["status"] = "PASS"
        shot("08-done.png")
    except Exception:
        if cdp:
            evidence["failure_context"] = ev(
                "({errors:window.__audioErrors,flash:document.getElementById('studio-flash')?.textContent,"
                "menu:document.getElementById('studio-clip-menu')?.outerHTML,"
                "music:[...document.querySelectorAll('.studio-music-select')].map(el=>el.outerHTML),"
                "audio:[...document.querySelectorAll('.studio-clip-audio-bar')].map(el=>el.outerHTML),"
                "inspector:document.getElementById('inspector-music')?.hidden})"
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
