"""Notices for the Windows onefolder. These tests do not certify compliance."""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "windows_third_party",
    Path(__file__).resolve().parents[1] / "packaging" / "windows_third_party.py",
)
assert _SPEC is not None and _SPEC.loader is not None
notices = importlib.util.module_from_spec(_SPEC)
sys.modules["windows_third_party"] = notices
_SPEC.loader.exec_module(notices)

INSPECTED_SHA256 = "2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3"
_VERSION = (
    "ffmpeg version 7.1-essentials_build-www.gyan.dev "
    "Copyright (c) 2000-2024 the FFmpeg developers\n"
    "configuration: --enable-gpl --enable-version3 --enable-static --enable-libx264\n"
)
_BUILDCONF = (
    "configuration:\n    --enable-gpl\n    --enable-version3\n"
    "    --enable-static\n    --enable-libx264\n"
)


def _evidence(sha: str = "abc") -> notices.FfmpegEvidence:
    return notices.FfmpegEvidence(
        sha256=sha,
        version_text=_VERSION,
        buildconf_text=_BUILDCONF,
        flags=notices.configuration_flags(_VERSION),
    )


def test_configuration_line_keeps_gpl_flags() -> None:
    assert notices.configuration_flags(_VERSION) == (
        "--enable-gpl",
        "--enable-version3",
        "--enable-static",
        "--enable-libx264",
    )


def test_quoted_linker_flag_matches_buildconf() -> None:
    version = (
        "ffmpeg version 7.1\n"
        "configuration: --enable-gpl --enable-libx264 "
        "--extra-ldflags='-L/tmp/prefix/lib -static'\n"
    )
    buildconf = (
        "configuration:\n"
        "    --enable-gpl\n"
        "    --enable-libx264\n"
        "    --extra-ldflags='-L/tmp/prefix/lib -static'\n"
    )
    flags = notices.require_buildconf(version, buildconf)
    assert "--enable-libx264" in flags
    assert any(flag.startswith("--extra-ldflags=") for flag in flags)


def test_buildconf_must_repeat_the_version_flags() -> None:
    with pytest.raises(ValueError, match="missing flags"):
        notices.require_buildconf(_VERSION, "configuration:\n    --enable-gpl\n")


def _blockers(tmp_path: Path, **overrides: object) -> tuple[str, ...]:
    values = {
        "notices": tmp_path,
        "wheel_license_in_bundle": True,
        "geocoder_source_in_bundle": False,
        "geocoder_py_matches_upstream": True,
        "geocoder_wheel_license": "lgpl",
        "csv_in_bundle": True,
        "geonames_csv_matches": False,
        "missing_license_files": (),
    }
    values.update(overrides)
    return notices.itch_sale_blockers(_evidence(), **values)


def test_gpl_binary_without_library_sources_is_no_go(tmp_path: Path) -> None:
    text = "\n".join(_blockers(tmp_path))
    assert "--enable-gpl" in text
    assert "does not contain corresponding source" in text
    assert "replace the frozen copy" in text
    assert "b08d7969c5" not in text


def test_identified_gyan_binary_still_has_no_corresponding_source(tmp_path: Path) -> None:
    evidence = notices.FfmpegEvidence(
        sha256=notices._MATCHING_FFMPEG_SHA256,
        version_text=_VERSION,
        buildconf_text=_BUILDCONF,
        flags=notices.configuration_flags(_VERSION),
    )
    blockers = notices.itch_sale_blockers(
        evidence,
        notices=tmp_path,
        wheel_license_in_bundle=True,
        geocoder_source_in_bundle=True,
        geocoder_py_matches_upstream=True,
        geocoder_wheel_license="lgpl",
        csv_in_bundle=True,
        geonames_csv_matches=False,
        missing_license_files=(),
    )
    text = "\n".join(blockers)
    assert "b08d7969c5" in text
    assert "not corresponding source" in text
    source = tmp_path / "ffmpeg-corresponding-source"
    source.mkdir()
    (source / "LIBRARY_SOURCES_AND_BUILD_SCRIPTS.txt").write_text("not-the-hash\n", encoding="utf-8")
    still = notices.itch_sale_blockers(
        evidence,
        notices=tmp_path,
        wheel_license_in_bundle=True,
        geocoder_source_in_bundle=True,
        geocoder_py_matches_upstream=True,
        geocoder_wheel_license="lgpl",
        csv_in_bundle=True,
        geonames_csv_matches=False,
        missing_license_files=(),
    )
    assert any("not corresponding source" in item for item in still)


