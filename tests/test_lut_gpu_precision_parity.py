"""CPU tetrahedral vs RGBA8-quantized table error (#360).

The WebGL path historically uploaded LUT tables as RGBA8. Float table sampling
(CPU / JS tetrahedral / WebGL float textures) is the operator reference
(max abs channel ≤1e-5). This module measures the unavoidable RGBA8 error
without weakening the encoded swatch gate (≤3.0).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from orga_drone.studio_managed_lut import ManagedCube, sample_lut

PROBES = [
    (0.0, 0.0, 0.0),
    (1.0, 1.0, 1.0),
    (0.5, 0.5, 0.5),
    (0.25, 0.5, 0.75),
    (0.1, 0.2, 0.3),
    (0.9, 0.1, 0.5),
    (0.01, 0.01, 0.01),
    (0.99, 0.99, 0.5),
    (1.0 / 3.0, 2.0 / 3.0, 0.125),
    (0.42, 0.17, 0.83),
]

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "planning" / "360-gpu-precision-parity.json"


def _identity_cube(size: int) -> ManagedCube:
    triples: list[tuple[float, float, float]] = []
    for blue in range(size):
        for green in range(size):
            for red in range(size):
                triples.append(
                    (red / (size - 1), green / (size - 1), blue / (size - 1))
                )
    return ManagedCube(
        size=size,
        data=tuple(triples),
        domain_min=(0.0, 0.0, 0.0),
        domain_max=(1.0, 1.0, 1.0),
        input_profile="srgb",
        output_profile="srgb",
        digest="identity-test",
    )


def _contrast_cube(size: int) -> ManagedCube:
    triples: list[tuple[float, float, float]] = []
    for blue in range(size):
        for green in range(size):
            for red in range(size):
                x = red / (size - 1)
                y = green / (size - 1)
                z = blue / (size - 1)
                triples.append((x * x, math.sqrt(y), min(1.0, z * 1.4)))
    return ManagedCube(
        size=size,
        data=tuple(triples),
        domain_min=(0.0, 0.0, 0.0),
        domain_max=(1.0, 1.0, 1.0),
        input_profile="srgb",
        output_profile="srgb",
        digest="contrast-test",
    )


def _quantize_cube(lut: ManagedCube) -> ManagedCube:
    quantized = tuple(
        (
            round(sample[0] * 255) / 255.0,
            round(sample[1] * 255) / 255.0,
            round(sample[2] * 255) / 255.0,
        )
        for sample in lut.data
    )
    return ManagedCube(
        size=lut.size,
        data=quantized,
        domain_min=lut.domain_min,
        domain_max=lut.domain_max,
        input_profile=lut.input_profile,
        output_profile=lut.output_profile,
        digest=f"{lut.digest}-rgba8",
    )


def _parity_stats(
    reference: ManagedCube, candidate: ManagedCube
) -> dict[str, float | int]:
    max_err = 0.0
    total = 0.0
    count = 0
    for rgb in PROBES:
        a = sample_lut(reference, rgb)
        b = sample_lut(candidate, rgb)
        for channel in range(3):
            err = abs(a[channel] - b[channel])
            max_err = max(max_err, err)
            total += err
            count += 1
    return {
        "max_error": max_err,
        "mean_error": total / count if count else 0.0,
        "samples": count,
    }


def test_float_identity_within_operator_gate() -> None:
    lut = _identity_cube(33)
    for rgb in PROBES:
        out = sample_lut(lut, rgb)
        for channel in range(3):
            assert abs(out[channel] - rgb[channel]) <= 1e-5


def test_rgba8_quantization_measured_and_documented(tmp_path: Path) -> None:
    float_lut = _contrast_cube(33)
    rgba8_lut = _quantize_cube(float_lut)
    stats = _parity_stats(float_lut, rgba8_lut)
    # Unavoidable table quantization — must exceed the float operator gate.
    assert stats["max_error"] > 1e-5
    # Must not quietly exceed the encoded swatch float equivalent (~1 code).
    assert stats["max_error"] < (3.0 / 255.0) + 1e-3

    identity_stats = _parity_stats(_identity_cube(17), _quantize_cube(_identity_cube(17)))

    payload = {
        "issue": 360,
        "gate_float_operator_max_abs": 1e-5,
        "gate_encoded_swatch_rgb": 3.0,
        "float_path": {
            "status": "capability_gated_rgba16f_or_rgba32f",
            "note": (
                "WebGL uploads float LUT tables when RGBA16F/32F texImage3D "
                "succeeds; probe sets exact:true. Export/CPU remain reference."
            ),
        },
        "rgba8_fallback": {
            "status": "exact_false",
            "reason": "rgba8-quantization",
            "contrast_33": stats,
            "identity_17": identity_stats,
            "cause": (
                "Uint8 UNORM table storage rounds each lattice RGB before "
                "tetrahedral texelFetch; interpolation cannot recover lost bits."
            ),
        },
        "probes": PROBES,
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert EVIDENCE.is_file()
    loaded = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert loaded["rgba8_fallback"]["contrast_33"]["max_error"] == pytest.approx(
        stats["max_error"]
    )
