"""Feasibility measurements for a manual local tracker. Not a product module.

OpenCV is optional. CI without cv2 records NOT_RUN for the optical-flow cases.
The box rules below are the only contract this spike is willing to recommend.
"""

from __future__ import annotations

from typing import Any

import pytest

cv2: Any
np: Any
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def _clip_box(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    width = min(1.0, max(0.02, w))
    height = min(1.0, max(0.02, h))
    left = min(1.0 - width, max(0.0, x))
    top = min(1.0 - height, max(0.0, y))
    return (round(left, 4), round(top, 4), round(width, 4), round(height, 4))


def _interpolate(
    start: tuple[float, float, float, float],
    end: tuple[float, float, float, float],
    amount: float,
) -> tuple[float, float, float, float]:
    mix = min(1.0, max(0.0, amount))
    return _clip_box(*(a + (b - a) * mix for a, b in zip(start, end, strict=True)))


def test_manual_correction_interpolates_inside_the_existing_mask_box() -> None:
    start = _clip_box(0.1, 0.2, 0.2, 0.2)
    end = _clip_box(0.5, 0.2, 0.2, 0.2)
    mid = _interpolate(start, end, 0.5)
    assert mid == (0.3, 0.2, 0.2, 0.2)
    assert _interpolate(start, end, 5.0) == end


def _marker() -> Any:
    patch = np.zeros((18, 18, 3), dtype=np.uint8)
    patch[:, :] = (10, 10, 10)
    patch[2:16, 7:11] = (250, 250, 250)
    patch[7:11, 2:16] = (250, 20, 20)
    return patch


def _background() -> Any:
    image = np.zeros((96, 128, 3), dtype=np.uint8)
    image[:, :] = (30, 40, 35)
    image[:, 0:128:8] = (70, 60, 50)
    return image


def _frames(motion: str) -> tuple[list[Any], list[tuple[int, int]]]:
    background = _background()
    patch = _marker()
    frames = []
    centers = []
    for index in range(16):
        frame = background.copy()
        if motion == "zoom":
            scale = 1.0 + index * 0.08
            patch_now = cv2.resize(
                patch,
                (max(4, int(18 * scale)), max(4, int(18 * scale))),
                interpolation=cv2.INTER_NEAREST,
            )
            x, y = 54, 39
            height, width = patch_now.shape[:2]
            frame[y : y + height, x : x + width] = patch_now
            centers.append((x + width // 2, y + height // 2))
            frames.append(frame)
            continue
        visible = motion != "occlusion" or index < 8
        if visible:
            x, y = 8 + index * 4, 40
            frame[y : y + 18, x : x + 18] = patch
            centers.append((x + 9, y + 9))
        frames.append(frame)
    return frames, centers


def _track(frames: list[Any], box: tuple[int, int, int, int]) -> tuple[list[tuple[float, float]], int | None]:
    x, y, width, height = box
    previous = cv2.cvtColor(frames[0], cv2.COLOR_RGB2GRAY)
    region = np.zeros_like(previous)
    region[y : y + height, x : x + width] = 255
    points = cv2.goodFeaturesToTrack(
        previous, mask=region, maxCorners=30, qualityLevel=0.15, minDistance=2
    )
    path = [(x + width / 2, y + height / 2)]
    lost_at = None
    for index, frame in enumerate(frames[1:], start=1):
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        if points is None or len(points) < 6:
            lost_at = index
            break
        nxt, status, _err = cv2.calcOpticalFlowPyrLK(previous, gray, points, None)
        keep = status.reshape(-1) == 1
        if nxt is None or int(keep.sum()) < 6:
            lost_at = index
            break
        back, back_status, _err = cv2.calcOpticalFlowPyrLK(gray, previous, nxt, None)
        if back is None:
            lost_at = index
            break
        both = keep & (back_status.reshape(-1) == 1)
        if int(both.sum()) < 6:
            lost_at = index
            break
        delta = (nxt[both] - points.reshape(-1, 1, 2)[both]).reshape(-1, 2)
        returned = (back[both] - points.reshape(-1, 1, 2)[both]).reshape(-1, 2)
        if float(np.median(np.abs(returned))) > 1.0:
            lost_at = index
            break
        shift = np.median(delta, axis=0)
        x = int(round(x + float(shift[0])))
        y = int(round(y + float(shift[1])))
        path.append((x + width / 2, y + height / 2))
        points = nxt[keep].reshape(-1, 1, 2)
        previous = gray
    return path, lost_at


def test_textured_patch_stays_close_during_a_short_pan() -> None:
    frames, centers = _frames("pan")
    path, lost_at = _track(frames, (8, 40, 18, 18))
    assert lost_at is None
    assert len(path) == len(centers)
    errors = [abs(found[0] - truth[0]) + abs(found[1] - truth[1]) for found, truth in zip(path, centers, strict=True)]
    assert max(errors) <= 3.0


def test_occlusion_is_reported_instead_of_a_silent_drift() -> None:
    frames, _centers = _frames("occlusion")
    _path, lost_at = _track(frames, (8, 40, 18, 18))
    assert lost_at is not None
    assert lost_at <= 12


def test_zoom_keeps_a_box_while_the_center_drifts() -> None:
    frames, centers = _frames("zoom")
    path, lost_at = _track(frames, (54, 39, 18, 18))
    assert lost_at is None
    errors = [
        abs(found[0] - truth[0]) + abs(found[1] - truth[1])
        for found, truth in zip(path, centers, strict=True)
    ]
    assert max(errors) >= 4.0
