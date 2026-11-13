"""Spatial materialization: photo OK, video fail-closed, cache isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

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
                            "axes": [0.4, 0.4],
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


def test_video_spatial_export_is_fail_closed(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not-a-real-video")
    with pytest.raises(ManagedApplyError) as exc:
        materialize_spatial_managed_media(
            video, _grade(), tmp_path / "work", kind="video", grade_digest="a" * 40
        )
    assert exc.value.code == "UNSUPPORTED_GRADE"
