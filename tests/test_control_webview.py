"""Opt-in Windows/WebView2 bridge smoke using an isolated synthetic library.

Run: $env:ORGA_DRONE_CONTROL_WEBVIEW_E2E='1'; python -m pytest tests/test_control_webview.py
The child owns its app, media, key, window and temporary data; no user library opens.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("ORGA_DRONE_CONTROL_WEBVIEW_E2E") != "1",
    reason="Opt-in Windows desktop/WebView2 session required",
)
def test_control_webview_smoke():
    result = subprocess.run(
        [sys.executable, "-m", "tests.test_control_webview"],
        capture_output=True,
        text=True,
        timeout=100,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CONTROL_WEBVIEW_SMOKE_OK" in result.stdout


def _run_smoke() -> None:
    import hashlib
    import json
    import secrets
    import socket
    import tempfile
    import threading
    import time
    import urllib.error
    import urllib.request
    from pathlib import Path

    import uvicorn
    import webview
    import orga_drone.app as app_module
    from orga_drone.config import Settings
    from orga_drone.ffmpeg_bin import find_ffmpeg
    from orga_drone.lut_library import import_lut_bytes
    from tests.test_studio_history import _seed

    def wait(check, label):
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline:
            result = check()
            if result:
                return result
            time.sleep(0.1)
        raise AssertionError("Timed out: " + label)

    with tempfile.TemporaryDirectory(prefix="orga-control-webview-") as folder:
        base = Path(folder)
        app_module.settings = Settings(data_dir=base / "data")
        app = app_module.create_app()
        db = app.state.db
        clip_a = _seed(db, base / "synthetic", "A.MP4", 3)
        pid = db.list_studio_items()[0].project_id
        clip_b = _seed(db, base / "synthetic", "B.MP4", 3, project_id=pid)
        for filename in ("A.MP4", "B.MP4"):
            subprocess.run(
                [
                    find_ffmpeg(),
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=320x180:rate=30",
                    "-t",
                    "3",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(base / "synthetic" / filename),
                ],
                check=True,
                capture_output=True,
            )
        source_hashes = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (base / "synthetic").iterdir()
        }
        lut = import_lut_bytes(
            db,
            base / "data",
            b"LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n",
            source_label="synthetic identity.cube",
        ).entry.asset_name
        observed = {}
        original_poll = app.state.control.poll

        def observe_poll(payload):
            observed.update(payload)
            return original_poll(payload)

        app.state.control.poll = observe_poll
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen(128)
        origin = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", access_log=False)
        )
        thread = threading.Thread(
            target=lambda: server.run(sockets=[listener]), daemon=True
        )
        thread.start()
        wait(lambda: server.started, "server startup")
        key = secrets.token_hex(32)

        def request(path, payload=None, authenticated=True):
            headers = {"Origin": origin, "Content-Type": "application/json"}
            if authenticated:
                headers["Authorization"] = "Bearer " + key
            req = urllib.request.Request(
                origin + path,
                headers=headers,
                data=None if payload is None else json.dumps(payload).encode(),
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.load(response)

        def api(path, payload=None):
            return request("/api/control/v1/" + path, payload)

        window = webview.create_window(
            "Orga Drone synthetic Control API smoke",
            "about:blank",
            width=1200,
            height=850,
            hidden=True,
        )
        errors = []

        def verify():
            try:
                window.load_url(origin + "/studio")
                wait(lambda: observed.get("session_id"), "live Studio bridge")
                # Pair through the same internal enable endpoint as the disclosure.
                # Keep the random key out of evaluate_js strings and renderer logs.
                request(
                    "/api/studio/control/enable",
                    {"session_id": observed["session_id"], "pairing_key": key},
                    authenticated=False,
                )

                def ready(clip_id):
                    try:
                        state = api("editor-state")
                    except urllib.error.HTTPError as exc:
                        if json.load(exc)["error"]["code"] == "EDITOR_NOT_READY":
                            return None
                        raise
                    return (
                        state
                        if state["ready"]
                        and not state["busy"]
                        and state["clip_id"] == clip_id
                        else None
                    )

                wait(lambda: ready(clip_a), "clip A readiness")
                window.evaluate_js("""window.controlPreviewMutations = 0;
                    new MutationObserver(() => { window.controlPreviewMutations += 1; }).observe(
                      document.getElementById('studio-preview-video'), {attributes:true}); true;""")

                def command(kind, clip_id, extra):
                    state = wait(lambda: ready(clip_id), "target readiness")
                    body = {
                        "command_id": secrets.token_hex(10),
                        "type": kind,
                        "session_id": state["session_id"],
                        "project_id": pid,
                        "clip_id": clip_id,
                        "expected_state_token": state["state_token"],
                        "expires_at": time.time() + 15,
                        **extra,
                    }
                    return body, api("commands", body)

                edit, _ = command(
                    "set_clip_properties",
                    clip_a,
                    {
                        "properties": {
                            "contrast": 15,
                            "saturation_percent": 120,
                            "creative_lut_id": lut,
                            "creative_lut_strength_percent": 100,
                        }
                    },
                )
                wait(
                    lambda: api("commands/" + edit["command_id"])["ui_applied"],
                    "external edit UI acknowledgement",
                )
                assert (
                    window.evaluate_js(
                        "Number(document.getElementById('inspector-image-contrast').value)"
                    )
                    == 15
                )
                assert (
                    window.evaluate_js(
                        "Number(document.getElementById('inspector-image-saturation').value)"
                    )
                    == 20
                )
                wait(
                    lambda: window.evaluate_js("window.controlPreviewMutations > 0"),
                    "preview DOM refresh",
                )
                window.evaluate_js(
                    f"document.querySelector('[data-select-clip=\"{clip_b}\"]').click(); true;"
                )
                wait(lambda: ready(clip_b), "clip B selection")
                try:
                    command(
                        "undo_last_change",
                        clip_b,
                        {"undo_command_id": edit["command_id"]},
                    )
                    raise AssertionError("Undo for B unexpectedly admitted")
                except urllib.error.HTTPError as exc:
                    assert json.load(exc)["error"]["code"] == "UNDO_CONFLICT"
                assert (
                    window.evaluate_js(
                        f"JSON.parse(document.querySelector('#studio-grid [data-studio-id=\"{clip_a}\"]').dataset.imageAdjust).contrast"
                    )
                    == 15
                )
                window.evaluate_js(
                    f"document.querySelector('[data-select-clip=\"{clip_a}\"]').click(); true;"
                )
                undo, _ = command(
                    "undo_last_change", clip_a, {"undo_command_id": edit["command_id"]}
                )
                wait(
                    lambda: api("commands/" + undo["command_id"])["ui_applied"],
                    "Undo UI acknowledgement",
                )
                assert (
                    window.evaluate_js(
                        "Number(document.getElementById('inspector-image-contrast').value)"
                    )
                    == 0
                )
                window.evaluate_js(
                    "document.getElementById('studio-redo').click(); true;"
                )
                wait(
                    lambda: window.evaluate_js(
                        "Number(document.getElementById('inspector-image-contrast')?.value) === 15"
                    ),
                    "ordinary Redo reload",
                )
                request("/api/studio/control/disable", {}, authenticated=False)
                wait(
                    lambda: window.evaluate_js(
                        "document.querySelector('[data-control-status]').textContent.includes('aus') || document.querySelector('[data-control-status]').textContent.includes('off')"
                    ),
                    "disabled UI status",
                )
                # A normal manual edit still saves after external control is disabled.
                window.evaluate_js("""const field = document.getElementById('inspector-image-contrast');
                    field.value = '8'; field.dispatchEvent(new Event('input', {bubbles:true}));
                    field.dispatchEvent(new Event('change', {bubbles:true})); true;""")
                wait(
                    lambda: (
                        json.loads(db.list_studio_items(pid)[0].effect_settings)[
                            "image"
                        ]["contrast"]
                        == 8
                    ),
                    "manual save after disable",
                )
                assert source_hashes == {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (base / "synthetic").iterdir()
                }
                print(
                    "CONTROL_WEBVIEW_SMOKE_OK: edit, wrong-target rejection, Undo, Redo, preview DOM refresh, disable, manual save, unchanged synthetic sources",
                    flush=True,
                )
            except BaseException as exc:
                if isinstance(exc, urllib.error.HTTPError):
                    errors.append(
                        "HTTP status " + str(exc.code) + ": " + str(json.load(exc))
                    )
                errors.append(
                    type(exc).__name__ + ": " + str(exc).replace(key, "[redacted]")
                )
            finally:
                window.destroy()

        try:
            webview.start(
                verify,
                gui="edgechromium",
                private_mode=True,
                storage_path=str(base / "webview"),
            )
        finally:
            server.should_exit = True
            thread.join(timeout=3)
        if errors:
            raise AssertionError("; ".join(errors))


if __name__ == "__main__":
    _run_smoke()
