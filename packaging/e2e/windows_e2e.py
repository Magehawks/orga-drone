"""Packaged Windows E2E harness for the main admission gate (issue #262).

The workflow builds the onefolder ZIP, extracts it, and runs this file against
the extracted ``orga-drone.exe``. Synthetic media keeps the run deterministic
and independent of private libraries. WebView2 is driven over CDP only when the
app was launched with ORGA_DRONE_E2E=1 and ORGA_DRONE_CDP_PORT.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from orga_drone import __version__ as APP_VERSION

CDP_START_TIMEOUT_S = 120.0
JOURNEY_TIMEOUT_S = 120.0


class E2EError(RuntimeError):
    pass


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(url: str, timeout: float = 5.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def wait_cdp(port: int, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_error = ""
    while time.monotonic() < deadline:
        try:
            return http_json(f"http://127.0.0.1:{port}/json/version")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = str(exc)
            time.sleep(0.5)
    raise E2EError(f"CDP endpoint never appeared on port {port}: {last_error}")


def wait_page_target(port: int, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: list[Any] = []
    while time.monotonic() < deadline:
        try:
            targets = http_json(f"http://127.0.0.1:{port}/json/list")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            time.sleep(0.5)
            continue
        last = targets if isinstance(targets, list) else []
        for target in last:
            if (
                isinstance(target, dict)
                and target.get("type") == "page"
                and target.get("webSocketDebuggerUrl")
            ):
                return target
        time.sleep(0.5)
    raise E2EError(f"No CDP page target appeared; targets={last}")


def webview2_version() -> str:
    if sys.platform != "win32":
        return platform.platform()
    import winreg  # type: ignore[import-not-found]

    keys = (
        r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
        r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
        r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
    )
    for key in keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "pv")
        except OSError:
            continue
        if isinstance(value, str) and value not in {"", "0.0.0.0"}:
            return value
    return ""


class CDP:
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
                raise E2EError(f"CDP {method} failed: {message['error']}")
            return message.get("result")

    def evaluate(
        self,
        expression: str,
        *,
        await_promise: bool = False,
        user_gesture: bool = False,
    ) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": user_gesture,
            },
        )
        if result.get("exceptionDetails"):
            raise E2EError(f"JS exception: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def close(self) -> None:
        self._ws.close()


class AppProcess:
    def __init__(self, exe: Path, data_dir: Path) -> None:
        self.exe = exe
        self.data_dir = data_dir
        self.app_port = free_port()
        self.cdp_port = free_port()
        self.stdout_path = data_dir / "app-stdout.log"
        self.process: subprocess.Popen[bytes] | None = None
        self.cdp: CDP | None = None

    def start(self) -> None:
        env = os.environ.copy()
        env.pop("ORGA_DRONE_BROWSER", None)
        env["ORGA_DRONE_DATA_DIR"] = str(self.data_dir)
        env["ORGA_DRONE_HOST"] = "127.0.0.1"
        env["ORGA_DRONE_PORT"] = str(self.app_port)
        env["ORGA_DRONE_GEOCODE"] = "off"
        env["ORGA_DRONE_E2E"] = "1"
        env["ORGA_DRONE_CDP_PORT"] = str(self.cdp_port)
        with self.stdout_path.open("ab") as stdout:
            self.process = subprocess.Popen(
                [str(self.exe)],
                cwd=str(self.exe.parent),
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT,
            )
        wait_cdp(self.cdp_port, CDP_START_TIMEOUT_S)
        target = wait_page_target(self.cdp_port, CDP_START_TIMEOUT_S)
        self.cdp = CDP(str(target["webSocketDebuggerUrl"]))
        self.cdp.call("Page.enable")
        self.cdp.call("Runtime.enable")

    def stop(self) -> None:
        if self.cdp is not None:
            try:
                self.cdp.close()
            except Exception:  # noqa: BLE001 - best effort teardown
                pass
            self.cdp = None
        if self.process is None:
            return
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
        else:
            self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process = None

    def require_cdp(self) -> CDP:
        if self.cdp is None:
            raise E2EError("WebView2 CDP is not connected")
        return self.cdp


def wait_until(
    cdp: CDP, expression: str, *, timeout_s: float, description: str
) -> Any:
    deadline = time.monotonic() + timeout_s
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = cdp.evaluate(expression, await_promise=True)
        except E2EError:
            time.sleep(0.25)
            continue
        if last:
            return last
        time.sleep(0.25)
    raise E2EError(f"Timed out waiting for {description}; last={last!r}")


def navigate(cdp: CDP, port: int, path: str) -> None:
    cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{port}{path}"})
    wait_until(
        cdp,
        "document.readyState === 'complete' && !!document.body",
        timeout_s=60,
        description=f"page {path} to render",
    )


def page_text(cdp: CDP) -> str:
    return str(cdp.evaluate("document.body ? document.body.innerText : ''") or "")


def fetch_json(
    cdp: CDP,
    path: str,
    *,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    body = "null"
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        body = f"JSON.stringify({json.dumps(json_body)})"
    elif form_body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = f"new URLSearchParams({json.dumps(form_body)}).toString()"
    expression = (
        "(async () => {"
        f"const response = await fetch({json.dumps(path)}, {{"
        f"method: {json.dumps(method)}, headers: {json.dumps(headers)}, "
        f"body: {body}, redirect: 'follow'}});"
        "const text = await response.text();"
        "let data; try { data = JSON.parse(text); } catch (err) { data = text; }"
        "return {ok: response.ok, status: response.status, url: response.url, data};"
        "})()"
    )
    result = cdp.evaluate(expression, await_promise=True)
    if not isinstance(result, dict):
        raise E2EError(f"Unexpected fetch result for {path}: {result!r}")
    return result


def expect_ok(result: dict[str, Any], description: str) -> Any:
    if not result.get("ok"):
        raise E2EError(
            f"{description} failed: status={result.get('status')} data={result.get('data')!r}"
        )
    return result.get("data")


def make_jpeg(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (160, 120), color).save(path, format="JPEG")


def make_mp4(path: Path, ffmpeg: Path) -> None:
    command = [
        str(ffmpeg),
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=320x240:r=30:d=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, timeout=120)
    if completed.returncode != 0:
        raise E2EError(f"Could not create synthetic video: {completed.stderr!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_export(cdp: CDP, project_id: int, output_path: Path) -> dict[str, Any]:
    result = fetch_json(
        cdp,
        "/api/studio/export",
        method="POST",
        json_body={
            "project_id": project_id,
            "height": 720,
            "output_path": str(output_path),
        },
    )
    data = expect_ok(result, "Studio export start")
    job_id = str(data.get("job_id") or "")
    if not job_id:
        raise E2EError(f"Export did not return a job id: {data!r}")
    deadline = time.monotonic() + 180
    job: dict[str, Any] = {}
    while time.monotonic() < deadline:
        job = expect_ok(
            fetch_json(cdp, f"/api/studio/export/jobs/{job_id}"), "Export job status"
        )
        if job.get("state") in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.5)
    if job.get("state") != "completed":
        raise E2EError(f"Export did not complete: {job!r}")
    return job


def validate_export(ffmpeg: Path, output_path: Path) -> dict[str, Any]:
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise E2EError(f"Export file is missing or empty: {output_path}")
    decoded = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(output_path),
            "-vf",
            "fps=1,scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        timeout=60,
    )
    if decoded.returncode != 0:
        raise E2EError(f"Exported MP4 does not decode: {decoded.stderr!r}")
    frames = list(zip(*[iter(decoded.stdout)] * 3))
    if not 4 <= len(frames) <= 6:
        raise E2EError(f"Unexpected exported frame count: {len(frames)}")
    red = sum(1 for r, _g, b in frames if r > b + 50)
    blue = sum(1 for r, _g, b in frames if b > r + 50)
    if red < 1 or blue < 1:
        raise E2EError(f"Exported clip order/colors are wrong: {frames!r}")
    return {
        "bytes": output_path.stat().st_size,
        "sha256": sha256_file(output_path),
        "frames": len(frames),
        "red_frames": red,
        "blue_frames": blue,
    }


def read_photo_adjust(cdp: CDP, filename: str) -> dict[str, Any]:
    expression = (
        "(() => {"
        f"const clip = Array.from(document.querySelectorAll('.studio-clip')).find("
        f"el => el.getAttribute('data-filename') === {json.dumps(filename)});"
        "if (!clip) return null;"
        "try { return JSON.parse(clip.getAttribute('data-image-adjust') || '{}'); }"
        "catch (err) { return {}; }"
        "})()"
    )
    return cdp.evaluate(expression) or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--zip-sha256", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--merge-sha", required=True)
    parser.add_argument("--tree-sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    library = output_dir / "library"
    data_dir.mkdir(parents=True, exist_ok=True)
    library.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / "evidence.json"
    started = time.monotonic()

    evidence: dict[str, Any] = {
        "schema": "orga-drone-packaged-e2e-v1",
        "repository": args.repository,
        "pr_number": args.pr_number,
        "head_sha": args.head_sha,
        "base_sha": args.base_sha,
        "tested_merge_sha": args.merge_sha,
        "tested_tree_sha": args.tree_sha,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
        "artifact_name": args.artifact_name,
        "artifact_sha256": "",
        "artifact_size": 0,
        "app_version": APP_VERSION,
        "webview2_version": webview2_version(),
        "runner_image": f"{os.environ.get('ImageOS', '')} {os.environ.get('ImageVersion', '')}".strip()
        or platform.platform(),
        "result": "fail",
        "manual_checks_claimed": False,
        "journeys": {},
    }
    app: AppProcess | None = None
    background: list[AppProcess] = []

    def journey(name: str, function: Any) -> Any:
        began = time.monotonic()
        try:
            detail = function()
        except Exception as exc:  # noqa: BLE001 - evidence must record the failure
            evidence["journeys"][name] = {
                "ok": False,
                "elapsed_ms": int((time.monotonic() - began) * 1000),
                "error": f"{type(exc).__name__}: {exc}",
            }
            raise
        evidence["journeys"][name] = {
            "ok": True,
            "elapsed_ms": int((time.monotonic() - began) * 1000),
            "detail": detail,
        }
        return detail

    try:
        if not args.exe.is_file():
            raise E2EError(f"Packaged executable is missing: {args.exe}")
        if not args.zip.is_file():
            raise E2EError(f"Packaged ZIP is missing: {args.zip}")
        if sha256_file(args.zip) != args.zip_sha256.lower():
            raise E2EError("ZIP SHA-256 does not match the build output")
        evidence["artifact_sha256"] = sha256_file(args.zip)
        evidence["artifact_size"] = args.zip.stat().st_size

        photo = library / "e2e-blue.jpg"
        video = library / "e2e-red.mp4"
        make_jpeg(photo, (0, 0, 220))
        make_mp4(video, args.ffmpeg)
        originals = {path.name: sha256_file(path) for path in (photo, video)}
        expected_photo = "e2e-blue.jpg"
        expected_video = "e2e-red.mp4"

        app = AppProcess(args.exe, data_dir)
        app.start()
        cdp = app.require_cdp()

        def startup() -> dict[str, Any]:
            navigate(cdp, app.app_port, "/")
            wait_until(
                cdp,
                "document.title.length > 0 && location.href.startsWith('http://127.0.0.1:')",
                timeout_s=60,
                description="app title",
            )
            health = expect_ok(fetch_json(cdp, "/health"), "Health")
            if not isinstance(health, dict) or health.get("status") != "ok":
                raise E2EError(f"Health response is invalid: {health!r}")
            crash = data_dir / "startup-crash.log"
            if crash.exists():
                raise E2EError(f"startup-crash.log exists: {crash.read_text()}")
            return {"version": health.get("version"), "title": cdp.evaluate("document.title")}

        journey("startup", startup)

        state: dict[str, Any] = {}

        def media_import() -> dict[str, Any]:
            added = fetch_json(
                cdp,
                "/library/add",
                method="POST",
                form_body={"path": str(library), "label": "Packaged E2E"},
            )
            if not added.get("ok"):
                raise E2EError(
                    f"Library add failed: status={added.get('status')} data={added.get('data')!r}"
                )
            match = re.search(r"scan_job=([^&]+)", str(added.get("url") or ""))
            if match is None:
                raise E2EError(f"Scan job id is missing: {added!r}")
            job_id = match.group(1)
            deadline = time.monotonic() + JOURNEY_TIMEOUT_S
            job: dict[str, Any] = {}
            while time.monotonic() < deadline:
                job = expect_ok(
                    fetch_json(cdp, f"/api/scan-jobs/{job_id}"), "Scan status"
                )
                if job.get("state") in {"completed", "failed"}:
                    break
                time.sleep(0.5)
            if job.get("state") != "completed":
                raise E2EError(f"Scan did not complete: {job!r}")
            counts = job.get("counts") or {}
            if counts.get("photos") != 1 or counts.get("videos") != 1:
                raise E2EError(f"Unexpected scan counts: {counts!r}")
            state["photo_id"] = find_media(cdp, expected_photo)
            state["video_id"] = find_media(cdp, expected_video)
            return {"job_id": job_id, "counts": counts}

        journey("media_import", media_import)

        def library_navigation() -> dict[str, Any]:
            navigate(cdp, app.app_port, "/browse")
            wait_until(
                cdp,
                f"document.body.innerText.includes({json.dumps(expected_photo)})",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="photo in Browse",
            )
            text = page_text(cdp)
            if expected_video not in text:
                raise E2EError("Video is not listed in Browse")
            detail = expect_ok(
                fetch_json(cdp, f"/media/{state['photo_id']}"), "Media detail"
            )
            if expected_photo not in str(detail):
                raise E2EError("Media detail does not contain the photo")
            return {"browse_chars": len(text)}

        journey("library_navigation", library_navigation)

        def studio_open() -> dict[str, Any]:
            created = expect_ok(
                fetch_json(
                    cdp,
                    "/api/studio/projects",
                    method="POST",
                    json_body={"title": "Packaged E2E"},
                ),
                "Studio project create",
            )
            project_id = int(created["id"])
            expect_ok(
                fetch_json(
                    cdp, f"/api/studio/projects/{project_id}/open", method="POST"
                ),
                "Studio project open",
            )
            for media_id in (state["video_id"], state["photo_id"]):
                expect_ok(
                    fetch_json(
                        cdp,
                        f"/media/{media_id}/studio/add",
                        method="POST",
                        form_body={"return_to": "studio"},
                    ),
                    "Studio add",
                )
            navigate(cdp, app.app_port, "/studio")
            wait_until(
                cdp,
                f"document.body.innerText.includes({json.dumps(expected_photo)})",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="Studio photo clip",
            )
            text = page_text(cdp)
            if expected_video not in text or "studio-preview-video" not in str(
                cdp.evaluate("document.documentElement.outerHTML.slice(0, 100000)")
            ):
                raise E2EError("Studio did not render the video preview")
            state["project_id"] = project_id
            return {"project_id": project_id}

        journey("studio_open", studio_open)

        def playback() -> dict[str, Any]:
            cdp.evaluate(
                "(() => { const el = document.querySelector('.studio-clip[data-kind=\"video\"] "
                "[data-select-clip]'); if (el) el.click(); return !!el; })()",
                user_gesture=True,
            )
            wait_until(
                cdp,
                "(() => { const v = document.getElementById('studio-preview-video');"
                " return !!v && !v.hidden && v.readyState >= 2; })()",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="video preview ready",
            )
            cdp.evaluate(
                "(async () => { const v = document.getElementById('studio-preview-video');"
                " v.muted = true; await v.play(); return !v.paused; })()",
                await_promise=True,
                user_gesture=True,
            )
            time.sleep(1.0)
            state["playback"] = cdp.evaluate(
                "(() => { const v = document.getElementById('studio-preview-video');"
                " return {paused: v.paused, currentTime: v.currentTime, readyState: v.readyState}; })()"
            )
            cdp.evaluate("document.getElementById('studio-preview-video').pause()")
            playback_state = state["playback"]
            if not isinstance(playback_state, dict) or playback_state.get(
                "paused"
            ) or float(playback_state.get("currentTime") or 0) <= 0.2:
                raise E2EError(f"Playback did not advance: {playback_state!r}")
            shot = cdp.call("Page.captureScreenshot", {"format": "png"})
            (output_dir / "studio-playback.png").write_bytes(
                base64.b64decode(str(shot.get("data", "")))
            )
            return playback_state

        journey("playback", playback)

        def edit_persistence() -> dict[str, Any]:
            studio_id = cdp.evaluate(
                "(() => { const clip = Array.from(document.querySelectorAll('.studio-clip'))"
                f".find(el => el.getAttribute('data-filename') === {json.dumps(expected_photo)});"
                " return clip ? clip.getAttribute('data-studio-id') : null; })()"
            )
            if not studio_id:
                raise E2EError("Photo Studio clip id is missing")
            expect_ok(
                fetch_json(
                    cdp,
                    f"/api/studio/{studio_id}/image",
                    method="PATCH",
                    json_body={"exposure": 20},
                ),
                "Studio image edit",
            )
            navigate(cdp, app.app_port, "/studio")
            wait_until(
                cdp,
                f"document.body.innerText.includes({json.dumps(expected_photo)})",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="Studio reload",
            )
            adjust = read_photo_adjust(cdp, expected_photo)
            if int(adjust.get("exposure") or 0) != 20:
                raise E2EError(f"Image edit did not persist: {adjust!r}")
            return {"exposure": adjust.get("exposure")}

        journey("edit_persistence", edit_persistence)

        def export() -> dict[str, Any]:
            output_path = output_dir / "e2e-export.mp4"
            job = run_export(cdp, int(state["project_id"]), output_path)
            result = validate_export(args.ffmpeg, output_path)
            if str(job.get("output_path") or "") == "":
                raise E2EError(f"Export job has no output path: {job!r}")
            return result

        journey("export", export)

        def source_integrity() -> dict[str, Any]:
            if {
                path.name: sha256_file(path)
                for path in (photo, video)
            } != originals:
                raise E2EError("Source media changed during the E2E run")
            return {"files": sorted(originals)}

        journey("source_integrity", source_integrity)

        def relaunch_persistence() -> dict[str, Any]:
            app.stop()
            restarted = AppProcess(args.exe, data_dir)
            background.append(restarted)
            restarted.start()
            restarted_cdp = restarted.require_cdp()
            navigate(restarted_cdp, restarted.app_port, "/")
            expect_ok(
                fetch_json(
                    restarted_cdp,
                    f"/api/studio/projects/{state['project_id']}/open",
                    method="POST",
                ),
                "Reopen project after relaunch",
            )
            navigate(restarted_cdp, restarted.app_port, "/studio")
            wait_until(
                restarted_cdp,
                f"document.body.innerText.includes({json.dumps(expected_photo)})",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="Studio after relaunch",
            )
            adjust = read_photo_adjust(restarted_cdp, expected_photo)
            if int(adjust.get("exposure") or 0) != 20:
                raise E2EError(f"Edit did not persist after relaunch: {adjust!r}")
            restarted.stop()
            background.remove(restarted)
            return {"exposure": adjust.get("exposure")}

        journey("relaunch_persistence", relaunch_persistence)

        evidence["result"] = "pass"
        evidence["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return 0
    except Exception as exc:  # noqa: BLE001 - evidence must record the failure
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        evidence["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        print(f"E2E failure: {evidence['error']}", file=sys.stderr)
        evidence["traceback"] = traceback.format_exc()[-8000:]
        traceback.print_exc()
        log = data_dir / "orga-drone.log"
        if log.exists():
            print("--- orga-drone.log (tail) ---", file=sys.stderr)
            print("\n".join(log.read_text(errors="replace").splitlines()[-80:]), file=sys.stderr)
        crash = data_dir / "startup-crash.log"
        if crash.exists():
            print("--- startup-crash.log ---", file=sys.stderr)
            print(crash.read_text(errors="replace"), file=sys.stderr)
        return 1
    finally:
        if app is not None:
            app.stop()
        for process in background:
            process.stop()
        evidence.setdefault("elapsed_ms", int((time.monotonic() - started) * 1000))
        evidence.setdefault(
            "generated_at", datetime.now(timezone.utc).isoformat()
        )
        evidence_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"evidence={evidence_path}")
        print(f"evidence_result={evidence['result']}")


def find_media(cdp: CDP, filename: str) -> int:
    data = expect_ok(
        fetch_json(cdp, "/api/search", method="POST", json_body={"q": filename}),
        "Search",
    )
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise E2EError(f"Search response is invalid: {data!r}")
    for item in items:
        if isinstance(item, dict) and item.get("filename") == filename:
            return int(item["id"])
    raise E2EError(f"Media is missing from search: {filename}")


if __name__ == "__main__":
    sys.exit(main())
