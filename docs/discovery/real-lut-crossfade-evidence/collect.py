"""Packaged real-footage evidence collector. Outputs are private; never stage them."""

import argparse
import sys
import json
import base64
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging/e2e"))
from windows_e2e import (
    AppProcess,
    expect_ok,
    fetch_json,
    navigate,
    wait_until,
    sha256_file,
)
from studio_clock_probe import OBSERVE, SNAPSHOT, seek
from studio_crossfade_lut_probe import write_cube, decode_at
from studio_color_probe import export, image_bytes
from orga_drone.db import Database
from PIL import ImageChops, ImageStat

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--exe", required=True, type=Path)
parser.add_argument("--source-a", required=True, type=Path)
parser.add_argument("--source-b", required=True, type=Path)
parser.add_argument("--duration-a", required=True, type=float)
parser.add_argument("--duration-b", required=True, type=float)
parser.add_argument("--output-dir", required=True, type=Path)
parser.add_argument("modes", nargs="*", choices=["none", "same", "different", "mixed"])
args = parser.parse_args()
OUT = args.output_dir.resolve()
if OUT.exists():
    parser.error(
        "Use a fresh output directory; outputs can contain private images and paths."
    )
OUT.mkdir(parents=True)
SOURCES = [args.source_a.resolve(), args.source_b.resolve()]
DURATIONS = [args.duration_a, args.duration_b]
EXE = args.exe.resolve()
FF = next((EXE.parent / "_internal/imageio_ffmpeg/binaries").glob("*.exe"))


def patch(cdp, url, payload):
    return expect_ok(fetch_json(cdp, url, method="PATCH", json_body=payload), url)


def pause(cdp):
    cdp.evaluate(
        "(()=>{const b=document.querySelector('[data-transport=toggle]');if(document.getElementById('studio-root').dataset.playing==='1')b.click();})()"
    )
    # root has no authoritative playing attribute: native primary is authoritative here
    cdp.evaluate(
        "(()=>{const v=document.getElementById('studio-preview-video');if(!v.paused)document.querySelector('[data-transport=toggle]').click();})()"
    )


def capture(cdp):
    return image_bytes(
        cdp.evaluate(
            "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
        )
    )


def metrics(samples, baseline):
    pairs = []
    delays = [[], []]
    gaps = [[], []]
    seen = [set(), set()]
    for s in samples:
        if not 2 <= s["story"] <= 3:
            continue
        vs = s["videos"]
        if all(
            not v["hidden"]
            and not v["seeking"]
            and v["ready"] >= 2
            and v["presented"]
            and v["presented"]["observedAt"] >= baseline["now"]
            for v in vs
        ):
            pairs.append(
                abs(
                    vs[0]["presented"]["mediaTime"]
                    + 2
                    - vs[1]["presented"]["mediaTime"]
                )
            )
        for i, v in enumerate(vs):
            f = v["presented"]
            if (
                f
                and f["observedAt"] >= baseline["now"]
                and f["observedAt"] not in seen[i]
            ):
                if seen[i]:
                    gaps[i].append(f["observedAt"] - max(seen[i]))
                seen[i].add(f["observedAt"])
                delays[i].append(max(0, f["observedAt"] - f["expectedDisplayTime"]))
    overlap = [s for s in samples if 2 <= s["story"] <= 3]
    seeks = [s["videos"][1]["events"]["seeking"] for s in overlap]
    return {
        "paired_samples": len(pairs),
        "pair_drift_max_s": max(pairs) if pairs else None,
        "pair_drift_p95_s": sorted(pairs)[int(0.95 * (len(pairs) - 1))]
        if pairs
        else None,
        "outgoing_seeks_during_overlap": max(seeks) - min(seeks) if seeks else None,
        "outgoing_seeks_since_start": samples[-1]["videos"][1]["events"]["seeking"]
        - baseline["videos"][1]["events"]["seeking"],
        "callback_lateness_max_ms": [max(x, default=None) for x in delays],
        "presentation_gap_max_ms": [max(x, default=None) for x in gaps],
        "fresh_frames": [len(x) for x in seen],
    }


def collect(cdp, duration):
    return cdp.evaluate(
        "new Promise(resolve=>{const a=[];const start=performance.now();function tick(){a.push("
        + SNAPSHOT
        + ");if(performance.now()-start>"
        + str(duration)
        + "){resolve(a);return;}requestAnimationFrame(tick)}requestAnimationFrame(tick)})",
        await_promise=True,
    )


