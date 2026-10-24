# ADR 0019: Studio flight map without third-party tiles

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** Issue #108

## Context

Studio can already place timed overlays on the fitted picture and already
stores a GPS track on the media row when a scan finds one. Issue #108 asks for
a picture-in-picture flight map in preview and MP4, including a marker that
moves with the clip. It also requires an offline render and a decision on map
tiles: pack them only if the license is reliable, otherwise ship a local route.

## Decision

1. Do not download, request, or bundle third-party map tiles. The overlay is a
   plain panel plus the GPS track already stored for that clip.
2. Store the box in `effect_settings.map` (`enabled`, `x`, `y`, `w`, `h`) as
   fractions of the fitted picture, the same coordinate system as overlays.
   The box is clamped inside the frame. It defaults to the lower right and
   stays off until the user enables it.
3. A marker follows source time, including a trimmed video in-point. A GPS gap
   longer than two seconds holds the last fix. No GPS leaves the panel empty.
4. Preview and export use that stored track only. The source file is unchanged.
   This is not live tracking, a basemap, or a HUD.

## Alternatives considered

1. **Bundled or online raster tiles** — attribution, storage, and a network
   dependency this slice does not take on.
2. **A new overlay kind inside the eight timed overlays** — the map is on for
   the whole clip and should stay available beside a later HUD.

## Consequences

- Positive: Export stays offline. Older projects are unchanged until the map
  is enabled. Placement survives with the Story clip, including a Cut.
- Negative / trade-offs: The panel is not a street map. Preview and MP4 share
  the same route math; the export marker expression uses at most 32 fixes.
- Follow-up: map tiles stay out until a separate licensing decision. HUD
  fields stay in #107.
