import re
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw
import numpy as np
import argparse

parser = argparse.ArgumentParser(
    description="Render collected local preview/export comparisons. Review every crop for privacy before sharing."
)
parser.add_argument("--evidence-dir", required=True, type=Path)
args = parser.parse_args()
OUT = args.evidence_dir.resolve()
MAN = json.loads((OUT / "manifest-local.json").read_text())
FF = MAN["ffmpeg"]


def decode(path):
    r = subprocess.run(
        [
            FF,
            "-v",
            "error",
            "-i",
            str(path),
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
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, 360, 640, 3)


def mae(a, b):
    return float(np.mean(np.abs(a.astype(float) - b.astype(float))))


for mode in ["none", "same", "different", "mixed"]:
    out = OUT / mode
    r = json.loads((out / "report.json").read_text())
    video = decode(out / "story-export.mp4")
    summary = {
        "mode": mode,
        "export_frames": len(video),
        "export_duration_s": len(video) / 30,
        "export_black_frames": np.where(video.mean(axis=(1, 2, 3)) < 1)[0].tolist(),
        "export_identical_adjacent_frames": np.where(
            np.max(np.abs(np.diff(video.astype(np.int16), axis=0)), axis=(1, 2, 3)) == 0
        )[0].tolist(),
        "runs": r["runs"],
        "comparisons": r["comparisons"],
    }
    # Avoid forward-seek rounding: explicit output frame indexes. At .5, both 30 and 50fps have exact frame times.
    aligned = []
    for t in [2, 2.5, 3]:
        preview = np.array(
            Image.open(out / f"preview-{t}.png").convert("RGB").resize((640, 360))
        )
        ref = video[round(t * 30)]
        Image.fromarray(ref).save(out / f"export-index-{t}.png")
        aligned.append(
            {
                "requested_story_s": t,
                "export_frame_index": round(t * 30),
                "export_pts_s": round(t * 30) / 30,
                "preview_actual_story_s": next(
                    x["actual_story_s"]
                    for x in r["comparisons"]
                    if x["story_requested_s"] == t
                ),
                "mean_rgb_error": mae(preview, ref),
            }
        )
    summary["indexed_comparisons"] = aligned
    fs = sorted((out / "visual-frames").glob("*.jpg"))
    timestamps = r["visual_frame_timestamps"]
    duplicates = []
    visual = []
    previous = None
    prevref = None
    for i, p in enumerate(fs):
        a = np.array(Image.open(p).convert("RGB"))
        n = min(len(video) - 1, max(0, round(timestamps[i]["story"] * 30)))
        ref = video[n]
        entry = {
            "index": i,
            "wall_ms": timestamps[i]["now"],
            "story_s": timestamps[i]["story"],
            "export_frame_index": n,
            "export_pts_s": n / 30,
            "alignment_error_s": n / 30 - timestamps[i]["story"],
            "mean_rgb_error": mae(a, ref),
            "brightness": float(a.mean()),
        }
        if previous is not None:
            entry["preview_change_mae"] = mae(a, previous)
            entry["export_change_mae"] = mae(ref, prevref)
            if entry["preview_change_mae"] == 0:
                duplicates.append(entry)
        visual.append(entry)
        previous = a
        prevref = ref
    summary["captured_visual"] = {
        "frames": len(fs),
        "duplicates": duplicates,
        "brightness_min": min(x["brightness"] for x in visual),
        "brightness_max": max(x["brightness"] for x in visual),
        "max_frame_interval_ms": max(
            timestamps[i]["now"] - timestamps[i - 1]["now"]
            for i in range(1, len(timestamps))
        ),
        "samples": visual,
    }
    # Human-reviewable privacy crop: upper-right tree/sky area only; full originals stay local.
    crop = (440, 0, 640, 160)
    sheet = Image.new("RGB", (600, 3 * 190), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate([2.25, 2.5, 2.75]):
        for j, k in enumerate(["preview", "export"]):
            im = Image.open(out / f"{k}-{t}.png").crop(crop)
            sheet.paste(im, (j * 200, i * 190 + 25))
            d.text((j * 200 + 4, i * 190 + 5), f"{k} Story {t}s", fill="white")
        diff = ImageChops.difference(
            Image.open(out / f"preview-{t}.png").crop(crop),
            Image.open(out / f"export-{t}.png").crop(crop),
        )
        sheet.paste(diff, (400, i * 190 + 25))
        d.text((404, i * 190 + 5), "absolute RGB difference", fill="white")
    sheet.save(out / "sanitized-crop-comparison.png")
    # Variable-timing side-by-side preserves actual capture wall intervals; export is matched to recorded Story time.
    comparison = out / "comparison-frames"
    comparison.mkdir(exist_ok=True)
    lines = []
    for i, p in enumerate(fs):
        im = Image.new("RGB", (400, 190), (24, 24, 24))
        d = ImageDraw.Draw(im)
        im.paste(Image.open(p).crop(crop), (0, 30))
        im.paste(
            Image.fromarray(video[visual[i]["export_frame_index"]]).crop(crop),
            (200, 30),
        )
        d.text((3, 3), f"Preview {visual[i]['story_s']:.3f}s", fill="white")
        d.text((203, 3), f"Export {visual[i]['export_pts_s']:.3f}s", fill="white")
        im.save(comparison / f"{i:04d}.png")
        lines.append("file 'comparison-frames/" + f"{i:04d}.png" + "'")
        lines.append("option framerate 1000")
        if i + 1 < len(fs):
            lines.append(
                "duration "
                + str((timestamps[i + 1]["now"] - timestamps[i]["now"]) / 1000)
            )
    lines.extend(
        [f"file 'comparison-frames/{len(fs) - 1:04d}.png'", "option framerate 1000"]
    )
    (out / "comparison-concat.txt").write_text("\n".join(lines) + "\n")
    subprocess.run(
        [
            FF,
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(out / "comparison-concat.txt"),
            "-fps_mode",
            "vfr",
            "-enc_time_base",
            "1:1000",
            "-video_track_timescale",
            "1000",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(out / "sanitized-preview-export.mp4"),
        ],
        check=True,
    )
    check = subprocess.run(
        [
            FF,
            "-hide_banner",
            "-i",
            str(out / "sanitized-preview-export.mp4"),
            "-vf",
            "showinfo",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    pts = [float(x) for x in re.findall(r"n:\s*\d+.*?pts_time:([0-9.]+)", check.stderr)]
    expected = [(f["now"] - timestamps[0]["now"]) / 1000 for f in timestamps]
    assert len(pts) == len(expected) + 1, (len(pts), len(expected))
    max_error = max(abs(a - b) for a, b in zip(pts, expected))
    assert max_error <= 0.0011, max_error
    summary["comparison_movie"] = {
        "captured_frames": len(expected),
        "decoded_movie_frames": len(pts),
        "terminal_duplicate_frames": 1,
        "timebase_s": 0.001,
        "max_capture_pts_error_ms": max_error * 1000,
    }
    (out / "analysis.json").write_text(json.dumps(summary, indent=2))
    print(
        mode, len(video), "duplicates", len(duplicates), "indexed", aligned, flush=True
    )