def test_exe_sha_without_pinned_tarball_hashes_stays_blocked(tmp_path: Path) -> None:
    source = tmp_path / "ffmpeg-corresponding-source"
    source.mkdir()
    (source / "LIBRARY_SOURCES_AND_BUILD_SCRIPTS.txt").write_text(
        notices._MATCHING_FFMPEG_SHA256 + "\n",
        encoding="utf-8",
    )
    blockers = notices.itch_sale_blockers(
        notices.FfmpegEvidence(
            sha256=notices._MATCHING_FFMPEG_SHA256,
            version_text=_VERSION,
            buildconf_text=_BUILDCONF,
            flags=notices.configuration_flags(_VERSION),
        ),
        notices=tmp_path,
        wheel_license_in_bundle=True,
        geocoder_source_in_bundle=True,
        geocoder_py_matches_upstream=True,
        geocoder_wheel_license="lgpl",
        csv_in_bundle=True,
        geonames_csv_matches=True,
        missing_license_files=(),
    )
    assert any("not corresponding source" in item for item in blockers)


def test_pinned_tarball_list_clears_the_ffmpeg_blocker(tmp_path: Path) -> None:
    source = tmp_path / "ffmpeg-corresponding-source"
    source.mkdir()
    body = "abc\n" + "\n".join(notices._tarball_digests()) + "\n"
    (source / "LIBRARY_SOURCES_AND_BUILD_SCRIPTS.txt").write_text(body, encoding="utf-8")
    blockers = notices.itch_sale_blockers(
        _evidence("abc"),
        notices=tmp_path,
        wheel_license_in_bundle=True,
        geocoder_source_in_bundle=True,
        geocoder_py_matches_upstream=True,
        geocoder_wheel_license="lgpl",
        csv_in_bundle=True,
        geonames_csv_matches=True,
        missing_license_files=(),
    )
    assert blockers == ()


def test_verify_zip_exits_2_for_no_go(tmp_path: Path) -> None:
    root = tmp_path / "orga-drone" / notices.NOTICES
    root.mkdir(parents=True)
    for rel in notices._REQUIRED_IN_NOTICES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    (root / notices.VERDICT_NAME).write_text("NO-GO\n\nnot a certificate\n", encoding="utf-8")
    zip_path = tmp_path / "orga-drone-windows-x64.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, "orga-drone/" + path.relative_to(tmp_path / "orga-drone").as_posix())
    assert notices.verify_zip(zip_path) == 2


def test_verify_zip_exits_1_when_a_notice_is_missing(tmp_path: Path) -> None:
    zip_path = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("orga-drone/THIRD_PARTY_NOTICES/ITCH_SALE_VERDICT.txt", "NO-GO\n")
    assert notices.verify_zip(zip_path) == 1


def test_installed_windows_ffmpeg_is_the_inspected_gpl_build() -> None:
    exe = _windows_ffmpeg()
    if exe is None:
        pytest.skip("Windows imageio-ffmpeg 7.1 binary is not installed")
    evidence = notices.probe_ffmpeg(exe)
    assert evidence.sha256 == INSPECTED_SHA256
    assert "Copyright (c) 2000-2024 the FFmpeg developers" in evidence.version_text
    assert "--enable-gpl" in evidence.flags
    assert "--enable-version3" in evidence.flags
    assert "--enable-libx264" in evidence.flags
    assert "--enable-static" in evidence.flags


