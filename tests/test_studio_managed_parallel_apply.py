"""Exact parallel spatial apply preserves UVs and pixels (#532)."""

from __future__ import annotations

import os

import pytest

from orga_drone.studio_managed_apply import apply_managed_grade_image


def _grade() -> dict:
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "leaf",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1.0,
                "selection_id": "sel",
                "params": {
                    "exposure": 0.2,
                    "kelvin": 5000,
                    "tint": -40,
                    "contrast": 1.0,
                    "pivot": 0.18,
                    "saturation": 1.4,
                    "blacks": 0,
                    "shadows": 0,
                    "highlights": 0,
                    "whites": 0,
                },
            },
            {
                "id": "bg",
                "type": "managed-hsl-v1",
                "enabled": True,
                "mix": 1.0,
                "selection_id": "sel-inv",
                "params": {"hue": 0, "saturation": 0.0, "lightness": 0.0},
            },
        ],
        "selections": [
            {
                "id": "sel",
                "invert": False,
                "mask": {
                    "combine": "union",
                    "leaves": [
                        {
                            "type": "polygon",
                            "points": [
                                [0.2, 0.2],
                                [0.8, 0.25],
                                [0.7, 0.8],
                                [0.25, 0.75],
                            ],
                            "feather": 0.0,
                            "closed": True,
                        }
                    ],
                },
                "qualifier": None,
            },
            {
                "id": "sel-inv",
                "invert": True,
                "mask": {
                    "combine": "union",
                    "leaves": [
                        {
                            "type": "polygon",
                            "points": [
                                [0.2, 0.2],
                                [0.8, 0.25],
                                [0.7, 0.8],
                                [0.25, 0.75],
                            ],
                            "feather": 0.0,
                            "closed": True,
                        }
                    ],
                },
                "qualifier": None,
            },
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def _pixels(width: int, height: int) -> list[list[tuple[float, float, float]]]:
    rows: list[list[tuple[float, float, float]]] = []
    for y in range(height):
        row: list[tuple[float, float, float]] = []
        for x in range(width):
            row.append(
                (
                    (x / max(1, width - 1)) * 0.7 + 0.1,
                    (y / max(1, height - 1)) * 0.5 + 0.2,
                    0.35,
                )
            )
        rows.append(row)
    return rows


def test_parallel_matches_serial_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    grade = _grade()
    pixels = _pixels(64, 96)
    monkeypatch.setenv("ORGA_SPATIAL_APPLY_WORKERS", "1")
    serial = apply_managed_grade_image(pixels, grade)
    monkeypatch.setenv("ORGA_SPATIAL_APPLY_WORKERS", "4")
    parallel = apply_managed_grade_image(pixels, grade)
    assert parallel == serial


def test_strip_boundary_uv_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Odd height forces uneven strips; seam rows must match serial."""
    grade = _grade()
    pixels = _pixels(48, 97)
    monkeypatch.setenv("ORGA_SPATIAL_APPLY_WORKERS", "1")
    serial = apply_managed_grade_image(pixels, grade)
    monkeypatch.setenv("ORGA_SPATIAL_APPLY_WORKERS", "3")
    parallel = apply_managed_grade_image(pixels, grade)
    for y in (0, 32, 33, 64, 65, 96):
        assert parallel[y] == serial[y]
