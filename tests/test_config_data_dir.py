"""Cross-platform data directory resolution (config._default_data_dir)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orga_drone import config


@pytest.fixture(autouse=True)
def _clear_data_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORGA_DRONE_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)


def _fake_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: home))


def test_override_orga_drone_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "custom-data"
    monkeypatch.setenv("ORGA_DRONE_DATA_DIR", str(target))
    assert config._default_data_dir() == target.resolve()


def test_override_expands_user_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("ORGA_DRONE_DATA_DIR", "~/orga-override")
    assert config._default_data_dir() == (tmp_path / "orga-override").resolve()


def test_windows_uses_appdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    appdata = tmp_path / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    # A fake macOS Application Support must not win on Windows.
    (tmp_path / "Library" / "Application Support").mkdir(parents=True)
    _fake_home(monkeypatch, tmp_path)
    assert config._default_data_dir(os_name="nt", platform="win32") == (
        appdata / "orga-drone"
    ).resolve()


def test_windows_falls_back_when_appdata_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    _fake_home(monkeypatch, tmp_path)
    expected = tmp_path / "AppData" / "Roaming" / "orga-drone"
    assert config._default_data_dir(os_name="nt", platform="win32") == expected.resolve()


def test_macos_uses_application_support_via_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_home(monkeypatch, tmp_path)
    # Directory need not exist — platform decides, not Path.exists().
    expected = tmp_path / "Library" / "Application Support" / "orga-drone"
    assert config._default_data_dir(os_name="posix", platform="darwin") == (
        expected.resolve()
    )


def test_macos_ignores_xdg_data_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_home(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-should-not-win"))
    expected = tmp_path / "Library" / "Application Support" / "orga-drone"
    assert config._default_data_dir(os_name="posix", platform="darwin") == (
        expected.resolve()
    )


def test_linux_uses_xdg_data_home_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xdg = tmp_path / "xdg-data"
    _fake_home(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    # Even if a macOS-style folder exists, Linux must not use it.
    (tmp_path / "Library" / "Application Support").mkdir(parents=True)
    assert config._default_data_dir(os_name="posix", platform="linux") == (
        xdg / "orga-drone"
    ).resolve()


def test_linux_default_without_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_home(monkeypatch, tmp_path)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    expected = tmp_path / ".local" / "share" / "orga-drone"
    assert config._default_data_dir(os_name="posix", platform="linux") == (
        expected.resolve()
    )


def test_linux_relative_xdg_data_home_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_home(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", "relative-xdg")
    expected = tmp_path / ".local" / "share" / "orga-drone"
    assert config._default_data_dir(os_name="posix", platform="linux") == (
        expected.resolve()
    )


def test_linux_empty_xdg_data_home_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_home(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", "   ")
    expected = tmp_path / ".local" / "share" / "orga-drone"
    assert config._default_data_dir(os_name="posix", platform="linux") == (
        expected.resolve()
    )


def test_is_absolute_data_path_accepts_posix_and_windows() -> None:
    assert config._is_absolute_data_path("/var/lib/orga")
    assert config._is_absolute_data_path(r"C:\Users\x\AppData")
    assert config._is_absolute_data_path("D:/data")
    assert not config._is_absolute_data_path("relative-xdg")
    assert not config._is_absolute_data_path("")
    assert not config._is_absolute_data_path("C:")


def test_lut_subdir_stays_under_data_dir(tmp_path: Path) -> None:
    from orga_drone.studio_lut import lut_asset_dir

    root = tmp_path / "orga-drone"
    assert lut_asset_dir(root) == root / "luts"
