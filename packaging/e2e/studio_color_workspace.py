"""Focused Windows/WebView2 source-app journey for Creative/Pro color workspace.

Validates mode switching, Quick Look race safety across clip selection, and the
grade-summary update after Pro HSL edits. Synthetic media only. Not packaged/MOTW.
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
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

_spec = importlib.util.spec_from_file_location(
    "color_workspace_windows_e2e", Path(__file__).with_name("windows_e2e.py")
)
assert _spec and _spec.loader
_harness: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)
free_port = _harness.free_port
wait_cdp, wait_page_target = _harness.wait_cdp, _harness.wait_page_target


def run(out: Path) -> None:
    from orga_drone.config import Settings
    from orga_drone.db import Database
    from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs

    out.mkdir(parents=True, exist_ok=False)
    data, media = out / "data", out / "media"
    media.mkdir()
    ffmpeg = find_ffmpeg()
    assert ffmpeg
    Image.new("RGB", (640, 360), (80, 120, 160)).save(media / "clip-a.jpg")
    Image.new("RGB", (640, 360), (160, 90, 60)).save(media / "clip-b.jpg")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x5078a0:s=640x360:r=30:d=1",
            "-pix_fmt",
            "yuv420p",
            str(media / "clip-c.mp4"),
        ],
        check=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    )
    db = Database(Settings(data_dir=data).db_path)
    root = db.add_root(media, label="Synthetic color workspace")
    project = db.create_studio_project("Synthetic color workspace")
    ids: list[int] = []
    originals: dict[str, str] = {}
    for source in sorted(media.iterdir()):
        kind = "video" if source.suffix == ".mp4" else "photo"
        originals[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        mid = db.upsert_media(
            dict(
                root_id=root,
                kind=kind,
                path=str(source),
                filename=source.name,
                size_bytes=source.stat().st_size,
                width=640,
                height=360,
                duration_s=1 if kind == "video" else None,
                has_srt=0,
                has_lrf=0,
            )
        )
        cid, _ = db.add_studio_item(
            str(source),
            identity_key=source.name,
            filename=source.name,
            kind=kind,
            recorded_at=None,
            project_id=project.id,
            source_media_id=mid,
        )
        ids.append(cid)

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

    def select(cid: int) -> None:
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
        select(ids[0])

        mode = ev(
            "(()=>{const p=document.getElementById('inspector-image-panel');"
            "return {mode:p.dataset.imageMode,"
            "hslHidden:getComputedStyle(document.getElementById('inspector-image-section-hsl')).display==='none',"
            "summary:document.getElementById('studio-color-grade-summary').textContent};})()"
        )
        assert mode["mode"] == "creative", mode
        assert mode["hslHidden"] is True, mode
        result["cases"].append({"name": "creative_default_hides_hsl", "ok": True})

        switched = ev(
            "(()=>{document.querySelector('[data-image-mode=pro]').click();"
            "const p=document.getElementById('inspector-image-panel');"
            "return {mode:p.dataset.imageMode,"
            "hslHidden:getComputedStyle(document.getElementById('inspector-image-section-hsl')).display==='none'};})()"
        )
        assert switched["mode"] == "pro", switched
        assert switched["hslHidden"] is False, switched
        result["cases"].append({"name": "pro_reveals_hsl", "ok": True})

        look_race = ev(
            f"""(async()=>{{
              const a=document.querySelector('#studio-grid [data-select-clip="{ids[0]}"]');
              const b=document.querySelector('#studio-grid [data-select-clip="{ids[1]}"]');
              a.dispatchEvent(new MouseEvent('click',{{bubbles:true}}));
              document.querySelector('[data-inspector-tab-button=image]').click();
              const chip=document.querySelector('[data-quick-look-chip=\"cinematic\"]');
              const pending=chip.click();
              b.dispatchEvent(new MouseEvent('click',{{bubbles:true}}));
              document.querySelector('[data-inspector-tab-button=image]').click();
              await Promise.resolve(pending);
              await new Promise(r=>setTimeout(r,250));
              const selected=document.querySelector('#studio-grid .studio-clip.is-selected');
              const selectEl=document.getElementById('inspector-quick-look');
              return {{
                selectedId: selected && selected.dataset.studioId,
                look: selectEl && selectEl.value,
                chip: document.querySelector('[data-quick-look-chip=\"cinematic\"]')?.getAttribute('aria-checked'),
                aLook: a.dataset.quickLook || '',
                bLook: b.dataset.quickLook || ''
              }};
            }})()"""
        )
        assert str(look_race["selectedId"]) == str(ids[1]), look_race
        assert look_race["look"] != "cinematic" or look_race["bLook"] == "cinematic", look_race
        # Clip B must keep its own UI; A's cinematic must not become B's visible look unless B also got it.
        assert look_race["look"] == (look_race["bLook"] or ""), look_race
        assert look_race["chip"] == ("true" if look_race["look"] == "cinematic" else "false"), look_race
        result["cases"].append({"name": "quick_look_clip_switch_race", "ok": True, "detail": look_race})

        hsl_summary = ev(
            f"""(async()=>{{
              const a=document.querySelector('#studio-grid [data-select-clip="{ids[0]}"]');
              a.dispatchEvent(new MouseEvent('click',{{bubbles:true}}));
              document.querySelector('[data-inspector-tab-button=image]').click();
              document.querySelector('[data-image-mode=pro]').click();
              const section=document.getElementById('inspector-image-section-hsl');
              if (section && !section.open) section.open = true;
              const hue=document.getElementById('inspector-hsl-hue');
              hue.value='40';
              hue.dispatchEvent(new Event('input',{{bubbles:true}}));
              hue.dispatchEvent(new Event('change',{{bubbles:true}}));
              await new Promise(r=>setTimeout(r,200));
              return document.getElementById('studio-color-grade-summary').textContent;
            }})()"""
        )
        assert "HSL" in str(hsl_summary) or "HSL aktiv" in str(hsl_summary), hsl_summary
        result["cases"].append({"name": "hsl_updates_grade_summary", "ok": True, "summary": hsl_summary})

        compare = ev(
            "(()=>{const btn=document.getElementById('inspector-look-compare');"
            "return {disabled:btn.disabled,label:btn.textContent.trim()};})()"
        )
        assert compare["disabled"] is False, compare
        result["cases"].append({"name": "hold_to_compare_enabled", "ok": True})

        result["status"] = "PASS"
        result["clip_ids"] = ids
    except Exception as exc:  # noqa: BLE001 - report full journey failure
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
