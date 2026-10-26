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
    "ffmpeg-7.1-essentials-GPLv3.txt",
    "ffmpeg-7.1-essentials-README.txt",
    "imageio-ffmpeg-LICENSE",
    "ffmpeg-7.1-essentials-SOURCE-GAP.txt",
    "leaflet-1.9.4-BSD-2-Clause.txt",
    "leaflet.markercluster-MIT-LICENCE.txt",
    "lucide-0.469.0-ISC.txt",
    "fontsource-OFL-1.1.txt",
    "pyinstaller-COPYING.txt",
    "reverse-geocoder-LGPL-2.1.txt",
    "reverse-geocoder/__init__.py",
    "reverse-geocoder/cKDTree_MP.py",
    "reverse-geocoder/METADATA",
    "reverse-geocoder/WHEEL_HAS_NO_LICENSE.txt",
    "dist-info-without-license.txt",
)

# Byte-identical to thampiman/reverse-geocoder master on 2026-10-26.
_GEOCODER_SOURCE_SHA256 = {
    "__init__.py": "64b4a62906216d6aa9718fae3b6332f323fc589cb57a048b2be15b1ed6cc0640",
    "cKDTree_MP.py": "932e77d70058e445a45773115dc22d939f07c2cbb91bc7a9433dc7b4b25b0cf9",
}
_MATCHING_FFMPEG_SHA256 = "2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3"
_FFMPEG_COMMIT = "b08d7969c5"

