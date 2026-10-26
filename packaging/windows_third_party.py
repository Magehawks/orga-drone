"""Write third-party notices from a Windows onefolder and refuse an unproven sale.

The script copies evidence it can read from the built folder and from the
installed wheels. It does not decide that the bundle is license-compliant.
``verify-zip`` exits 2 when the itch.io sale verdict is NO-GO, so the release
workflow stops before uploading that zip.

This does not change the MIT license of Orga Drone.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

NOTICES = "THIRD_PARTY_NOTICES"
VERDICT_NAME = "ITCH_SALE_VERDICT.txt"
ZIP_PREFIX = "orga-drone/" + NOTICES + "/"

_REQUIRED_IN_NOTICES = (
    "README.txt",
    VERDICT_NAME,
    "ffmpeg-version.txt",
    "ffmpeg-buildconf.txt",
    "ffmpeg-sha256.txt",
    "imageio-ffmpeg-LICENSE",
    "reverse-geocoder-LGPL-2.1.txt",
    "reverse-geocoder/__init__.py",
    "reverse-geocoder/cKDTree_MP.py",
    "reverse-geocoder/METADATA",
    "reverse-geocoder/WHEEL_HAS_NO_LICENSE.txt",
)

_GPL_FLAGS = ("--enable-gpl", "--enable-version3", "--enable-libx264")
_SOURCE_DIR = "ffmpeg-corresponding-source"
_SOURCE_SHA = "SOURCE_SHA256.txt"


@dataclass(frozen=True)
class FfmpegEvidence:
    sha256: str
    version_text: str
    buildconf_text: str
    flags: tuple[str, ...]


def configuration_flags(version_text: str) -> tuple[str, ...]:
    """Return the flags from the ``configuration:`` line of ``ffmpeg -version``."""
    for line in version_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("configuration:"):
            flags = tuple(part for part in stripped.split()[1:] if part.startswith("--"))
            if not flags:
                raise ValueError("ffmpeg configuration line has no flags")
            return flags
    raise ValueError("ffmpeg -version has no configuration line")


def buildconf_flags(buildconf_text: str) -> tuple[str, ...]:
    flags = tuple(
        line.strip() for line in buildconf_text.splitlines() if line.strip().startswith("--")
    )
    if not flags:
        raise ValueError("ffmpeg -buildconf has no flags")
    return flags


def require_buildconf(version_text: str, buildconf_text: str) -> tuple[str, ...]:
    """Return version flags, or raise if ``-buildconf`` drops one of them."""
    version_flags = configuration_flags(version_text)
    conf_flags = buildconf_flags(buildconf_text)
    missing = [flag for flag in version_flags if flag not in conf_flags]
    if missing:
        raise ValueError("ffmpeg -buildconf is missing flags from -version: " + ", ".join(missing))
    return version_flags


def probe_ffmpeg(exe: Path) -> FfmpegEvidence:
    version_text = _run(exe, ["-hide_banner", "-version"])
    buildconf_text = _run(exe, ["-hide_banner", "-buildconf"])
    flags = require_buildconf(version_text, buildconf_text)
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    return FfmpegEvidence(digest, version_text, buildconf_text, flags)


def itch_sale_blockers(
    evidence: FfmpegEvidence,
    *,
    notices: Path,
    wheel_license_in_bundle: bool,
    geocoder_source_in_bundle: bool,
    geocoder_wheel_license: str,
) -> tuple[str, ...]:
    """Reasons the inspected build is not shown to be sellable on itch.io.

    An empty result would be GO. This tree does not produce an empty result
    for the gyan.dev GPL binary, and it does not treat an empty result as
    legal advice.
    """
    blockers: list[str] = []
    present = [flag for flag in _GPL_FLAGS if flag in evidence.flags]
    source_sha = notices / _SOURCE_DIR / _SOURCE_SHA
    recorded = source_sha.read_text(encoding="utf-8").strip().lower() if source_sha.is_file() else ""
    source_matches = recorded == evidence.sha256
    configure = notices / _SOURCE_DIR / "configure"
    if present and not (source_matches and configure.is_file()):
        blockers.append(
            "Bundled ffmpeg configuration includes "
            + ", ".join(present)
            + ". FFmpeg's own legal page says that using GPL parts makes the GPL apply to "
            "FFmpeg, and it names libx264 as a GPL library. The zip has no corresponding "
            "source whose SOURCE_SHA256.txt matches this binary."
        )
    if not wheel_license_in_bundle:
        blockers.append(
            "The imageio-ffmpeg BSD-2-Clause LICENSE was not already in the onefolder. "
            "A copy was taken from the installed wheel. That BSD text does not license "
            "the ffmpeg executable."
        )
    if geocoder_wheel_license.strip().lower() != "lgpl":
        blockers.append(
            "reverse-geocoder wheel metadata License field is "
            + repr(geocoder_wheel_license)
            + ", not the expected 'lgpl'."
        )
    if not geocoder_source_in_bundle:
        blockers.append(
            "reverse-geocoder 1.5.1 is frozen as bytecode. The wheel ships no LICENSE file "
            "and no copyright header. Upstream master has an LGPL-2.1 LICENSE, but the wheel "
            "was not proven to be that git revision. Copying the .py files into this folder "
            "does not show that a recipient can replace the frozen copy."
        )
    blockers.append(
        "Packages other than ffmpeg, imageio-ffmpeg, and reverse-geocoder in this "
        "onefolder were not audited. This verdict does not clear them."
    )
    return tuple(blockers)


def write_notices(bundle: Path) -> tuple[str, ...]:
    """Write ``THIRD_PARTY_NOTICES`` under ``bundle``. Return sale blockers."""
    exe = _one_ffmpeg(bundle)
    evidence = probe_ffmpeg(exe)
    license_path, license_was_bundled = _imageio_license(bundle)
    geocoder_files, geocoder_license, geocoder_was_bundled = _reverse_geocoder(bundle)
    notices = bundle / NOTICES
    if notices.exists():
        shutil.rmtree(notices)
    notices.mkdir()
    (notices / "ffmpeg-version.txt").write_text(evidence.version_text, encoding="utf-8", newline="\n")
    (notices / "ffmpeg-buildconf.txt").write_text(evidence.buildconf_text, encoding="utf-8", newline="\n")
    (notices / "ffmpeg-sha256.txt").write_text(evidence.sha256 + "\n", encoding="utf-8", newline="\n")
    shutil.copyfile(license_path, notices / "imageio-ffmpeg-LICENSE")
    lgpl = _repo_root() / "packaging" / "third_party" / "reverse-geocoder-LGPL-2.1.txt"
    if not lgpl.is_file():
        raise FileNotFoundError(lgpl)
    shutil.copyfile(lgpl, notices / "reverse-geocoder-LGPL-2.1.txt")
    source = notices / "reverse-geocoder"
    source.mkdir()
    for name, path in geocoder_files.items():
        shutil.copyfile(path, source / name)
    (source / "WHEEL_HAS_NO_LICENSE.txt").write_text(
        "The installed reverse_geocoder wheel has no LICENSE file.\n"
        "Metadata License field: "
        + geocoder_license
        + "\n"
        "The LGPL-2.1 text next to this directory was copied from upstream git master.\n"
        "See packaging/third_party/PROVENANCE.txt. That copy does not prove the wheel "
        "was built from that revision.\n",
        encoding="utf-8",
        newline="\n",
    )
    blockers = itch_sale_blockers(
        evidence,
        notices=notices,
        wheel_license_in_bundle=license_was_bundled,
        geocoder_source_in_bundle=geocoder_was_bundled,
        geocoder_wheel_license=geocoder_license,
    )
    verdict = "GO" if not blockers else "NO-GO"
    lines = [
        verdict,
        "",
        "This file is not a compliance certificate and not legal advice.",
        "itch.io sale of this Windows build is not shown to be permitted.",
        "",
        "ffmpeg sha256: " + evidence.sha256,
        "imageio-ffmpeg LICENSE already in the onefolder: " + str(license_was_bundled).lower(),
        "reverse-geocoder .py already outside the archive: " + str(geocoder_was_bundled).lower(),
        "",
    ]
    if blockers:
        lines.append("Blockers:")
        lines.extend("- " + item for item in blockers)
    else:
        lines.append("No blocker was recorded by this script.")
    text = "\n".join(lines) + "\n"
    (notices / VERDICT_NAME).write_text(text, encoding="utf-8", newline="\n")
    (notices / "README.txt").write_text(
        "Notices collected from the onefolder and the wheels used to build it.\n"
        "Orga Drone remains MIT. These notices do not relicense it.\n"
        "imageio-ffmpeg's BSD-2-Clause license covers that Python package.\n"
        "It does not license the ffmpeg executable shipped in the wheel.\n"
        "ffmpeg -version and ffmpeg -buildconf were run on the bundled executable.\n"
        "Sale verdict: " + verdict + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return blockers


def verify_zip(zip_path: Path) -> int:
    """Return 0 for GO, 2 for a consistent NO-GO, 1 when the zip is incomplete."""
    with zipfile.ZipFile(zip_path) as archive:
        names = {item.replace("\\", "/") for item in archive.namelist()}
        missing = [ZIP_PREFIX + rel for rel in _REQUIRED_IN_NOTICES if ZIP_PREFIX + rel not in names]
        if missing:
            print("missing notice files:\n" + "\n".join(missing), file=sys.stderr)
            return 1
        verdict = archive.read(ZIP_PREFIX + VERDICT_NAME).decode("utf-8")
    first = verdict.splitlines()[0].strip() if verdict.splitlines() else ""
    print(first)
    if first == "NO-GO":
        return 2
    if first == "GO":
        return 0
    print("verdict is neither GO nor NO-GO", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write")
    write.add_argument("bundle", type=Path)
    verify = sub.add_parser("verify-zip")
    verify.add_argument("zip_path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "write":
            blockers = write_notices(args.bundle)
            print("NO-GO" if blockers else "GO")
            return 0
        return verify_zip(args.zip_path)
    except (OSError, ValueError, subprocess.CalledProcessError, importlib.metadata.PackageNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run(exe: Path, args: list[str]) -> str:
    completed = subprocess.run(
        [str(exe), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return completed.stdout


def _one_ffmpeg(bundle: Path) -> Path:
    matches = sorted(path for path in bundle.rglob("ffmpeg*.exe") if path.is_file())
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one ffmpeg executable, found {len(matches)} in {bundle}")
    return matches[0]


def _imageio_license(bundle: Path) -> tuple[Path, bool]:
    found = [
        path
        for path in bundle.rglob("LICENSE")
        if path.is_file() and "imageio_ffmpeg" in path.parent.name
    ]
    if len(found) == 1:
        return found[0], True
    if len(found) > 1:
        raise FileNotFoundError("more than one imageio-ffmpeg LICENSE in the onefolder")
    return _dist_info_file("imageio-ffmpeg", "LICENSE"), False


def _reverse_geocoder(bundle: Path) -> tuple[dict[str, Path], str, bool]:
    distribution = importlib.metadata.distribution("reverse_geocoder")
    metadata = _dist_info_file("reverse_geocoder", "METADATA")
    license_name = distribution.metadata["License"] or ""
    files = {
        "__init__.py": _package_file(distribution, "__init__.py"),
        "cKDTree_MP.py": _package_file(distribution, "cKDTree_MP.py"),
        "METADATA": metadata,
    }
    bundled_source = any(
        path.parent.name == "reverse_geocoder" and NOTICES not in path.parts
        for path in bundle.rglob("__init__.py")
    )
    return files, license_name, bundled_source


def _package_file(distribution: importlib.metadata.Distribution, name: str) -> Path:
    for file in distribution.files or []:
        if file.name == name and "dist-info" not in file.as_posix():
            path = Path(str(distribution.locate_file(file)))
            if path.is_file():
                return path
    raise FileNotFoundError(f"reverse_geocoder has no {name}")


def _dist_info_file(dist_name: str, name: str) -> Path:
    distribution = importlib.metadata.distribution(dist_name)
    for file in distribution.files or []:
        posix = file.as_posix()
        if posix.endswith(".dist-info/" + name) or posix.endswith(".dist-info/licenses/" + name):
            path = Path(str(distribution.locate_file(file)))
            if path.is_file():
                return path
    raise FileNotFoundError(f"{dist_name} has no dist-info file {name}")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


if __name__ == "__main__":
    raise SystemExit(main())
