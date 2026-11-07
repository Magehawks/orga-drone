import sys
import json
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging/e2e"))
from windows_e2e import AppProcess, navigate, wait_until
from studio_clock_probe import OBSERVE, SNAPSHOT, seek
import argparse

parser = argparse.ArgumentParser(
    description="Repeated crop captures of the existing isolated real-footage Stories. Captures add load; keep timing runs separate."
)
parser.add_argument("--evidence-dir", required=True, type=Path)
parser.add_argument("--exe", required=True, type=Path)
args = parser.parse_args()
OUT = args.evidence_dir.resolve()
EXE = args.exe.resolve()
for mode in ["none", "same", "different", "mixed"]:
    out = OUT / mode
    app = AppProcess(EXE, out / "data")
    records = []
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
        for kind, start, duration in [
            ("continuous", 1.3, 2200),
            ("inside", 2.25, 1000),
        ]:
            for n in range(10):
                cdp.evaluate(
                    "(()=>{if(!document.getElementById('studio-preview-video').paused)document.querySelector('[data-transport=toggle]').click()})()"
                )
                seek(cdp, start)
                cdp.evaluate(
                    "document.querySelector('[data-transport=toggle]').click()",
                    user_gesture=True,
                )
                frames = cdp.evaluate(
                    """new Promise(resolve=>{const frames=[];let last=0;const start=performance.now();const c=document.createElement('canvas');c.width=200;c.height=160;const x=c.getContext('2d');function tick(now){if(now-last>=32){last=now;x.drawImage(document.getElementById('studio-preview-blit'),440,0,200,160,0,0,200,160);frames.push({now,story:"""
                    + SNAPSHOT
                    + """.story,jpeg:c.toDataURL('image/jpeg',.95).split(',')[1]})}if(now-start>"""
                    + str(duration)
                    + """){resolve(frames);return}requestAnimationFrame(tick)}requestAnimationFrame(tick)})""",
                    await_promise=True,
                )
                cdp.evaluate(
                    "(()=>{if(!document.getElementById('studio-preview-video').paused)document.querySelector('[data-transport=toggle]').click()})()"
                )
                folder = out / "repeated-visual" / f"{kind}-{n + 1:02d}"
                folder.mkdir(parents=True, exist_ok=True)
                for i, f in enumerate(frames):
                    (folder / f"{i:04d}.jpg").write_bytes(
                        base64.b64decode(f.pop("jpeg"))
                    )
                (folder / "timestamps.json").write_text(json.dumps(frames))
                records.append({"kind": kind, "run": n + 1, "frames": len(frames)})
                (out / "repeated-visual.json").write_text(json.dumps(records, indent=2))
        print(mode, "repeated visual", len(records), flush=True)
    finally:
        app.stop()
