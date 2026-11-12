"""Local, non-generative object-removal spike (issue #297).

This is not a Studio feature. It checks whether a manually masked region can
be rebuilt from real pixels of another frame of the same shot. OpenCV is not
a packaged dependency; the translation search uses Pillow only. A second test
runs when a local OpenCV install is present and is skipped otherwise.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

import pytest
from PIL import Image, ImageChops, ImageDraw

RGB = tuple[int, int, int]


def _pattern(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (
                (x * 13 + y * 7) % 256,
                (x * 3 + 40) % 256,
                (y * 5 + 15) % 256,
            )
    return image


def _shift(image: Image.Image, dx: int, dy: int, fill: RGB = (0, 0, 0)) -> Image.Image:
    moved = Image.new("RGB", image.size, fill)
    moved.paste(image, (dx, dy))
    return moved


def _paint_rect(image: Image.Image, box: tuple[int, int, int, int], color: RGB) -> Image.Image:
    painted = image.copy()
    draw = ImageDraw.Draw(painted)
    draw.rectangle(box, fill=color)
    return painted


def _mask(size: tuple[int, int], box: tuple[int, int, int, int]) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    return mask


def _dilate(mask: Image.Image, radius: int) -> Image.Image:
    if radius <= 0:
        return mask
    width, height = mask.size
    source = mask.load()
    assert source is not None
    dilated = Image.new("L", mask.size, 0)
    output = dilated.load()
    assert output is not None
    points = [
        (x, y)
        for y in range(height)
        for x in range(width)
        if source[x, y] > 0
    ]
    for x, y in points:
        for dy in range(-radius, radius + 1):
            yy = y + dy
            if yy < 0 or yy >= height:
                continue
            for dx in range(-radius, radius + 1):
                xx = x + dx
                if 0 <= xx < width:
                    output[xx, yy] = 255
    return dilated


def estimate_translation(
    reference: Image.Image,
    donor: Image.Image,
    known: Image.Image,
    *,
    max_shift: int,
) -> tuple[int, int]:
    """Shift of ``donor`` that best matches ``reference`` outside ``known``.

    ``known`` is 255 where the reference frame is occluded and must not vote.
    """
    width, height = reference.size
    ref = reference.load()
    src = donor.load()
    hide = known.load()
    assert ref is not None and src is not None and hide is not None
    best = (0, 0)
    best_score: float | None = None
    for dy in range(-max_shift, max_shift + 1):
        for dx in range(-max_shift, max_shift + 1):
            total = 0
            count = 0
            for y in range(height):
                yy = y - dy
                if yy < 0 or yy >= height:
                    continue
                for x in range(width):
                    if hide[x, y]:
                        continue
                    xx = x - dx
                    if xx < 0 or xx >= width:
                        continue
                    a = ref[x, y]
                    b = src[xx, yy]
                    total += abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
                    count += 1
            if count == 0:
                continue
            score = total / count
            if best_score is None or score < best_score:
                best_score = score
                best = (dx, dy)
    return best


def fill_from_frame(
    occluded: Image.Image,
    donor: Image.Image,
    mask: Image.Image,
    *,
    shift: tuple[int, int] = (0, 0),
    feather: int = 1,
) -> tuple[Image.Image, bool]:
    """Copy donor pixels into the mask. Return the frame and whether it filled.

    Pixels outside the feathered mask stay equal to ``occluded``. When the
    donor still shows the same pixels inside the mask, nothing is invented.
    """
    if occluded.size != donor.size or occluded.size != mask.size:
        raise ValueError("frames and mask must share one size")
    aligned = _shift(donor, shift[0], shift[1])
    hard = mask.load()
    cover = _dilate(mask, feather).load()
    src = occluded.load()
    got = aligned.load()
    assert hard is not None and cover is not None and src is not None and got is not None
    width, height = occluded.size
    changed = 0
    covered = 0
    for y in range(height):
        for x in range(width):
            if hard[x, y] and got[x, y] != src[x, y]:
                changed += 1
            if hard[x, y]:
                covered += 1
    if covered == 0 or changed / covered < 0.5:
        return occluded.copy(), False
    output = occluded.copy()
    pixels = output.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width):
            if not cover[x, y]:
                continue
            if hard[x, y]:
                pixels[x, y] = got[x, y]
            else:
                a = src[x, y]
                b = got[x, y]
                pixels[x, y] = tuple((a[i] + b[i]) // 2 for i in range(3))
    return output, True


def _outside(mask: Image.Image, radius: int) -> Iterable[tuple[int, int]]:
    cover = _dilate(mask, radius).load()
    assert cover is not None
    width, height = mask.size
    for y in range(height):
        for x in range(width):
            if not cover[x, y]:
                yield x, y


def test_static_camera_reuses_a_real_background_frame() -> None:
    background = _pattern(96, 64)
    hole = (30, 20, 45, 40)
    occluded = _paint_rect(background, hole, (220, 10, 10))
    donor = _paint_rect(background, (60, 20, 75, 40), (220, 10, 10))
    mask = _mask(background.size, hole)
    shift = estimate_translation(occluded, donor, mask, max_shift=2)
    assert shift == (0, 0)
    filled, ok = fill_from_frame(occluded, donor, mask, shift=shift, feather=1)
    assert ok is True
    src = occluded.load()
    out = filled.load()
    truth = background.load()
    hide = mask.load()
    assert src is not None and out is not None and truth is not None and hide is not None
    for x, y in _outside(mask, 1):
        assert out[x, y] == src[x, y]
    for y in range(21, 40):
        for x in range(31, 45):
            assert hide[x, y]
            assert out[x, y] == truth[x, y]
            assert out[x, y] != (220, 10, 10)


def test_one_translation_aligns_a_shifted_shot() -> None:
    background = _pattern(96, 64)
    hole = (28, 18, 44, 36)
    occluded = _paint_rect(background, hole, (220, 10, 10))
    # Donor is the same world shifted by (+6, -3), with the object elsewhere.
    donor_bg = _shift(background, 6, -3, fill=(1, 2, 3))
    donor = _paint_rect(donor_bg, (70, 8, 86, 26), (220, 10, 10))
    mask = _mask(background.size, hole)
    shift = estimate_translation(occluded, donor, mask, max_shift=8)
    assert shift == (-6, 3)
    filled, ok = fill_from_frame(occluded, donor, mask, shift=shift, feather=0)
    assert ok is True
    out = filled.load()
    src = occluded.load()
    truth = background.load()
    hide = mask.load()
    assert out is not None and src is not None and truth is not None and hide is not None
    for x, y in _outside(mask, 0):
        assert out[x, y] == src[x, y]
    for y in range(19, 36):
        for x in range(29, 44):
            assert out[x, y] == truth[x, y]


def test_no_visible_background_is_left_unchanged() -> None:
    background = _pattern(96, 64)
    hole = (30, 20, 50, 40)
    occluded = _paint_rect(background, hole, (220, 10, 10))
    mask = _mask(background.size, hole)
    filled, ok = fill_from_frame(occluded, occluded, mask, feather=1)
    assert ok is False
    assert ImageChops.difference(filled, occluded).getbbox() is None


def _stack(far: Image.Image, near: Image.Image) -> Image.Image:
    frame = Image.new("RGB", far.size)
    frame.paste(far.crop((0, 0, far.width, 32)), (0, 0))
    frame.paste(near.crop((0, 32, near.width, near.height)), (0, 32))
    return frame


def test_one_shift_cannot_rebuild_two_depths() -> None:
    """Parallax: one translation matches only one plane inside the mask."""
    far = _pattern(96, 64)
    near = far.transpose(Image.Transpose.ROTATE_180)
    world = _stack(far, near)
    hole = (20, 8, 40, 56)
    occluded = _paint_rect(world, hole, (220, 10, 10))
    donor = _stack(_shift(far, 2, 0), _shift(near, 10, 0))
    mask = _mask(world.size, hole)
    shift = estimate_translation(occluded, donor, mask, max_shift=12)
    filled, ok = fill_from_frame(occluded, donor, mask, shift=shift, feather=0)
    assert ok is True
    out = filled.load()
    truth = world.load()
    assert out is not None and truth is not None
    mismatches = 0
    for y in range(9, 56):
        for x in range(21, 40):
            if out[x, y] != truth[x, y]:
                mismatches += 1
    assert mismatches > 0


def test_search_cost_on_a_small_frame_stays_bounded() -> None:
    background = _pattern(160, 90)
    hole = (40, 30, 70, 60)
    occluded = _paint_rect(background, hole, (220, 10, 10))
    donor = _shift(background, 4, -2)
    mask = _mask(background.size, hole)
    started = time.perf_counter()
    shift = estimate_translation(occluded, donor, mask, max_shift=4)
    elapsed = time.perf_counter() - started
    assert shift == (-4, 2)
    assert elapsed < 5.0


def _view(world: Image.Image, origin_x: int, size: tuple[int, int]) -> Image.Image:
    width, height = size
    view = Image.new("RGB", size, (0, 0, 0))
    view.paste(world.crop((origin_x, 0, origin_x + width, height)), (0, 0))
    return view


def test_moving_camera_reuses_the_same_shot() -> None:
    """A translating camera and a moving object, still one physical shot."""
    world = _pattern(220, 64)
    view_size = (96, 64)
    hole = (18, 14, 34, 34)
    frames: list[Image.Image] = []
    for step in range(6):
        view = _view(world, step * 4, view_size)
        object_box = (18 + step * 6, 14, 34 + step * 6, 34)
        frame = _paint_rect(view, object_box, (220, 10, 10))
        shadow = (object_box[2] + 2, 26, object_box[2] + 10, 34)
        frames.append(_paint_rect(frame, shadow, (8, 8, 8)))
    mask = _mask(view_size, hole)
    donor_step = 4
    started = time.perf_counter()
    shift = estimate_translation(frames[0], frames[donor_step], mask, max_shift=20)
    align_s = time.perf_counter() - started
    assert shift == (16, 0)
    filled, ok = fill_from_frame(
        frames[0], frames[donor_step], mask, shift=shift, feather=1
    )
    assert ok is True
    out = filled.load()
    src = frames[0].load()
    truth = _view(world, 0, view_size).load()
    assert out is not None and src is not None and truth is not None
    outside_changed = 0
    interior_wrong = 0
    for x, y in _outside(mask, 1):
        if out[x, y] != src[x, y]:
            outside_changed += 1
    for y in range(15, 34):
        for x in range(19, 34):
            if out[x, y] != truth[x, y]:
                interior_wrong += 1
    assert outside_changed == 0
    assert interior_wrong == 0
    # The shadow sits outside the mask and must stay. It is not reconstructed.
    assert out[40, 30] == (8, 8, 8)
    # Feather ring is a one-pixel average, the only seam treatment.
    cover = _dilate(mask, 1).load()
    hard = mask.load()
    assert cover is not None and hard is not None
    blended = 0
    for y in range(64):
        for x in range(96):
            if cover[x, y] and not hard[x, y] and out[x, y] != src[x, y]:
                blended += 1
    # Matching donor background makes the one-pixel feather identical to the
    # original. The visible change is the mask interior, not a halo.
    assert blended == 0
    removed = 0
    for y in range(15, 34):
        for x in range(19, 34):
            if out[x, y] != src[x, y]:
                removed += 1
    assert removed > 0
    later_hole = (24, 14, 40, 34)
    later_mask = _mask(view_size, later_hole)
    filled_later, later_ok = fill_from_frame(
        frames[1], frames[5], later_mask, shift=(16, 0), feather=1
    )
    assert later_ok is True
    later_out = filled_later.load()
    later_truth = _view(world, 4, view_size).load()
    assert later_out is not None and later_truth is not None
    flicker = 0
    for y in range(15, 34):
        for x in range(25, 40):
            if later_out[x, y] != later_truth[x, y]:
                flicker += 1
    assert flicker == 0
    evidence = Path(__file__).resolve().parents[1] / "docs" / "discovery" / "297-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    frames[0].save(evidence / "before.png")
    frames[donor_step].save(evidence / "donor.png")
    filled.save(evidence / "after.png")
    (evidence / "metrics.json").write_text(
        json.dumps(
            {
                "camera": "synthetic translation, 4 px per frame",
                "outside_mask_changed_pixels": outside_changed,
                "interior_mismatch_pixels": interior_wrong,
                "shadow_pixel_kept": list(out[40, 30]),
                "feather_pixels_changed": blended,
                "mask_pixels_replaced": removed,
                "synthetic_flicker_mismatch_pixels": flicker,
                "align_seconds": round(align_s, 3),
                "frame_size": [96, 64],
                "search_radius_px": 20,
                "real_footage": "NOT_RUN",
                "flicker_on_real_footage": "NOT_RUN",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_opencv_phase_correlation_matches_the_same_shift() -> None:
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    background = _pattern(96, 64)
    # Correlate the clean shot with its shifted copy. The padded border keeps
    # the peak about one pixel off an integer, which is the tolerance below.
    ref = cv2.cvtColor(np.array(background), cv2.COLOR_RGB2GRAY).astype("float32")
    src = cv2.cvtColor(
        np.array(_shift(background, 6, -3, fill=(0, 0, 0))), cv2.COLOR_RGB2GRAY
    ).astype("float32")
    (dx, dy), response = cv2.phaseCorrelate(src, ref)
    assert abs(abs(dx) - 6) <= 1.5
    assert abs(abs(dy) - 3) <= 1.5
    assert response > 0.2
