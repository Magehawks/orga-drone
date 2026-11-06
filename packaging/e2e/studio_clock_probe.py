"""Observe existing packaged Story playback clocks and presented video frames.

Uses only existing cut/crossfade, real ruler seeks and transport. rVFC callbacks
observe presented frames; they never set source or Story time.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw

from windows_e2e import (  # type: ignore[import-not-found]
    AppProcess,
    E2EError,
    expect_ok,
    fetch_json,
    navigate,
    run_export,
    sha256_file,
    wait_until,
)


def summarize(report: dict) -> dict:
    """Missing presented frames are never treated as zero-error observations."""
    samples = report["playback"]
    if not samples:
        return {"status": "INSUFFICIENT_SAMPLES"}
    overlap = [
        s
        for s in samples
        if 2.1 < s["story"] < 2.9 and all(not v["hidden"] for v in s["videos"])
    ]
    if report["transition"] != "crossfade" or len(overlap) < 2:
        return {"status": "NOT_A_CROSSFADE_TRACE", "samples": len(samples)}
    primary = [
        s
        for s in overlap
        if s["videos"][0]["ready"] >= 2
        and not s["videos"][0]["paused"]
        and not s["videos"][0]["seeking"]
        and s["videos"][0]["src"] != s["videos"][1]["src"]
    ]
    if not primary:
        return {"status": "NO_PRIMARY_SAMPLES", "overlap_samples": len(overlap)}
    stable = [
        s
        for s in overlap
        if all(
            v["presented"]
            and not v["seeking"]
            and v["ready"] >= 2
            and v["presented"]["observedAt"] >= samples[0]["now"]
            for v in s["videos"]
        )
    ]
    paired = [
        abs(
            s["videos"][0]["presented"]["mediaTime"]
            + 2
            - s["videos"][1]["presented"]["mediaTime"]
        )
        for s in stable
    ]
    fresh_b = {
        s["videos"][1]["presented"]["observedAt"]
        for s in overlap
        if s["videos"][1]["presented"]
        and s["videos"][1]["presented"]["observedAt"] >= samples[0]["now"]
    }
    seek_overlap = [
        s
        for s in report.get("seeks", [])
        if 2.0 <= s["story"] <= 3.0 and all(not v["hidden"] for v in s["videos"])
    ]
    primary_seek = [
        abs(s["videos"][0]["currentTime"] - (s["story"] - 2)) for s in seek_overlap
    ]
    outgoing_seek = [
        abs(s["videos"][1]["currentTime"] - s["story"]) for s in seek_overlap
    ]
    progress_error = []
    for s in seek_overlap:
        raw = s["videos"][0].get("opacity", "")
        try:
            progress_error.append(abs(float(raw) - (s["story"] - 2)))
        except (TypeError, ValueError):
            pass
    plateaus = []
    first = samples[0]
    for sample in samples[1:]:
        if abs(sample["story"] - first["story"]) > 0.0001:
            plateaus.append(sample["now"] - first["now"])
            first = sample
    return {
        "status": "OBSERVED",
        "samples": len(samples),
        "overlap_samples": len(overlap),
        "primary_samples": len(primary),
        "primary_story_drift_max_s": max(
            abs(s["videos"][0]["currentTime"] - (s["story"] - 2)) for s in primary
        ),
        "story_plateau_max_ms": max(plateaus, default=0),
        "outgoing_seek_delta": overlap[-1]["videos"][1]["events"]["seeking"]
        - overlap[0]["videos"][1]["events"]["seeking"],
        "fresh_outgoing_presentations": len(fresh_b),
        "paused_seek_samples": len(seek_overlap),
        "paused_seek_primary_error_max_s": max(primary_seek) if primary_seek else None,
        "paused_seek_outgoing_error_max_s": max(outgoing_seek) if outgoing_seek else None,
        "paused_seek_progress_error_max": max(progress_error) if progress_error else None,
        "stable_presented_pairs": len(paired),
        "presented_pair_drift_max_s": max(paired) if paired else None,
        "presented_pair_drift_p95_s": sorted(paired)[int(0.95 * (len(paired) - 1))]
        if paired
        else None,
    }


def fixture(ffmpeg: str, path: Path, incoming: bool) -> None:
    frames = []
    for n in range(90):
        image = Image.new(
            "RGB", (640, 360), (55, 120, 185) if incoming else (180, 100, 60)
        )
        draw = ImageDraw.Draw(image)
        x = 60 + n * (3 if incoming else 2)
        draw.rectangle((x, 230, x + 48, 310), fill=(210, 210, 210))
        draw.rectangle((0, 180, 639, 195), fill=(40, 40, 40))
        frames.append(image.tobytes())
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "640x360",
            "-r",
            "30",
            "-i",
            "-",
            "-an",
            "-vf",
            "scale=1280:720:out_color_matrix=bt709:out_range=tv,format=yuv420p,"
            "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "10",
            str(path),
        ],
        input=b"".join(frames),
        capture_output=True,
        check=False,
        timeout=90,
    )
    if result.returncode:
        raise E2EError(result.stderr.decode(errors="replace"))


OBSERVE = """(() => {
 const p={frames:{},events:{}}; window.__storyClockProbe=p;
 for(const id of ['studio-preview-video','studio-preview-video-b']) {
  const v=document.getElementById(id);p.events[id]={timeupdate:0,seeking:0,seeked:0};
  for(const e of ['timeupdate','seeking','seeked'])v.addEventListener(e,()=>p.events[id][e]++);
  const observe=(now,m)=>{p.frames[id]={mediaTime:m.mediaTime,expectedDisplayTime:m.expectedDisplayTime,
    presentedFrames:m.presentedFrames,observedAt:now,src:v.currentSrc};v.requestVideoFrameCallback(observe)};
  v.requestVideoFrameCallback(observe);
 }
})()"""

SNAPSHOT = """(() => {
 const p=window.__storyClockProbe;
 const total=Number(document.getElementById('studio-root').dataset.totalS);
 const story=parseFloat(document.getElementById('studio-playhead').style.left)/document.getElementById('studio-timeline-scroll').clientWidth*total;
 return {now:performance.now(),story,total,videos:['studio-preview-video','studio-preview-video-b'].map(id=>{
  const v=document.getElementById(id);return {id,hidden:v.hidden,paused:v.paused,seeking:v.seeking,
    ready:v.readyState,currentTime:v.currentTime,src:v.currentSrc,opacity:v.style.opacity,
    presented:p.frames[id]||null,events:{...p.events[id]}};})};
})()"""


def seek(cdp, t: float) -> None:
    cdp.evaluate(f"""(() => {{const c=document.getElementById('studio-timeline-canvas');
      const total=Number(document.getElementById('studio-root').dataset.totalS);
      const x=c.getBoundingClientRect().left+document.getElementById('studio-timeline-scroll').clientWidth*{t}/total;
      document.getElementById('studio-ruler').dispatchEvent(new MouseEvent('click',{{bubbles:true,clientX:x}}));}})()""")
    wait_until(
        cdp,
        "['studio-preview-video','studio-preview-video-b'].every(id=>{const v=document.getElementById(id);return v.hidden||(!v.seeking&&v.readyState>=2)})",
        timeout_s=15,
        description="paused seek",
    )
    time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--transition", choices=["cut", "fade_black", "crossfade"], default="crossfade"
    )
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Use a new/empty output directory")
    out.mkdir(parents=True, exist_ok=True)
    library, data = out / "library", out / "data"
    library.mkdir()
    data.mkdir()
    report: dict = {
        "status": "INCOMPLETE",
        "transition": args.transition,
        "errors": [],
        "seeks": [],
        "playback": [],
    }
    report_path = out / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    app = None
    try:
        report["exe_sha256"] = sha256_file(args.exe)
        report["studio_js_sha256"] = sha256_file(
            args.exe.resolve().parent / "_internal/orga_drone/static/js/studio.js"
        )
        files = [library / "clock-a.mp4", library / "clock-b.mp4"]
        for i, path in enumerate(files):
            fixture(args.ffmpeg, path, bool(i))
            os.utime(path, (1700000000 + i * 86400,) * 2)
        hashes = {p.name: sha256_file(p) for p in files}
        app = AppProcess(args.exe.resolve(), data)
        app.start()
        cdp = app.require_cdp()
        report["browser"] = cdp.call("Browser.getVersion")
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1500, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )
        navigate(cdp, app.app_port, "/")
        expect_ok(
            fetch_json(
                cdp,
                "/library/add",
                method="POST",
                form_body={"path": str(library), "label": "Synthetic clock controls"},
            ),
            "scan",
        )
        deadline = time.monotonic() + 90
        while True:
            found = expect_ok(
                fetch_json(cdp, "/api/search", method="POST", json_body={"q": ""}),
                "find",
            )
            ids = {it["filename"]: it["id"] for it in found["items"]}
            if all(p.name in ids for p in files):
                break
            if time.monotonic() > deadline:
                raise E2EError("Synthetic scan incomplete")
            time.sleep(0.5)
        pid = expect_ok(
            fetch_json(
                cdp,
                "/api/studio/projects",
                method="POST",
                json_body={"title": "Existing clock control"},
            ),
            "create",
        )["id"]
        expect_ok(
            fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"), "open"
        )
        for p in files:
            expect_ok(
                fetch_json(
                    cdp,
                    f"/media/{ids[p.name]}/studio/add",
                    method="POST",
                    form_body={"return_to": "studio"},
                ),
                "add",
            )
        navigate(cdp, app.app_port, "/studio")
        wait_until(
            cdp,
            "document.querySelectorAll('.studio-clip').length===2",
            timeout_s=30,
            description="Story",
        )
        clip_ids = cdp.evaluate(
            "[...document.querySelectorAll('.studio-clip')].map(c=>c.dataset.studioId)"
        )
        expect_ok(
            fetch_json(
                cdp,
                f"/api/studio/{clip_ids[0]}/transition",
                method="PATCH",
                json_body={"type": args.transition, "duration_s": 1},
            ),
            "existing transition",
        )
        exported = out / "story-export.mp4"
        run_export(cdp, pid, exported)
        report["export_sha256"] = sha256_file(exported)
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
        for index, t in enumerate([0, 1.5, 2, 2.5, 3, 3.2, 4.5]):
            seek(cdp, t)
            state = cdp.evaluate(SNAPSHOT)
            report["seeks"].append(state)
            c = cdp.evaluate(
                "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
            )
            (out / f"seek-{index}.png").write_bytes(base64.b64decode(c))
        seek(cdp, 1.4)
        cdp.evaluate(
            "document.querySelector('[data-transport=toggle]').click()",
            user_gesture=True,
        )
        samples = cdp.evaluate(
            """new Promise(resolve=>{const samples=[];const start=performance.now();
          const collect=()=>{samples.push("""
            + SNAPSHOT
            + """);
            if(performance.now()-start>2600){resolve(samples);return;}requestAnimationFrame(collect);};
          requestAnimationFrame(collect);})""",
            await_promise=True,
        )
        report["playback"] = samples
        cdp.evaluate("document.querySelector('[data-transport=toggle]').click()")
        shot = cdp.call("Page.captureScreenshot", {"format": "png"})
        (out / "studio-after-playback.png").write_bytes(base64.b64decode(shot["data"]))
        report["sources_unchanged"] = hashes == {p.name: sha256_file(p) for p in files}
        report["summary"] = summarize(report)
        report["status"] = "COMPLETE_DIAGNOSTIC_NOT_PARITY_APPROVAL"
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if app:
            try:
                app.stop()
            except Exception as exc:  # noqa: BLE001
                report["status"] = "INCOMPLETE"
                report["errors"].append(str(exc))
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "samples": len(report["playback"]),
                "errors": report["errors"],
            }
        )
    )
    return 0 if report["status"] == "COMPLETE_DIAGNOSTIC_NOT_PARITY_APPROVAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
