"""Spatial materialization: photo + video, cache isolation, outside-mask parity."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_managed_apply import ManagedApplyError
from orga_drone.studio_managed_spatial_export import (
    materialize_spatial_managed_media,
    source_identity,
    spatial_work_dir,
)


def _grade() -> dict:
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1,
                "selection_id": "sel-1",
                "params": {
                    "exposure": 1.0,
                    "kelvin": 6500,
                    "tint": 0,
                    "contrast": 1,
                    "pivot": 0.18,
                    "saturation": 0.0,
                    "blacks": 0,
                    "shadows": 0,
                    "highlights": 0,
                    "whites": 0,
                },
            }
        ],
        "selections": [
            {
                "id": "sel-1",
                "mask": {
                    "combine": "union",
                    "leaves": [
                        {
                            "type": "radial",
                            "center": [0.5, 0.5],
                            "axes": [0.25, 0.25],
                            "feather": 0.0,
                        }
                    ],
                },
                "qualifier": None,
                "invert": False,
            }
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def _write_photo(path: Path, color: tuple[int, int, int]) -> Path:
    Image.new("RGB", (32, 32), color).save(path, format="JPEG", quality=95)
    return path


def _run_ffmpeg(*args: str) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )


def _write_video(path: Path, *, with_audio: bool = True) -> Path:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    # Solid red field; center will be desaturated by the radial grade.
    args = [
        "-f",
        "lavfi",
        "-i",
        "color=c=0xc82828:s=64x48:r=10:d=0.3",
    ]
    if with_audio:
        args.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=8000:duration=0.3",
                "-shortest",
                "-c:a",
                "aac",
            ]
        )
    args.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    _run_ffmpeg(*args)
    return path


def _extract_frame(video: Path, dest: Path, *, time_s: float = 0.05) -> Path:
    _run_ffmpeg(
        "-ss",
        f"{time_s:.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        str(dest),
    )
    return dest


def test_source_identity_differs_for_distinct_files(tmp_path: Path) -> None:
    a = _write_photo(tmp_path / "a.jpg", (200, 40, 40))
    b = _write_photo(tmp_path / "b.jpg", (40, 200, 40))
    assert source_identity(a) != source_identity(b)
    assert spatial_work_dir(tmp_path, grade_digest="abcd" * 8, source=a) != spatial_work_dir(
        tmp_path, grade_digest="abcd" * 8, source=b
    )


def test_photo_materialize_and_cache_isolation(tmp_path: Path) -> None:
    a = _write_photo(tmp_path / "a.jpg", (220, 30, 30))
    b = _write_photo(tmp_path / "b.jpg", (30, 220, 30))
    grade = _grade()
    digest = "f" * 40
    out_a = materialize_spatial_managed_media(
        a, grade, tmp_path / "work", kind="photo", grade_digest=digest
    )
    out_b = materialize_spatial_managed_media(
        b, grade, tmp_path / "work", kind="photo", grade_digest=digest
    )
    assert out_a != out_b
    assert out_a.is_file() and out_b.is_file()
    # Cache hit returns the same path for the same source.
    again = materialize_spatial_managed_media(
        a, grade, tmp_path / "work", kind="photo", grade_digest=digest
    )
    assert again == out_a


def test_video_spatial_export_grades_and_preserves_audio(tmp_path: Path) -> None:
    video = _write_video(tmp_path / "clip.mp4", with_audio=True)
    grade = _grade()
    digest = "a" * 40
    out = materialize_spatial_managed_media(
        video, grade, tmp_path / "work", kind="video", grade_digest=digest
    )
    assert out.is_file() and out.suffix == ".mp4"
    # Cache hit.
    again = materialize_spatial_managed_media(
        video, grade, tmp_path / "work", kind="video", grade_digest=digest
    )
    assert again == out

    # Audio stream still present.
    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(out)],
        check=False,
        capture_output=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    )
    text = (probe.stderr or b"").decode("utf-8", errors="replace").lower()
    assert " audio:" in text or "\naudio:" in text


def test_video_spatial_matches_cpu_reference_within_encoding_tolerance(
    tmp_path: Path,
) -> None:
    """Decoded graded frames match the CPU applicator within yuv420p CRF18 drift.

    Outside-mask pixels are not bit-identical to the source: managed input/output
    transforms still run. The gate compares against the same CPU reference used
    for photo spatial grades.
    """
    from orga_drone.studio_managed_apply import apply_managed_grade_image

    video = _write_video(tmp_path / "clip.mp4", with_audio=False)
    grade = _grade()
    out = materialize_spatial_managed_media(
        video, grade, tmp_path / "work", kind="video", grade_digest="b" * 40
    )
    src_frame = _extract_frame(video, tmp_path / "src.png")
    graded_frame = _extract_frame(out, tmp_path / "graded.png")
    with Image.open(src_frame) as src_img, Image.open(graded_frame) as graded_img:
        src = src_img.convert("RGB")
        graded = graded_img.convert("RGB")
        assert src.size == graded.size
        width, height = src.size
        px = src.load()
        rows = [
            [
                (px[x, y][0] / 255.0, px[x, y][1] / 255.0, px[x, y][2] / 255.0)
                for x in range(width)
            ]
            for y in range(height)
        ]
        ref = apply_managed_grade_image(rows, grade, lattice_domain="srgb")

        def _err(x: int, y: int) -> int:
            rr, rg, rb = ref[y][x]
            er = int(min(255, max(0, round(rr * 255))))
            eg = int(min(255, max(0, round(rg * 255))))
            eb = int(min(255, max(0, round(rb * 255))))
            gr, gg, gb = graded.getpixel((x, y))
            return max(abs(er - gr), abs(eg - gg), abs(eb - gb))

        # Corner (outside mask) and center (inside mask).
        assert _err(2, 2) <= 12
        assert _err(width // 2, height // 2) <= 12
        # Center must be near-neutral after saturation=0 inside the radial.
        cr, cg, cb = graded.getpixel((width // 2, height // 2))
        assert max(cr, cg, cb) - min(cr, cg, cb) <= 16


def test_unknown_kind_fail_closed(tmp_path: Path) -> None:
    photo = _write_photo(tmp_path / "a.jpg", (10, 10, 10))
    with pytest.raises(ManagedApplyError) as exc:
        materialize_spatial_managed_media(
            photo, _grade(), tmp_path / "work", kind="audio", grade_digest="c" * 40
        )
    assert exc.value.code == "UNSUPPORTED_GRADE"
