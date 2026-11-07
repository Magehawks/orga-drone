import json
import subprocess
import numpy as np
from pathlib import Path
from PIL import Image
import argparse

parser = argparse.ArgumentParser(
    description="Independent FFmpeg export reference and same-Story-time frame comparisons. Outputs stay in the private evidence directory."
)
parser.add_argument("--evidence-dir", required=True, type=Path)
parser.add_argument("--source-a", required=True, type=Path)
parser.add_argument("--source-b", required=True, type=Path)
args = parser.parse_args()
OUT = args.evidence_dir.resolve()
FF = json.loads((OUT / "manifest-local.json").read_text())["ffmpeg"]
SOURCES = [str(args.source_a.resolve()), str(args.source_b.resolve())]
for mode in ["none", "same", "different", "mixed"]:
    out = OUT / mode
    args = [FF, "-v", "error"]
    for source in SOURCES:
        args += ["-ss", "10", "-t", "3", "-i", source]
    filters = []
    for i in range(2):
        vf = f"[{i}:v:0]setpts=PTS-STARTPTS,scale=1280:720:out_color_matrix=bt709:out_range=tv,setsar=1,fps=30,format=yuv420p"
        if mode != "none" and not (mode == "mixed" and i == 1):
            lut = out / ("blue.cube" if mode == "different" and i == 1 else "red.cube")
            path = str(lut.resolve()).replace("\\", "/").replace(":", "\\:")
            vf += ",lut3d=file='" + path + "':interp=tetrahedral"
        filters.append(vf + f",settb=1/30[v{i}]")
    filters.append(
        "[v0][v1]xfade=transition=fade:duration=1:offset=2,scale=640:360[out]"
    )
    r = subprocess.run(
        args
        + [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-an",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
    )
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace"))
    ref = np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, 360, 640, 3)
    r = subprocess.run(
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
    exported = np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, 360, 640, 3)
    n = min(len(ref), len(exported))
    errors = np.abs(ref[:n].astype(np.int16) - exported[:n].astype(np.int16)).mean(
        axis=(1, 2, 3)
    )
    report = {
        "method": "Independent direct-input FFmpeg linear xfade, 720p30, 10-13 s trims, tetrahedral LUTs; not application stitch code",
        "reference_frames": len(ref),
        "application_export_frames": len(exported),
        "per_frame_mean_rgb_error": errors.tolist(),
        "transition_mean_rgb_error": float(errors[60:90].mean()),
        "transition_max_frame_mean_rgb_error": float(errors[60:90].max()),
        "outside_transition_max_frame_mean_rgb_error": float(
            max(errors[:60].max(), errors[90:].max())
        ),
    }
    report["transition_lag_mae"] = {
        str(lag): float(
            np.abs(
                ref[60:90].astype(np.int16)
                - exported[60 + lag : 90 + lag].astype(np.int16)
            ).mean()
        )
        for lag in range(-3, 4)
    }
    report["exact_preview_vs_export"] = []
    exact = json.loads((out / "exact-paused.json").read_text())
    sheet = Image.new("RGB", (600, 3 * 190), (24, 24, 24))
    from PIL import ImageDraw, ImageChops

    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate([2.2, 2.5, 2.8]):
        a = np.array(Image.open(out / f"exact-preview-{t}.png").convert("RGB"))
        b = exported[round(t * 30)]
        row = next(x for x in exact if x["requested_story_s"] == t)
        report["exact_preview_vs_export"].append(
            {
                "story_s": t,
                "actual_story_s": row["state"]["story"],
                "export_frame_index": round(t * 30),
                "export_pts_s": round(t * 30) / 30,
                "presented_source_times_s": [
                    v["presented"]["mediaTime"] if v["presented"] else None
                    for v in row["state"]["videos"]
                ],
                "preview_vs_export_mae": float(
                    np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()
                ),
                "export_vs_oracle_mae": float(errors[round(t * 30)]),
                "preview_vs_oracle_mae": float(
                    np.abs(
                        a.astype(np.int16) - ref[round(t * 30)].astype(np.int16)
                    ).mean()
                ),
            }
        )
        for j, (im, label) in enumerate(
            [
                (Image.fromarray(a), "preview"),
                (Image.fromarray(b), "export"),
                (
                    ImageChops.difference(Image.fromarray(a), Image.fromarray(b)),
                    "absolute RGB difference",
                ),
            ]
        ):
            sheet.paste(im.crop((440, 0, 640, 160)), (j * 200, i * 190 + 25))
            draw.text((j * 200 + 3, i * 190 + 4), f"{label} {t}s", fill="white")
    sheet.save(out / "sanitized-exact-comparison.png")
    for t in [1.9, 2, 2.5, 3, 3.1]:
        Image.fromarray(ref[round(t * 30)]).save(out / f"oracle-{t}.png")
    (out / "oracle.json").write_text(json.dumps(report, indent=2))
    print(
        mode,
        report["transition_max_frame_mean_rgb_error"],
        report["outside_transition_max_frame_mean_rgb_error"],
        flush=True,
    )
