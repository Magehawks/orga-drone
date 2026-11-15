"""Run existing synthetic packaged probes on an extracted local manual RC.

This creates no GitHub admission evidence. A failed strict quality gate remains
failed even when the corresponding bounded fixture or functional journey passes.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROBES = ROOT / "packaging/e2e"


def gate_result(passed: object) -> str:
    if passed is None:
        return "NOT TESTED"
    return "PASS" if passed is True else "FAIL"


def timing_gate(drift: float | None) -> str:
    if drift is None:
        return "NOT TESTED"
    # Native metadata is recorded to microseconds, not an extra frame allowance.
    return gate_result(math.isfinite(drift) and 0 <= drift <= 1 / 30 + 0.000001)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    package = args.package_dir.resolve()
    out = args.output_dir.resolve()
    if out.exists():
        parser.error("Use a fresh smoke output directory.")
    out.mkdir(parents=True)
    manifest = json.loads((package / "rc-build.json").read_text(encoding="utf-8"))
    exe = package / "extracted-test/orga-drone/orga-drone.exe"
    ffmpeg = next((exe.parent / "_internal/imageio_ffmpeg/binaries").glob("*.exe"))
    archive = package / f"orga-drone-manual-rc-{manifest['build_sha'][:7]}.zip"
    sha = manifest["build_sha"]
    tree = subprocess.check_output(
        ["git", "rev-parse", f"{sha}^{{tree}}"], cwd=ROOT, text=True
    ).strip()
    commands: list[tuple[str, str, list[str]]] = [
        (
            "functional",
            "windows_e2e.py",
            [
                "--zip",
                str(archive),
                "--zip-sha256",
                manifest["zip_sha256"],
                "--artifact-name",
                "local-manual-rc-not-an-actions-artifact",
                "--artifact-api-digest",
                "NOT_APPLICABLE_LOCAL_ONLY",
                "--artifact-api-size",
                "0",
                "--repository",
                "Magehawks/orga-drone",
                "--pr-number",
                "0",
                "--head-sha",
                sha,
                "--base-sha",
                sha,
                "--merge-sha",
                sha,
                "--tree-sha",
                tree,
                "--run-id",
                "0",
                "--run-attempt",
                "1",
            ],
        ),
        ("color", "studio_color_probe.py", []),
        (
            "lut-creative",
            "studio_lut_smoke.py",
            ["--fixture-dir", str(out / "color"), "--lut-role", "creative"],
        ),
        (
            "lut-conversion",
            "studio_lut_smoke.py",
            ["--fixture-dir", str(out / "color"), "--lut-role", "conversion"],
        ),
        *[
            (
                f"clock-{transition}",
                "studio_clock_probe.py",
                ["--transition", transition],
            )
            for transition in ("cut", "fade_black", "crossfade")
        ],
        *[
            (
                f"crossfade-lut-{mode}",
                "studio_crossfade_lut_probe.py",
                ["--lut-mode", mode],
            )
            for mode in ("one", "two")
        ],
    ]
    summary: dict = {
        "kind": "local-manual-rc-smoke-not-admission-evidence",
        "build_sha": sha,
        "zip_sha256": manifest["zip_sha256"],
        "commands": {},
        "quality_gates": {
            "real_DJI_crossfade_one_frame": "FAIL carried from #316; not retested as a human acceptance test",
            "human_acceptance": "NOT TESTED",
            "MOTW_Explorer_native_dialogs": "NOT TESTED",
        },
    }
    for name, script, extra in commands:
        command = [
            sys.executable,
            str(PROBES / script),
            "--exe",
            str(exe),
            "--ffmpeg",
            str(ffmpeg),
            "--output-dir",
            str(out / name),
            *extra,
        ]
        with (out / f"{name}.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT
            )
        summary["commands"][name] = {"exit_code": result.returncode}
        print(name, result.returncode, flush=True)
        (out / "smoke-summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    for name, _, _ in commands:
        report_path = (
            out / name / ("evidence.json" if name == "functional" else "report.json")
        )
        if not report_path.is_file():
            summary["commands"][name]["status"] = "MISSING_REPORT"
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if name == "functional":
            summary["commands"][name].update(
                result=report.get("result"),
                journeys=report.get("journeys"),
                webview2_version=report.get("webview2_version"),
            )
        else:
            keys = (
                "status",
                "errors",
                "source_unchanged",
                "sources_unchanged",
                "summary",
                "playback_summary",
                "inside_crossfade_summary",
                "strict_parity_pass",
                "parity_pass",
                "decision",
                "lut_role",
                "applied_color_look",
                "paused_vs_export",
                "playing_vs_export",
                "seek_vs_export",
                "baseline_max_swatch_mean_rgb_error",
                "tolerance_max_swatch_mean_rgb",
                "browser",
            )
            summary["commands"][name].update(
                {k: report[k] for k in keys if k in report}
            )
    for role in ("creative", "conversion"):
        report = summary["commands"][f"lut-{role}"]
        summary["quality_gates"][f"lut_{role}_strict_3_levels"] = gate_result(
            report.get("strict_parity_pass")
        )
        summary["quality_gates"][f"lut_{role}_existing_bounded_fixture"] = gate_result(
            report.get("parity_pass")
        )
    # Existing traces round source timestamps to microseconds. This numerical
    # epsilon does not allow an additional frame, nor waive #316's real gate.
    for name, key in (
        ("clock-crossfade", "summary"),
        ("crossfade-lut-one", "playback_summary"),
        ("crossfade-lut-two", "playback_summary"),
    ):
        drift = summary["commands"][name].get(key, {}).get("presented_pair_drift_max_s")
        summary["quality_gates"][f"{name}_synthetic_one_frame"] = timing_gate(drift)
    summary["functional_commands_pass"] = all(
        result["exit_code"] == 0 for result in summary["commands"].values()
    )
    summary["release_authorized"] = False
    (out / "smoke-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary["quality_gates"], indent=2))
    return (
        1
        if any(value != "PASS" for value in summary["quality_gates"].values())
        or not summary["functional_commands_pass"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
