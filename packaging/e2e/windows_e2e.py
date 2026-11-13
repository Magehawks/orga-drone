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
import math
import os
import platform
import re
import secrets
import socket
import struct
import subprocess
import sys
import time
import wave
import tomllib
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


def _app_version() -> str:
    try:
        data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    return version if isinstance(version, str) else ""

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
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = dict(headers or {})
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


def fetch_binary(cdp: CDP, path: str, description: str) -> bytes:
    """Fetch a binary resource through the page session (Origin checks apply)."""
    expression = (
        "(async () => {"
        f"const response = await fetch({json.dumps(path)}, {{redirect: 'follow'}});"
        "const buffer = await response.arrayBuffer();"
        "let binary = '';"
        "const bytes = new Uint8Array(buffer);"
        "const chunk = 0x8000;"
        "for (let i = 0; i < bytes.length; i += chunk) {"
        "binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));"
        "}"
        "return {ok: response.ok, status: response.status, base64: btoa(binary)};"
        "})()"
    )
    result = cdp.evaluate(expression, await_promise=True)
    if not isinstance(result, dict) or not result.get("ok"):
        raise E2EError(
            f"{description} failed: status={result.get('status') if isinstance(result, dict) else result!r}"
        )
    return base64.b64decode(str(result.get("base64", "")))


def make_jpeg(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (160, 120), color).save(path, format="JPEG")


