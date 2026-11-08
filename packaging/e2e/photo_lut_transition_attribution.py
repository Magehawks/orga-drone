"""Analysis-only exact-alpha and standalone-video controls for synthetic probe data."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from studio_clock_probe import seek
from studio_color_probe import compare, export
from studio_photo_lut_probe import capture, patch, reference
from windows_e2e import AppProcess, expect_ok, fetch_json, navigate


def run(args) -> None:
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    fixture = args.fixture_run.resolve()
    original = json.loads((fixture / "report.json").read_text(encoding="utf-8"))
    if not original["synthetic_only"] or not original["sources_unchanged"]:
        raise ValueError("Requires completed synthetic photo probe data")
    data = fixture / "data"
    with sqlite3.connect((data / "orga-drone.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        projects = dict(db.execute("select title,id from studio_projects"))
        video_id = db.execute("select id from media where filename='swatches.mp4'").fetchone()[0]
    app = AppProcess(args.exe.resolve(), data)
    report = {"synthetic_only": True, "controls": []}
    try:
        app.start()
        cdp = app.require_cdp()
        cdp.call("Emulation.setDeviceMetricsOverride", dict(width=1500, height=1000, deviceScaleFactor=1, mobile=False))
        navigate(cdp, app.app_port, "/")

        def open_project(pid):
            expect_ok(fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"), "open")
            navigate(cdp, app.app_port, "/studio")
            cdp.evaluate("if(document.getElementById('studio-preview-frame')) document.getElementById('studio-preview-frame').style.cssText="
                         "'width:640px;height:360px;max-width:none;border:0;padding:0;flex-shrink:0';"
                         "document.querySelector('[data-timeline-zoom=fit]')?.click()")

        open_project(projects["Synthetic photo LUT photos-different"])
        for point in (2.25, 2.5, 2.75):
            seek(cdp, point)
            time.sleep(0.8)
            before, state = capture(cdp)
            ref, index = reference(args.ffmpeg, fixture / "photos-different/export.mp4", state["time"])
            alpha = (index / 30) - 2
            cdp.evaluate("(()=>{const m=document.getElementById('studio-preview-image');m.style.opacity=" +
                         json.dumps(str(alpha)) + ";m.dispatchEvent(new Event('load'))})()")
            time.sleep(0.1)
            aligned, _ = capture(cdp)
            report["controls"].append({"name": "photos-exact-alpha", "state": state,
                "export_frame": index, "controlled_alpha": alpha,
                "before": compare(before, ref), "aligned": compare(aligned, ref)})
            aligned.save(out / f"photos-aligned-{index}.png")
        open_project(projects["Synthetic photo LUT photo-video"])
        look = cdp.evaluate("JSON.parse(document.querySelectorAll('.studio-clip')[1].dataset.colorLook)")
        pid = expect_ok(fetch_json(cdp, "/api/studio/projects", method="POST",
                                   json_body={"title": "Synthetic standalone video attribution"}), "project")["id"]
        open_project(pid)
        expect_ok(fetch_json(cdp, f"/media/{video_id}/studio/add", method="POST", form_body={"return_to": "studio"}), "add")
        open_project(pid)
        clip = cdp.evaluate("document.querySelector('.studio-clip').dataset.studioId")
        patch(cdp, clip, "color", look)
        open_project(pid)
        output = out / "video-export.mp4"
        export(cdp, pid, output)
        for label, playing in (("paused", False), ("playing", True), ("after-pause", False)):
            if label == "paused":
                seek(cdp, 1)
            else:
                cdp.evaluate("document.querySelector('[data-transport=toggle]').click()", user_gesture=True)
            time.sleep(0.6)
            preview, state = capture(cdp)
            ref, index = reference(args.ffmpeg, output, state["time"])
            preview.save(out / f"video-{label}-preview.png")
            ref.save(out / f"video-{label}-export.png")
            report["controls"].append({"name": "video-" + label, "playing": playing,
                "state": state, "export_frame": index, "comparison": compare(preview, ref)})
    finally:
        app.stop()
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--fixture-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
