"""Focused source-app Windows/WebView2 journey; synthetic media only.

This is not packaged release evidence. Run with --output-dir pointing to a new folder.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

_spec = importlib.util.spec_from_file_location(
    "ramp_e2e", Path(__file__).with_name("windows_e2e.py")
)
assert _spec and _spec.loader
_harness: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)


def run(out: Path, *, proxy_case: bool = False) -> None:
    from orga_drone.config import Settings
    from orga_drone.db import Database
    from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs

    out.mkdir(parents=True, exist_ok=False)
    media = out / "media"
    media.mkdir()
    ffmpeg = find_ffmpeg()
    assert ffmpeg
    db = Database(Settings(data_dir=out / "data").db_path)
    root = db.add_root(media, label="Synthetic ramp journey")
    project = db.create_studio_project("Synthetic FPV speed ramps")
    db.set_open_studio_project_id(project.id)
    ids = []
    originals = {}
    for width, height in ((1920, 1080), (3840, 2160)):
        source = media / f"synthetic-{height}.mp4"
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=s={width}x{height}:r=60:d=4",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(source),
            ],
            check=True,
            timeout=120,
            **subprocess_no_window_kwargs(),
        )
        originals[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        mid = db.upsert_media(
            dict(
                root_id=root,
                kind="video",
                path=str(source),
                filename=source.name,
                size_bytes=source.stat().st_size,
                duration_s=4,
                width=width,
                height=height,
                has_srt=0,
                has_lrf=0,
            )
        )
        cid, _ = db.add_studio_item(
            str(source),
            identity_key=source.name,
            filename=source.name,
            recorded_at=None,
            kind="video",
            project_id=project.id,
            source_media_id=mid,
        )
        ids.append(cid)
    if proxy_case:
        from orga_drone.studio_lut import import_lut_from_path

        cube = out / "identity.cube"
        cube.write_text(
            "LUT_3D_SIZE 2\n"
            + "\n".join(f"{r} {g} {b}" for b in (0, 1) for g in (0, 1) for r in (0, 1))
            + "\n"
        )
        asset = import_lut_from_path(out / "data", cube)
        db.set_studio_section(ids[0], source_in_s=1, source_out_s=4, repeats=1)
        db.set_studio_color_look(
            ids[0], dict(creative_lut=asset, creative_strength=100)
        )
        db.set_studio_hsl(ids[0], {"range": "blue", "hue": 10})
    db.set_studio_transition(ids[0], "crossfade", 0.5)
    song = out / "music.wav"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=20",
            str(song),
        ],
        check=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    )
    db.set_studio_music(project.id, str(song))
    port, debug = _harness.free_port(), _harness.free_port()
    repo = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(repo / "src"),
        ORGA_DRONE_DATA_DIR=str(out / "data"),
        ORGA_DRONE_HOST="127.0.0.1",
        ORGA_DRONE_PORT=str(port),
        ORGA_DRONE_GEOCODE="off",
        ORGA_DRONE_E2E="1",
        ORGA_DRONE_CDP_PORT=str(debug),
    )
    env.pop("ORGA_DRONE_BROWSER", None)
    base = f"http://127.0.0.1:{port}"
    process = None
    cdp = None
    evidence: dict[str, Any] = {
        "status": "INCOMPLETE",
        "source_app": True,
        "synthetic_only": True,
    }

    def start() -> None:
        nonlocal process, cdp
        with (out / "app.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "orga_drone"],
                cwd=repo,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        _harness.wait_cdp(debug, 45)
        target = _harness.wait_page_target(debug, 30)
        cdp = _harness.CDP(target["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "window.__rampErrors=[];addEventListener('error',e=>window.__rampErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__rampErrors.push(String(e.reason)))"
            },
        )
        cdp.call("Page.navigate", {"url": base + "/studio"})
        until("!!document.querySelector('[data-ramp-apply]')")
        time.sleep(1)

    def stop() -> None:
        nonlocal cdp, process
        if cdp:
            cdp.close()
            cdp = None
        if process:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            process.wait(timeout=15)
            process = None

    def ev(js: str) -> Any:
        assert cdp
        return cdp.evaluate(js, await_promise=True, user_gesture=True)

    def until(js: str) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if ev(js):
                return
            time.sleep(0.05)
        raise AssertionError("Timed out: " + js)

    def select(cid: int) -> None:
        ev(
            f"(()=>{{let e=document.querySelector('#studio-grid [data-select-clip=\"{cid}\"]');let r=e.getBoundingClientRect();e.dispatchEvent(new MouseEvent('click',{{bubbles:true,clientX:r.x+1}}));}})()"
        )
        ev("document.querySelector('[data-inspector-tab-button=clip]').click()")

    def ramp(cid: int) -> Any:
        return ev(
            f"JSON.parse(document.querySelector('#studio-grid [data-studio-id=\"{cid}\"]').dataset.speedRamp)"
        )

    try:
        start()
        assert cdp
        evidence["webview2"] = _harness.webview2_version()
        select(ids[0])
        presets = ["slow_fast_slow", "fast_slow_fast", "acceleration", "deceleration"]
        for preset in presets:
            ev(
                f"document.querySelector('[data-ramp-preset]').value='{preset}';document.querySelector('[data-ramp-apply]').click()"
            )
            until("!document.querySelector('[data-ramp-apply]').disabled")
            assert ramp(ids[0]) is not None
        evidence["four_presets"] = True
        ev(
            "document.querySelector('[data-ramp-speed]').value='0.75';document.querySelector('[data-ramp-speed]').dispatchEvent(new Event('change',{bubbles:true}))"
        )
        until("!document.querySelector('[data-ramp-apply]').disabled")
        assert ramp(ids[0])["points"][0]["speed"] == 0.75
        before = ramp(ids[0])
        ev("document.getElementById('studio-undo').click()")
        until(
            "!!document.querySelector('[data-ramp-speed]') && !document.getElementById('studio-redo').disabled"
        )
        assert ramp(ids[0]) != before
        ev("document.getElementById('studio-redo').click()")
        until(
            "!!document.querySelector('[data-ramp-speed]') && document.getElementById('studio-redo').disabled"
        )
        assert ramp(ids[0]) == before
        evidence["numeric_edit_undo_redo"] = True
        select(ids[0])
        ev(
            "document.querySelector('[data-ramp-preset]').value='slow_fast_slow';document.querySelector('[data-ramp-apply]').click()"
        )
        until("!document.querySelector('[data-ramp-apply]').disabled")
        before = ramp(ids[0])
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )
        ev(
            "document.getElementById('inspector-speed-ramp').scrollIntoView({block:'center'})"
        )
        ev(
            "document.querySelector('.studio-ramp-curve').scrollIntoView({block:'center'})"
        )
        ev("new Promise(ok=>requestAnimationFrame(()=>requestAnimationFrame(ok)))")
        # Drive the Effect-lane handles with PointerEvents so hit-testing does not
        # depend on CDP mouse coordinate rounding against the scaled SVG ellipses.
        changed = ev(
            """(async()=>{
              const handle=document.querySelectorAll('.studio-ramp-point')[1];
              const curve=document.querySelector('.studio-ramp-curve');
              if(!handle||!curve) return false;
              const start=handle.getBoundingClientRect();
              const x=start.x+start.width/2, y=start.y+start.height/2;
              const opts={pointerId:1,pointerType:'mouse',isPrimary:true,bubbles:true,cancelable:true,clientX:x,clientY:y};
              handle.dispatchEvent(new PointerEvent('pointerdown', opts));
              curve.dispatchEvent(new PointerEvent('pointermove', {...opts, clientY:y+28}));
              curve.dispatchEvent(new PointerEvent('pointerup', {...opts, clientY:y+28}));
              await new Promise(ok=>requestAnimationFrame(()=>requestAnimationFrame(ok)));
              return true;
            })()"""
        )
        assert changed, "Pointer curve gesture could not target a handle"
        until("!document.querySelector('[data-ramp-apply]').disabled")
        assert ramp(ids[0]) != before, "Dragging did not change the curve"
        before = ramp(ids[0])
        evidence["pointer_curve_edit"] = True
        ev(
            "document.getElementById('inspector-section-repeats').value='2';document.getElementById('inspector-section-repeats').dispatchEvent(new Event('change',{bubbles:true}))"
        )
        until(
            f"document.querySelector('#studio-grid [data-studio-id=\"{ids[0]}\"]').dataset.sectionRepeats==='2'"
        )
        # Curve width is one Story pass; clip width is occupancy (duration minus an
        # outgoing Crossfade). Wait for layout, then compare against occupancy.
        until(
            f"""(async()=>{{
              const {{rampTime}}=await import('/static/js/studio/speed-ramp.js');
              const clip=document.querySelector('#studio-grid [data-studio-id=\"{ids[0]}\"]');
              const curve=document.querySelector('.studio-ramp-curve');
              if (!clip || !curve || clip.dataset.sectionRepeats!=='2') return false;
              const d=clip.dataset;
              const r=JSON.parse(d.speedRamp||'null');
              if (!r) return false;
              const cycle=rampTime(r,Number(d.sourceOut)||Number(d.mediaDuration))-rampTime(r,Number(d.sourceIn)||0);
              const occupancy=Number(d.occupancyS);
              if (!(cycle>0) || !(occupancy>0)) return false;
              await new Promise(ok=>requestAnimationFrame(()=>requestAnimationFrame(ok)));
              const ratio=curve.getBoundingClientRect().width/clip.getBoundingClientRect().width;
              return Math.abs(ratio-(cycle/occupancy))<0.02;
            }})()"""
        )
        measured = ev(
            f"""(async()=>{{
              const {{rampTime}}=await import('/static/js/studio/speed-ramp.js');
              const clip=document.querySelector('#studio-grid [data-studio-id=\"{ids[0]}\"]');
              const curve=document.querySelector('.studio-ramp-curve');
              const d=clip.dataset;
              const r=JSON.parse(d.speedRamp);
              const cycle=rampTime(r,Number(d.sourceOut)||Number(d.mediaDuration))-rampTime(r,Number(d.sourceIn)||0);
              return {{
                ratio:curve.getBoundingClientRect().width/clip.getBoundingClientRect().width,
                expected:cycle/Number(d.occupancyS),
                occupancy:Number(d.occupancyS),
                effective:Number(d.effectiveDuration),
              }};
            }})()"""
        )
        assert abs(measured["ratio"] - measured["expected"]) < 0.02, measured
        ev(
            "document.getElementById('inspector-section-repeats').value='1';document.getElementById('inspector-section-repeats').dispatchEvent(new Event('change',{bubbles:true}))"
        )
        until(
            f"document.querySelector('#studio-grid [data-studio-id=\"{ids[0]}\"]').dataset.sectionRepeats==='1'"
        )
        evidence["repeat_curve_one_pass"] = True
        screenshot = cdp.call("Page.captureScreenshot", {"format": "png"})
        (out / "speed-curve.png").write_bytes(base64.b64decode(screenshot["data"]))
        select(ids[1])
        ev("document.querySelector('[data-ramp-apply]').click()")
        until("!document.querySelector('[data-ramp-apply]').disabled")
        assert ramp(ids[1]) is not None
        select(ids[0])
        # Capture actual playback samples for both decoder layers through the join.
        if proxy_case:
            until(
                "document.getElementById('studio-preview-video').getAttribute('src')?.includes('playback-proxy')"
            )
        ev("document.querySelector('[data-transport=toggle]').click()")
        until("!document.getElementById('studio-preview-video').paused")
        samples = ev("""(async()=>{const {rampTime}=await import('/static/js/studio/speed-ramp.js');
          const rows=[...document.querySelectorAll('#studio-grid .studio-clip')];let cursor=0;
          const clips=rows.map(e=>{const p={id:e.dataset.studioId,start:cursor,in:Number(e.dataset.sourceIn)||0,ramp:JSON.parse(e.dataset.speedRamp),stream:e.dataset.streamUrl,
            proxy:e.dataset.proxyUrl};cursor+=Number(e.dataset.effectiveDuration)-(e.dataset.appliedType==='crossfade'?Number(e.dataset.appliedDuration):0);return p});
          const locate=src=>clips.find(c=>c.stream===src||c.proxy===src||src?.startsWith('/api/studio/'+c.id+'/playback-proxy'));
          const expected=(v,c)=>c?c.start+rampTime(c.ramp,v.currentTime+(v.getAttribute('src')?.includes('playback-proxy')?c.in:0))-rampTime(c.ramp,c.in):null;
          const samples=[];const start=performance.now();
          while(performance.now()-start<12000){const a=document.getElementById('studio-preview-video');
            const b=document.getElementById('studio-preview-video-b');
            const clip=locate(a.getAttribute('src'));
            samples.push({wall:(performance.now()-start)/1000,a:a.currentTime,rate:a.playbackRate,
              muted:a.muted,b:b.currentTime,bRate:b.playbackRate,bVisible:!b.hidden,
              expected:expected(a,clip),bExpected:expected(b,locate(b.getAttribute('src'))),bProxy:b.getAttribute('src')?.includes('playback-proxy'),music:document.getElementById('studio-music-audio').currentTime,
              dropped:a.getVideoPlaybackQuality().droppedVideoFrames,total:a.getVideoPlaybackQuality().totalVideoFrames,
              story:Number(document.getElementById('studio-playhead').getAttribute('aria-valuenow'))});
            await new Promise(ok=>setTimeout(ok,20));}return samples})()""")
        evidence["playback_samples"] = samples
        assert any(s["bVisible"] for s in samples), (
            "Transition second decoder never appeared"
        )
        assert len({round(s["rate"], 2) for s in samples}) > 5
        assert all(s["muted"] for s in samples)
        assert all(s["expected"] is not None for s in samples)
        evidence["max_playhead_error_s"] = max(
            abs(s["expected"] - s["story"]) for s in samples
        )
        evidence["max_music_error_s"] = max(
            abs(s["expected"] - s["music"]) for s in samples
        )
        assert evidence["max_playhead_error_s"] <= 0.12
        assert evidence["max_music_error_s"] <= 0.4
        if proxy_case:
            proxy_samples = [s for s in samples if s["bVisible"] and s["bProxy"]]
            assert proxy_samples, "Trimmed outgoing proxy was not shown"
            evidence["max_proxy_crossfade_error_s"] = max(
                abs(s["bExpected"] - s["expected"]) for s in proxy_samples
            )
            assert evidence["max_proxy_crossfade_error_s"] <= 0.15
        stop()
        start()
        assert ramp(ids[0]) == before
        assert ramp(ids[1]) is not None
        evidence["relaunch_restores"] = True
        destination = out / "ramp-1080p.mp4"
        started = time.monotonic()
        job = ev(
            "fetch('/api/studio/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify("
            + json.dumps(
                dict(project_id=project.id, height=1080, output_path=str(destination))
            )
            + ")}).then(r=>r.json())"
        )
        assert "job_id" in job, job
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status = ev(
                f"fetch('/api/studio/export/jobs/{job['job_id']}').then(r=>r.json())"
            )
            if status["state"] in {"completed", "failed", "cancelled"}:
                assert status["state"] == "completed", status
                break
            time.sleep(0.2)
        else:
            raise AssertionError("Export timed out")
        subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(destination), "-f", "null", "-"],
            check=True,
            capture_output=True,
            timeout=60,
            **subprocess_no_window_kwargs(),
        )
        evidence["export_1080p_decode"] = True
        evidence["export_seconds"] = round(time.monotonic() - started, 3)
        destination_4k = out / "ramp-2160.mp4"
        started_4k = time.monotonic()
        job_4k = ev(
            "fetch('/api/studio/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify("
            + json.dumps(
                dict(project_id=project.id, height=2160, output_path=str(destination_4k))
            )
            + ")}).then(r=>r.json())"
        )
        assert "job_id" in job_4k, job_4k
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            status = ev(
                f"fetch('/api/studio/export/jobs/{job_4k['job_id']}').then(r=>r.json())"
            )
            if status["state"] in {"completed", "failed", "cancelled"}:
                assert status["state"] == "completed", status
                break
            time.sleep(0.2)
        else:
            raise AssertionError("4K export timed out")
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(destination_4k)],
            capture_output=True,
            text=True,
            timeout=30,
            **subprocess_no_window_kwargs(),
        )
        assert "3840x2160" in probe.stderr, probe.stderr
        subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(destination_4k), "-f", "null", "-"],
            check=True,
            capture_output=True,
            timeout=120,
            **subprocess_no_window_kwargs(),
        )
        evidence["export_2160_decode"] = True
        evidence["export_2160_seconds"] = round(time.monotonic() - started_4k, 3)
        for source in media.iterdir():
            assert (
                hashlib.sha256(source.read_bytes()).hexdigest()
                == originals[source.name]
            )
        evidence["originals_unchanged"] = True
        evidence["status"] = "PASS"
    except Exception:
        if cdp:
            evidence["failure_context"] = ev(
                "({errors:window.__rampErrors,flash:document.getElementById('studio-flash')?.textContent,selection:document.querySelector('.studio-clip.is-selected')?.dataset,controls:document.getElementById('inspector-speed-ramp')?.outerHTML})"
            )
            screenshot = cdp.call("Page.captureScreenshot", {"format": "png"})
            (out / "failure.png").write_bytes(base64.b64decode(screenshot["data"]))
        raise
    finally:
        (out / "evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        stop()
    print(
        json.dumps(
            {k: v for k, v in evidence.items() if k != "playback_samples"}, indent=2
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--proxy-case", action="store_true")
    args = parser.parse_args()
    run(args.output_dir.resolve(), proxy_case=args.proxy_case)
