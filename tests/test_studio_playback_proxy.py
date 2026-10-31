"""Single-clip LUT playback proxy generation (Issue #222)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from orga_drone.config import Settings
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import FfmpegStudioEncoder
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_image import ImageAdjust
from orga_drone.studio_lut import ColorLook, import_lut_from_path
from orga_drone.studio_playback_proxy import (
    PROXY_CRF,
    PROXY_PRESET,
    PROXY_VERSION,
    PlaybackProxyError,
    PlaybackProxyRequest,
    cache_key_for,
    cached_playback_proxy,
    cleanup_playback_proxies,
    proxy_filter_chain,
    proxy_timeout_for,
    render_playback_proxy,
)


def _run(ffmpeg: str, *args: str) -> None:
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )


def _extract(ffmpeg: str, video: Path, t_s: float, dest: Path) -> Path:
    _run(
        ffmpeg,
        "-ss",
        str(t_s),
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        "scale=in_color_matrix=bt709:in_range=tv,format=rgb24",
        str(dest),
    )
    return dest


def _write_cube(path: Path) -> None:
    lines = ['TITLE "Synthetic channel transform"', "LUT_3D_SIZE 2"]
    for b in (0, 1):
        for g in (0, 1):
            for r in (0, 1):
                lines.append(f"{0.2 + r * 0.7} {g * 0.65} {b * 0.8}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_playback_proxy_strengths_match_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    source = tmp_path / "synthetic.mp4"
    _run(
        ffmpeg,
        "-f",
        "lavfi",
        "-i",
        "smptebars=s=1280x720:r=30:d=10",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=10",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(source),
    )
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    cube = tmp_path / "synthetic.cube"
    _write_cube(cube)
    asset = import_lut_from_path(data, cube)
    grade = ImageAdjust(exposure=8, warmth=5, highlights=-5)
    results: list[dict[str, float | int]] = []
    means: list[tuple[float, float, float]] = []
    max_error = 0.0

    for strength in (0, 50, 100):
        look = ColorLook(
            input_profile="dlog_m",
            conversion_lut=asset,
            conversion_confirmed=True,
            creative_lut=asset,
            creative_strength=strength,
        )
        request = PlaybackProxyRequest(
            source, source_start_s=0.0, source_end_s=10.0, image=grade, look=look,
        )
        started = time.perf_counter()
        proxy = render_playback_proxy(request, data_dir=data)
        generation_s = time.perf_counter() - started
        assert proxy.parent == data / "playback-proxies"
        assert proxy.stat().st_size > 0

        seek_started = time.perf_counter()
        _run(ffmpeg, "-ss", "5", "-i", str(proxy), "-frames:v", "1", "-f", "null", "-")
        seek_s = time.perf_counter() - seek_started

        clip = StudioExportClip(
            source, "video", 10.0, source_start_s=0.0, source_end_s=10.0,
            image=grade, color_look=look,
        )
        exported = FfmpegStudioEncoder().render(StudioExportConfig(
            output_path=tmp_path / f"export-{strength}.mp4",
            width=1280, height=720, clips=(clip,), quality="standard",
        ))
        for local in (2.0, 7.0):
            a = _extract(ffmpeg, proxy, local, tmp_path / f"proxy-{strength}-{local}.png")
            b = _extract(ffmpeg, exported, local, tmp_path / f"export-{strength}-{local}.png")
            with Image.open(a) as proxy_image, Image.open(b) as export_image:
                assert proxy_image.size == (1280, 720)
                difference = ImageStat.Stat(
                    ImageChops.difference(
                        proxy_image.convert("RGB"), export_image.convert("RGB")
                    )
                )
                error = max(difference.mean)
                max_error = max(max_error, error)
                assert error < 8, json.dumps({
                    "strength": strength,
                    "time": local,
                    "error": difference.mean,
                })
                if local == 2.0:
                    means.append(tuple(ImageStat.Stat(proxy_image.convert("RGB")).mean))
        results.append({
            "strength": strength,
            "generation_s": round(generation_s, 3),
            "seek_s": round(seek_s, 3),
            "bytes": proxy.stat().st_size,
        })

    print(json.dumps({"max_error": round(max_error, 3), "runs": results}))
    assert max(abs(means[0][i] - means[2][i]) for i in range(3)) > 10
    assert means[0][1] > means[1][1] > means[2][1]
    assert results[0]["generation_s"] < 120
    assert results[0]["seek_s"] < 2.0
    assert results[0]["bytes"] < 12 * 1024 * 1024
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert render_playback_proxy(
        PlaybackProxyRequest(
            source, source_start_s=0.0, source_end_s=10.0, image=grade,
            look=ColorLook(
                input_profile="dlog_m", conversion_lut=asset,
                conversion_confirmed=True, creative_lut=asset, creative_strength=100,
            ),
        ),
        data_dir=data,
    ).is_file()


def test_playback_proxy_failure_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    cube = tmp_path / "synthetic.cube"
    _write_cube(cube)
    asset = import_lut_from_path(data, cube)
    media = tmp_path / "source.mp4"
    media.write_bytes(b"not a real video")
    original = media.read_bytes()
    cache = tmp_path / "cache"

    def fail_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args[0], 1, b"", b"synthetic ffmpeg failure")

    monkeypatch.setattr("orga_drone.studio_playback_proxy.find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("orga_drone.studio_playback_proxy.subprocess.run", fail_run)
    with pytest.raises(PlaybackProxyError) as exc:
        render_playback_proxy(
            PlaybackProxyRequest(
                media,
                image=ImageAdjust(),
                look=ColorLook(creative_lut=asset, creative_strength=100),
            ),
            data_dir=data,
            cache_dir=cache,
        )
    assert exc.value.code == "proxy_failed"
    assert not list(cache.rglob("*.mp4"))
    work = cache / "work"
    assert not work.exists() or not any(work.iterdir())
    assert media.read_bytes() == original


def test_cache_key_covers_inputs_and_lut_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data"
    media = tmp_path / "source.mp4"
    media.write_bytes(b"media")
    cube = tmp_path / "synthetic.cube"
    _write_cube(cube)
    asset = import_lut_from_path(data, cube)
    stat = media.stat()
    base = PlaybackProxyRequest(
        media,
        source_start_s=1.0,
        source_end_s=2.0,
        image=ImageAdjust(exposure=3),
        look=ColorLook(creative_lut=asset, creative_strength=50),
    )
    base_args = {
        "media_mtime_ns": stat.st_mtime_ns,
        "media_size": stat.st_size,
        "data_dir": data,
    }
    key = cache_key_for(base, **base_args)
    variants = [
        replace(base, source_start_s=1.1),
        replace(base, source_end_s=2.1),
        replace(base, image=ImageAdjust(exposure=4)),
        replace(base, look=ColorLook(creative_lut=asset, creative_strength=51)),
        replace(base, max_width=1279),
        replace(base, saturation=0.9),
    ]
    for variant in variants:
        assert cache_key_for(variant, **base_args) != key
    assert cache_key_for(base, **{**base_args, "media_size": stat.st_size + 1}) != key
    assert cache_key_for(
        base, **{**base_args, "media_mtime_ns": stat.st_mtime_ns + 1}
    ) != key
    monkeypatch.setattr(
        "orga_drone.studio_playback_proxy.PROXY_VERSION", PROXY_VERSION + 1
    )
    assert cache_key_for(base, **base_args) != key
    monkeypatch.undo()
    data.joinpath("playback-proxies").mkdir(parents=True)
    cached = data / "playback-proxies" / f"{key}.mp4"
    cached.write_bytes(b"proxy")
    assert cached_playback_proxy(base, data_dir=data) == cached
    assert cached_playback_proxy(base, data_dir=data, cache_dir=data / "playback-proxies")
    # Same asset name, different content: old cache entry is not reusable.
    lines = ['TITLE "Changed"', "LUT_3D_SIZE 2"] + ["1 1 1"] * 7 + ["0 0 0"]
    (data / "luts" / asset).write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert cached_playback_proxy(base, data_dir=data) is None


def test_proxy_chain_scales_before_lut_and_uses_fast_encoder(tmp_path: Path) -> None:
    data = tmp_path / "data"
    cube = tmp_path / "synthetic.cube"
    _write_cube(cube)
    asset = import_lut_from_path(data, cube)
    request = PlaybackProxyRequest(
        tmp_path / "source.mp4",
        image=ImageAdjust(exposure=5),
        look=ColorLook(creative_lut=asset, creative_strength=100),
    )
    chain = proxy_filter_chain(
        request, data_dir=data, work_dir=tmp_path / "work"
    )
    assert chain.startswith("scale=")
    assert chain.index("lut3d=") > chain.index("scale=")
    assert PROXY_PRESET == "ultrafast"
    assert PROXY_CRF == 23


def test_proxy_timeout_scales_for_long_real_clips() -> None:
    assert proxy_timeout_for(0) == 180.0
    assert proxy_timeout_for(10) == 180.0
    assert proxy_timeout_for(77.326) == pytest.approx(618.608)
    assert proxy_timeout_for(float("nan")) == 180.0
    assert proxy_timeout_for(100_000) == 1800.0


def test_cleanup_bounds_cache_and_keeps_outside_files(tmp_path: Path) -> None:
    now = 1_000_000.0
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    note = cache / "note.txt"
    note.write_bytes(b"keep")
    old = cache / "old.mp4"
    old.write_bytes(b"old")
    fresh = cache / "fresh.mp4"
    fresh.write_bytes(b"fresh")
    keep = cache / "keep.mp4"
    keep.write_bytes(b"keep")
    work = cache / "work"
    work.mkdir()
    old_work = work / "old"
    old_work.mkdir()
    fresh_work = work / "fresh"
    fresh_work.mkdir()
    for path, age in (
        (old, 1_000),
        (fresh, 100),
        (keep, 10),
        (old_work, 1_000),
        (fresh_work, 10),
    ):
        os.utime(path, (now - age, now - age))
    removed = cleanup_playback_proxies(
        cache,
        max_bytes=8,
        max_age_s=500,
        orphan_age_s=500,
        now=now,
        keep=keep,
    )
    assert removed == 3
    assert not old.exists()
    assert not fresh.exists()
    assert keep.exists()
    assert note.exists()
    assert outside.exists()
    assert not old_work.exists()
    assert fresh_work.exists()


def test_superseded_generation_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data"
    media = tmp_path / "source.mp4"
    media.write_bytes(b"media")
    cube = tmp_path / "synthetic.cube"
    _write_cube(cube)
    asset = import_lut_from_path(data, cube)
    cache = tmp_path / "cache"
    request = PlaybackProxyRequest(
        media,
        look=ColorLook(creative_lut=asset, creative_strength=100),
    )

    def run_changed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        changed = ['TITLE "Changed"', "LUT_3D_SIZE 2"] + ["1 1 1"] * 7 + ["0 0 0"]
        (data / "luts" / asset).write_text(
            "\n".join(changed) + "\n", encoding="utf-8"
        )
        Path(args[0][-1]).write_bytes(b"partial")  # type: ignore[index]
        return subprocess.CompletedProcess(args[0], 0, b"", b"")

    monkeypatch.setattr("orga_drone.studio_playback_proxy.find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("orga_drone.studio_playback_proxy.subprocess.run", run_changed)
    with pytest.raises(PlaybackProxyError) as exc:
        render_playback_proxy(request, data_dir=data, cache_dir=cache)
    assert exc.value.code == "superseded"
    assert not list(cache.rglob("*.mp4"))
    work = cache / "work"
    assert not work.exists() or not any(work.iterdir())
