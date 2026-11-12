# Local object removal: feasibility spike (#297)

Status: **NO-GO for a 2.4.0 Studio feature.** This spike does not add a
removal tool, an API, or an MCP action. It only measures whether a manually
masked region can be rebuilt from real pixels of another frame of the same
shot.

Snapshot: `develop` at `6c38d24`. Host: Windows, Python 3.12, Pillow from the
project dependencies, local OpenCV 4.9.0 (not a project dependency).

## What was measured

`tests/test_object_removal_spike.py` builds synthetic shots. Every pixel
outside the mask, including its one-pixel feather, is required to stay equal
to the original frame.

| Case | Result |
|---|---|
| Static camera, object moved, background visible in the other frame | Filled from that frame. Mask interior matches the real background. |
| Whole frame translated by a known amount | Pillow search recovers the integer shift. Local OpenCV `phaseCorrelate` is within 1.5 px; the padded border keeps it off an integer. |
| Object covers the same pixels in every frame | No fill. The frame is unchanged. Nothing is invented. |
| Mask crosses two planes that move by different amounts | One shift cannot rebuild both. The interior does not match the true unoccluded shot. |
| 160×90 search, shift range ±4 | Finished in under 5 s in CPython. |

## What was not measured

- Real drone footage, shadows, motion blur, or frame-to-frame flicker.
- A 1080p or 4K search. The pure-Python search is exhaustive and is not a
  preview or export path.
- Optical flow or a homography fitted to tracked features. Phase correlation
  was the only OpenCV probe, and only on a noise-free translation.
- Windows packaged E2E. There is no product surface to package. NOT_APPLICABLE.

OpenCV is installed on this machine and is absent from `pyproject.toml`.
CI passes the Pillow tests and skips the OpenCV test when `cv2` is missing.
That skip is NOT_RUN, not a failure and not a PASS.

## Recommendation

Do not ship object removal in 2.4.0 and do not add OpenCV to the Windows
build for this purpose. A later milestone can reopen the question only with
permitted footage, a bounded flow or homography prototype, and an explicit
dependency decision. The honest product behavior when the background was
never visible is to leave the frame unchanged.
