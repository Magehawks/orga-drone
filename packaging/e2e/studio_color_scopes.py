"""Windows/WebView2 journey for Pro scopes UI against disclosed test patterns.

Verifies Creative hides scopes, Pro reveals them, fixture mode labels honestly,
and toggling scopes does not mutate clip grade datasets. Synthetic media only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image

_spec = importlib.util.spec_from_file_location(
    "color_scopes_windows_e2e", Path(__file__).with_name("windows_e2e.py")
)
assert _spec and _spec.loader
_harness: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)
free_port = _harness.free_port
wait_cdp, wait_page_target = _harness.wait_cdp, _harness.wait_page_target


def run(out: Path) -> None:
    from orga_drone.config import Settings
    from orga_drone.db import Database

    out.mkdir(parents=True, exist_ok=False)
    data, media = out / "data", out / "media"
    media.mkdir()
    Image.new("RGB", (640, 360), (80, 120, 160)).save(media / "clip-a.jpg")
    db = Database(Settings(data_dir=data).db_path)
    root = db.add_root(media, label="Synthetic scopes")
    project = db.create_studio_project("Synthetic scopes")
    source = media / "clip-a.jpg"
    originals = {source.name: hashlib.sha256(source.read_bytes()).hexdigest()}
    mid = db.upsert_media(
        dict(
            root_id=root,
            kind="photo",
            path=str(source),
            filename=source.name,
            size_bytes=source.stat().st_size,
            width=640,
            height=360,
            duration_s=None,
            has_srt=0,
            has_lrf=0,
        )
    )
    cid, _ = db.add_studio_item(
        str(source),
        identity_key=source.name,
        filename=source.name,
        kind="photo",
        recorded_at=None,
        project_id=project.id,
        source_media_id=mid,
    )

    port, debug = free_port(), free_port()
    repo = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(repo / "src"),
        ORGA_DRONE_DATA_DIR=str(data),
        ORGA_DRONE_HOST="127.0.0.1",
        ORGA_DRONE_PORT=str(port),
        ORGA_DRONE_GEOCODE="off",
        ORGA_DRONE_E2E="1",
        ORGA_DRONE_CDP_PORT=str(debug),
    )
    env.pop("ORGA_DRONE_BROWSER", None)
    base = f"http://127.0.0.1:{port}"
    cdp = None
    with (out / "app.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "orga_drone"],
            cwd=repo,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    result: dict[str, Any] = {"status": "INCOMPLETE", "cases": []}

    def ev(expression: str) -> Any:
        assert cdp
        return cdp.evaluate(expression, await_promise=True, user_gesture=True)

    def until(expression: str, timeout_s: float = 30) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if ev(expression):
                return
            time.sleep(0.05)
        raise AssertionError("Timed out: " + expression)

    try:
        result["browser"] = wait_cdp(debug, 120)["Browser"]
        result["source_hashes"] = originals
        cdp = _harness.CDP(wait_page_target(debug, 120)["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            dict(width=1600, height=1000, deviceScaleFactor=1, mobile=False),
        )
        cdp.call("Page.navigate", {"url": base + f"/studio?project_id={project.id}"})
        until("!!document.getElementById('studio-grid')")
        ev(
            f"(()=>{{let e=document.querySelector('#studio-grid [data-select-clip=\"{cid}\"]');"
            f"let r=e.getBoundingClientRect();"
            f"e.dispatchEvent(new MouseEvent('click',{{bubbles:true,clientX:r.x+1}}));"
            f"document.querySelector('[data-inspector-tab-button=image]').click();}})()"
        )
        until(
            f"document.querySelector('#studio-grid .studio-clip.is-selected')"
            f"?.dataset.studioId === '{cid}'"
        )

        creative = ev(
            "(()=>{const p=document.getElementById('inspector-image-panel');"
            "const s=document.getElementById('inspector-image-section-scopes');"
            "return {mode:p.dataset.imageMode,"
            "hidden:getComputedStyle(s).display==='none'};})()"
        )
        assert creative["mode"] == "creative", creative
        assert creative["hidden"] is True, creative
        result["cases"].append({"name": "creative_hides_scopes", "ok": True})

        pro = ev(
            "(()=>{document.querySelector('[data-image-mode=pro]').click();"
            "const s=document.getElementById('inspector-image-section-scopes');"
            "if(s && !s.open) s.open=true;"
            "return {mode:document.getElementById('inspector-image-panel').dataset.imageMode,"
            "hidden:getComputedStyle(s).display==='none',"
            "kinds:[...s.querySelectorAll('[data-scope-kind]')].map(b=>b.dataset.scopeKind)};})()"
        )
        assert pro["mode"] == "pro", pro
        assert pro["hidden"] is False, pro
        assert pro["kinds"] == ["histogram", "waveform", "parade", "vectorscope"], pro
        result["cases"].append({"name": "pro_reveals_four_scopes", "ok": True, "detail": pro})

        before = ev(
            "(()=>{const c=document.querySelector('#studio-grid .studio-clip.is-selected');"
            "return {image:c.dataset.imageAdjust||'', look:c.dataset.colorLook||'',"
            "hsl:c.dataset.hsl||'', wheels:c.dataset.colorWheels||''};})()"
        )
        fixture = ev(
            """(()=>{
              const root=document.getElementById('inspector-image-section-scopes');
              const enable=root.querySelector('[data-scope-fixture-enable]');
              enable.checked=true;
              enable.dispatchEvent(new Event('change',{bubbles:true}));
              root.querySelector('[data-scope-kind=vectorscope]').click();
              const disclosure=root.querySelector('[data-scope-disclosure]').textContent;
              const status=root.querySelector('[data-scope-status]').textContent;
              const c=document.querySelector('#studio-grid .studio-clip.is-selected');
              return {
                disclosure, status, fixtureMode: root.dataset.scopeFixtureMode,
                image:c.dataset.imageAdjust||'', look:c.dataset.colorLook||'',
                hsl:c.dataset.hsl||'', wheels:c.dataset.colorWheels||''
              };
            })()"""
        )
        assert fixture["fixtureMode"] == "1", fixture
        assert "test pattern" in fixture["disclosure"].lower() or "testmuster" in fixture["disclosure"].lower() or "not a measurement" in fixture["disclosure"].lower() or "keine messung" in fixture["disclosure"].lower(), fixture
        assert "not a media measurement" in fixture["status"].lower() or "keine medienmessung" in fixture["status"].lower() or "test pattern" in fixture["status"].lower(), fixture
        assert fixture["image"] == before["image"], fixture
        assert fixture["look"] == before["look"], fixture
        assert fixture["hsl"] == before["hsl"], fixture
        assert fixture["wheels"] == before["wheels"], fixture
        result["cases"].append({"name": "fixture_disclosure_no_grade_mutation", "ok": True})

        result["status"] = "PASS"
        result["clip_id"] = cid
    except Exception as exc:  # noqa: BLE001
        result["status"] = "FAIL"
        result["error"] = str(exc)
        raise
    finally:
        if cdp is not None:
            try:
                cdp.close()
            except Exception:  # noqa: BLE001
                pass
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.out)
    print(json.dumps({"status": "PASS", "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
