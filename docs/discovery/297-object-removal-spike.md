# Local object removal: feasibility spike (#297)

Status: **NO-GO for a 2.4.0 Studio feature.** This spike does not add a
removal tool, an API, or an MCP action. It measures whether a manually masked
region can be rebuilt from real pixels of another frame of the same shot.

Host: Windows, Python 3.12, Pillow from the project dependencies. Local
OpenCV 4.9.0 is present on the measurement machine and is not a project
dependency. Real drone footage was not used.

## Moving-camera evidence

`test_moving_camera_reuses_the_same_shot` builds one synthetic shot. The
camera translates 4 px per frame. A red rectangle and a dark shadow move
across that shot. Frame 0 is filled from frame 4 after a searched translation.
The pictures are the files next to this note:

| File | What it shows |
|---|---|
| `297-evidence/before.png` | Frame 0 with the object and its shadow |
| `297-evidence/donor.png` | Frame 4 of the same shot, object moved |
| `297-evidence/after.png` | Frame 0 after the mask was filled from frame 4 |
| `297-evidence/metrics.json` | The counts below |

Measured on a 96×64 frame, search radius 20 px, align time 2.238 s:

| Check | Result |
|---|---|
| Pixels outside the mask and its one-pixel feather | 0 changed |
| Mask interior versus the true unoccluded background | 0 mismatches |
| Pixels replaced inside the mask | 285 |
| Shadow pixel outside the mask | Kept at RGB (8, 8, 8). The shadow is not removed. |
| Feather ring versus the original | 0 changed, because the aligned donor already matched the surrounding background. The seam is the mask edge, not a halo. |
| Next frame, filled the same way, versus its true background | 0 mismatches. Synthetic flicker against the truth is 0. |
| Real footage, motion blur, and real flicker | **NOT_RUN** |

## Other synthetic cases

| Case | Result |
|---|---|
| Static camera, object moved, background visible in the other frame | Filled from that frame. Interior matches the real background. |
| Whole frame translated by a known amount | Pillow search recovers the integer shift. Local OpenCV `phaseCorrelate` is within 1.5 px. |
| Object covers the same pixels in every frame | No fill. The frame is unchanged. Nothing is invented. |
| Mask crosses two planes that move by different amounts | One shift cannot rebuild both. Parallax stays wrong. |
| 160×90 search, shift range ±4 | Finished in under 5 s in CPython. |

## Performance, dependency, and packaging

The search compares every candidate shift in CPython. 2.238 s for a 96×64
frame and a ±20 px radius is already too slow for a timeline preview, and it
does not scale to 1080p. This spike did not run a 1080p search and does not
invent a timing for one.

OpenCV is absent from `pyproject.toml` and from `packaging/orga-drone.spec`.
The local `cv2` package is about 111 MB (93 files, 111,218,388 bytes). Adding
it to the Windows build would ship that weight for a method that still fails
on parallax and on a hidden background. CI skips the OpenCV test when `cv2`
is missing. That skip is **NOT_RUN**, not a pass.

## Recommendation

Do not ship object removal in 2.4.0 and do not add OpenCV to the Windows
build for this purpose. A later milestone can reopen the question only with
permitted footage, a bounded flow or homography prototype, and an explicit
dependency decision. When the background was never visible, the measured
behavior is to leave the frame unchanged. Shadows outside the mask stay.
One translation cannot repair parallax.
