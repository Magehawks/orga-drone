"""Controlled existing-clip color diagnostics in packaged Studio (issues #189/#267).

Synthetic, static SDR swatches remove frame-selection ambiguity. Metadata-only
controls share encoded picture data. No grades, LUTs or new transitions are used.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

from windows_e2e import (  # type: ignore[import-not-found]
    AppProcess,
    E2EError,
    expect_ok,
    fetch_json,
    navigate,
    sha256_file,
    wait_until,
)

COLORS = [
    (180, 100, 60),
    (55, 120, 185),
    (128, 128, 128),
    (32, 32, 32),
    (210, 210, 210),
    (70, 170, 95),
    (180, 65, 140),
    (210, 180, 70),
]
CASES = [
    ("709-tv", "bt709", "tv"),
    ("601-tv", "bt601", "tv"),
    ("709-pc", "bt709", "pc"),
    ("601-pc", "bt601", "pc"),
    ("untagged-601", "bt601", None),
    ("untagged-709", "bt709", None),
]


def ffmpeg(binary: str, args: list[str]) -> bytes:
    result = subprocess.run(
        [binary, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        raise E2EError(result.stderr.decode(errors="replace"))
    return result.stdout


def image_bytes(encoded: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")


def compare(a: Image.Image, b: Image.Image) -> dict:
    a, b = a.resize((640, 360)), b.resize((640, 360))
    diff = ImageChops.difference(a, b)
    patches: list[dict] = []
    for i in range(8):
        x, y = i % 4 * 160, i // 4 * 180
        box = (x + 32, y + 32, x + 128, y + 148)
        patches.append(
            {
                "a": ImageStat.Stat(a.crop(box)).mean,
                "b": ImageStat.Stat(b.crop(box)).mean,
                "mean_rgb_error": sum(ImageStat.Stat(diff.crop(box)).mean) / 3,
            }
        )
    return {
        "full_mean_rgb_error": sum(ImageStat.Stat(diff).mean) / 3,
        "max_swatch_mean_rgb_error": max(p["mean_rgb_error"] for p in patches),
        "patches": patches,
    }


def export(cdp, pid: int, path: Path) -> dict:
    started = expect_ok(
        fetch_json(
            cdp,
            "/api/studio/export",
            method="POST",
            json_body={
                "project_id": pid,
                "height": 720,
                "quality": "best",
                "output_path": str(path),
            },
        ),
        "export",
    )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        job = expect_ok(
            fetch_json(cdp, f"/api/studio/export/jobs/{started['job_id']}"), "job"
        )
        if job["state"] == "completed":
            return job
        if job["state"] in {"failed", "cancelled"}:
            raise E2EError(str(job))
        time.sleep(0.25)
    raise E2EError("Export timeout")


def decode(binary: str, path: Path, matrix: str | None = None) -> Image.Image:
    vf = "scale=640:360" + (f":in_color_matrix={matrix}" if matrix else "")
    return Image.open(
        io.BytesIO(
            ffmpeg(
                binary,
                [
                    "-i",
                    str(path),
                    "-vf",
                    vf,
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "-",
                ],
            )
        )
    ).convert("RGB")


def encode_fixture(
    binary: str,
    palette: Path,
    target: Path,
    matrix: str,
    color_range: str | None,
    duration: str = "2",
) -> None:
    tag = "bt709" if matrix == "bt709" else "smpte170m"
    filters = f"scale=1280:720:out_color_matrix={matrix}:out_range={color_range or 'tv'},format=yuv420p"
    tags = []
    if color_range:
        filters += f",setparams=colorspace={tag}:color_primaries={tag}:color_trc={tag}:range={color_range}"
        tags = [
            "-colorspace",
            tag,
            "-color_primaries",
            tag,
            "-color_trc",
            tag,
            "-color_range",
            color_range,
        ]
    else:
        filters += ",setparams=colorspace=unknown:color_primaries=unknown:color_trc=unknown:range=unspecified"
    ffmpeg(
        binary,
        [
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(palette),
            "-t",
            duration,
            "-vf",
            filters,
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "10",
            "-preset",
            "ultrafast",
            *tags,
            str(target),
        ],
    )


def finish_diagnostic(report: dict) -> None:
    if not report["sources_unchanged"]:
        raise E2EError("Source hashes changed during diagnostic")
    if not report["metadata_only_control_same_yuv"]:
        raise E2EError("Metadata control changed decoded picture samples")
    if report["errors"] or len(report["cases"]) != 7:
        raise E2EError("Diagnostic case coverage is incomplete")
    report["status"] = "COMPLETE_DIAGNOSTIC_NOT_PARITY_APPROVAL"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Use a new/empty output directory; prior evidence is preserved")
    out.mkdir(parents=True, exist_ok=True)
    library, data = out / "library", out / "data"
    library.mkdir()
    data.mkdir()
    report: dict = {"status": "INCOMPLETE", "cases": [], "errors": []}
    report_path = out / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    app = None
    try:
        report["exe_sha256"] = sha256_file(args.exe)
        report["studio_js_sha256"] = sha256_file(
            args.exe.resolve().parent / "_internal/orga_drone/static/js/studio.js"
        )
        report["ffmpeg_version"] = (
            ffmpeg(args.ffmpeg, ["-version"]).decode().splitlines()[0]
        )
        palette = Image.new("RGB", (640, 360))
        draw = ImageDraw.Draw(palette)
        for i, color in enumerate(COLORS):
            x, y = i % 4 * 160, i // 4 * 180
            draw.rectangle((x, y, x + 159, y + 179), fill=color)
        palette.save(out / "palette.png")
        for index, (name, matrix, color_range) in enumerate(CASES):
            target = library / f"{name}.mp4"
            encode_fixture(
                args.ffmpeg, out / "palette.png", target, matrix, color_range
            )
            os.utime(target, (1700000000 + index * 86400,) * 2)
        # Same compressed pictures as 601-tv, only H.264 VUI matrix/primaries/TRC change.
        retag = library / "retag-601-as-709.mp4"
        ffmpeg(
            args.ffmpeg,
            [
                "-i",
                str(library / "601-tv.mp4"),
                "-c",
                "copy",
                "-bsf:v",
                "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
                "-colorspace",
                "bt709",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-color_range",
                "tv",
                str(retag),
            ],
        )
        os.utime(retag, (1700000000 + 6 * 86400,) * 2)
        sources = sorted(library.glob("*.mp4"))
        hashes = {p.name: sha256_file(p) for p in sources}
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
                form_body={"path": str(library), "label": "Synthetic color controls"},
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
            if all(p.name in ids for p in sources):
                break
            if time.monotonic() > deadline:
                raise E2EError(f"Synthetic scan incomplete: {list(ids)}")
            time.sleep(0.5)
        for source in sources:
            name = source.stem
            pid = expect_ok(
                fetch_json(
                    cdp,
                    "/api/studio/projects",
                    method="POST",
                    json_body={"title": name},
                ),
                "create",
            )["id"]
            expect_ok(
                fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"),
                "open",
            )
            expect_ok(
                fetch_json(
                    cdp,
                    f"/media/{ids[source.name]}/studio/add",
                    method="POST",
                    form_body={"return_to": "studio"},
                ),
                "add",
            )
            navigate(cdp, app.app_port, "/studio")
            wait_until(
                cdp,
                "document.getElementById('studio-preview-video')?.readyState>=2",
                timeout_s=30,
                description="ordinary preview",
            )
            cdp.evaluate(
                "document.getElementById('studio-preview-frame').style.cssText='width:640px;height:360px;max-width:none;border:0;padding:0;flex-shrink:0'"
            )
            time.sleep(0.3)
            capture = cdp.evaluate("""(() => {
              const v=document.getElementById('studio-preview-video'), b=document.getElementById('studio-preview-blit');
              function copy(width,height,space) { const c=document.createElement('canvas');c.width=width;c.height=height;
                const ctx=c.getContext('2d',space?{colorSpace:space}:undefined);ctx.imageSmoothingQuality='high';ctx.drawImage(v,0,0,width,height);
                return {png:c.toDataURL().split(',')[1],attributes:ctx.getContextAttributes?.()}; }
              return {blit:b.toDataURL().split(',')[1],hidden:b.hidden,sourceTime:v.currentTime,
                filter:v.style.filter,opacity:v.style.opacity,native:copy(v.videoWidth,v.videoHeight),
                scaled:copy(640,360),srgb:copy(640,360,'srgb'),blitAttributes:b.getContext('2d').getContextAttributes?.()};
            })()""")
            if capture["hidden"]:
                raise E2EError("Real Story canvas hidden")
            pictures = {"blit": image_bytes(capture.pop("blit"))}
            for key in ("native", "scaled", "srgb"):
                value = capture.pop(key)
                pictures[key] = image_bytes(value.pop("png"))
                capture[key] = value
            exported = out / f"{name}-export.mp4"
            export(cdp, pid, exported)
            for key, decode_matrix in [
                ("source_auto", None),
                ("source_601", "bt601"),
                ("source_709", "bt709"),
            ]:
                pictures[key] = decode(args.ffmpeg, source, decode_matrix)
            pictures["export_ffmpeg"] = decode(args.ffmpeg, exported)
            # Browser decoding of the exported file is a decoder control, not Studio replacement.
            blob = base64.b64encode(exported.read_bytes()).decode()
            encoded = cdp.evaluate(
                f"""(async()=>{{const v=document.createElement('video');v.muted=true;
              v.playsInline=true;v.style.cssText='position:fixed;left:-10000px;width:640px;height:360px';document.body.appendChild(v);
              v.src='data:video/mp4;base64,{blob}';await new Promise((r,j)=>{{v.onloadeddata=r;v.onerror=()=>j('export decode failed')}});
              const frame=new Promise(r=>v.requestVideoFrameCallback(()=>r()));await v.play();await frame;v.pause();
              const c=document.createElement('canvas');c.width=640;c.height=360;c.getContext('2d').drawImage(v,0,0,640,360);
              const png=c.toDataURL().split(',')[1];v.removeAttribute('src');v.load();v.remove();return png;}})()""",
                await_promise=True,
            )
            pictures["export_browser"] = image_bytes(encoded)
            for key, picture in pictures.items():
                picture.save(out / f"{name}-{key}.png")
            probe = subprocess.run(
                [args.ffmpeg, "-hide_banner", "-i", str(source)],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            row = {
                "name": name,
                "source_sha256": hashes[source.name],
                "export_sha256": sha256_file(exported),
                "source_video_info": [
                    s.strip() for s in probe.stderr.splitlines() if "Video:" in s
                ],
                "capture": capture,
                "comparisons": {},
            }
            raw_yuv = ffmpeg(
                args.ffmpeg,
                [
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-pix_fmt",
                    "yuv420p",
                    "-f",
                    "rawvideo",
                    "-",
                ],
            )
            row["decoded_yuv_sha256"] = hashlib.sha256(raw_yuv).hexdigest()
            for a, b in [
                ("blit", "native"),
                ("blit", "scaled"),
                ("scaled", "srgb"),
                ("native", "source_auto"),
                ("native", "source_601"),
                ("native", "source_709"),
                ("blit", "export_ffmpeg"),
                ("native", "export_browser"),
                ("export_browser", "export_ffmpeg"),
                ("source_auto", "export_ffmpeg"),
            ]:
                row["comparisons"][a + "_vs_" + b] = compare(pictures[a], pictures[b])
            report["cases"].append(row)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["sources_unchanged"] = hashes == {
            p.name: sha256_file(p) for p in sources
        }
        rows = {row["name"]: row for row in report["cases"]}
        report["metadata_only_control_same_yuv"] = (
            rows["601-tv"]["decoded_yuv_sha256"]
            == rows["retag-601-as-709"]["decoded_yuv_sha256"]
        )
        finish_diagnostic(report)
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
                "cases": len(report["cases"]),
                "errors": report["errors"],
            }
        )
    )
    return 0 if not report["errors"] and len(report["cases"]) == 7 else 1


if __name__ == "__main__":
    raise SystemExit(main())
