"""Fail closed unless a release tag matches ``pyproject.toml``.

The Windows release workflow runs this before packaging and before any
GitHub Release is created. A missing version, a non ``X.Y.Z`` version, a
``__version__`` drift, or a tag other than ``v{version}`` exits 1.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
INIT_VERSION_RE = re.compile(r'(?m)^__version__\s*=\s*"([^"]+)"\s*$')


class ReleaseVersionError(Exception):
    """The tag or version files are not safe to publish."""


def pyproject_version(path: Path) -> str:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseVersionError(f"Cannot read version from {path}: {exc}") from exc
    project = data.get("project")
    if not isinstance(project, dict):
        raise ReleaseVersionError(f"Missing [project] table in {path}")
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ReleaseVersionError(f"Missing project.version in {path}")
    version = version.strip()
    if SEMVER_RE.fullmatch(version) is None:
        raise ReleaseVersionError(f"project.version {version!r} is not X.Y.Z")
    return version


def package_version(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseVersionError(f"Cannot read {path}: {exc}") from exc
    match = INIT_VERSION_RE.search(text)
    if match is None:
        raise ReleaseVersionError(f"Missing __version__ in {path}")
    found = match.group(1)
    if SEMVER_RE.fullmatch(found) is None:
        raise ReleaseVersionError(f"__version__ {found!r} is not X.Y.Z")
    return found


def verify_release_version(
    pyproject: Path,
    package_init: Path,
    tag: str | None,
) -> str:
    """Return the pyproject version, or raise ``ReleaseVersionError``."""
    version = pyproject_version(pyproject)
    init_version = package_version(package_init)
    if init_version != version:
        raise ReleaseVersionError(
            f"__version__ {init_version!r} does not match pyproject.toml {version!r}"
        )
    if tag is not None:
        expected = f"v{version}"
        if tag != expected:
            raise ReleaseVersionError(
                f"Tag {tag!r} does not match pyproject.toml version "
                f"{version!r} (expected {expected})"
            )
    return version


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default=None,
        help="Git tag to compare. Omit to only check version files.",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=root / "pyproject.toml",
    )
    parser.add_argument(
        "--package-init",
        type=Path,
        default=root / "src" / "orga_drone" / "__init__.py",
    )
    args = parser.parse_args(argv)
    try:
        version = verify_release_version(args.pyproject, args.package_init, args.tag)
    except ReleaseVersionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"version={version}")
    if args.tag:
        print(f"tag={args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
