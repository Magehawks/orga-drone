# Local motion tracking spike (#298)

Status: feasibility only. This is not a Studio tracker, not a mask editor,
and not a reason to package OpenCV.

## What was measured

The existing privacy mask is one normalized rectangle (`x`, `y`, `w`, `h`)
on a Story clip, optionally limited to a source-time range. It does not store
per-frame motion.

OpenCV 4.9.0 is present on this development machine and is not a project
dependency. `cv2.TrackerCSRT_create` is absent. `calcOpticalFlowPyrLK` is
present. The measurement uses that Lucas-Kanade flow on synthetic frames
only: a high-contrast cross moving over a static striped background, 96×128,
16 frames. No footage, coordinates, or people were used.

| Case | Result |
|---|---|
| Manual box, 4 px/frame translation | Tracked all 16 frames. Center error 0 px. |
| Marker removed after frame 8 | Forward-backward check reported lost at frame 8. It did not keep sliding. |
| Marker grows in place (scale) | The tracker never reported lost. Center error reached 5 px because the box stays the original size. |

CI without `cv2` skips the optical-flow tests. That result is NOT_RUN, not a
pass. Real footage, motion blur, 1080p timing, and a packaged executable are
NOT_RUN.

## Recommendation

NO-GO for a production tracking editor in 2.4.0.

A short synthetic translation can be followed, and a forward-backward check
can stop an obvious occlusion. Scale already leaves a live box in the wrong
place. That is silent drift. Subject Focus, automatic person detection, and
tracked object removal stay out. OpenCV should not be added to the package
for this purpose.

A later issue, if the Product Owner asks, can store manual mask corrections
in the existing normalized box and interpolate between them. That needs no
tracker and no new database column until an approved design says otherwise.
Preview and export would keep using `studio_mask.py`.

## Out of scope

No new route, no Control API action, no `studio.js` behavior, and no change
to saved mask JSON.
