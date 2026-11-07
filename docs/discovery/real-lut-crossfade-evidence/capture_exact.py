import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging/e2e"))
from windows_e2e import AppProcess, navigate, wait_until
from studio_clock_probe import OBSERVE, SNAPSHOT
from studio_color_probe import image_bytes
import argparse

parser = argparse.ArgumentParser(
    description="Supplemental exact-coordinate paused captures on the collected isolated Stories."
)
parser.add_argument("--evidence-dir", required=True, type=Path)
parser.add_argument("--exe", required=True, type=Path)
args = parser.parse_args()
OUT = args.evidence_dir.resolve()
EXE = args.exe.resolve()
for mode in ["none", "same", "different", "mixed"]:
    out = OUT / mode
    app = AppProcess(EXE, out / "data")
    report = []
    try:
        app.start()
        cdp = app.require_cdp()
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1500, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )
        navigate(cdp, app.app_port, "/studio")
        wait_until(
            cdp,
            "document.getElementById('studio-preview-video')?.readyState>=2",
            timeout_s=30,
            description="preview",
        )
        cdp.evaluate(
            "document.getElementById('studio-preview-frame').style.cssText='width:640px;height:360px;max-width:none;border:0;padding:0;flex-shrink:0';document.querySelector('[data-timeline-zoom=fit]').click()"
        )
        cdp.evaluate(OBSERVE)
        for t in [2, 2.2, 2.5, 2.8, 3]:
            cdp.evaluate(
                """(()=>{const c=document.getElementById('studio-timeline-canvas');const total=Number(document.getElementById('studio-root').dataset.totalS);const x=c.getBoundingClientRect().left+document.getElementById('studio-timeline-scroll').clientWidth*"""
                + str(t)
                + """/total;const e=new MouseEvent('click',{bubbles:true});Object.defineProperty(e,'clientX',{value:x});document.getElementById('studio-ruler').dispatchEvent(e)})()"""
            )
            wait_until(
                cdp,
                "['studio-preview-video','studio-preview-video-b'].every(id=>{const v=document.getElementById(id);return v.hidden||(!v.seeking&&v.readyState>=2)})",
                timeout_s=30,
                description="seek",
            )
            time.sleep(0.5)
            snap = cdp.evaluate(SNAPSHOT)
            im = image_bytes(
                cdp.evaluate(
                    "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
                )
            )
            im.save(out / f"exact-preview-{t}.png")
            report.append({"requested_story_s": t, "state": snap})
        (out / "exact-paused.json").write_text(json.dumps(report, indent=2))
        print(mode, "exact captures", len(report), flush=True)
    finally:
        app.stop()
