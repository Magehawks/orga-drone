# Local object proposal acceleration (#554) and multi-seed (#550)

## What changed

- Classical LAB-ish flood proposal uses NumPy distance field + OpenCV
  connected components, morphology, and contours when available.
- Coverage metric matches the Python flood path; polygon vertex count may
  differ slightly due to `approxPolyDP` vs Douglas-Peucker ordering.
- Force the Python oracle with `ORGA_OBJECT_SELECT_BACKEND=python`.
- Optional **multi-seed** union (`seeds` on `/grade/object-select`) and
  connected **expand** (`expand_passes`, default 2) improve mottled coverage
  without a second mask engine or cloud inference.
- Studio UI: Shift+click adds a seed after the first proposal; Esc finishes.
  Status shows elapsed time when a proposal takes longer than ~0.5 s.

## Acceptance

Typical ~2 MP Neon Relic seed proposal targets under 1 s (measured ~0.04–0.16 s
cold/warm on Ryzen-class Windows with OpenCV for single and multi-seed).

Downscale: proposals run at `max_edge` default 640; full-resolution refine is
the polygon / brush path after accept. Expand can raise coverage on mottled
subjects; over-coverage vs a chroma TARGET remains a classical-method ceiling
(~0.55–0.65 magenta IoU) without ONNX — leaf **recall** vs TARGET is the
complete-coverage gate (≥0.90 in `tests/test_neon_relic_object_select_coverage.py`
when fixtures are present).

Honest labeling: local classical object **proposal**, not AI freistellung.

## Acceptance timings (masking completion)

Measured on Windows against Neon Relic ~2.23 MP (`00-before-original.jpg`),
multi-seed + expand (`0.55/0.75` + two extra seeds, `max_edge=640`, `expand_passes=2`):

| Mode | Wall time |
| --- | --- |
| Cold proposal | ~0.28–0.33 s |
| Warm median | ~0.08 s |
| Packaged native object-select (synthetic leaf E2E) | ~0.77 s |

Automated gate: `tests/test_studio_object_select_multiseed.py::test_proposal_under_one_second_on_2mp`
and Neon opt-in `tests/test_neon_relic_object_select_coverage.py` (requires local fixtures).

