"""Fail-closed plan for an itch.io Windows test channel.

This module never runs butler and never uploads a build. It checks the
onefolder layout, the known Version A zip, and whether this tree may be
called Version B. The maintainer copies the printed command only after the
itch.io page is Draft or Restricted.

See packaging/itch/README.md and ADR 0013.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

VERSION_A_USERVERSION = "1.9.0"
VERSION_B_USERVERSION = "1.10.0"
BASELINE_COMMIT = "9eb28b0"
BASELINE_ZIP_SHA256 = (
    "DB79717444EDD34A26DD43BE53E4420FCDA3075D4430F3F78292640716B70D88"
)
TEST_CHANNEL = "windows-x64-test"
OVERLAYS_READY = Path("packaging") / "itch" / "OVERLAYS_READY"
_TARGET_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38})/[a-z0-9](?:[a-z0-9-]{0,38})$")
_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
_FORBIDDEN_NAMES = {
    ".env",
    "app_prefs.json",
    "startup-crash.log",
    "theme.json",
}
_TOP_LEVEL_MEDIA = {
    ".dng",
    ".heic",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp4",
    ".srt",
}


class PushRefused(Exception):
    """A local guard refused the upload command. Nothing was uploaded."""


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def read_app_version(repo_root: Path) -> str:
    init_py = repo_root / "src" / "orga_drone" / "__init__.py"
    if not init_py.is_file():
        raise PushRefused(f"missing {init_py}")
    match = _VERSION_RE.search(init_py.read_text(encoding="utf-8"))
    if match is None:
        raise PushRefused(f"could not read __version__ from {init_py}")
    return match.group(1)


def version_b_blockers(repo_root: Path) -> tuple[str, ...]:
    """Why this tree must not be uploaded as Version B."""
    blockers: list[str] = []
    version = read_app_version(repo_root)
    if version != VERSION_B_USERVERSION:
        blockers.append(
            f"app version is {version}; Version B requires {VERSION_B_USERVERSION}"
        )
    image = repo_root / "src" / "orga_drone" / "studio_image.py"
    if not image.is_file():
        blockers.append("image correction is missing (src/orga_drone/studio_image.py)")
    marker = repo_root / OVERLAYS_READY
    if not marker.is_file():
        blockers.append(
            "timed overlays are not in this tree (issue #78); "
            f"do not add {OVERLAYS_READY.as_posix()} until that build is real"
        )
    return tuple(blockers)


def validate_onefolder(build_dir: Path) -> None:
    """Require exe + _internal and reject bundled user data or source media."""
    if not build_dir.is_dir():
        raise PushRefused(f"build directory does not exist: {build_dir}")
    exe = build_dir / "orga-drone.exe"
    internal = build_dir / "_internal"
    if not exe.is_file() or exe.stat().st_size <= 0:
        raise PushRefused("onefolder build needs a non-empty orga-drone.exe")
    if not internal.is_dir() or not any(internal.iterdir()):
        raise PushRefused("onefolder build needs a non-empty _internal directory")
    for child in build_dir.iterdir():
        if child.is_file() and child.suffix.lower() in _TOP_LEVEL_MEDIA:
            raise PushRefused(f"refusing to upload source media at {child.name}")
    for path in build_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name in _FORBIDDEN_NAMES or path.name.endswith(".sqlite3"):
            raise PushRefused(f"refusing to upload user data file {path.name}")


def assert_user_data_outside(
    install_dir: Path,
    data_dir: Path,
    media_paths: tuple[Path, ...] = (),
) -> None:
    """Library, settings, and source media must sit outside the install folder."""
    install = install_dir.resolve()
    data = data_dir.resolve()
    if data == install or data.is_relative_to(install) or install.is_relative_to(data):
        raise PushRefused(
            "user data must stay outside the install directory "
            f"({data} is not disjoint from {install})"
        )
    for media in media_paths:
        resolved = media.resolve()
        if resolved == install or resolved.is_relative_to(install):
            raise PushRefused(f"media must not live inside the install directory: {resolved}")


def _fingerprint(root: Path) -> dict[str, str]:
    if root.is_file():
        return {root.name: sha256_file(root)}
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found[path.relative_to(root).as_posix()] = sha256_file(path)
    return found


def replace_install_directory(
    install_dir: Path,
    incoming: Path,
    *,
    data_dir: Path,
    media_paths: tuple[Path, ...] = (),
) -> None:
    """Replace application files inside install_dir. Leave data_dir and media alone.

    Local stand-in for an itch.io app update: the install folder changes, the
    library database and original media do not. This does not talk to itch.io.
    """
    validate_onefolder(install_dir)
    validate_onefolder(incoming)
    install = install_dir.resolve()
    new_build = incoming.resolve()
    if install == new_build or new_build.is_relative_to(install) or install.is_relative_to(new_build):
        raise PushRefused("incoming build must be a different directory from the install")
    assert_user_data_outside(install, data_dir, media_paths)
    before = _fingerprint(data_dir)
    media_before = {path: sha256_file(path) for path in media_paths}
    for child in list(install.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in new_build.iterdir():
        dest = install / child.name
        if child.is_dir():
            shutil.copytree(child, dest)
        else:
            shutil.copy2(child, dest)
    if _fingerprint(data_dir) != before:
        raise PushRefused("user data changed while replacing the install directory")
    for path, digest in media_before.items():
        if sha256_file(path) != digest:
            raise PushRefused(f"media changed while replacing the install directory: {path}")


def _require_visibility(visibility: str) -> str:
    cleaned = visibility.strip().lower()
    if cleaned not in {"draft", "restricted"}:
        raise PushRefused(
            "itch.io page visibility must be draft or restricted; "
            "a public paid launch is refused"
        )
    return cleaned


def _require_target(target: str) -> str:
    cleaned = target.strip()
    if not _TARGET_RE.fullmatch(cleaned):
        raise PushRefused(
            "target must be a lowercase itch.io owner/game slug, without a channel"
        )
    return cleaned


def verify_baseline_zip(zip_path: Path, *, expected_sha256: str | None = None) -> str:
    expected = BASELINE_ZIP_SHA256 if expected_sha256 is None else expected_sha256.strip().upper()
    if not zip_path.is_file():
        raise PushRefused(f"baseline zip does not exist: {zip_path}")
    digest = sha256_file(zip_path)
    if digest != expected:
        raise PushRefused(
            "zip SHA256 does not match Version A "
            f"({BASELINE_COMMIT}); refusing to treat it as the stable baseline"
        )
    return digest


def push_argv(
    *,
    slot: str,
    build_dir: Path,
    target: str,
    visibility: str,
    repo_root: Path | None = None,
    zip_path: Path | None = None,
    channel_exists: bool = False,
    expected_sha256: str | None = None,
) -> list[str]:
    """Return a butler push command. The caller has to run it; this function does not."""
    _require_visibility(visibility)
    owner_game = _require_target(target)
    validate_onefolder(build_dir)
    spec = f"{owner_game}:{TEST_CHANNEL}"
    build = str(build_dir.resolve())
    if slot == "A":
        if channel_exists:
            raise PushRefused(
                "Version A is the first push and must create the hidden test channel"
            )
        if zip_path is None:
            raise PushRefused("Version A requires the baseline zip so its SHA256 can be checked")
        verify_baseline_zip(zip_path, expected_sha256=expected_sha256)
        return [
            "butler",
            "push",
            build,
            spec,
            "--userversion",
            VERSION_A_USERVERSION,
            "--hidden",
        ]
    if slot == "B":
        if repo_root is None:
            raise PushRefused("Version B requires the source tree that produced the build")
        blockers = version_b_blockers(repo_root)
        if blockers:
            raise PushRefused(" ".join(blockers))
        if not channel_exists:
            raise PushRefused(
                "Version B must update the existing test channel. "
                "Creating that channel without --hidden would offer the upload immediately, "
                "and --hidden cannot be used once the channel exists."
            )
        return [
            "butler",
            "push",
            build,
            spec,
            "--userversion",
            VERSION_B_USERVERSION,
        ]
    raise PushRefused("slot must be A or B")


def status_report(repo_root: Path) -> str:
    blockers = version_b_blockers(repo_root)
    blocker_lines = [f"- {item}" for item in blockers] or ["- none"]
    lines = [
        "itch.io upload: not executed by this tool",
        f"test channel: {TEST_CHANNEL}",
        "page visibility required: draft or restricted",
        f"Version A: {VERSION_A_USERVERSION} commit {BASELINE_COMMIT}",
        f"Version A zip SHA256: {BASELINE_ZIP_SHA256}",
        f"Version B: {VERSION_B_USERVERSION}",
        "Version B blockers:",
        *blocker_lines,
        "Windows MOTW smoke test remains mandatory (packaging/README.md).",
        "Direct ZIP installs do not receive itch.io app updates.",
        "User data stays in %APPDATA%\\orga-drone, outside the install directory.",
    ]
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print a fail-closed itch.io test-channel plan. Never uploads."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    status = sub.add_parser("status", help="Show A/B identifiers and Version B blockers")
    status.add_argument("--repo", type=Path, default=None)

    verify = sub.add_parser("verify-zip", help="Check a zip against the Version A SHA256")
    verify.add_argument("zip_path", type=Path)

    layout = sub.add_parser("check-layout", help="Check an onefolder directory")
    layout.add_argument("build_dir", type=Path)

    command = sub.add_parser("command", help="Print a butler push command without running it")
    command.add_argument("--slot", required=True, choices=("A", "B"))
    command.add_argument("--build", required=True, type=Path)
    command.add_argument("--target", required=True)
    command.add_argument("--visibility", required=True)
    command.add_argument("--zip", type=Path, default=None)
    command.add_argument("--repo", type=Path, default=None)
    command.add_argument("--channel-exists", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "status":
            repo = args.repo if args.repo is not None else default_repo_root()
            sys.stdout.write(status_report(repo))
            return 0
        if args.cmd == "verify-zip":
            digest = verify_baseline_zip(args.zip_path)
            sys.stdout.write(f"Version A zip SHA256 matches {digest}\n")
            return 0
        if args.cmd == "check-layout":
            validate_onefolder(args.build_dir)
            sys.stdout.write(f"onefolder layout ok: {args.build_dir}\n")
            return 0
        if args.cmd == "command":
            repo = args.repo if args.repo is not None else default_repo_root()
            argv_out = push_argv(
                slot=args.slot,
                build_dir=args.build,
                target=args.target,
                visibility=args.visibility,
                repo_root=repo,
                zip_path=args.zip,
                channel_exists=args.channel_exists,
            )
            sys.stdout.write(
                "Not executed. Confirm the itch.io page is Draft or Restricted, "
                "then run this command yourself:\n"
            )
            sys.stdout.write(" ".join(argv_out) + "\n")
            return 0
    except PushRefused as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return 2
    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
