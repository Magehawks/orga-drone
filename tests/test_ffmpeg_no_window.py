"""Windows: ffmpeg/ffprobe must not flash a console window (CREATE_NO_WINDOW)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orga_drone.ffmpeg_bin import (
    subprocess_below_normal_kwargs,
    subprocess_no_window_kwargs,
)


def test_subprocess_no_window_kwargs_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    class _StartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = 0

    monkeypatch.setattr("orga_drone.ffmpeg_bin.sys.platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "STARTUPINFO", _StartupInfo, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
    kwargs = subprocess_no_window_kwargs()
    assert kwargs["creationflags"] == 0x08000000
    startupinfo = kwargs["startupinfo"]
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startupinfo.wShowWindow == subprocess.SW_HIDE


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_subprocess_no_window_kwargs_non_windows(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr("orga_drone.ffmpeg_bin.sys.platform", platform)
    assert subprocess_no_window_kwargs() == {}


def test_preview_processes_keep_no_window_and_lower_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    monkeypatch.setattr("orga_drone.ffmpeg_bin.sys.platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(
        subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000, raising=False
    )
    kwargs = subprocess_below_normal_kwargs()
    assert kwargs["creationflags"] == 0x08000000 | 0x00004000


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_preview_processes_lower_priority_only_on_windows(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr("orga_drone.ffmpeg_bin.sys.platform", platform)
    assert subprocess_below_normal_kwargs() == {}


def test_run_ffmpeg_pass_creationflags_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orga_drone.export import studio_encoder as se

    monkeypatch.setattr("orga_drone.ffmpeg_bin.sys.platform", "win32")
    monkeypatch.setattr(se.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):  # type: ignore[no-untyped-def]
            captured["kwargs"] = kwargs
            self.stdout = iter(())
            self.returncode = 0

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return 0

        def poll(self):  # type: ignore[no-untyped-def]
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr(se.subprocess, "Popen", _FakePopen)
    se._run_ffmpeg(["ffmpeg", "-y", "-i", "in.mp4", "out.mp4"])
    assert captured["kwargs"].get("creationflags") == 0x08000000
    assert captured["kwargs"].get("shell") is not True
    assert captured["kwargs"]["stderr"] is not se.subprocess.PIPE


def test_run_ffmpeg_popen_pass_creationflags_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.export import studio_encoder as se

    monkeypatch.setattr("orga_drone.ffmpeg_bin.sys.platform", "win32")
    monkeypatch.setattr(se.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    out = tmp_path / "seg.mp4"
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):  # type: ignore[no-untyped-def]
            captured["kwargs"] = kwargs
            self.stdout = iter(["out_time_ms=250000\n", "progress=end\n"])
            self.stderr = None
            self.returncode = 0

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr(se.subprocess, "Popen", _FakePopen)
    times: list[float] = []
    se._run_ffmpeg(
        ["ffmpeg", "-y", "-i", "in.mp4", str(out)],
        on_time=times.append,
        duration_s=1.0,
    )
    assert times and times[0] == 0.25
    assert captured["kwargs"].get("creationflags") == 0x08000000
    assert captured["kwargs"].get("shell") is not True
    assert captured["kwargs"]["stdout"] is se.subprocess.PIPE
    assert captured["kwargs"]["stderr"] is not se.subprocess.PIPE


def test_run_ffmpeg_no_creationflags_on_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orga_drone.export import studio_encoder as se

    monkeypatch.setattr("orga_drone.ffmpeg_bin.sys.platform", "linux")
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):  # type: ignore[no-untyped-def]
            captured["kwargs"] = kwargs
            self.stdout = iter(())
            self.returncode = 0

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return 0

        def poll(self):  # type: ignore[no-untyped-def]
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr(se.subprocess, "Popen", _FakePopen)
    se._run_ffmpeg(["ffmpeg", "-y", "-i", "in.mp4", "out.mp4"])
    assert "creationflags" not in captured["kwargs"]