def test_write_notices_from_the_inspected_binary_stays_no_go(tmp_path: Path) -> None:
    exe = _windows_ffmpeg()
    if exe is None:
        pytest.skip("Windows imageio-ffmpeg 7.1 binary is not installed")
    binary_dir = tmp_path / "imageio_ffmpeg" / "binaries"
    binary_dir.mkdir(parents=True)
    target = binary_dir / exe.name
    try:
        target.hardlink_to(exe)
    except OSError:
        target.write_bytes(exe.read_bytes())
    dist_info = tmp_path / "imageio_ffmpeg-0.6.0.dist-info"
    dist_info.mkdir()
    license_text = Path(notices._dist_info_file("imageio-ffmpeg", "LICENSE")).read_text(encoding="utf-8")
    (dist_info / "LICENSE").write_text(license_text, encoding="utf-8")
    blockers = notices.write_notices(tmp_path)
    verdict = (tmp_path / notices.NOTICES / notices.VERDICT_NAME).read_text(encoding="utf-8")
    assert verdict.startswith("NO-GO\n")
    assert blockers
    assert "BSD 2-Clause License" in (tmp_path / notices.NOTICES / "imageio-ffmpeg-LICENSE").read_text(encoding="utf-8")
    stored = (tmp_path / notices.NOTICES / "reverse-geocoder-LGPL-2.1.txt").read_bytes()
    upstream = (Path(__file__).resolve().parents[1] / "packaging" / "third_party" / "reverse-geocoder-LGPL-2.1.txt").read_bytes()
    assert stored == upstream
    readme = (tmp_path / notices.NOTICES / "ffmpeg-7.1-essentials-README.txt").read_text(encoding="utf-8")
    assert "b08d7969c5" in readme
    assert "x264 v0.164.3192" in readme
    gpl = (tmp_path / notices.NOTICES / "ffmpeg-7.1-essentials-GPLv3.txt").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in gpl
    assert "Version 3, 29 June 2007" in gpl
    copying = (tmp_path / notices.NOTICES / "pyinstaller-COPYING.txt").read_text(encoding="utf-8")
    assert "Bootloader Exception" in copying
    leaflet = (tmp_path / notices.NOTICES / "leaflet-1.9.4-BSD-2-Clause.txt").read_text(encoding="utf-8")
    assert "Copyright (c) 2010-2023, Volodymyr Agafonkin" in leaflet
    lucide = (tmp_path / notices.NOTICES / "lucide-0.469.0-ISC.txt").read_text(encoding="utf-8")
    assert "Lucide Contributors 2022" in lucide
    markercluster = (tmp_path / notices.NOTICES / "leaflet.markercluster-MIT-LICENCE.txt").read_text(
        encoding="utf-8"
    )
    assert "Copyright 2012 David Leaver" in markercluster
    ofl = (tmp_path / notices.NOTICES / "fontsource-OFL-1.1.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in ofl
    gap = (tmp_path / notices.NOTICES / "ffmpeg-7.1-essentials-SOURCE-GAP.txt").read_text(encoding="utf-8")
    assert "does not clear the sale gate" in gap
    assert "Open legal questions" in verdict
    assert "not a legal opinion" in verdict
    assert "GPLv3 has been satisfied" not in verdict


def test_imageio_license_under_dist_info_licenses_counts_as_bundled(tmp_path: Path) -> None:
    dist_info = tmp_path / "imageio_ffmpeg-0.7.0.dist-info" / "licenses"
    dist_info.mkdir(parents=True)
    license_path = dist_info / "LICENSE"
    license_path.write_text("BSD 2-Clause License\n", encoding="utf-8")

    found, bundled = notices._imageio_license(tmp_path)

    assert bundled is True
    assert found == license_path


def _windows_ffmpeg() -> Path | None:
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if exe.name == "ffmpeg-win-x86_64-v7.1.exe" and exe.is_file():
        return exe
    return None
