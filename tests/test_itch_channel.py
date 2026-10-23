"""itch.io Windows channel guards (issue #82). The tests do not upload."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "itch_channel",
    Path(__file__).resolve().parents[1] / "packaging" / "itch_channel.py",
)
assert _SPEC is not None and _SPEC.loader is not None
itch_channel = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(itch_channel)

REPO = Path(__file__).resolve().parents[1]
PushRefused = itch_channel.PushRefused


def _onefolder(path: Path, marker: bytes = b"A") -> Path:
    path.mkdir(parents=True)
    (path / "orga-drone.exe").write_bytes(marker)
    internal = path / "_internal"
    internal.mkdir()
    (internal / "placeholder.txt").write_text("ok", encoding="utf-8")
    return path


def _ready_b_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    package = repo / "src" / "orga_drone"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "1.10.0"\n', encoding="utf-8")
    (package / "studio_image.py").write_text("# image correction\n", encoding="utf-8")
    marker_dir = repo / "packaging" / "itch"
    marker_dir.mkdir(parents=True)
    (marker_dir / "OVERLAYS_READY").write_text("ready\n", encoding="utf-8")
    return repo


def test_versions_and_channel_are_distinct() -> None:
    assert itch_channel.VERSION_A_USERVERSION != itch_channel.VERSION_B_USERVERSION
    assert itch_channel.VERSION_A_USERVERSION == "1.9.0"
    assert itch_channel.VERSION_B_USERVERSION == "1.10.0"
    assert "windows" in itch_channel.TEST_CHANNEL
    assert itch_channel.TEST_CHANNEL.endswith("-test")


def test_release_notes_sha_matches_version_a() -> None:
    notes = (REPO / "releases" / "1.9.0" / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert itch_channel.BASELINE_ZIP_SHA256 in notes
    assert itch_channel.BASELINE_COMMIT in notes


def test_this_tree_is_not_version_b() -> None:
    blockers = itch_channel.version_b_blockers(REPO)
    assert any("1.10.0" in item for item in blockers)
    assert any("issue #78" in item for item in blockers)
    assert not any("image correction is missing" in item for item in blockers)
    assert not (REPO / itch_channel.OVERLAYS_READY).exists()


def test_module_does_not_launch_butler() -> None:
    text = (REPO / "packaging" / "itch_channel.py").read_text(encoding="utf-8")
    for banned in ("subprocess", "os.system", "Popen", "check_call", "urlopen"):
        assert banned not in text


def test_status_mentions_visibility_and_zip_updates(capsys: pytest.CaptureFixture[str]) -> None:
    assert itch_channel.main(["status", "--repo", str(REPO)]) == 0
    output = capsys.readouterr().out
    assert "not executed" in output
    assert "draft or restricted" in output
    assert "1.9.0" in output
    assert "1.10.0" in output
    assert "ZIP" in output
    assert "%APPDATA%" in output


def test_layout_rejects_database_and_media(tmp_path: Path) -> None:
    build = _onefolder(tmp_path / "build")
    (build / "_internal" / "orga-drone.sqlite3").write_bytes(b"library")
    with pytest.raises(PushRefused, match="sqlite"):
        itch_channel.validate_onefolder(build)

    clean = _onefolder(tmp_path / "clean")
    (clean / "clip.MP4").write_bytes(b"video")
    with pytest.raises(PushRefused, match="media"):
        itch_channel.validate_onefolder(clean)

    onefile = tmp_path / "onefile"
    onefile.mkdir()
    (onefile / "orga-drone.exe").write_bytes(b"exe")
    with pytest.raises(PushRefused, match="_internal"):
        itch_channel.validate_onefolder(onefile)


def test_wrong_baseline_zip_is_refused(tmp_path: Path) -> None:
    zip_path = tmp_path / "orga-drone-windows-x64.zip"
    zip_path.write_bytes(b"not-the-release")
    with pytest.raises(PushRefused, match="SHA256"):
        itch_channel.verify_baseline_zip(zip_path)
    assert itch_channel.main(["verify-zip", str(zip_path)]) == 2


def test_public_visibility_is_refused(tmp_path: Path) -> None:
    build = _onefolder(tmp_path / "build")
    with pytest.raises(PushRefused, match="public"):
        itch_channel.push_argv(
            slot="A",
            build_dir=build,
            target="owner/game",
            visibility="public",
            zip_path=tmp_path / "missing.zip",
        )


def test_version_a_command_is_hidden_and_not_run(tmp_path: Path) -> None:
    build = _onefolder(tmp_path / "orga-drone")
    zip_path = tmp_path / "baseline.zip"
    payload = b"baseline-zip"
    zip_path.write_bytes(payload)
    digest = itch_channel.sha256_file(zip_path)
    argv = itch_channel.push_argv(
        slot="A",
        build_dir=build,
        target="owner/game",
        visibility="restricted",
        zip_path=zip_path,
        expected_sha256=digest,
    )
    assert argv[0] == "butler"
    assert "--hidden" in argv
    assert "--userversion" in argv
    assert itch_channel.VERSION_A_USERVERSION in argv
    assert argv[3] == f"owner/game:{itch_channel.TEST_CHANNEL}"
    assert "public" not in argv


def test_version_a_cli_prints_command_without_uploading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build = _onefolder(tmp_path / "orga-drone")
    zip_path = tmp_path / "baseline.zip"
    zip_path.write_bytes(b"baseline-zip")
    digest = itch_channel.sha256_file(zip_path)
    real_sha = itch_channel.BASELINE_ZIP_SHA256
    itch_channel.BASELINE_ZIP_SHA256 = digest
    try:
        code = itch_channel.main(
            [
                "command",
                "--slot",
                "A",
                "--build",
                str(build),
                "--zip",
                str(zip_path),
                "--target",
                "owner/game",
                "--visibility",
                "draft",
            ]
        )
    finally:
        itch_channel.BASELINE_ZIP_SHA256 = real_sha
    assert code == 0
    output = capsys.readouterr().out
    assert "Not executed" in output
    assert "--hidden" in output
    assert itch_channel.TEST_CHANNEL in output


def test_version_b_from_this_tree_is_refused(tmp_path: Path) -> None:
    build = _onefolder(tmp_path / "build")
    with pytest.raises(PushRefused, match="issue #78"):
        itch_channel.push_argv(
            slot="B",
            build_dir=build,
            target="owner/game",
            visibility="draft",
            repo_root=REPO,
            channel_exists=True,
        )


def test_version_b_command_updates_existing_channel(tmp_path: Path) -> None:
    build = _onefolder(tmp_path / "build", marker=b"B")
    repo = _ready_b_repo(tmp_path)
    with pytest.raises(PushRefused, match="existing test channel"):
        itch_channel.push_argv(
            slot="B",
            build_dir=build,
            target="owner/game",
            visibility="restricted",
            repo_root=repo,
            channel_exists=False,
        )
    argv = itch_channel.push_argv(
        slot="B",
        build_dir=build,
        target="owner/game",
        visibility="restricted",
        repo_root=repo,
        channel_exists=True,
    )
    assert "--hidden" not in argv
    assert itch_channel.VERSION_B_USERVERSION in argv
    assert argv[3].endswith(itch_channel.TEST_CHANNEL)


def test_target_must_be_lowercase_owner_game(tmp_path: Path) -> None:
    build = _onefolder(tmp_path / "build")
    with pytest.raises(PushRefused, match="owner/game"):
        itch_channel.push_argv(
            slot="B",
            build_dir=build,
            target="Magehawks/orga-drone:windows",
            visibility="draft",
            repo_root=_ready_b_repo(tmp_path),
            channel_exists=True,
        )


def test_replace_install_keeps_library_and_media(tmp_path: Path) -> None:
    install = _onefolder(tmp_path / "install", marker=b"version-a")
    incoming = _onefolder(tmp_path / "incoming", marker=b"version-b")
    data = tmp_path / "AppData" / "orga-drone"
    data.mkdir(parents=True)
    database = data / "orga-drone.sqlite3"
    theme = data / "theme.json"
    prefs = data / "app_prefs.json"
    database.write_bytes(b"library-and-studio")
    theme.write_text('{"theme":"dark"}\n', encoding="utf-8")
    prefs.write_text('{"last_export_directory":"D:\\\\out"}\n', encoding="utf-8")
    media = tmp_path / "library" / "DJI_0001.MP4"
    media.parent.mkdir()
    media.write_bytes(b"original-media")

    itch_channel.replace_install_directory(
        install,
        incoming,
        data_dir=data,
        media_paths=(media,),
    )

    assert (install / "orga-drone.exe").read_bytes() == b"version-b"
    assert database.read_bytes() == b"library-and-studio"
    assert theme.read_text(encoding="utf-8").startswith('{"theme"')
    assert "last_export_directory" in prefs.read_text(encoding="utf-8")
    assert media.read_bytes() == b"original-media"
    itch_channel.assert_user_data_outside(install, data, (media,))


def test_replace_refuses_data_inside_install_and_leaves_it(tmp_path: Path) -> None:
    install = _onefolder(tmp_path / "install")
    incoming = _onefolder(tmp_path / "incoming", marker=b"B")
    data = install / "data"
    data.mkdir()
    database = data / "orga-drone.sqlite3"
    database.write_bytes(b"library")
    with pytest.raises(PushRefused):
        itch_channel.replace_install_directory(install, incoming, data_dir=data)
    assert database.read_bytes() == b"library"
    assert (install / "orga-drone.exe").read_bytes() == b"A"
