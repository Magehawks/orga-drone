"""Issue 320 final isolated experiment. Never imports or patches production rendering.

Run from the existing PR checkout; all inputs must be synthetic existing probes.
Raw RGB inputs are decoded once, shared byte-for-byte by A/B, at frame 0 / PTS 0.
Requires Pillow, NumPy and psutil in the analysis environment only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import psutil
from PIL import Image, ImageChops, ImageStat


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(command, log):
    start = time.perf_counter()
    with log.open("wb") as stream:
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stream)
        peak = child_peak = 0
        while proc.poll() is None:
            try:
                info = psutil.Process(proc.pid).memory_info()
                peak = max(peak, info.rss)
                child_peak = max(child_peak, getattr(info, "peak_wset", info.rss))
            except psutil.Error:
                pass
            time.sleep(0.005)
        if proc.wait():
            raise RuntimeError(f"FFmpeg failed: {log}")
    return dict(
        seconds=time.perf_counter() - start,
        sampled_rss_bytes=peak,
        peak_working_set_bytes=child_peak,
    )


def detail(a, b):
    x, y = (np.asarray(p.convert("L"), dtype=np.float64) for p in (a, b))

    def metrics(z):
        h, w = z.shape
        fine = (
            z[int(h * 0.55) : int(h * 0.70), int(w * 0.1) : int(w * 0.9)]
            .mean(axis=1)
            .std()
        )
        broad = (
            z[int(h * 0.80) : int(h * 0.95), int(w * 0.1) : int(w * 0.9)]
            .mean(axis=1)
            .std()
        )
        medium = (
            z[int(h * 0.1) : int(h * 0.4), int(w * 0.55) : int(w * 0.95)]
            .mean(axis=0)
            .std()
        )
        gradient = (
            np.abs(np.diff(z, axis=1)).mean() + np.abs(np.diff(z, axis=0)).mean()
        ) / z.std()
        return dict(
            normalized_gradient=float(gradient),
            fine_to_broad=float(fine / broad),
            medium_to_broad=float(medium / broad),
        )

    ma, mb = metrics(x), metrics(y)
    return dict(
        exact_pixels=a.tobytes() == b.tobytes(),
        mean_rgb_error=sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3,
        baseline=ma,
        candidate=mb,
        change_percent={k: (mb[k] / ma[k] - 1) * 100 for k in ma},
    )


def swatches(a, b):
    a, b = a.resize((640, 360)), b.resize((640, 360))
    diff = ImageChops.difference(a, b)
    errors = []
    for i in range(8):
        x, y = i % 4 * 160, i // 4 * 180
        errors.append(
            sum(ImageStat.Stat(diff.crop((x + 32, y + 32, x + 128, y + 148))).mean) / 3
        )
    return dict(max_swatch_mean_rgb_error=max(errors), patches=errors)


def run(args):
    root = args.root.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    ffmpeg = str(args.ffmpeg.resolve())
    cube = root / "build/issue320-develop-baseline/synthetic-red.cube"
    # Relative LUT path avoids platform-specific escaping; cwd is recorded.
    lut = f"lut3d=file={cube.relative_to(root).as_posix()}:interp=tetrahedral"
    report = dict(
        status="INCOMPLETE",
        synthetic_only=True,
        ffmpeg_sha256=sha(Path(ffmpeg)),
        frame_index=0,
        pts=0,
        repetitions=3,
        cwd=str(root),
        boundary="gbrpf32le LUT computation -> rgb24 -> downstream scale/YUV",
        source_hashes={},
        detail=[],
        performance=[],
        color=[],
        commands=[],
    )

    def execute(raw, size, chain, target, log, frames=1, encode=False):
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "verbose",
            "-filter_threads",
            "1",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{size[0]}x{size[1]}",
            "-framerate",
            "30",
            "-stream_loop",
            "-1",
            "-i",
            str(raw),
            "-frames:v",
            str(frames),
            "-vf",
            chain,
            "-an",
        ]
        if encode:
            command += [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
            ]
        else:
            command += ["-c:v", "png", "-threads", "1"]
        command += ["-y", str(target)]
        report["commands"].append(dict(argv=command, filter_chain=chain, log=log.name))
        return measure(command, log)

    try:
        sources = [
            root / f"build/precision-detail-fixtures/detail-{h}.{ext}"
            for h in (1080, 2160)
            for ext in ("jpg", "png")
        ]
        sources.append(root / "build/issue320-stage-controls/video-cpu-source.png")
        for source in sources:
            report["source_hashes"][str(source.relative_to(root))] = sha(source)
            with Image.open(source) as im:
                picture = im.convert("RGB")
            size = picture.size
            raw = out / (source.stem + "-" + source.suffix[1:] + ".rgb")
            raw.write_bytes(picture.tobytes())
            report["source_hashes"][raw.name] = sha(raw)
            is_detail = source.name.startswith("detail-")
            for graded in (False, True) if is_detail else (True,):
                a_stage = lut if graded else "null"
                b_stage = f"format=gbrpf32le,{lut},format=rgb24" if graded else "null"
                variants = {"baseline": a_stage, "candidate": b_stage}
                modes = ("native", "third", "yuv") if is_detail else ("yuv",)
                for mode in modes:
                    w, h = size if mode != "third" else (size[0] // 3, size[1] // 3)
                    tail = (
                        (
                            f",scale={w}:{h}:out_color_matrix=bt709:out_range=tv,format=yuv420p,"
                            "setparams=colorspace=bt709:range=tv,"
                            "scale=in_color_matrix=bt709:in_range=tv,format=rgb24"
                        )
                        if mode == "yuv"
                        else f",scale={w}:{h},format=rgb24"
                    )
                    paths = {}
                    for label, stage in variants.items():
                        name = (
                            f"{source.stem}-{source.suffix[1:]}-{graded}-{mode}-{label}"
                        )
                        paths[label] = out / (name + ".png")
                        execute(
                            raw, size, stage + tail, paths[label], out / (name + ".log")
                        )
                    with (
                        Image.open(paths["baseline"]) as a,
                        Image.open(paths["candidate"]) as b,
                    ):
                        if is_detail:
                            report["detail"].append(
                                dict(
                                    source=source.name,
                                    graded=graded,
                                    mode=mode,
                                    dimensions=[w, h],
                                    **detail(a.convert("RGB"), b.convert("RGB")),
                                )
                            )
                        else:
                            reference = (
                                root
                                / "build/issue320-stage-controls/video-paused-preview.png"
                            )
                            with Image.open(reference) as ref:
                                report["color"].append(
                                    dict(
                                        reference=str(reference.relative_to(root)),
                                        reference_sha256=sha(reference),
                                        baseline=swatches(
                                            a.convert("RGB"), ref.convert("RGB")
                                        ),
                                        candidate=swatches(
                                            b.convert("RGB"), ref.convert("RGB")
                                        ),
                                    )
                                )
            # Evidence-first retention gate: do not start later fixtures or performance
            # when any measured detail response falls. No tolerance is introduced.
            negative = [
                row
                for row in report["detail"]
                if row["source"] == source.name
                and row["graded"]
                and any(value < 0 for value in row["change_percent"].values())
            ]
            if negative:
                report["status"] = "EARLY_STOP_DETAIL_GATE_FAILED"
                report["failed_detail_rows"] = negative
                report["sources_unchanged"] = all(
                    sha(root / name) == value
                    for name, value in report["source_hashes"].items()
                    if len(Path(name).parts) > 1
                )
                return
            # Timing and memory: native 2-second MP4 from the same decoded detail image.
            # PNG-only input suffices; JPEG and PNG quality controls above remain separate.
            if is_detail and source.suffix == ".png":
                tail = f",scale={size[0]}:{size[1]}:out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=colorspace=bt709:range=tv"
                for repeat in range(3):
                    # Alternate first runner to reduce directional warm-up bias.
                    for label in (
                        ("baseline", "candidate")
                        if repeat % 2 == 0
                        else ("candidate", "baseline")
                    ):
                        stage = (
                            lut
                            if label == "baseline"
                            else f"format=gbrpf32le,{lut},format=rgb24"
                        )
                        name = f"perf-{size[1]}-{repeat}-{label}"
                        result = execute(
                            raw,
                            size,
                            stage + tail,
                            out / (name + ".mp4"),
                            out / (name + ".log"),
                            frames=60,
                            encode=True,
                        )
                        report["performance"].append(
                            dict(height=size[1], repeat=repeat, label=label, **result)
                        )
            (out / "report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            print(source.name, "complete", flush=True)
        report["sources_unchanged"] = all(
            sha(root / name) == value
            for name, value in report["source_hashes"].items()
            if len(Path(name).parts) > 1
        )
        report["status"] = "COMPLETE"
    finally:
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