def make_wav(path: Path, frequency: float, seconds: float = 0.6) -> None:
    """16-bit mono WAV. ffmpeg and the waveform cache can both decode it."""
    rate = 8000
    count = int(rate * seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for index in range(count):
            sample = int(12000 * math.sin(2 * math.pi * frequency * index / rate))
            frames += struct.pack("<h", sample)
        handle.writeframes(frames)


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


def run_export(
    cdp: CDP, project_id: int, output_path: Path, *, height: int = 720
) -> dict[str, Any]:
    result = fetch_json(
        cdp,
        "/api/studio/export",
        method="POST",
        json_body={
            "project_id": project_id,
            "height": height,
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


def probe_video_size(ffmpeg: Path, output_path: Path) -> tuple[int, int]:
    """Return (width, height) from ffmpeg -i stderr (no ffprobe required)."""
    completed = subprocess.run(
        [str(ffmpeg), "-i", str(output_path)],
        capture_output=True,
        timeout=60,
    )
    text = (completed.stderr or b"").decode("utf-8", errors="replace")
    match = re.search(r"Video:.*?\s(\d{2,5})x(\d{2,5})", text)
    if match is None:
        raise E2EError(f"Could not probe video size: {text[-500:]!r}")
    return int(match.group(1)), int(match.group(2))


def audio_peak(ffmpeg: Path, output_path: Path) -> float:
    """Max absolute sample of the first exported audio second."""
    decoded = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(output_path),
            "-map",
            "0:a:0",
            "-t",
            "1",
            "-ac",
            "1",
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        timeout=60,
    )
    if decoded.returncode != 0 or len(decoded.stdout) < 4:
        raise E2EError(f"Exported MP4 has no decodable audio: {decoded.stderr!r}")
    usable = decoded.stdout[: len(decoded.stdout) - (len(decoded.stdout) % 4)]
    peak = 0.0
    for offset in range(0, len(usable), 4):
        sample = abs(struct.unpack_from("<f", usable, offset)[0])
        if sample > peak:
            peak = sample
    return peak


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
    local = "--local" in sys.argv
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--zip", required=not local, type=Path)
    parser.add_argument("--zip-sha256", required=not local)
    parser.add_argument("--artifact-name", required=not local)
    parser.add_argument("--artifact-api-digest", required=not local)
    parser.add_argument("--artifact-api-size", required=not local, type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--repository", default="local")
    parser.add_argument("--pr-number", default=0, type=int)
    parser.add_argument("--head-sha", default="local")
    parser.add_argument("--base-sha", default="local")
    parser.add_argument("--merge-sha", default="local")
    parser.add_argument("--tree-sha", default="local")
    parser.add_argument("--run-id", default=0, type=int)
    parser.add_argument("--run-attempt", default=0, type=int)
    args = parser.parse_args()
    if not local and args.repository == "local":
        parser.error("--repository is required unless --local is set")

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
        "artifact_api_digest": args.artifact_api_digest,
        "artifact_api_size": args.artifact_api_size,
        "app_version": _app_version(),
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
        if local:
            evidence["admission"] = "local-development"
            evidence["artifact_sha256"] = ""
            evidence["artifact_size"] = 0
        else:
            if args.zip is None or not args.zip.is_file():
                raise E2EError(f"Packaged ZIP is missing: {args.zip}")
            if sha256_file(args.zip) != str(args.zip_sha256).lower():
                raise E2EError("ZIP SHA-256 does not match the build output")
            evidence["artifact_sha256"] = sha256_file(args.zip)
            evidence["artifact_size"] = args.zip.stat().st_size

        photo = library / "e2e-blue.jpg"
        video = library / "e2e-red.mp4"
        make_jpeg(photo, (0, 0, 220))
        make_mp4(video, args.ffmpeg)
        media_files = [photo, video]
        originals = {path.name: sha256_file(path) for path in media_files}
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

        def timeline_transitions() -> dict[str, Any]:
            """Crossfade, Blur Dissolve, and Soft Wipe on the outgoing video clip."""
            video_clip_id = cdp.evaluate(
                "(() => { const clip = Array.from(document.querySelectorAll('.studio-clip'))"
                f".find(el => el.getAttribute('data-filename') === {json.dumps(expected_video)});"
                " return clip ? Number(clip.getAttribute('data-studio-id')) : null; })()"
            )
            if not video_clip_id:
                raise E2EError("Video Studio clip id is missing for transitions")
            applied: dict[str, Any] = {}
            for transition_type in (
                "crossfade",
                "blur_dissolve",
                "soft_wipe_left",
            ):
                body = expect_ok(
                    fetch_json(
                        cdp,
                        f"/api/studio/{int(video_clip_id)}/transition",
                        method="PATCH",
                        json_body={"type": transition_type, "duration_s": 0.5},
                    ),
                    f"Transition {transition_type}",
                )
                if body.get("type") != transition_type:
                    raise E2EError(f"Transition type not stored: {body!r}")
                if body.get("applied_type") != transition_type:
                    raise E2EError(f"Transition not applied: {body!r}")
                applied[transition_type] = {
                    "duration_s": body.get("duration_s"),
                    "applied_duration_s": body.get("applied_duration_s"),
                    "fallback_cut": body.get("fallback_cut"),
                }
            # Leave Soft Wipe active for later exports (overlap shortens story).
            shot = cdp.call("Page.captureScreenshot", {"format": "png"})
            (output_dir / "studio-transitions.png").write_bytes(
                base64.b64decode(str(shot.get("data", "")))
            )
            state["video_clip_id"] = int(video_clip_id)
            return applied

        journey("timeline_transitions", timeline_transitions)

        def speed_and_timelapse() -> dict[str, Any]:
            """Speed Ramp region + Timelapse flat ramp via the same speed-ramp API."""
            clip_id = int(state["video_clip_id"])
            ramp = {
                "v": 1,
                "interp": "reciprocal_smoothstep",
                "points": [
                    {"source_s": 0.0, "speed": 1.0},
                    {"source_s": 2.0, "speed": 4.0},
                ],
                "region": {"start_s": 0.0, "end_s": 2.0},
            }
            ramped = expect_ok(
                fetch_json(
                    cdp,
                    f"/api/studio/{clip_id}/speed-ramp",
                    method="PATCH",
                    json_body={"speed_ramp": ramp},
                ),
                "Speed ramp apply",
            )
            if not isinstance(ramped.get("speed_ramp"), dict):
                raise E2EError(f"Speed ramp did not persist: {ramped!r}")
            if float(ramped.get("effective_duration_s") or 0) <= 0:
                raise E2EError(f"Speed ramp has no effective duration: {ramped!r}")
            # Timelapse Inspector writes a flat ADR-0034 ramp after confirm.
            flat = {
                "v": 1,
                "interp": "reciprocal_smoothstep",
                "points": [
                    {"source_s": 0.0, "speed": 2.0},
                    {"source_s": 2.0, "speed": 2.0},
                ],
            }
            timed = expect_ok(
                fetch_json(
                    cdp,
                    f"/api/studio/{clip_id}/speed-ramp",
                    method="PATCH",
                    json_body={"speed_ramp": flat},
                ),
                "Timelapse flat ramp apply",
            )
            points = (timed.get("speed_ramp") or {}).get("points") or []
            if len(points) != 2 or abs(float(points[0].get("speed") or 0) - 2.0) > 1e-6:
                raise E2EError(f"Timelapse flat ramp missing: {timed!r}")
            # Clear before the long SFX/export journeys so frame-count gates stay stable.
            cleared = expect_ok(
                fetch_json(
                    cdp,
                    f"/api/studio/{clip_id}/speed-ramp",
                    method="PATCH",
                    json_body={"speed_ramp": None},
                ),
                "Speed ramp clear",
            )
            if cleared.get("speed_ramp") is not None:
                raise E2EError(f"Speed ramp did not clear: {cleared!r}")
            navigate(cdp, app.app_port, "/studio")
            wait_until(
                cdp,
                "!!document.getElementById('inspector-timelapse')",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="Timelapse inspector panel",
            )
            shot = cdp.call("Page.captureScreenshot", {"format": "png"})
            (output_dir / "studio-timelapse-inspector.png").write_bytes(
                base64.b64decode(str(shot.get("data", "")))
            )
            return {
                "ramp_effective_duration_s": ramped.get("effective_duration_s"),
                "timelapse_effective_duration_s": timed.get("effective_duration_s"),
                "cleared": True,
            }

        journey("speed_and_timelapse", speed_and_timelapse)

        def undo_redo_timeline() -> dict[str, Any]:
            studio_id = cdp.evaluate(
                "(() => { const clip = Array.from(document.querySelectorAll('.studio-clip'))"
                f".find(el => el.getAttribute('data-filename') === {json.dumps(expected_photo)});"
                " return clip ? clip.getAttribute('data-studio-id') : null; })()"
            )
            if not studio_id:
                raise E2EError("Photo Studio clip id is missing for undo/redo")
            expect_ok(
                fetch_json(
                    cdp,
                    f"/api/studio/{studio_id}/image",
                    method="PATCH",
                    json_body={"exposure": 35},
                ),
                "Undo/redo exposure edit",
            )
            undone = expect_ok(
                fetch_json(cdp, "/api/studio/history/undo", method="POST"),
                "Timeline undo",
            )
            if undone.get("ok") is False:
                raise E2EError(f"Undo rejected: {undone!r}")
            adjust = read_photo_adjust(cdp, expected_photo)
            # DOM may be stale until reload; verify via reopen.
            navigate(cdp, app.app_port, "/studio")
            wait_until(
                cdp,
                f"document.body.innerText.includes({json.dumps(expected_photo)})",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="Studio after undo",
            )
            adjust = read_photo_adjust(cdp, expected_photo)
            if int(adjust.get("exposure") or 0) != 20:
                raise E2EError(f"Undo did not restore exposure 20: {adjust!r}")
            expect_ok(
                fetch_json(cdp, "/api/studio/history/redo", method="POST"),
                "Timeline redo",
            )
            navigate(cdp, app.app_port, "/studio")
            wait_until(
                cdp,
                f"document.body.innerText.includes({json.dumps(expected_photo)})",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="Studio after redo",
            )
            adjust = read_photo_adjust(cdp, expected_photo)
            if int(adjust.get("exposure") or 0) != 35:
                raise E2EError(f"Redo did not restore exposure 35: {adjust!r}")
            # Restore the baseline exposure used by relaunch_persistence.
            expect_ok(
                fetch_json(
                    cdp,
                    f"/api/studio/{studio_id}/image",
                    method="PATCH",
                    json_body={"exposure": 20},
                ),
                "Restore baseline exposure",
            )
            return {"after_undo": 20, "after_redo": 35, "restored": 20}

        journey("undo_redo_timeline", undo_redo_timeline)

        def export_1080p() -> dict[str, Any]:
            output_path = output_dir / "e2e-export-1080p.mp4"
            job = run_export(
                cdp, int(state["project_id"]), output_path, height=1080
            )
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                raise E2EError(f"1080p export missing: {output_path}")
            width, height = probe_video_size(args.ffmpeg, output_path)
            if height != 1080:
                raise E2EError(f"1080p export height mismatch: {width}x{height}")
            if str(job.get("output_path") or "") == "":
                raise E2EError(f"1080p export job has no output path: {job!r}")
            return {
                "bytes": output_path.stat().st_size,
                "sha256": sha256_file(output_path),
                "width": width,
                "height": height,
            }

        journey("export_1080p", export_1080p)

        def sfx_lane() -> dict[str, Any]:
            music = library / "e2e-bed.wav"
            hit = library / "e2e-hit.wav"
            whoosh = library / "e2e-whoosh.wav"
            make_wav(music, 220, seconds=1.2)
            make_wav(hit, 660, seconds=0.5)
            make_wav(whoosh, 440, seconds=0.8)
            for path in (music, hit, whoosh):
                media_files.append(path)
                originals[path.name] = sha256_file(path)
            project_id = int(state["project_id"])
            expect_ok(
                fetch_json(
                    cdp,
                    f"/api/studio/projects/{project_id}/music",
                    method="POST",
                    json_body={"path": str(music.resolve())},
                ),
                "Music add",
            )
            placed: list[Any] = []
            for path, start in ((hit, 0.4), (whoosh, 1.1)):
                payload = expect_ok(
                    fetch_json(
                        cdp,
                        f"/api/studio/projects/{project_id}/sfx",
                        method="POST",
                        json_body={"path": str(path.resolve()), "start_s": start},
                    ),
                    "SFX add",
                )
                placed = payload.get("clips") or []
            if len(placed) != 2:
                raise E2EError(f"Expected two SFX clips: {placed!r}")
            for clip in placed:
                wave_url = str(clip.get("waveform_url") or "")
                if not wave_url:
                    raise E2EError(f"SFX clip has no waveform URL: {clip!r}")
                waveform = expect_ok(fetch_json(cdp, wave_url.split("?")[0]), "SFX waveform")
                if waveform.get("status") != "ready" or not waveform.get("peaks"):
                    raise E2EError(f"SFX waveform is not ready: {waveform!r}")
            navigate(cdp, app.app_port, "/studio")
            wait_until(
                cdp,
                "document.querySelectorAll('.studio-sfx-clip').length === 2",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="two SFX clips",
            )
            wait_until(
                cdp,
                "(() => { const clips = [...document.querySelectorAll('.studio-sfx-clip')];"
                " return clips.length === 2 && clips.every(el => el.dataset.waveform === 'ready'"
                " && el.querySelector('.studio-sfx-wave')?.width > 0); })()",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="SFX waveforms painted",
            )
            before = float(placed[0]["start_s"])
            dragged = cdp.evaluate(
                "(() => { const el = document.querySelector('.studio-sfx-clip');"
                " const rect = el.getBoundingClientRect();"
                " const x = rect.left + rect.width / 2; const y = rect.top + rect.height / 2;"
                " el.dispatchEvent(new PointerEvent('pointerdown', {button:0, clientX:x, clientY:y, bubbles:true, pointerId:1}));"
                " window.dispatchEvent(new PointerEvent('pointermove', {button:0, clientX:x+120, clientY:y, bubbles:true, pointerId:1}));"
                " window.dispatchEvent(new PointerEvent('pointerup', {button:0, clientX:x+120, clientY:y, bubbles:true, pointerId:1}));"
                " return true; })()"
            )
            if dragged is not True:
                raise E2EError("SFX drag did not dispatch")
            deadline = time.monotonic() + 20
            moved: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                current = expect_ok(
                    fetch_json(cdp, f"/api/studio/projects/{project_id}/sfx"),
                    "SFX list after drag",
                )
                clips = current.get("clips") or []
                match = next((item for item in clips if item.get("id") == placed[0]["id"]), None)
                if isinstance(match, dict) and abs(float(match["start_s"]) - before) > 0.05:
                    moved = match
                    break
                time.sleep(0.25)
            if moved is None:
                raise E2EError("SFX drag did not change the Story start")
            second = next(item for item in placed if item.get("id") != moved["id"])
            trimmed_out = float(second["source_out_s"])
            cdp.evaluate(
                "(() => { const el = document.querySelector("
                f"'.studio-sfx-clip[data-sfx-id=\"{int(second['id'])}\"]');"
                " if (!el) return false; el.focus();"
                " el.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowLeft', shiftKey:true, bubbles:true}));"
                " return true; })()"
            )
            deadline = time.monotonic() + 20
            trimmed: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                current = expect_ok(
                    fetch_json(cdp, f"/api/studio/projects/{project_id}/sfx"),
                    "SFX list after trim",
                )
                match = next(
                    (item for item in current.get("clips") or [] if item.get("id") == second["id"]),
                    None,
                )
                if isinstance(match, dict) and float(match["source_out_s"]) < trimmed_out - 0.05:
                    trimmed = match
                    break
                time.sleep(0.25)
            if trimmed is None:
                raise E2EError("SFX keyboard trim did not shorten the clip")
            undone = expect_ok(
                fetch_json(cdp, "/api/studio/history/undo", method="POST"),
                "SFX undo",
            )
            if not undone.get("ok", True) and undone.get("can_undo") is False:
                raise E2EError(f"SFX undo failed: {undone!r}")
            restored = expect_ok(
                fetch_json(cdp, f"/api/studio/projects/{project_id}/sfx"),
                "SFX list after undo",
            )
            restored_clip = next(
                (item for item in restored.get("clips") or [] if item.get("id") == second["id"]),
                None,
            )
            if not isinstance(restored_clip, dict) or abs(
                float(restored_clip["source_out_s"]) - trimmed_out
            ) > 0.02:
                raise E2EError(f"Undo did not restore the SFX trim: {restored_clip!r}")
            expect_ok(
                fetch_json(cdp, "/api/studio/history/redo", method="POST"),
                "SFX redo",
            )
            navigate(cdp, app.app_port, "/studio")
            wait_until(
                cdp,
                "document.querySelectorAll('.studio-sfx-clip').length === 2",
                timeout_s=JOURNEY_TIMEOUT_S,
                description="SFX clips after reopen",
            )
            state["expect_audio"] = True
            return {
                "clips": 2,
                "dragged_start_s": moved["start_s"],
                "trimmed_source_out_s": trimmed["source_out_s"],
                "music": music.name,
            }

        journey("sfx_lane", sfx_lane)

        def sfx_control() -> dict[str, Any]:
            project_id = int(state["project_id"])
            listing = expect_ok(
                fetch_json(cdp, f"/api/studio/projects/{project_id}/sfx"),
                "SFX list for control",
            )
            clip = (listing.get("clips") or [None])[0]
            if not isinstance(clip, dict):
                raise E2EError("Control API has no SFX clip to update")
            studio_id = cdp.evaluate(
                "(() => { const el = document.querySelector('.studio-clip[data-kind=\"video\"]');"
                " return el ? Number(el.getAttribute('data-studio-id')) : 0; })()"
            )
            key = secrets.token_hex(32)
            session_id = "packaged-e2e-sfx"
            expect_ok(
                fetch_json(
                    cdp,
                    "/api/studio/control/enable",
                    method="POST",
                    json_body={"session_id": session_id, "pairing_key": key},
                ),
                "Control enable",
            )
            editor = {
                "project_id": project_id,
                "clip_id": int(studio_id) if studio_id else None,
                "selection_revision": 1,
                "playhead_s": 0,
                "playing": False,
                "busy": False,
                "ready": True,
            }
            expect_ok(
                fetch_json(
                    cdp,
                    "/api/studio/control/poll",
                    method="POST",
                    json_body={"session_id": session_id, "state": editor},
                ),
                "Control poll",
            )
            token_body = expect_ok(
                fetch_json(
                    cdp,
                    "/api/control/v1/editor-state",
                    headers={"Authorization": f"Bearer {key}"},
                ),
                "Control editor state",
            )
            command_id = secrets.token_hex(8)
            expect_ok(
                fetch_json(
                    cdp,
                    "/api/control/v1/commands",
                    method="POST",
                    headers={"Authorization": f"Bearer {key}"},
                    json_body={
                        "command_id": command_id,
                        "type": "project_action",
                        "action": "sfx.update",
                        "action_version": 1,
                        "params": {
                            "clip_id": clip["id"],
                            "start_s": clip["start_s"],
                            "source_in_s": clip["source_in_s"],
                            "source_out_s": clip["source_out_s"],
                            "volume": 0.35,
                            "fade_in_s": clip["fade_in_s"],
                            "fade_out_s": clip["fade_out_s"],
                        },
                        "session_id": session_id,
                        "project_id": project_id,
                        "clip_id": None,
                        "expected_state_token": token_body["state_token"],
                        "expires_at": time.time() + 30,
                    },
                ),
                "Control submit",
            )
            executed = expect_ok(
                fetch_json(
                    cdp,
                    "/api/studio/control/execute",
                    method="POST",
                    json_body={
                        "session_id": session_id,
                        "state": editor,
                        "command_id": command_id,
                    },
                ),
                "Control execute",
            )
            if executed.get("status") not in {"persisted", "persisted_ui_unconfirmed"}:
                raise E2EError(f"Control SFX update did not persist: {executed!r}")
            checked = expect_ok(
                fetch_json(cdp, f"/api/studio/projects/{project_id}/sfx"),
                "SFX list after control update",
            )
            updated = next(
                (item for item in checked.get("clips") or [] if item.get("id") == clip["id"]),
                None,
            )
            if not isinstance(updated, dict) or abs(float(updated["volume"]) - 0.35) > 0.02:
                raise E2EError(f"Control API did not change SFX volume: {updated!r}")
            if "file_path" in str(executed.get("canonical")):
                raise E2EError("Control response included a source path")
            return {"volume": updated["volume"], "status": executed.get("status")}

        journey("sfx_control", sfx_control)

        def export() -> dict[str, Any]:
            output_path = output_dir / "e2e-export.mp4"
            job = run_export(cdp, int(state["project_id"]), output_path)
            result = validate_export(args.ffmpeg, output_path)
            if state.get("expect_audio"):
                result["audio_peak"] = audio_peak(args.ffmpeg, output_path)
                if result["audio_peak"] <= 0.001:
                    raise E2EError("Exported MP4 audio is silent")
            if str(job.get("output_path") or "") == "":
                raise E2EError(f"Export job has no output path: {job!r}")
            return result

        journey("export", export)

        def image_export() -> dict[str, Any]:
            options = expect_ok(
                fetch_json(
                    cdp, f"/api/media/{state['photo_id']}/export/options"
                ),
                "Image export options",
            )
            presets = options.get("presets") if isinstance(options, dict) else None
            if not isinstance(presets, list) or not presets:
                raise E2EError(f"Image export presets are missing: {options!r}")
            preset = next(
                (
                    item
                    for item in presets
                    if isinstance(item, dict) and item.get("id") == "instagram"
                ),
                presets[0],
            )
            if not isinstance(preset, dict):
                raise E2EError(f"Image export preset is invalid: {preset!r}")
            suggested = str(preset.get("suggested_filename") or "e2e-image.jpg")
            output_path = output_dir / f"e2e-image{Path(suggested).suffix or '.jpg'}"
            started = expect_ok(
                fetch_json(
                    cdp,
                    f"/api/media/{state['photo_id']}/export",
                    method="POST",
                    json_body={
                        "preset": preset["id"],
                        "output_path": str(output_path),
                    },
                ),
                "Image export start",
            )
            job_id = str(started.get("job_id") or "")
            if not job_id:
                raise E2EError(f"Image export did not return a job id: {started!r}")
            deadline = time.monotonic() + 120
            job: dict[str, Any] = {}
            while time.monotonic() < deadline:
                job = expect_ok(
                    fetch_json(cdp, f"/api/studio/export/jobs/{job_id}"),
                    "Image export job status",
                )
                if job.get("state") in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.25)
            if job.get("state") != "completed":
                raise E2EError(f"Image export did not complete: {job!r}")
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                raise E2EError(f"Image export is missing or empty: {output_path}")
            with Image.open(output_path) as image:
                image.verify()
            return {
                "preset": preset["id"],
                "bytes": output_path.stat().st_size,
                "sha256": sha256_file(output_path),
            }

        journey("image_export", image_export)

        def lut_parity() -> dict[str, Any]:
            """Deterministic .cube fixture: Studio LUT preview vs exported
            MP4 frame (issue #267). Fail closed on missing/mismatched
            evidence; synthetic media only; tolerance is the documented
            video budget (JPEG still + H.264 chroma/scaling)."""
            tolerance = 8.0
            cube = library / "e2e-parity.cube"
            # Red input (1,0,0) -> (1, 0.35, 0.35): visible, measurable shift.
            cube_lines = ['TITLE "Packaged E2E parity transform"', "LUT_3D_SIZE 2"]
            for blue in (0, 1):
                for green in (0, 1):
                    for red in (0, 1):
                        cube_lines.append(
                            f"{red} {0.35 + green * 0.65} {0.35 + blue * 0.65}"
                        )
            cube.write_text("\n".join(cube_lines) + "\n", encoding="utf-8")
            cube_sha256 = sha256_file(cube)

            imported = expect_ok(
                fetch_json(cdp, "/api/studio/luts", method="POST", json_body={"path": str(cube)}),
                "LUT import",
            )
            asset = str(imported.get("asset_name") or "")
            if not asset:
                raise E2EError(f"LUT import returned no asset name: {imported!r}")

            video_clip_id = cdp.evaluate(
                "(() => { const clip = Array.from(document.querySelectorAll('.studio-clip'))"
                f".find(el => el.getAttribute('data-filename') === {json.dumps(expected_video)});"
                " return clip ? clip.getAttribute('data-studio-id') : null; })()"
            )
            if not video_clip_id:
                raise E2EError("Video Studio clip id is missing")
            expect_ok(
                fetch_json(
                    cdp,
                    f"/api/studio/{video_clip_id}/color",
                    method="PATCH",
                    json_body={
                        "input_profile": "rec709",
                        "creative_lut": asset,
                        "creative_strength": 100,
                    },
                ),
                "LUT apply on video clip",
            )

            preview = fetch_binary(
                cdp,
                f"/api/studio/{video_clip_id}/preview-frame?t_s=0",
                "LUT preview still",
            )
            preview_path = output_dir / "e2e-lut-preview.jpg"
            preview_path.write_bytes(preview)

            parity_export = output_dir / "e2e-lut-parity.mp4"
            run_export(cdp, int(state["project_id"]), parity_export)

            export_frame = output_dir / "e2e-lut-export-frame.png"
            decoded = subprocess.run(
                [
                    str(args.ffmpeg), "-y", "-loglevel", "error",
                    "-i", str(parity_export), "-frames:v", "1",
                    "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24",
                    str(export_frame),
                ],
                capture_output=True,
                timeout=120,
            )
            if decoded.returncode != 0 or not export_frame.is_file():
                raise E2EError(f"Could not decode the export frame: {decoded.stderr!r}")

            with Image.open(preview_path) as still, Image.open(export_frame) as frame:
                still_rgb = still.convert("RGB").resize(frame.size)
                frame_rgb = frame.convert("RGB")
                width, height = frame_rgb.size
                center = (width // 4, height // 4, width - width // 4, height - height // 4)
                still_mean = ImageStat.Stat(still_rgb.crop(center)).mean
                export_mean = ImageStat.Stat(frame_rgb.crop(center)).mean
                errors = [abs(still_mean[i] - export_mean[i]) for i in range(3)]
                if max(errors) > tolerance:
                    raise E2EError(
                        "LUT preview/export parity exceeded the tolerance: "
                        f"still={still_mean} export={export_mean} "
                        f"errors={errors} tolerance={tolerance}"
                    )
                # The LUT must visibly reach BOTH planes (a silently skipped
                # grade would show G/B near the ungraded red baseline).
                for plane_name, plane in (("preview", still_mean), ("export", export_mean)):
                    if plane[1] < 20.0 or plane[2] < 20.0:
                        raise E2EError(
                            f"LUT is not visibly applied in the {plane_name}: {plane}"
                        )
            return {
                "cube_sha256": cube_sha256,
                "asset": asset,
                "tolerance": tolerance,
                "errors": [round(error, 3) for error in errors],
                "preview_mean": [round(value, 2) for value in still_mean],
                "export_mean": [round(value, 2) for value in export_mean],
            }

        journey("lut_parity", lut_parity)

        def source_integrity() -> dict[str, Any]:
            if {
                path.name: sha256_file(path)
                for path in media_files
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

        def shutdown() -> dict[str, Any]:
            """Ensure no packaged app process remains after journeys complete."""
            stopped: list[int] = []
            for process in list(background):
                if process.process is not None:
                    stopped.append(int(process.process.pid))
                process.stop()
                background.remove(process)
            if app is not None and app.process is not None:
                stopped.append(int(app.process.pid))
                app.stop()
            crash = data_dir / "startup-crash.log"
            if crash.exists():
                raise E2EError(f"startup-crash.log after shutdown: {crash.read_text()}")
            return {"stopped_pids": stopped, "clean": True}

        journey("shutdown", shutdown)

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