def run(mode):
    out = OUT / mode
    out.mkdir(exist_ok=True)
    data = out / "data"
    data.mkdir(exist_ok=True)
    db = Database(data / "orga-drone.sqlite3")
    ids = []
    for n, p in enumerate(SOURCES):
        root = db.add_root(p.parent, label="Read-only real footage")
        asset = db.upsert_asset(
            root_id=root,
            path=p,
            kind="video",
            size_bytes=p.stat().st_size,
            mtime=p.stat().st_mtime,
            stem_base=p.stem,
        )
        ids.append(
            db.upsert_media(
                dict(
                    root_id=root,
                    primary_asset_id=asset,
                    kind="video",
                    filename=p.name,
                    path=str(p),
                    size_bytes=p.stat().st_size,
                    duration_s=DURATIONS[n],
                    width=3840,
                    height=2160,
                    has_srt=0,
                    has_lrf=0,
                    drone_model="DJI Avata 2",
                    camera_model="FC8485",
                )
            )
        )
    report = {"mode": mode, "runs": [], "paused": [], "errors": []}
    app = AppProcess(EXE, data)
    try:
        app.start()
        cdp = app.require_cdp()
        report["browser"] = cdp.call("Browser.getVersion")
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            dict(width=1500, height=1000, deviceScaleFactor=1, mobile=False),
        )
        navigate(cdp, app.app_port, "/")
        pid = expect_ok(
            fetch_json(
                cdp,
                "/api/studio/projects",
                method="POST",
                json_body={"title": "Real Avata crossfade " + mode},
            ),
            "project",
        )["id"]
        expect_ok(
            fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"), "open"
        )
        for mid in ids:
            expect_ok(
                fetch_json(
                    cdp,
                    f"/media/{mid}/studio/add",
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
            description="clips",
        )
        clips = cdp.evaluate(
            "[...document.querySelectorAll('.studio-clip')].map(c=>c.dataset.studioId)"
        )
        for c in clips:
            patch(
                cdp,
                f"/api/studio/{c}/section",
                {"source_in_s": 10, "source_out_s": 13, "repeats": 1},
            )
        patch(
            cdp,
            f"/api/studio/{clips[0]}/transition",
            {"type": "crossfade", "duration_s": 1},
        )
        for i, c in enumerate(clips):
            if mode == "none" or mode == "mixed" and i == 1:
                continue
            variant = "blue" if mode == "different" and i == 1 else "red"
            cube = out / (variant + ".cube")
            write_cube(cube, size=17, variant=variant)
            asset = expect_ok(
                fetch_json(
                    cdp, "/api/luts", method="POST", json_body={"path": str(cube)}
                ),
                "lut",
            )["asset_name"]
            patch(
                cdp,
                f"/api/studio/{c}/color",
                {
                    "input_profile": "rec709",
                    "creative_lut": asset,
                    "creative_strength": 100,
                },
            )
        navigate(cdp, app.app_port, "/studio")
        wait_until(
            cdp,
            "document.getElementById('studio-preview-video')?.readyState>=2",
            timeout_s=45,
            description="preview",
        )
        cdp.evaluate(
            "document.getElementById('studio-preview-frame').style.cssText='width:640px;height:360px;max-width:none;border:0;padding:0;flex-shrink:0';document.querySelector('[data-timeline-zoom=fit]').click()"
        )
        cdp.evaluate(OBSERVE)
        cdp.evaluate(
            """(()=>{window.__allFrames=[];window.__seekEvents=[];for(const id of ['studio-preview-video','studio-preview-video-b']){const v=document.getElementById(id);v.addEventListener('seeking',()=>window.__seekEvents.push({id,now:performance.now()}));function f(now,m){window.__allFrames.push({id,now,mediaTime:m.mediaTime,expectedDisplayTime:m.expectedDisplayTime,presentationTime:m.presentationTime,processingDuration:m.processingDuration,presentedFrames:m.presentedFrames});v.requestVideoFrameCallback(f)}v.requestVideoFrameCallback(f)}})()"""
        )
        report["render_path"] = cdp.evaluate(
            "({webgl:document.getElementById('studio-preview-frame').dataset.lutWebgl})"
        )
        for kind, start, duration in [
            ("continuous", 1.3, 2100),
            ("inside", 2.25, 1000),
        ]:
            for n in range(10):
                pause(cdp)
                seek(cdp, start)
                base = cdp.evaluate(SNAPSHOT)
                cdp.evaluate(
                    "document.querySelector('[data-transport=toggle]').click()",
                    user_gesture=True,
                )
                samples = collect(cdp, duration)
                pause(cdp)
                callbacks = cdp.evaluate(
                    "window.__allFrames.filter(f=>f.now>=" + str(base["now"]) + ")"
                )
                (out / f"{kind}-{n + 1:02d}-callbacks.json").write_text(
                    json.dumps(callbacks)
                )
                m = metrics(samples, base)
                m["callback_frame_count"] = [
                    len([f for f in callbacks if f["id"] == v])
                    for v in ["studio-preview-video", "studio-preview-video-b"]
                ]
                m["decode_processing_max_ms"] = max(
                    [
                        f["processingDuration"] * 1000
                        for f in callbacks
                        if f.get("processingDuration") is not None
                    ],
                    default=None,
                )
                m["callback_lateness_all_max_ms"] = max(
                    [max(0, f["now"] - f["expectedDisplayTime"]) for f in callbacks],
                    default=None,
                )
                m.update(kind=kind, run=n + 1)
                report["runs"].append(m)
                (out / f"{kind}-{n + 1:02d}-trace.json").write_text(json.dumps(samples))
                (out / "report.json").write_text(json.dumps(report, indent=2))
        for n in range(10):
            for t in [2.25, 2.5, 2.75]:
                seek(cdp, t)
                im = capture(cdp)
                snap = cdp.evaluate(SNAPSHOT)
                im.save(out / f"paused-{n + 1:02d}-{t}.png")
                report["paused"].append(
                    {
                        "run": n + 1,
                        "story_s": t,
                        "brightness": sum(ImageStat.Stat(im).mean) / 3,
                        "state": snap,
                    }
                )
                (out / "report.json").write_text(json.dumps(report, indent=2))
        export(cdp, pid, out / "story-export.mp4")
        report["export_sha256"] = sha256_file(out / "story-export.mp4")
        report["comparisons"] = []
        for t in [1.966667, 2, 2.25, 2.5, 2.75, 3, 3.033333]:
            seek(cdp, t)
            preview = capture(cdp).convert("RGB").resize((640, 360))
            ref = decode_at(str(FF), out / "story-export.mp4", t)
            preview.save(out / f"preview-{t}.png")
            ref.save(out / f"export-{t}.png")
            diff = ImageChops.difference(preview, ref)
            diff.save(out / f"diff-{t}.png")
            report["comparisons"].append(
                {
                    "story_requested_s": t,
                    "actual_story_s": cdp.evaluate(SNAPSHOT)["story"],
                    "mean_rgb_error": sum(ImageStat.Stat(diff).mean) / 3,
                    "preview_brightness": sum(ImageStat.Stat(preview).mean) / 3,
                    "export_brightness": sum(ImageStat.Stat(ref).mean) / 3,
                }
            )
        # Separate captured visual playback: JPEG frames at most every 33ms, never used for timing gate.
        seek(cdp, 1.3)
        cdp.evaluate(
            "document.querySelector('[data-transport=toggle]').click()",
            user_gesture=True,
        )
        frames = cdp.evaluate(
            """new Promise(resolve=>{const frames=[];let last=0;const start=performance.now();const c=document.createElement('canvas');c.width=640;c.height=360;const x=c.getContext('2d');function tick(now){if(now-last>=32){last=now;x.drawImage(document.getElementById('studio-preview-blit'),0,0,640,360);frames.push({now,story:"""
            + SNAPSHOT
            + """.story,jpeg:c.toDataURL('image/jpeg',.9).split(',')[1]})}if(now-start>2200){resolve(frames);return}requestAnimationFrame(tick)}requestAnimationFrame(tick)})""",
            await_promise=True,
        )
        pause(cdp)
        (out / "visual-frames").mkdir(exist_ok=True)
        for i, f in enumerate(frames):
            (out / "visual-frames" / f"{i:04d}.jpg").write_bytes(
                base64.b64decode(f.pop("jpeg"))
            )
        report["visual_frame_timestamps"] = frames
        report["status"] = "COLLECTED"
    except Exception as e:
        report["errors"].append(str(e))
        report["status"] = "INCOMPLETE"
    finally:
        app.stop()
        (out / "report.json").write_text(json.dumps(report, indent=2))
    print(mode, report["status"], report["errors"], flush=True)


if __name__ == "__main__":
    manifest = {
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "exe_sha256": sha256_file(EXE),
        "sources": [
            {"alias": chr(65 + i), "sha256": sha256_file(p), "bytes": p.stat().st_size}
            for i, p in enumerate(SOURCES)
        ],
        "ffmpeg": str(FF),
    }
    (OUT / "manifest-local.json").write_text(json.dumps(manifest, indent=2))
    for mode in args.modes or ["none", "same", "different", "mixed"]:
        run(mode)
    manifest["sources_unchanged"] = all(
        sha256_file(p) == s["sha256"] for p, s in zip(SOURCES, manifest["sources"])
    )
    (OUT / "manifest-local.json").write_text(json.dumps(manifest, indent=2))
