# Local object proposal acceleration (#554)

## What changed

- Classical LAB-ish flood proposal uses NumPy distance field + OpenCV
  connected components, morphology, and contours when available.
- Coverage metric matches the Python flood path; polygon vertex count may
  differ slightly due to `approxPolyDP` vs Douglas-Peucker ordering.
- Force the Python oracle with `ORGA_OBJECT_SELECT_BACKEND=python`.

## Acceptance

Typical ~2 MP Neon Relic seed proposal targets under 1 s (measured ~0.04 s
cold/warm on Ryzen-class Windows with OpenCV).
