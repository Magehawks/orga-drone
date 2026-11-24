"""Package a freshly built onefolder for local human acceptance, never publish it."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--analysis-toc", type=Path, required=True)
    parser.add_argument("--build-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("Use a fresh output directory; existing files are never replaced.")
    subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            args.build_sha,
            "--",
            "src",
            "packaging/orga-drone.spec",
            "packaging/run_orga_drone.py",
        ],
        cwd=ROOT,
        check=True,
    )
    toc = ast.literal_eval(args.analysis_toc.read_text(encoding="utf-8"))
    modules: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, (tuple, list)):
            if (
                len(value) == 3
                and isinstance(value[0], str)
                and value[0].startswith("orga_drone")
                and value[2] == "PYMODULE"
            ):
                modules.append(str(value[1]))
            for item in value:
                walk(item)

    walk(toc)
    if not modules or any(
        not Path(path).resolve().is_relative_to(ROOT / "src") for path in modules
    ):
        raise ValueError("The build contains Orga Drone modules from another checkout.")
    stage = output / "package"
    stage.mkdir(parents=True)
    bundle = stage / "orga-drone"
    shutil.copytree(args.bundle.resolve(), bundle)
    for relative in ("static/js/studio.js", "static/js/studio-lut-webgl.js"):
        if digest(ROOT / "src/orga_drone" / relative) != digest(
            bundle / "_internal/orga_drone" / relative
        ):
            raise ValueError(f"Packaged source mismatch: {relative}")
    # Match the documented release workflow, using the pinned locally built encoder.
    pinned = ROOT / "packaging/third_party/ffmpeg-gpl/bin/ffmpeg.exe"
    encoders = list(bundle.rglob("ffmpeg*.exe"))
    if not encoders:
        raise ValueError("The onefolder has no FFmpeg binary.")
    if pinned.is_file():
        for encoder in encoders:
            shutil.copyfile(pinned, encoder)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "packaging/windows_third_party.py"),
            "write",
            str(bundle),
        ],
        env=env,
        check=True,
    )
    banned = {
        ".sqlite",
        ".sqlite3",
        ".db",
        ".mp4",
        ".mov",
        ".lrv",
        ".lrf",
        ".srt",
        ".insv",
        ".dng",
    }
    if any(
        p.is_file() and (p.suffix.lower() in banned or p.name == ".env")
        for p in bundle.rglob("*")
    ):
        raise ValueError(
            "Bundle contains a database, environment file, or source media."
        )
    shutil.copyfile(
        Path(__file__).with_name("Start-Manual-RC.cmd"), stage / "Start-Manual-RC.cmd"
    )
    shutil.copyfile(
        ROOT / "docs/validation/MANUAL_RC_DE.md", stage / "MANUAL_TEST_DE.md"
    )
    # Synthetic creative test transforms; no source media is included.
    sys.path.insert(0, str(ROOT / "packaging/e2e"))
    from studio_crossfade_lut_probe import write_cube  # type: ignore[import-not-found]

    for variant in ("red", "blue"):
        write_cube(stage / f"TEST-creative-{variant}.cube", size=17, variant=variant)
    exe = bundle / "orga-drone.exe"
    manifest = {
        "kind": "local-manual-rc-not-release-or-admission-evidence",
        "build_sha": args.build_sha,
        "exe_sha256": digest(exe),
        "verified_current_checkout_modules": len(modules),
        "ffmpeg_version": subprocess.check_output(
            [str(encoders[0]), "-version"], text=True
        ).splitlines()[0],
        "ffmpeg_sha256": digest(encoders[0]),
        "third_party_verdict": (
            bundle / "THIRD_PARTY_NOTICES/ITCH_SALE_VERDICT.txt"
        ).read_text(encoding="utf-8"),
        "human_acceptance": "NOT TESTED",
        "motw_explorer_extraction": "NOT TESTED; required before publication",
        "isolation": "Start-Manual-RC.cmd -> manual-test-data beside this launcher; ephemeral loopback port; CDP off",
    }
    (stage / "RC_BUILD.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    archive = output / f"orga-drone-manual-rc-{args.build_sha[:7]}.zip"
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zipped:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(stage).as_posix())
    extracted = output / "extracted-test"
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:
            raise ValueError("ZIP CRC verification failed.")
        zipped.extractall(extracted)
    files = [p for p in stage.rglob("*") if p.is_file()]
    if any(digest(p) != digest(extracted / p.relative_to(stage)) for p in files):
        raise ValueError("Extracted files do not match packaged files.")
    manifest.update(
        zip_sha256=digest(archive),
        zip_bytes=archive.stat().st_size,
        extraction="PASS, programmatic CRC and every-file SHA-256",
        packaged_files=len(files),
    )
    (output / "rc-build.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (output / (archive.name + ".sha256")).write_text(
        f"{manifest['zip_sha256']}  {archive.name}\n", encoding="ascii", newline="\n"
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