_GPL_FLAGS = ("--enable-gpl", "--enable-version3", "--enable-libx264")
_SOURCE_DIR = "ffmpeg-corresponding-source"


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
    geocoder_py_matches_upstream: bool,
    geocoder_wheel_license: str,
    csv_in_bundle: bool,
    missing_license_files: tuple[str, ...],
) -> tuple[str, ...]:
    """Reasons this onefolder is not shown to be sellable on itch.io.

    An empty tuple would be GO. Nothing here treats GO as legal advice.
    A README and a GPLv3 text do not clear the FFmpeg blocker.
    """
    blockers: list[str] = []
    present = [flag for flag in _GPL_FLAGS if flag in evidence.flags]
    libraries = notices / _SOURCE_DIR / "LIBRARY_SOURCES_AND_BUILD_SCRIPTS.txt"
    recorded = libraries.read_text(encoding="utf-8").strip().lower() if libraries.is_file() else ""
    if present and not recorded.startswith(evidence.sha256):
        identified = ""
        if evidence.sha256 == _MATCHING_FFMPEG_SHA256:
            identified = (
                " This executable matches gyan.dev GitHub release 7.1 "
                "ffmpeg-7.1-essentials_build.zip (2024-09-30), whose README says GPL v3 "
                "and names FFmpeg commit "
                + _FFMPEG_COMMIT
                + ". That README lists external library versions and does not include "
                "their source or the build scripts. A general upstream link is not "
                "corresponding source. GPLv3 section 6c's written offer is only for "
                "occasional noncommercial copies and was not attached to this binary."
            )
        blockers.append(
            "Bundled ffmpeg configuration includes "
            + ", ".join(present)
            + ". FFmpeg's legal page says GPL parts make the GPL apply to FFmpeg, and it "
            "names libx264 as a GPL library. The zip does not contain corresponding source."
            + identified
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
    if not geocoder_py_matches_upstream:
        blockers.append(
            "reverse-geocoder .py files do not match the upstream master hashes recorded "
            "for the LGPL-2.1 text shipped here."
        )
    if not geocoder_source_in_bundle:
        blockers.append(
            "reverse-geocoder is frozen as bytecode. The wheel has no copyright header. "
            "Copying the matching .py files into this folder does not show that a recipient "
            "can replace the frozen copy."
        )
    if not csv_in_bundle:
        blockers.append(
            "rg_cities1000.csv from the reverse-geocoder wheel is not in the onefolder, "
            "so offline place lookup in the frozen app is not shown."
        )
    if missing_license_files:
        blockers.append(
            "These bundled dist-info directories have no LICENSE or COPYING file: "
            + ", ".join(missing_license_files)
            + "."
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
    third_party = _repo_root() / "packaging" / "third_party"
    for name in (
        "reverse-geocoder-LGPL-2.1.txt",
        "ffmpeg-7.1-essentials-GPLv3.txt",
        "ffmpeg-7.1-essentials-README.txt",
        "ffmpeg-7.1-essentials-SOURCE-GAP.txt",
        "leaflet-1.9.4-BSD-2-Clause.txt",
        "leaflet.markercluster-MIT-LICENCE.txt",
        "lucide-0.469.0-ISC.txt",
        "fontsource-OFL-1.1.txt",
    ):
        src = third_party / name
        if not src.is_file():
            raise FileNotFoundError(src)
        shutil.copyfile(src, notices / name)
    shutil.copyfile(_pyinstaller_copying(), notices / "pyinstaller-COPYING.txt")
    source = notices / "reverse-geocoder"
    source.mkdir()
    for name, path in geocoder_files.items():
        shutil.copyfile(path, source / name)
    py_matches = _geocoder_sources_match(source)
    csv_in_bundle = _csv_outside_notices(bundle)
    if csv_in_bundle:
        (notices / "GEONAMES_ATTRIBUTION.txt").write_text(
            "rg_cities1000.csv is shipped inside the reverse-geocoder wheel and, when "
            "packaging collects it, inside this onefolder.\n"
            "https://www.geonames.org/export/ says the data is under a Creative Commons "
            "attribution license and that commercial use is allowed. "
            "https://download.geonames.org/export/dump/readme.txt retrieved 2026-10-26 "
            "says the gazetteer extract files are Creative Commons Attribution 4.0. "
            "The bundled CSV is the reduced reverse_geocoder 1.5.1 file, has no license "
            "header, and was not hash-matched to a dated dump. Credit GeoNames: "
            "https://www.geonames.org/\n",
            encoding="utf-8",
            newline="\n",
        )
    missing_licenses = _missing_dist_info_licenses(bundle)
    (notices / "dist-info-without-license.txt").write_text(
        "\n".join(missing_licenses) + ("\n" if missing_licenses else ""),
        encoding="utf-8",
        newline="\n",
    )
    (source / "WHEEL_HAS_NO_LICENSE.txt").write_text(
        "The installed reverse_geocoder wheel has no LICENSE file.\n"
        "Metadata License field: "
        + geocoder_license
        + "\n"
        "__init__.py and cKDTree_MP.py match upstream master SHA256 "
        + str(py_matches).lower()
        + ".\n"
        "Expected __init__.py "
        + _GEOCODER_SOURCE_SHA256["__init__.py"]
        + "\n"
        "Expected cKDTree_MP.py "
        + _GEOCODER_SOURCE_SHA256["cKDTree_MP.py"]
        + "\n"
        "The LGPL-2.1 text applies to those matching sources. The wheel still has no "
        "copyright header. Frozen bytecode is not a replaceable copy.\n",
        encoding="utf-8",
        newline="\n",
    )
    blockers = itch_sale_blockers(
        evidence,
        notices=notices,
        geocoder_py_matches_upstream=py_matches,
        csv_in_bundle=csv_in_bundle,
        missing_license_files=missing_licenses,
        wheel_license_in_bundle=license_was_bundled,
        geocoder_source_in_bundle=geocoder_was_bundled,
        geocoder_wheel_license=geocoder_license,
    )
    verdict = "GO" if not blockers else "NO-GO"
    lines = [
        verdict,
        "",
        "This file is not a compliance certificate and not legal advice.",
        (
            "No technical blocker was recorded. This is not a legal opinion."
            if not blockers
            else "itch.io sale of this Windows build is not shown to be permitted."
        ),
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
    lines.append("")
    lines.append(
        "Open legal questions. These lines do not change GO or NO-GO. "
        "A technical GO is not a legal opinion."
    )
    lines.extend("- " + item for item in _open_legal_questions())
    text = "\n".join(lines) + "\n"
    (notices / VERDICT_NAME).write_text(text, encoding="utf-8", newline="\n")
    (notices / "README.txt").write_text(
        "Notices collected from the onefolder and the wheels used to build it.\n"
        "Orga Drone remains MIT. These notices do not relicense it.\n"
        "imageio-ffmpeg's BSD-2-Clause license covers that Python package.\n"
        "It does not license the ffmpeg executable shipped in the wheel.\n"
        "Leaflet 1.9.4, Leaflet.markercluster 1.5.2/1.5.3, Lucide 0.469.0, and the\n"
        "matched Fontsource OFL text are included. They do not license FFmpeg.\n"
        "ffmpeg-7.1-essentials-SOURCE-GAP.txt records the missing corresponding source.\n"
        "That gap file does not clear the sale verdict.\n"
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


def _pyinstaller_copying() -> Path:
    return _dist_info_file("pyinstaller", "COPYING.txt")


def _geocoder_sources_match(source: Path) -> bool:
    for name, expected in _GEOCODER_SOURCE_SHA256.items():
        digest = hashlib.sha256((source / name).read_bytes()).hexdigest()
        if digest != expected:
            return False
    return True


def _csv_outside_notices(bundle: Path) -> bool:
    for path in bundle.rglob("rg_cities1000.csv"):
        if path.is_file() and NOTICES not in path.parts:
            return True
    return False


def _missing_dist_info_licenses(bundle: Path) -> tuple[str, ...]:
    missing: list[str] = []
    for info in sorted(bundle.rglob("*.dist-info")):
        if not info.is_dir() or NOTICES in info.parts:
            continue
        found = False
        for path in info.rglob("*"):
            if path.is_file() and path.name.upper().startswith(("LICENSE", "COPYING")):
                found = True
                break
        if not found:
            missing.append(info.name)
    return tuple(missing)


def _open_legal_questions() -> tuple[str, ...]:
    return (
        "The effect of a separate ffmpeg process on the MIT application is undecided.",
        "Whether copied reverse-geocoder .py files satisfy LGPL-2.1 section 6 for a "
        "PyInstaller PYZ is undecided. WinError 1455 during a frozen probe was a "
        "page-file failure, not a license finding.",
        "rg_cities1000.csv was not hash-matched to a GeoNames dump. The dump readme "
        "retrieved on 2026-10-26 says the extract files are CC BY 4.0.",
        "The PyInstaller bootloader exception is included as text. Its legal effect "
        "is undecided.",
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


if __name__ == "__main__":
    raise SystemExit(main())
