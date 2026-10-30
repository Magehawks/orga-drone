"""Windows release tag must match pyproject.toml before any publish."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "verify_release_version.py"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-release.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SPEC = ROOT / "packaging" / "orga-drone.spec"


def _load():
    spec = importlib.util.spec_from_file_location("verify_release_version", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def version_mod():
    return _load()


def _write_versions(
    tmp_path: Path, version: str, init_version: str | None = None
) -> tuple[Path, Path]:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'[project]\nname = "orga-drone"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    package_init = tmp_path / "__init__.py"
    package_init.write_text(
        f'__version__ = "{init_version or version}"\n',
        encoding="utf-8",
    )
    return pyproject, package_init


def test_checked_in_version_matches_its_tag(version_mod) -> None:
    pyproject = ROOT / "pyproject.toml"
    package_init = ROOT / "src" / "orga_drone" / "__init__.py"
    version = version_mod.verify_release_version(pyproject, package_init, tag=None)
    assert version_mod.SEMVER_RE.fullmatch(version)
    assert (
        version_mod.verify_release_version(
            pyproject, package_init, tag=f"v{version}"
        )
        == version
    )


def test_tag_mismatch_fails(version_mod, tmp_path: Path) -> None:
    pyproject, package_init = _write_versions(tmp_path, "1.2.3")
    with pytest.raises(version_mod.ReleaseVersionError, match="does not match"):
        version_mod.verify_release_version(pyproject, package_init, tag="v9.9.9")


def test_missing_version_fails(version_mod, tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "orga-drone"\n', encoding="utf-8")
    package_init = tmp_path / "__init__.py"
    package_init.write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    with pytest.raises(version_mod.ReleaseVersionError, match="Missing"):
        version_mod.verify_release_version(pyproject, package_init, tag="v1.2.3")


def test_non_semver_fails(version_mod, tmp_path: Path) -> None:
    pyproject, package_init = _write_versions(tmp_path, "1.2.3rc1")
    with pytest.raises(version_mod.ReleaseVersionError, match="X.Y.Z"):
        version_mod.verify_release_version(pyproject, package_init, tag=None)


def test_init_mismatch_fails(version_mod, tmp_path: Path) -> None:
    pyproject, package_init = _write_versions(tmp_path, "1.2.3", init_version="1.2.4")
    with pytest.raises(version_mod.ReleaseVersionError, match="__version__"):
        version_mod.verify_release_version(pyproject, package_init, tag="v1.2.3")


def test_untagged_name_fails(version_mod, tmp_path: Path) -> None:
    pyproject, package_init = _write_versions(tmp_path, "1.2.3")
    with pytest.raises(version_mod.ReleaseVersionError, match="does not match"):
        version_mod.verify_release_version(pyproject, package_init, tag="1.2.3")


def test_cli_exit_codes(tmp_path: Path) -> None:
    pyproject, package_init = _write_versions(tmp_path, "1.2.3")
    ok = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pyproject",
            str(pyproject),
            "--package-init",
            str(package_init),
            "--tag",
            "v1.2.3",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0
    assert "version=1.2.3" in ok.stdout
    bad = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pyproject",
            str(pyproject),
            "--package-init",
            str(package_init),
            "--tag",
            "v1.2.4",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 1
    assert "does not match" in bad.stderr


def test_windows_release_workflow_is_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "\n    branches:" not in text
    assert "tags:" in text
    assert '- "v*.*.*"' in text
    assert "uses: ./.github/workflows/ci.yml" in text
    assert "needs: [verify-version, quality]" in text
    assert "pyinstaller packaging/orga-drone.spec" in text
    assert "--onefile" not in text
    assert "orga-drone-windows-x64.zip" in text
    assert "--draft" in text
    assert "already published" in text
    assert text.count("contents: write") == 1
    assert "actions/checkout@v" not in text
    assert "actions/setup-python@v" not in text
    assert "actions/upload-artifact@v" not in text
    assert "actions/download-artifact@v" not in text
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_call:" in ci
    assert "ruff check ." in ci
    assert "mypy src" in ci
    assert "pytest" in ci


def test_spec_stays_onefolder() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    assert "exclude_binaries=True" in spec
    assert "COLLECT(" in spec
    assert "upx=False" in spec


def test_draft_notes_script_writes_unindented_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import textwrap

    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "python3 - <<'PY'\n"
    start = text.index(marker) + len(marker)
    body: list[str] = []
    for line in text[start:].splitlines():
        if line.strip() == "PY":
            break
        body.append(line)
    else:
        raise AssertionError("draft notes script is missing its PY terminator")
    script = textwrap.dedent("\n".join(body))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VERSION", "1.2.3")
    monkeypatch.setenv("COMMIT", "abc123")
    monkeypatch.setenv("SHA256", "deadbeef")
    monkeypatch.setenv("TAG", "v1.2.3")
    exec(compile(script, "draft_notes.py", "exec"), {})
    notes = (tmp_path / "DRAFT_RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert notes.startswith("## Draft — notes only (no Windows zip on GitHub)\n")
    assert "| Version | 1.2.3 |" in notes
    assert "| Commit | abc123 |" in notes
    assert "deadbeef  orga-drone-windows-x64.zip" in notes
    assert "Actions artifact `orga-drone-windows-x64`" in notes
    assert "without** uploading `orga-drone-windows-x64.zip`" in notes
