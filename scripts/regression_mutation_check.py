"""Controlled temporary mutations proving permanent regression gates catch faults.

Mutates production sources, runs the mapped suite, expects FAILURE, then reverts
every change with git checkout. Never commits deliberate regressions.

Usage (from repo root, clean worktree):
  python scripts/regression_mutation_check.py
  python scripts/regression_mutation_check.py --case hsl_export
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MutationCase:
    id: str
    description: str
    path: str
    old: str
    new: str
    command: list[str]


CASES: list[MutationCase] = [
    MutationCase(
        id="canvas_coordinate_mapping",
        description="Invert letterbox content scale so mask boxes leave the picture",
        path="src/orga_drone/studio_mask.py",
        old="    scale = min(frame_w / src_w, frame_h / src_h)",
        new="    scale = max(frame_w / src_w, frame_h / src_h)  # MUTATION: wrong contain fit",
        command=[
            sys.executable,
            "-m",
            "pytest",
            "tests/test_studio_mask.py::test_letterbox_box_scales_between_resolutions",
            "-q",
            "--tb=line",
        ],
    ),
    MutationCase(
        id="hsl_export",
        description="No-op HSL apply so graded export matches neutral",
        path="src/orga_drone/studio_hsl.py",
        old=(
            "    if not hue_delta and saturation_factor == 1.0 and not luminance_delta:\n"
            "        return red, green, blue\n"
            "    new_hue = _wrap_hue(hue + hue_delta)\n"
            "    new_saturation = min(1.0, max(0.0, saturation * max(0.0, saturation_factor)))"
        ),
        new=(
            "    if True:  # MUTATION: disable HSL export effect\n"
            "        return red, green, blue\n"
            "    new_hue = _wrap_hue(hue + hue_delta)\n"
            "    new_saturation = min(1.0, max(0.0, saturation * max(0.0, saturation_factor)))"
        ),
        command=[
            sys.executable,
            "-m",
            "pytest",
            "tests/test_photo_hsl_export_api.py::test_api_export_applies_blue_saturation_minus_100_jpg_and_png",
            "-q",
            "--tb=line",
        ],
    ),
    MutationCase(
        id="clip_targeting",
        description="Skip wrong-clip STALE_SELECTION rejection",
        path="src/orga_drone/control.py",
        old=(
            "        elif not project_action and not export_command "
            'and expected_clip != state["clip_id"]:\n'
            '            raise ControlError("STALE_SELECTION")'
        ),
        new=(
            "        elif not project_action and not export_command "
            'and expected_clip != state["clip_id"]:\n'
            "            pass  # MUTATION: skip wrong-clip targeting"
        ),
        command=[
            sys.executable,
            "-m",
            "pytest",
            "tests/test_control_api.py::test_apply_action_wrong_clip_target_is_rejected",
            "-q",
            "--tb=line",
        ],
    ),
    MutationCase(
        id="persistence",
        description="Skip appending story undo snapshots so edits are not reversible in history",
        path="src/orga_drone/studio_history.py",
        old=(
            "            hist.undo.append(before)\n"
            "            extra = len(hist.undo) - MAX_STORY_HISTORY"
        ),
        new=(
            "            # MUTATION: disable persistence into undo stack\n"
            "            extra = len(hist.undo) - MAX_STORY_HISTORY"
        ),
        command=[
            sys.executable,
            "-m",
            "pytest",
            "tests/test_studio_history.py::test_cut_remove_trim_reorder_and_redo_invalidation",
            "-q",
            "--tb=line",
        ],
    ),
    MutationCase(
        id="undo_redo",
        description="Make undo_story always report failure",
        path="src/orga_drone/studio_history.py",
        old=(
            "def undo_story(db: Database, project_id: int) -> bool:\n"
            "    with transactional_story_undo(db, project_id) as conn:\n"
            "        return conn is not None"
        ),
        new=(
            "def undo_story(db: Database, project_id: int) -> bool:\n"
            "    return False  # MUTATION: break undo\n"
            "    with transactional_story_undo(db, project_id) as conn:\n"
            "        return conn is not None"
        ),
        command=[
            sys.executable,
            "-m",
            "pytest",
            "tests/test_studio_history.py::test_effects_group_into_one_step_and_restart_drops_history",
            "-q",
            "--tb=line",
        ],
    ),
    MutationCase(
        id="transition_timing",
        description="Clamp transition duration to a constant wrong value",
        path="src/orga_drone/studio_transition.py",
        old="def clamp_user_duration(duration_s: float) -> float:",
        new=(
            "def clamp_user_duration(duration_s: float) -> float:\n"
            "    return 1.7  # MUTATION: ignore requested timing"
        ),
        command=[
            sys.executable,
            "-m",
            "pytest",
            "tests/test_studio_transition.py::test_clamp_user_duration_steps",
            "-q",
            "--tb=line",
        ],
    ),
    MutationCase(
        id="collage_export_cleanup",
        description="Skip collage export temp directory cleanup on failure",
        path="src/orga_drone/studio_collage_export.py",
        old="        shutil.rmtree(tmp_dir, ignore_errors=True)",
        new=(
            "        pass  # MUTATION: skip collage export cleanup\n"
            "        # shutil.rmtree(tmp_dir, ignore_errors=True)"
        ),
        command=[
            sys.executable,
            "-m",
            "pytest",
            "tests/test_studio_collage_export.py::test_story_cleans_up_failed_segment_and_preserves_existing_export",
            "-q",
            "--tb=line",
        ],
    ),
    MutationCase(
        id="scope_accumulation",
        description="Offset histogram bins so mid-gray no longer peaks at 128",
        path="src/orga_drone/static/js/studio/scopes/accumulate.js",
        old=(
            "export function histogramBin(code) {\n"
            "  return Math.min(255, Math.floor(256 * clamp01(code)));\n"
            "}"
        ),
        new=(
            "export function histogramBin(code) {\n"
            "  return Math.min(255, Math.floor(256 * clamp01(code)) + 32); // MUTATION\n"
            "}"
        ),
        command=["npm", "run", "test:js", "--", "tests/js/scopes_accumulate.test.js"],
    ),
    MutationCase(
        id="authorization_bypass",
        description="Allow foreign Host instead of returning 403",
        path="src/orga_drone/local_http.py",
        old='            return _forbidden("Host is not allowed")',
        new="            return await call_next(request)  # MUTATION: authorization bypass",
        command=[
            sys.executable,
            "-m",
            "pytest",
            "tests/test_local_http.py::test_foreign_host_and_origin_are_rejected",
            "-q",
            "--tb=line",
        ],
    ),
]


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    if cmd and cmd[0] == "npm" and sys.platform == "win32":
        # Prefer npm.cmd so PATH resolution works without shell=True list quirks.
        cmd = ["npm.cmd", *cmd[1:]]
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)


def git_checkout(rel: str) -> None:
    completed = run(["git", "checkout", "--", rel])
    if completed.returncode != 0:
        raise RuntimeError(f"Failed to revert {rel}: {completed.stderr}")


def apply_mutation(case: MutationCase) -> None:
    path = ROOT / case.path
    text = path.read_text(encoding="utf-8")
    if case.old not in text:
        raise RuntimeError(f"{case.id}: mutation anchor not found in {case.path}")
    if text.count(case.old) != 1:
        raise RuntimeError(f"{case.id}: mutation anchor is not unique in {case.path}")
    path.write_text(text.replace(case.old, case.new, 1), encoding="utf-8")


def ensure_clean(paths: set[str]) -> None:
    completed = run(["git", "status", "--porcelain", "--", *sorted(paths)])
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    dirty = [line for line in completed.stdout.splitlines() if line.strip()]
    if dirty:
        raise RuntimeError(
            "Worktree has local edits in mutation targets; commit/stash first:\n"
            + "\n".join(dirty)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "docs/discovery/275-283-284-mutation-results.json",
    )
    args = parser.parse_args()
    selected = [c for c in CASES if not args.cases or c.id in args.cases]
    if not selected:
        print("No cases selected", file=sys.stderr)
        return 2
    ensure_clean({c.path for c in selected})
    results: list[dict[str, object]] = []
    failed_integrity = False
    for case in selected:
        print(f"==> mutating {case.id}: {case.description}")
        apply_mutation(case)
        try:
            completed = run(case.command)
            expected_fail = completed.returncode != 0
            status = "caught" if expected_fail else "MISSED"
            if not expected_fail:
                failed_integrity = True
            snippet = (completed.stdout + completed.stderr)[-1200:]
            print(f"    test exit={completed.returncode} -> {status}")
            results.append(
                {
                    "id": case.id,
                    "description": case.description,
                    "path": case.path,
                    "command": case.command,
                    "test_exit_code": completed.returncode,
                    "caught": expected_fail,
                    "output_tail": snippet,
                }
            )
        finally:
            git_checkout(case.path)
            print(f"    reverted {case.path}")
    ensure_clean({c.path for c in selected})
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "orga-drone-regression-mutation-results-v1",
        "cases": results,
        "all_caught": all(bool(item["caught"]) for item in results),
        "note": "Mutations were temporary and reverted; nothing was committed.",
    }
    args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.json_out}")
    return 1 if failed_integrity else 0


if __name__ == "__main__":
    raise SystemExit(main())