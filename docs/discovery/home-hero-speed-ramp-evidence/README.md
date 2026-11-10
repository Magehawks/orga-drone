# Home hero + speed-ramp remove evidence

## Viewport measurements (1x DPR)

| Viewport | Hero box (CSS px) | Scale vs 1280x720 | Result |
|---|---|---|---|
| 900 | 868 x 288 | 0.678 | downscale, sufficient |
| 1440 | 1152 x 317 | 0.900 | downscale, sufficient |
| 1920 | 1632 x 346 | 1.275 | mild 1x upscale |

At 2x DPR on 1920, the browser needs ~3264 CSS device pixels of width; 1280x720 will look softer. Acceptable for this PR; see issue #335 for async higher-quality warming.

## Screenshots

- [home-hero-900.png](home-hero-900.png)
- [home-hero-1440.png](home-hero-1440.png)
- [home-hero-1920.png](home-hero-1920.png)

Welcome copy is outside the media preview at all three widths.

## Missing hero cache

`/media/{id}/hero-thumb` tries the mid-res `hero_` cache first. If generation fails, it falls back to the grid thumbnail and does **not** write a permanent `hero_` placeholder. Grid `/thumb` generation never calls hero creation. Limitation: first successful `/hero-thumb` generation may still block that one request on ffmpeg/Pillow; no background warm pipeline in this PR (#335).
