"""Supplemental packaged LUT smoke on an isolated studio_color_probe fixture.

Reads only that synthetic probe directory. This is not universal LUT parity or
GitHub admission evidence. The original source is never modified.
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

from studio_color_probe import compare, decode, export, image_bytes  # type: ignore[import-not-found]
from studio_clock_probe import seek as seek_story  # type: ignore[import-not-found]
from windows_e2e import (  # type: ignore[import-not-found]
    AppProcess,
    E2EError,
    expect_ok,
    fetch_json,
    navigate,
    sha256_file,
    wait_until,
)

STRICT_TOLERANCE = 3.0
BASELINE_TOLERANCE_EXTRA = 1.5


def lut_parity_decision(
    paused_max: float,
    playing_max: float,
    baseline_max: float,
    seek_max: float = 0.0,
) -> dict:
    """Bound LUT parity against the measured no-LUT color path.

    The strict 3/255 gate is the original #310 target. The measured tagged
    709 limited browser-vs-FFmpeg path is already above 2.5/255 before any LUT,
    so the bounded gate allows 1.5 code values over that baseline while still
    rejecting the 36/255 texel-centre sampling failure.
    """
    baseline = max(0.0, float(baseline_max or 0.0))
    tolerance = max(STRICT_TOLERANCE, baseline + BASELINE_TOLERANCE_EXTRA)
    worst = max(float(paused_max), float(playing_max), float(seek_max))
    strict = worst <= STRICT_TOLERANCE
    bounded = worst <= tolerance
    return {
        "baseline_max_swatch_mean_rgb_error": baseline,
        "strict_tolerance_max_swatch_mean_rgb": STRICT_TOLERANCE,
        "tolerance_max_swatch_mean_rgb": tolerance,
        "strict_parity_pass": strict,
        "parity_pass": bounded,
        "lut_max_extra_over_baseline": max(0.0, worst - baseline),
        "decision": "GO_BOUNDED_FIXTURE" if bounded else "NO-GO",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    fixture = args.fixture_dir.resolve()
    # Refuse arbitrary user data: require the successful synthetic fixture manifest.
    manifest = json.loads((fixture / "report.json").read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "COMPLETE_DIAGNOSTIC_NOT_PARITY_APPROVAL"
        or len(manifest.get("cases", [])) != 7
    ):
        parser.error("--fixture-dir must be a completed synthetic color probe")
    out = args.output_dir.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Use a fresh output directory")
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"status": "INCOMPLETE", "errors": []}
    report_path = out / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    app = None
    try:
        source = fixture / "library/709-tv.mp4"
        before = sha256_file(source)
        expected = next(
            r["source_sha256"] for r in manifest["cases"] if r["name"] == "709-tv"
        )
        if before != expected:
            raise E2EError("Synthetic source fingerprint mismatch")
        cube = out / "synthetic.cube"
        rows = ['TITLE "Synthetic channel transform"', "LUT_3D_SIZE 2"]
        for b in (0, 1):
            for g in (0, 1):
                for r in (0, 1):
                    rows.append(f"{0.1 + r * 0.75} {0.1 + g * 0.65} {0.1 + b * 0.7}")
        cube.write_text("\n".join(rows) + "\n", encoding="utf-8")
        app = AppProcess(args.exe.resolve(), fixture / "data")
        app.start()
        cdp = app.require_cdp()
        report["exe_sha256"] = sha256_file(args.exe)
        report["browser"] = cdp.call("Browser.getVersion")
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1500, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )
        navigate(cdp, app.app_port, "/")
        found = expect_ok(
            fetch_json(
                cdp, "/api/search", method="POST", json_body={"q": "709-tv.mp4"}
            ),
            "find",
        )
        mid = next(m["id"] for m in found["items"] if m["filename"] == "709-tv.mp4")
        pid = expect_ok(
            fetch_json(
                cdp,
                "/api/studio/projects",
                method="POST",
                json_body={"title": "Synthetic LUT smoke"},
            ),
            "create",
        )["id"]
        expect_ok(
            fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"), "open"
        )
        expect_ok(
            fetch_json(
                cdp,
                f"/media/{mid}/studio/add",
                method="POST",
                form_body={"return_to": "studio"},
            ),
            "add",
        )
        imported = expect_ok(
            fetch_json(cdp, "/api/luts", method="POST", json_body={"path": str(cube)}),
            "import cube",
        )
        navigate(cdp, app.app_port, "/studio")
        clip = cdp.evaluate("document.querySelector('.studio-clip').dataset.studioId")
        expect_ok(
            fetch_json(
                cdp,
                f"/api/studio/{clip}/color",
                method="PATCH",
                json_body={
                    "input_profile": "rec709",
                    "creative_lut": imported["asset_name"],
                    "creative_strength": 100,
                },
            ),
            "apply cube",
        )
        navigate(cdp, app.app_port, "/studio")
        wait_until(
            cdp,
            "document.getElementById('studio-preview-video')?.readyState>=2",
            timeout_s=30,
            description="LUT video",
        )
        cdp.evaluate(
            "document.getElementById('studio-preview-frame').style.cssText='width:640px;height:360px;max-width:none;border:0;padding:0;flex-shrink:0'"
        )
        wait_until(
            cdp,
            "document.getElementById('studio-preview-frame').dataset.lutWebgl==='1'||!document.getElementById('studio-preview-lut-still').hidden",
            timeout_s=30,
            description="rendered LUT preview",
        )
        time.sleep(0.3)
        c = cdp.evaluate(
            "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
        )
        paused = image_bytes(c)
        paused.save(out / "paused-lut.png")
        report["render_path"] = cdp.evaluate(
            "({webgl:document.getElementById('studio-preview-frame').dataset.lutWebgl,still:!document.getElementById('studio-preview-lut-still').hidden,chip:document.getElementById('studio-preview-lut-chip').textContent})"
        )
        exported = out / "lut-export.mp4"
        export(cdp, pid, exported)
        report["export_sha256"] = sha256_file(exported)
        reference = decode(args.ffmpeg, exported)
        reference.save(out / "export-lut.png")
        report["paused_vs_export"] = compare(paused, reference)
        seek_story(cdp, 1.0)
        time.sleep(0.3)
        report["seek"] = cdp.evaluate(
            """(() => {const v=document.getElementById('studio-preview-video');
          return {currentTime:v.currentTime,paused:v.paused,seeking:v.seeking,
            readyState:v.readyState,webgl:document.getElementById('studio-preview-frame').dataset.lutWebgl,
            still:!document.getElementById('studio-preview-lut-still').hidden};})()"""
        )
        seeked = image_bytes(
            cdp.evaluate(
                "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
            )
        )
        seeked.save(out / "seek-lut.png")
        report["seek_vs_export"] = compare(seeked, reference)
        before_play = cdp.evaluate(
            "document.getElementById('studio-preview-video').currentTime"
        )
        cdp.evaluate(
            "document.querySelector('[data-transport=toggle]').click()",
            user_gesture=True,
        )
        time.sleep(0.6)
        report["playback"] = (
            cdp.evaluate("""(() => {const v=document.getElementById('studio-preview-video');
          return {currentTime:v.currentTime,paused:v.paused,seeking:v.seeking,readyState:v.readyState,
            decodedFrames:v.getVideoPlaybackQuality().totalVideoFrames};})()""")
        )
        report["playback"]["beforeTime"] = before_play
        playback = report["playback"]
        if (
            playback["paused"]
            or playback["seeking"]
            or playback["readyState"] < 2
            or playback["currentTime"] - before_play < 0.2
        ):
            raise E2EError("Requested LUT playback did not actually advance")
        moving = image_bytes(
            cdp.evaluate(
                "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
            )
        )
        moving.save(out / "playing-lut.png")
        report["playing_vs_export"] = compare(moving, reference)
        cdp.evaluate("document.querySelector('[data-transport=toggle]').click()")
        (out / "studio-lut.png").write_bytes(
            base64.b64decode(
                cdp.call("Page.captureScreenshot", {"format": "png"})["data"]
            )
        )
        report["source_unchanged"] = before == sha256_file(source)
        if not report["source_unchanged"]:
            raise E2EError("Synthetic source changed")
        baseline_max = 0.0
        try:
            baseline_case = next(
                row for row in manifest["cases"] if row["name"] == "709-tv"
            )
            baseline_max = float(
                baseline_case["comparisons"]["blit_vs_export_ffmpeg"][
                    "max_swatch_mean_rgb_error"
                ]
            )
        except (KeyError, StopIteration, TypeError, ValueError):
            baseline_max = 0.0
        report.update(
            lut_parity_decision(
                report["paused_vs_export"]["max_swatch_mean_rgb_error"],
                report["playing_vs_export"]["max_swatch_mean_rgb_error"],
                baseline_max,
                report.get("seek_vs_export", {}).get("max_swatch_mean_rgb_error", 0.0),
            )
        )
        report["status"] = "COMPLETE_LUT_DIAGNOSTIC"
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
                "decision": report.get("decision"),
                "errors": report["errors"],
            }
        )
    )
    return 0 if report.get("parity_pass") and not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
