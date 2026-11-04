"""Phase 0 spike: launch the packaged Windows app and drive WebView2 over CDP.

This is throwaway feasibility work for issue #262. It answers one question:
can a GitHub-hosted Windows runner start the real WebView2 window and expose
the Chrome DevTools Protocol endpoint? It does not run release publication,
upload the build, or change the app.
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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CDP_START_TIMEOUT_S = 120.0


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
    raise RuntimeError(f"CDP endpoint never appeared on port {port}: {last_error}")


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
    raise RuntimeError(f"No CDP page target appeared; targets={last}")


class CDP:
    def __init__(self, websocket_url: str) -> None:
        import websocket

        self._next_id = 1
        self._ws = websocket.create_connection(
            websocket_url, timeout=20, suppress_origin=True
        )
        self._ws.settimeout(30)

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
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result")

    def evaluate(self, expression: str, *, await_promise: bool = False) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(f"JS exception: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def close(self) -> None:
        self._ws.close()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--command", nargs=argparse.REMAINDER)
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()

    if args.exe is None and not args.command:
        raise SystemExit("pass --exe or --command")
    if args.exe is not None and args.command:
        raise SystemExit("pass only one of --exe or --command")

    if args.exe is not None:
        exe = args.exe.resolve()
        if not exe.is_file():
            raise SystemExit(f"packaged executable is missing: {exe}")
        launch = [str(exe)]
        launch_cwd = str(exe.parent)
        launch_label = str(exe)
    else:
        launch = list(args.command)
        launch_cwd = str(Path.cwd())
        launch_label = " ".join(launch)

    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    app_port = free_port()
    cdp_port = free_port()

    env = os.environ.copy()
    env.pop("ORGA_DRONE_BROWSER", None)
    env["ORGA_DRONE_DATA_DIR"] = str(data_dir)
    env["ORGA_DRONE_HOST"] = "127.0.0.1"
    env["ORGA_DRONE_PORT"] = str(app_port)
    env["ORGA_DRONE_GEOCODE"] = "off"
    env["ORGA_DRONE_E2E"] = "1"
    env["ORGA_DRONE_CDP_PORT"] = str(cdp_port)

    stdout_path = data_dir / "spike-stdout.log"
    print(f"launching {launch_label} (app_port={app_port}, cdp_port={cdp_port})")
    with stdout_path.open("wb") as stdout:
        process = subprocess.Popen(
            launch,
            cwd=launch_cwd,
            env=env,
            stdout=stdout,
            stderr=subprocess.STDOUT,
        )

    cdp: CDP | None = None
    try:
        version = wait_cdp(cdp_port, CDP_START_TIMEOUT_S)
        print(f"cdp_version={version.get('Browser', '')} protocol={version.get('Protocol-Version', '')}")

        target = wait_page_target(cdp_port, CDP_START_TIMEOUT_S)
        print(f"cdp_target={target.get('url', '')}")

        cdp = CDP(str(target["webSocketDebuggerUrl"]))
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")

        deadline = time.monotonic() + 120
        title = ""
        href = ""
        while time.monotonic() < deadline:
            title = str(cdp.evaluate("document.title") or "")
            href = str(cdp.evaluate("location.href") or "")
            if href.startswith("http://127.0.0.1:") and title:
                break
            time.sleep(0.5)
        print(f"page_title={title!r} page_href={href!r}")
        if not href.startswith("http://127.0.0.1:"):
            raise RuntimeError(f"WebView never navigated to the local app: {href!r}")

        health = cdp.evaluate(
            "(async () => await (await fetch('/health')).json())()",
            await_promise=True,
        )
        print(f"health={json.dumps(health, sort_keys=True)}")
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise RuntimeError(f"health endpoint failed: {health!r}")

        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/browse"})
        deadline = time.monotonic() + 60
        body = ""
        while time.monotonic() < deadline:
            href = str(cdp.evaluate("location.href") or "")
            body = str(cdp.evaluate("document.body ? document.body.innerText : ''") or "")
            if "/browse" in href and body.strip():
                break
            time.sleep(0.5)
        print(f"browse_href={href!r} browse_text_length={len(body)}")
        if "/browse" not in href or not body.strip():
            raise RuntimeError("Browse page did not render in the packaged WebView2 window")

        shot = cdp.call("Page.captureScreenshot", {"format": "png"})
        png = base64.b64decode(str(shot.get("data", "")))
        shot_path = data_dir / "spike-browse.png"
        shot_path.write_bytes(png)
        print(f"screenshot_bytes={len(png)} screenshot_sha256_required=false")

        crash = data_dir / "startup-crash.log"
        if crash.exists():
            raise RuntimeError(f"startup-crash.log exists:\n{read_text(crash)}")
        print("spike_result=pass")
        return 0
    except Exception as exc:  # noqa: BLE001 - spike must print diagnostics
        print(f"spike_result=fail: {type(exc).__name__}: {exc}")
        log = read_text(data_dir / "orga-drone.log")
        if log:
            print("--- orga-drone.log (tail) ---")
            print("\n".join(log.splitlines()[-80:]))
        crash = read_text(data_dir / "startup-crash.log")
        if crash:
            print("--- startup-crash.log ---")
            print(crash)
        return 1
    finally:
        if cdp is not None:
            cdp.close()
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        print("--- spike-stdout.log (tail) ---")
        print("\n".join(read_text(stdout_path).splitlines()[-40:]))


if __name__ == "__main__":
    sys.exit(main())
