"""Issue #189: keep the preview/export parity contract discoverable in code."""

from __future__ import annotations

from pathlib import Path

import pytest

from orga_drone.export.studio_encoder import EXPORT_FPS
from orga_drone.studio_image import ImageAdjust, ffmpeg_grade_chain, preview_css_functions
from orga_drone.studio_transition import (
    TYPE_CROSSFADE,
    TYPE_CUT,
    apply_boundaries,
    item_effective_seconds,
    story_length_s,
)


def test_export_fps_stays_thirty() -> None:
    assert EXPORT_FPS == 30


def test_story_clock_helpers_remain_shared() -> None:
    durs = [4.0, 4.0]
    applied = apply_boundaries(durs, [TYPE_CROSSFADE, TYPE_CUT], [1.0, None])
    assert story_length_s(durs, applied) == pytest.approx(7.0)
    assert callable(item_effective_seconds)


def test_grade_preview_documents_approximation() -> None:
    image = ImageAdjust(exposure=50, contrast=0, saturation=0, warmth=0)
    css = preview_css_functions(image)
    assert "brightness" in css
    chain = ffmpeg_grade_chain(image)
    assert "exposure" in chain
    # Different filter families — intentional approximation, not pixel identity.
    assert "brightness" not in chain


def test_parity_discovery_note_exists() -> None:
    note = Path("docs/discovery/189-preview-export-parity.md")
    text = note.read_text(encoding="utf-8")
    assert "Parity contract" in text
    assert "approximate" in text.lower()
    assert "known gap" in text.lower()
