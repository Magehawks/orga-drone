#!/usr/bin/env python3
"""Controlled temporary mutations that must fail matching regression gates.

Every mutation is applied, verified to fail, then reverted. Nothing is committed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutation:
    name: str
    path: Path
    old: str
    new: str
    verify_cmd: list[str]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    src = str(ROOT / "src")
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not prev else src + os.pathsep + prev
    return env


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=_env(),
    )


def _git_checkout(paths: list[Path]) -> None:
    rels = [str(p.relative_to(ROOT)).replace("\\", "/") for p in paths]
    subprocess.run(["git", "checkout", "--", *rels], cwd=ROOT, check=True)


def _apply_text_mutation(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Mutation anchor not found in {path}: {old!r}")
    if text.count(old) != 1:
        raise RuntimeError(f"Mutation anchor not unique in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def build_mutations() -> list[Mutation]:
    py = sys.executable
    return [
        Mutation(
            name="incorrect_canvas_coordinate_mapping",
            path=ROOT / "src/orga_drone/studio_mask.py",
            old="    return origin_x, origin_y, content_w, content_h\n",
            new="    return 0, 0, frame_width, frame_height  # MUTATION\n",
            verify_cmd=[
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_studio_mask.py::test_letterbox_box_scales_between_resolutions",
            ],
        ),
        Mutation(
            name="broken_hsl_export",
            path=ROOT / "src/orga_drone/studio_hsl.py",
            old=(
                "def apply_hsl_rgb(red: float, green: float, blue: float, hsl: HslAdjust) "
                "-> tuple[float, float, float]:\n"
                "    \"\"\"Apply the mixer to one RGB triple. Neutral returns the input exactly.\"\"\"\n"
            ),
            new=(
                "def apply_hsl_rgb(red: float, green: float, blue: float, hsl: HslAdjust) "
                "-> tuple[float, float, float]:\n"
                "    \"\"\"Apply the mixer to one RGB triple. Neutral returns the input exactly.\"\"\"\n"
                "    return red, green, blue  # MUTATION broken_hsl_export\n"
            ),
            verify_cmd=[
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_photo_hsl_export_api.py::test_api_export_applies_blue_saturation_minus_100_jpg_and_png",
            ],
        ),
        Mutation(
            name="incorrect_clip_targeting",
            path=ROOT / "src/orga_drone/control.py",
            old=(
                "        elif not project_action and not export_command and expected_clip != state[\"clip_id\"]:\n"
                "            raise ControlError(\"STALE_SELECTION\")\n"
            ),
            new=(
                "        elif False and not project_action and not export_command and expected_clip != state[\"clip_id\"]:\n"
                "            raise ControlError(\"STALE_SELECTION\")  # MUTATION incorrect_clip_targeting\n"
            ),
            verify_cmd=[
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_control_api.py::test_apply_action_wrong_clip_target_is_rejected",
            ],
        ),
        Mutation(
            name="disabled_persistence",
            path=ROOT / "src/orga_drone/studio_history.py",
            old="        if after == before:\n",
            new="        if True or after == before:  # MUTATION disabled_persistence\n",
            verify_cmd=[
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_studio_history.py",
            ],
        ),
        Mutation(
            name="broken_undo_redo",
            path=ROOT / "src/orga_drone/studio_history.py",
            old=(
                "def undo_story(db: Database, project_id: int) -> bool:\n"
                "    with transactional_story_undo(db, project_id) as conn:\n"
                "        return conn is not None\n"
            ),
            new=(
                "def undo_story(db: Database, project_id: int) -> bool:\n"
                "    return False  # MUTATION broken_undo_redo\n"
                "    with transactional_story_undo(db, project_id) as conn:\n"
                "        return conn is not None\n"
            ),
            verify_cmd=[
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_studio_history.py",
            ],
        ),
        Mutation(
            name="broken_loop_mapping",
            path=ROOT / "src/orga_drone/static/js/studio/proxy-loop-map.js",
            old="  return proxyActive ? offset : inS + offset;\n",
            new="  return inS + offset; // MUTATION broken_loop_mapping\n",
            verify_cmd=["node", "--test", "tests/js/proxy_loop_map.test.js"],
        ),
        Mutation(
            name="broken_keyframe_interpolation",
            path=ROOT / "src/orga_drone/studio_color_animation.py",
            old=(
                "        exposure=_clamp_slider(round(_lerp(a.exposure, b.exposure, w))),\n"
            ),
            new=(
                "        exposure=a.exposure,  # MUTATION broken_keyframe_interpolation\n"
            ),
            verify_cmd=[
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_playback_effects_regression_contract.py::test_contract_211_keyframe_interpolation_is_deterministic",
            ],
        ),
        Mutation(
            name="incorrect_transition_timing",
            path=ROOT / "src/orga_drone/studio_transition.py",
            old=(
                "def clamp_user_duration(duration_s: float) -> float:\n"
                "    \"\"\"Clamp to 0.1–2.0 s and snap to 0.1 s steps.\"\"\"\n"
                "    stepped = round(float(duration_s) / DURATION_STEP_S) * DURATION_STEP_S\n"
            ),
            new=(
                "def clamp_user_duration(duration_s: float) -> float:\n"
                "    \"\"\"Clamp to 0.1–2.0 s and snap to 0.1 s steps.\"\"\"\n"
                "    return float(duration_s)  # MUTATION incorrect_transition_timing\n"
                "    stepped = round(float(duration_s) / DURATION_STEP_S) * DURATION_STEP_S\n"
            ),
            verify_cmd=[
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_studio_transition.py::test_clamp_user_duration_steps",
            ],
        ),
        Mutation(
            name="missing_collage_export_cleanup",
            path=ROOT / "src/orga_drone/studio_collage_export.py",
            old="        shutil.rmtree(tmp_dir, ignore_errors=True)\n",
            new="        pass  # MUTATION missing_collage_export_cleanup\n",
            verify_cmd=[
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_studio_collage_export.py::test_story_cleans_up_failed_segment_and_preserves_existing_export",
            ],
        ),
        Mutation(
            name="incorrect_scope_accumulation",
            path=ROOT / "src/orga_drone/static/js/studio/scopes/accumulate.js",
            old="export function histogramBin(code) {\n  return Math.min(255, Math.floor(256 * clamp01(code)));\n}\n",
            new="export function histogramBin(code) {\n  return Math.min(255, Math.floor(128 * clamp01(code))); // MUTATION\n}\n",
            verify_cmd=["node", "--test", "tests/js/scopes_accumulate.test.js"],
        ),
        Mutation(
            name="authorization_bypass",
            path=ROOT / "src/orga_drone/local_http.py",
            old=(
                "def trusted_host(host: str) -> bool:\n"
                "    name = host_name(host)\n"
                "    if name in LOOPBACK_HOSTS:\n"
                "        return True\n"
                "    return f\"[{name}]\" in LOOPBACK_HOSTS\n"
            ),
            new=(
                "def trusted_host(host: str) -> bool:\n"
                "    return True  # MUTATION authorization_bypass\n"
            ),
            verify_cmd=[
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_local_http.py::test_loopback_hosts_are_trusted",
            ],
        ),
    ]


def main() -> int:
    results: list[dict[str, object]] = []
    mutations = build_mutations()
    touched: list[Path] = []
    try:
        for mutation in mutations:
            print(f"==> mutate {mutation.name}")
            _apply_text_mutation(mutation.path, mutation.old, mutation.new)
            touched.append(mutation.path)
            started = time.time()
            proc = _run(mutation.verify_cmd)
            elapsed = round(time.time() - started, 2)
            failed = proc.returncode != 0
            results.append(
                {
                    "mutation": mutation.name,
                    "path": str(mutation.path.relative_to(ROOT)).replace("\\", "/"),
                    "verify_cmd": mutation.verify_cmd,
                    "failed_as_expected": failed,
                    "returncode": proc.returncode,
                    "elapsed_s": elapsed,
                    "stdout_tail": (proc.stdout or "")[-1200:],
                    "stderr_tail": (proc.stderr or "")[-1200:],
                }
            )
            print(
                f"    result returncode={proc.returncode} "
                f"failed_as_expected={failed} ({elapsed}s)"
            )
            _git_checkout([mutation.path])
            touched.remove(mutation.path)
            if not failed:
                print(f"ERROR: mutation {mutation.name} did not fail the gate")
                return 2

        print("==> clean curated gates after revert")
        clean = _run([sys.executable, str(ROOT / "scripts" / "run_regression_gates.py")])
        results.append(
            {
                "mutation": "CLEAN_SUITE",
                "failed_as_expected": clean.returncode == 0,
                "returncode": clean.returncode,
                "stdout_tail": (clean.stdout or "")[-1200:],
                "stderr_tail": (clean.stderr or "")[-1200:],
            }
        )
        if clean.returncode != 0:
            print("ERROR: clean suite failed after mutations were reverted")
            print(clean.stdout)
            print(clean.stderr)
            return 3

        compact = []
        for row in results:
            entry = {
                "mutation": row["mutation"],
                "failed_as_expected": row["failed_as_expected"],
                "returncode": row["returncode"],
                "reverted": row["mutation"] != "CLEAN_SUITE",
            }
            if "path" in row:
                entry["production_path"] = str(Path(row["path"]).as_posix())
            if "verify_cmd" in row:
                # Drop absolute interpreter paths from committed evidence.
                cmd = list(row["verify_cmd"])
                if cmd and Path(cmd[0]).name.lower().startswith("python"):
                    cmd[0] = "python"
                entry["verify_cmd"] = cmd
            compact.append(entry)
        evidence = {
            "schema": "orga-drone-regression-mutation-results-v1",
            "issues": [275, 283, 284],
            "harness": "scripts/mutation_check_regression_gates.py",
            "all_caught": all(
                r["failed_as_expected"] for r in compact if r["mutation"] != "CLEAN_SUITE"
            ),
            "clean_suite_after_revert": (
                "PASS"
                if next(r for r in compact if r["mutation"] == "CLEAN_SUITE")["returncode"] == 0
                else "FAIL"
            ),
            "results": [r for r in compact if r["mutation"] != "CLEAN_SUITE"],
        }
        json_out = ROOT / "docs/discovery/275-283-284-mutation-results.json"
        json_out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        out = ROOT / "docs/discovery/regression-gates-mutation-evidence.md"
        lines = [
            "# Regression gate mutation evidence",
            "",
            "Generated by `scripts/mutation_check_regression_gates.py`.",
            "Deliberate production regressions were **not** committed.",
            "",
            "| Mutation | Matching gate failed? | Return code |",
            "| --- | --- | --- |",
        ]
        for row in results:
            if row["mutation"] == "CLEAN_SUITE":
                continue
            lines.append(
                f"| `{row['mutation']}` | "
                f"{'YES' if row['failed_as_expected'] else 'NO'} | "
                f"{row['returncode']} |"
            )
        clean_row = next(r for r in results if r["mutation"] == "CLEAN_SUITE")
        lines.extend(
            [
                "",
                f"Clean curated suite after revert: "
                f"{'PASS' if clean_row['returncode'] == 0 else 'FAIL'} "
                f"(exit {clean_row['returncode']}).",
                "",
                "Machine-readable companion: "
                "[`275-283-284-mutation-results.json`](275-283-284-mutation-results.json).",
                "",
            ]
        )
        out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        print(f"wrote {out}")
        print(f"wrote {json_out}")
        return 0
    finally:
        if touched:
            _git_checkout(touched)


if __name__ == "__main__":
    raise SystemExit(main())
