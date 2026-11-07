import json
import subprocess
import hashlib
from pathlib import Path
import numpy as np
from PIL import Image
import argparse

parser = argparse.ArgumentParser(
    description="Summarize repeated captured crop holds; a capture gap alone is not a freeze duration."
)
parser.add_argument("--evidence-dir", required=True, type=Path)
args = parser.parse_args()
OUT = args.evidence_dir.resolve()
FF = json.loads((OUT / "manifest-local.json").read_text())["ffmpeg"]
for mode in ["none", "same", "different", "mixed"]:
    out = OUT / mode
    result = subprocess.run(
        [
            FF,
            "-v",
            "error",
            "-i",
            str(out / "story-export.mp4"),
            "-map",
            "0:v:0",
            "-vf",
            "scale=640:360",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    video = np.frombuffer(result.stdout, dtype=np.uint8).reshape(-1, 360, 640, 3)[
        :, 0:160, 440:640
    ]
    runs = []
    for folder in sorted((out / "repeated-visual").iterdir()):
        ts = json.loads((folder / "timestamps.json").read_text())
        images = [
            np.array(Image.open(folder / f"{i:04d}.jpg").convert("RGB"))
            for i in range(len(ts))
        ]
        hashes = [hashlib.sha256(a.tobytes()).hexdigest() for a in images]
        holds = []
        start = 0
        for i in range(1, len(ts) + 1):
            if i < len(ts) and hashes[i] == hashes[start]:
                continue
            if i - start > 1:
                end = i - 1
                a = video[min(149, max(0, round(ts[start]["story"] * 30)))]
                b = video[min(149, max(0, round(ts[end]["story"] * 30)))]
                holds.append(
                    {
                        "first": start,
                        "last": end,
                        "observed_same_image_ms": ts[end]["now"] - ts[start]["now"],
                        "story_start_s": ts[start]["story"],
                        "story_end_s": ts[end]["story"],
                        "matched_export_change_mae": float(
                            np.abs(a.astype(float) - b.astype(float)).mean()
                        ),
                    }
                )
            start = i
        overlap = [
            h for h in holds if h["story_end_s"] >= 2 and h["story_start_s"] <= 3
        ]
        brightness = [float(a.mean()) for a in images]
        record = {
            "kind": folder.name.split("-")[0],
            "run": int(folder.name.split("-")[1]),
            "frames": len(ts),
            "observed_overlap_holds": overlap,
            "max_capture_gap_ms": max(b["now"] - a["now"] for a, b in zip(ts, ts[1:])),
            "black_crop_samples": sum(x < 1 for x in brightness),
            "brightness_min": min(brightness),
            "brightness_max": max(brightness),
            "maximum_adjacent_brightness_change": max(
                abs(b - a) for a, b in zip(brightness, brightness[1:])
            ),
        }
        runs.append(record)
    summary = {
        "mode": mode,
        "runs": runs,
        "total_visual_runs": len(runs),
        "crop": "x=440,y=0,width=200,height=160 of a 640x360 blit",
        "qualification": "Captured crop holds, not display-photon or full-screen freeze durations. Capture gaps do not prove the UI froze.",
    }
    (out / "repeated-visual-analysis.json").write_text(json.dumps(summary, indent=2))
    print(
        mode,
        "runs",
        len(runs),
        "max overlap hold",
        max(
            [
                h["observed_same_image_ms"]
                for r in runs
                for h in r["observed_overlap_holds"]
            ],
            default=0,
        ),
        "black",
        sum(r["black_crop_samples"] for r in runs),
        flush=True,
    )
