"""Actual packaged photo detail captures at 1080p/4K, neutral/LUT and DPR 1/3."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

from orga_drone.db import Database
from studio_color_probe import image_bytes
from studio_crossfade_lut_probe import write_cube
from studio_photo_lut_probe import patch
from windows_e2e import AppProcess, expect_ok, fetch_json, navigate, sha256_file, wait_until


def fixtures(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    for height in (1080, 2160):
        width = height * 16 // 9
        picture = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(picture)
        for x in range(width):
            period = 2 if x < width // 2 else 32
            draw.line((x, 0, x, height // 2 - 1), fill="white" if (x // period) % 2 else "black")
        for y in range(height // 2, height):
            period = 8 if y < height * 3 // 4 else 64
            draw.line((0, y, width - 1, y), fill="white" if (y // period) % 2 else "black")
        picture.save(root / f"detail-{height}.png")
        picture.save(root / f"detail-{height}.jpg", quality=98, subsampling=0)


def run(args) -> None:
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    library = args.fixtures.resolve()
    if not library.exists():
        fixtures(library)
    hashes = {p.name: sha256_file(p) for p in library.iterdir()}
    data = out / "data"
    data.mkdir()
    db = Database(data / "orga-drone.sqlite3")
    root = db.add_root(library)
    ids = {}
    for source in sorted(library.iterdir()):
        with Image.open(source) as picture:
            width, height = picture.size
        st = source.stat()
        asset = db.upsert_asset(root_id=root, path=source, kind="photo", size_bytes=st.st_size,
                               mtime=st.st_mtime, stem_base=source.stem)
        ids[source.name] = db.upsert_media(dict(root_id=root, primary_asset_id=asset, kind="photo",
            filename=source.name, path=str(source), size_bytes=st.st_size, duration_s=None,
            width=width, height=height, has_srt=0, has_lrf=0))
    report = {"synthetic_only": True, "exe_sha256": sha256_file(args.exe),
              "source_hashes": hashes, "captures": [], "status": "INCOMPLETE"}
    app = AppProcess(args.exe.resolve(), data)
    try:
        app.start()
        cdp = app.require_cdp()
        navigate(cdp, app.app_port, "/")
        cube = out / "synthetic-red.cube"
        write_cube(cube, size=17, variant="red")
        asset = expect_ok(fetch_json(cdp, "/api/luts", method="POST",
                                    json_body={"path": str(cube)}), "lut")["asset_name"]
        for name, media in ids.items():
            pid = expect_ok(fetch_json(cdp, "/api/studio/projects", method="POST",
                json_body={"title": "Synthetic precision detail " + name}), "project")["id"]
            expect_ok(fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"), "open")
            expect_ok(fetch_json(cdp, f"/media/{media}/studio/add", method="POST",
                                 form_body={"return_to": "studio"}), "add")
            navigate(cdp, app.app_port, "/studio")
            clip = cdp.evaluate("document.querySelector('.studio-clip').dataset.studioId")
            height = 2160 if "2160" in name else 1080
            css_w, css_h = (1280, 720) if height == 2160 else (640, 360)
            for label in ("neutral", "lut"):
                if label == "lut":
                    patch(cdp, clip, "color", {"input_profile": "rec709", "creative_lut": asset,
                                               "creative_strength": 100})
                for dpr in (1, 3):
                    cdp.call("Emulation.setDeviceMetricsOverride", dict(width=1500, height=1000,
                                                                       deviceScaleFactor=dpr, mobile=False))
                    navigate(cdp, app.app_port, "/studio")
                    cdp.evaluate("document.getElementById('studio-preview-frame').style.cssText=" +
                        json.dumps(f"width:{css_w}px;height:{css_h}px;max-width:none;max-height:none;border:0;padding:0;flex-shrink:0"))
                    wait_until(cdp, "document.getElementById('studio-preview-image').naturalWidth>0",
                               timeout_s=30, description="native photo decoded")
                    if label == "lut":
                        wait_until(cdp, "!document.getElementById('studio-preview-lut-still').hidden",
                                   timeout_s=30, description="graded photo decoded")
                    wait_until(cdp, f"document.getElementById('studio-preview-blit').width==={css_w * dpr}&&"
                        f"document.getElementById('studio-preview-blit').height==={css_h * dpr}",
                        timeout_s=30, description="requested backing resolution painted")
                    time.sleep(0.2)
                    result = cdp.evaluate("(()=>{const c=document.getElementById('studio-preview-blit');"
                        "const m=document.getElementById('studio-preview-image');return {"
                        "png:c.toDataURL().split(',')[1],size:[c.width,c.height],"
                        "sourceSize:[m.naturalWidth,m.naturalHeight],dpr:devicePixelRatio,"
                        "still:!document.getElementById('studio-preview-lut-still').hidden}})()")
                    picture = image_bytes(result.pop("png"))
                    filename = f"{name}-{label}-dpr{dpr}.png"
                    picture.save(out / filename)
                    assert result["size"] == [css_w * dpr, css_h * dpr], result
                    report["captures"].append(dict(name=name, look=label, dpr=dpr, file=filename,
                        state=result, stddev=ImageStat.Stat(picture).stddev))
                    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["status"] = "COMPLETE"
    finally:
        app.stop()
        report["sources_unchanged"] = hashes == {p.name: sha256_file(p) for p in library.iterdir()}
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.compare_baseline:
        import numpy as np

        baseline = args.compare_baseline.resolve()
        previous = json.loads((baseline / "report.json").read_text(encoding="utf-8"))
        assert previous["status"] == report["status"] == "COMPLETE"
        assert previous["source_hashes"] == report["source_hashes"]
        comparisons = []
        for capture in report["captures"]:
            with Image.open(baseline / capture["file"]) as a, Image.open(out / capture["file"]) as b:
                assert a.size == b.size
                difference = ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB")))
                # Remove brightness/contrast offsets so changed RGB rounding is
                # not mislabeled as blur. Raw channel stddev/error stay recorded.
                x = np.asarray(a.convert("L"), dtype=np.float64)
                y = np.asarray(b.convert("L"), dtype=np.float64)
                x_std, y_std = float(x.std()), float(y.std())
                xn, yn = (x - x.mean()) / x_std, (y - y.mean()) / y_std
                gx = float(np.abs(np.diff(x, axis=1)).mean() + np.abs(np.diff(x, axis=0)).mean()) / x_std
                gy = float(np.abs(np.diff(y, axis=1)).mean() + np.abs(np.diff(y, axis=0)).mean()) / y_std
                def stripe_response(pixels):
                    h, w = pixels.shape
                    fine = pixels[int(h*.55):int(h*.70), int(w*.1):int(w*.9)].mean(axis=1)
                    broad = pixels[int(h*.80):int(h*.95), int(w*.1):int(w*.9)].mean(axis=1)
                    medium = pixels[int(h*.1):int(h*.4), int(w*.55):int(w*.95)].mean(axis=0)
                    return {"fine_stddev": float(fine.std()), "broad_stddev": float(broad.std()),
                            "medium_stddev": float(medium.std())}
                bs, cs = stripe_response(x), stripe_response(y)
                comparisons.append({"file": capture["file"], "look": capture["look"],
                    "size": list(a.size), "exact_pixels": a.tobytes() == b.tobytes(),
                    "mean_rgb_error": sum(difference.mean) / 3,
                    "baseline_luma_stddev": x_std, "candidate_luma_stddev": y_std,
                    "structure_correlation": float((xn * yn).mean()),
                    "normalized_structure_mae": float(np.abs(xn - yn).mean()),
                    "normalized_gradient_change_percent": (gy / gx - 1) * 100,
                    "stripe_response_baseline": bs, "stripe_response_candidate": cs,
                    "fine_to_broad_change_percent": ((cs["fine_stddev"] / cs["broad_stddev"]) /
                        (bs["fine_stddev"] / bs["broad_stddev"]) - 1) * 100,
                    "medium_to_broad_change_percent": ((cs["medium_stddev"] / cs["broad_stddev"]) /
                        (bs["medium_stddev"] / bs["broad_stddev"]) - 1) * 100})
        report["comparisons"] = comparisons
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare-baseline", type=Path)
    run(parser.parse_args())
