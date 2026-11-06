"""Nonshipping #301 gate: actual Story canvas, seek, playback and app MP4 export.

Requires a onefolder candidate with the soft_wipe_left experiment applied.
No DOM document replacement, fake clocks, or direct calls to renderer internals.
All media and application state are synthetic and isolated under --output-dir.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import subprocess
import time
from pathlib import Path
from typing import cast

from PIL import Image, ImageChops, ImageDraw, ImageStat

from windows_e2e import (  # type: ignore[import-not-found]
    AppProcess, E2EError, expect_ok, fetch_json, navigate,
    sha256_file, wait_until,
)

W, H, FPS = 640, 360, 30
# Locked before the first run. Errors are measured in 8-bit RGB levels.
CRITERIA = {
    "region_mean_rgb_max": 3.0,
    "region_p95_max_channel_error_max": 6,
    "alpha_profile_max_error": 0.03,
    "midpoint_reveal_position_error_px_max": 2,
    "source_clock_error_s_max": 1 / FPS,
    "reference_frame_tolerance": 1,
}
REGIONS = {
    "full": (0, 0, W, H),
    "left_edge": (0, 0, 64, H),
    "right_edge": (W - 64, 0, W, H),
    "center": (288, 0, 352, H),
    "motion": (0, 220, W, 330),
}


def ffmpeg(binary: str, args: list[str], data: bytes | None = None) -> bytes:
    done = subprocess.run(
        [binary, "-hide_banner", "-loglevel", "error", "-y", *args],
        input=data, capture_output=True, check=False, timeout=120,
    )
    if done.returncode:
        raise E2EError(done.stderr.decode(errors="replace"))
    return done.stdout


def make_video(binary: str, target: Path, incoming: bool) -> None:
    frames = []
    for n in range(90):
        image = Image.new("RGB", (W, H), (55, 120, 185) if incoming else (180, 100, 60))
        draw = ImageDraw.Draw(image)
        x = 60 + n * (3 if incoming else 2)
        draw.rectangle((x, 230, x + 48, 310), fill=(210, 210, 210))
        draw.rectangle((0, 180, W, 195), fill=(40, 40, 40))
        frames.append(image.tobytes())
    ffmpeg(binary, [
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "30",
        "-i", "-", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10",
        "-vf", "scale=1280:720", "-pix_fmt", "yuv420p", str(target),
    ], b"".join(frames))


def percentile95(image: Image.Image) -> int:
    channels = image.split()
    maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    histogram = maximum.histogram()
    goal = image.width * image.height * .95
    count = 0
    for value, n in enumerate(histogram):
        count += n
        if count >= goal:
            return value
    return 255


def metrics(preview: Image.Image, reference: Image.Image) -> dict[str, dict[str, float]]:
    result = {}
    diff = ImageChops.difference(preview, reference)
    for name, box in REGIONS.items():
        roi = diff.crop(box)
        result[name] = {
            "mean_rgb": sum(ImageStat.Stat(roi).mean) / 3,
            "p95_max_channel_error": percentile95(roi),
        }
    return result


def regions_pass(values: dict[str, dict[str, float]]) -> bool:
    return all(
        m["mean_rgb"] <= CRITERIA["region_mean_rgb_max"]
        and m["p95_max_channel_error"] <= CRITERIA["region_p95_max_channel_error_max"]
        for m in values.values()
    )


CAPTURE = """(() => {
 const c=document.getElementById('studio-preview-blit');
 const grid=document.getElementById('studio-timeline-canvas');
 const total=Number(document.getElementById('studio-root').dataset.totalS);
 const t=parseFloat(document.getElementById('studio-playhead').style.left)/document.getElementById('studio-timeline-scroll').clientWidth*total;
 const videos=['studio-preview-video','studio-preview-video-b'].map(id=>{
   const v=document.getElementById(id); return {id,hidden:v.hidden,paused:v.paused,
      time:v.currentTime,seeking:v.seeking,ready:v.readyState,src:v.currentSrc}; });
 return {time:t, videos, canvasHidden:c.hidden, width:c.width,height:c.height,
   png:c.toDataURL('image/png').split(',')[1]};
})()"""


def seek(cdp, seconds: float) -> None:
    cdp.evaluate(f"""(() => {{
      const c=document.getElementById('studio-timeline-canvas');
      const total=Number(document.getElementById('studio-root').dataset.totalS);
      const x=c.getBoundingClientRect().left+document.getElementById('studio-timeline-scroll').clientWidth*{seconds}/total;
      document.querySelector('.studio-ruler').dispatchEvent(new MouseEvent('click',{{bubbles:true,clientX:x}}));
    }})()""")
    wait_until(cdp, "['studio-preview-video','studio-preview-video-b'].every(id=>{const v=document.getElementById(id);return v.hidden||(!v.seeking&&v.readyState>=2)})",
               timeout_s=15, description="seek settled")
    cdp.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))", await_promise=True)
    time.sleep(.15)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("--output-dir must be new or empty; existing evidence is never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    library, data = output / "library", output / "data"
    library.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    report: dict = {"decision": "NO-GO", "phase": "setup", "criteria": CRITERIA, "samples": [],
                    "scope": "neutral 720p sources/export, 640x360 visible preview, no audio/other effects", "errors": []}
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    app = None
    try:
        report["exe_sha256"] = sha256_file(args.exe)
        report["packaged_static_sha256"] = {
            name: sha256_file(args.exe.resolve().parent / "_internal/orga_drone/static/js" / name)
            for name in ("studio.js", "studio/soft-wipe.js")
        }
        report["ffmpeg_version"] = ffmpeg(args.ffmpeg, ["-version"]).decode().splitlines()[0]
        paths = [library / "wipe-a.mp4", library / "wipe-b.mp4"]
        for i, path in enumerate(paths):
            make_video(args.ffmpeg, path, bool(i))
            # Different synthetic dates avoid the normal library session collapse.
            stamp = 1700000000 + i * 86400
            os.utime(path, (stamp, stamp))
        hashes = {p.name: sha256_file(p) for p in paths}
        app = AppProcess(args.exe.resolve(), data)
        app.start()
        cdp = app.require_cdp()
        report["browser"] = cdp.call("Browser.getVersion")
        navigate(cdp, app.app_port, "/")
        result = fetch_json(cdp, "/library/add", method="POST", form_body={"path":str(library), "label":"Synthetic wipe gate"})
        expect_ok(result, "import")
        # Scan is asynchronous; search until both synthetic clips are available.
        deadline = time.monotonic() + 90
        while True:
            try:
                found = expect_ok(fetch_json(cdp, "/api/search", method="POST", json_body={"q":""}), "synthetic search")
                by_name = {item["filename"]:item["id"] for item in found["items"]}
                if not all(p.name in by_name for p in paths):
                    raise E2EError(f"Synthetic scan is not ready: {list(by_name)}")
                media = [by_name[p.name] for p in paths]
                break
            except E2EError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.5)
        project = expect_ok(fetch_json(cdp, "/api/studio/projects", method="POST", json_body={"title":"Soft wipe gate"}), "project")
        pid = project["id"]
        expect_ok(fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"), "open")
        for mid in media:
            expect_ok(fetch_json(cdp, f"/media/{mid}/studio/add", method="POST", form_body={"return_to":"studio"}), "add clip")
        navigate(cdp, app.app_port, "/studio")
        wait_until(cdp, "document.querySelectorAll('.studio-clip').length===2", timeout_s=30, description="two Story clips")
        ids = cdp.evaluate("[...document.querySelectorAll('.studio-clip')].map(c=>c.dataset.studioId)")
        expect_ok(fetch_json(cdp, f"/api/studio/{ids[0]}/transition", method="PATCH", json_body={"type":"soft_wipe_left","duration_s":1}), "wipe")
        exported = output / "story-export.mp4"
        started = expect_ok(fetch_json(cdp, "/api/studio/export", method="POST", json_body={"project_id":pid,"height":720,"quality":"best","output_path":str(exported)}), "export")
        deadline = time.monotonic() + 180
        while True:
            job = expect_ok(fetch_json(cdp, f"/api/studio/export/jobs/{started['job_id']}"), "export job")
            if job["state"] == "completed":
                break
            if job["state"] in {"failed","cancelled"} or time.monotonic() > deadline:
                raise E2EError(f"export failed: {job}")
            time.sleep(.5)
        report["export_sha256"] = sha256_file(exported)
        raw = ffmpeg(args.ffmpeg, ["-i",str(exported),"-vf",f"scale={W}:{H}","-f","rawvideo","-pix_fmt","rgb24","-"])
        size = W * H * 3
        references = [Image.frombytes("RGB", (W,H), raw[i:i+size]) for i in range(0,len(raw),size)]
        report["export_frames"] = len(references)
        cdp.call("Emulation.setDeviceMetricsOverride", {"width":1500,"height":1000,"deviceScaleFactor":1,"mobile":False})
        navigate(cdp, app.app_port, "/studio")
        wait_until(cdp, "document.querySelector('.studio-clip[data-applied-type=soft_wipe_left]')!==null", timeout_s=30, description="persisted wipe")
        # Resize the actual visible preview; do not replace its DOM/render code.
        cdp.evaluate("document.getElementById('studio-preview-frame').style.cssText='width:640px;height:360px;max-width:none;aspect-ratio:auto;border:0;padding:0;flex-shrink:0';document.querySelector('[data-timeline-zoom=fit]').click()")
        cdp.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))", await_promise=True)
        def capture(label: str, moving: bool) -> dict:
            sample = cdp.evaluate(CAPTURE)
            picture = Image.open(io.BytesIO(base64.b64decode(sample.pop("png")))).convert("RGB")
            if picture.size != (W,H) or sample["canvasHidden"]:
                raise E2EError(f"actual visible canvas is unavailable: {sample}")
            picture.save(output / f"{label}-preview.png")
            n = round(sample["time"] * FPS)
            candidates = [(j, metrics(picture, references[j])) for j in range(max(0,n-1),min(len(references),n+2))]
            best, values = min(candidates, key=lambda item: sum(m["mean_rgb"] for m in item[1].values()))
            references[best].save(output / f"{label}-export.png")
            sample.update({"label":label,"moving":moving,"reference_frame":best,"regions":values,"regions_pass":regions_pass(values)})
            # During overlap both sources must correspond to this actual Story time.
            clock_errors = []
            if moving and 2.05 < sample["time"] < 2.95:
                for v in sample["videos"]:
                    expected = sample["time"] - (2 if v["id"] == "studio-preview-video" else 0)
                    clock_errors.append(abs(v["time"]-expected))
                sample["clock_errors_s"] = clock_errors
            report["samples"].append(sample)
            return sample
        report["phase"] = "measuring"
        for index, t in enumerate([2-1/FPS,2,2+1/FPS,2.25,2.5,2.75,3-1/FPS,3,3+1/FPS]):
            seek(cdp,t)
            capture(f"seek-{index}",False)
            if index == 4:
                shot = cdp.call("Page.captureScreenshot", {"format":"png"})
                (output/"visible-studio-midpoint.png").write_bytes(base64.b64decode(shot["data"]))
        seek(cdp,1.7)
        cdp.evaluate("document.querySelector('[data-transport=toggle]').click()",user_gesture=True)
        deadline = time.monotonic()+8
        moving: list[dict] = []
        while time.monotonic() < deadline:
            sample = capture(f"play-{len(moving):02d}",True)
            moving.append(sample)
            if sample["time"] > 3.1:
                break
            time.sleep(.04)
        cdp.evaluate("document.querySelector('[data-transport=toggle]').click()")
        report["source_unchanged"] = hashes == {p.name:sha256_file(p) for p in paths}
        overlap = [s for s in moving if "clock_errors_s" in s]
        if len(overlap) < 3 or moving[-1]["time"] < 3.1 or overlap[-1]["time"] - overlap[0]["time"] < .5:
            report["errors"].append("Playback did not traverse the overlap")
        if overlap and any(overlap[-1]["videos"][i]["time"] <= overlap[0]["videos"][i]["time"] for i in (0,1)):
            report["errors"].append("Both source pictures did not advance")
        if any(not s["regions_pass"] for s in report["samples"]):
            report["errors"].append("Spatial parity criteria failed")
        if any(max(s["clock_errors_s"]) > 1/FPS for s in overlap):
            report["errors"].append("Moving source clock differs by more than one output frame")
        if not report["source_unchanged"]:
            report["errors"].append("Source hashes changed")
        # Alpha/position analysis is required even if spatial or temporal checks fail.
        midpoint = Image.open(output/"seek-4-preview.png").convert("RGB")
        outgoing = cast(tuple[int, int, int], references[0].getpixel((0,40)))
        incoming = cast(tuple[int, int, int], references[-1].getpixel((0,40)))
        channel = max(range(3),key=lambda ch:abs(incoming[ch]-outgoing[ch]))
        measured = [(cast(tuple[int, int, int], midpoint.getpixel((x,40)))[channel]-outgoing[channel])/(incoming[channel]-outgoing[channel]) for x in range(W)]
        expected = [(x/W)**2*(3-2*x/W) for x in range(W)]
        report["midpoint_alpha_max_error"] = max(abs(a-b) for a,b in zip(measured,expected))
        report["midpoint_reveal_position_error_px"] = abs(min(range(W),key=lambda x:abs(measured[x]-.5))-W/2)
        if report["midpoint_alpha_max_error"] > .03 or report["midpoint_reveal_position_error_px"] > 2:
            report["errors"].append("Alpha/reveal position criteria failed")
        if not report["errors"]:
            report["decision"] = "GO_NEUTRAL_SPIKE_ONLY"
        report["phase"] = "measured"
    except Exception as exc:  # noqa: BLE001 - preserve negative gate evidence
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if app:
            try:
                app.stop()
            except Exception as exc:  # noqa: BLE001 - retain report after cleanup failure
                report["decision"] = "NO-GO"
                report["errors"].append(f"Cleanup failed: {type(exc).__name__}: {exc}")
        report_path.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "samples"},indent=2))
    return 0 if report["decision"] == "GO_NEUTRAL_SPIKE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
