# ADR 0027: Studio local `.cube` LUT and D-Log M conversion

## Status

Accepted (Issue #174; architecture from #172).

## Context

Log footage such as DJI D-Log M looks flat without a display conversion. Users
also want optional creative 3D LUTs. Orga Drone already redistributes GPL
FFmpeg; discovery #172 selected FFmpeg `lut3d` as the export path and forbade a
second pixel engine.

## Decision

1. Store validated `.cube` copies under the local data directory (`luts/`).
2. Persist per-clip looks in `effect_settings.color` (additive JSON).
3. Keep **technical conversion** (e.g. confirmed D-Log M → Rec.709 via a
   user-supplied LUT) separate from an optional **creative LUT** and strength.
4. Never auto-apply conversion from SRT `color_md` or filenames; the UI may
   suggest when `dlog_m` is present, and the user must confirm and choose a
   `.cube`.
5. Do not redistribute camera-vendor LUTs with the app.
6. Export filter order: static grade → conversion LUT → creative LUT →
   saturation ramp → framing / scale.
7. Preview continues to approximate grade sliders only; LUT application is
   export-truth until a shared still path exists. UI copy states this honestly.

## Addendum: central LUT catalog

Accepted with the LUT library slice. Files keep `{32hex}.cube` names under
`luts/`. SQLite `lut_assets` stores display name, content SHA-256, and import
time. Clip references stay `effect_settings.color.*_lut` asset names. Shared
HTTP surface is `/api/luts` (Studio import alias `/api/studio/luts` remains).
Delete is refused while any Studio clip references the asset. The catalog does
not classify conversion vs creative; that role is chosen only when applying a
LUT in Studio.

## Consequences

- Missing LUT references fail export with an actionable error.
- Creative strength below 100 writes a temporary cube blended toward identity.
- Still / social photo export paths stay on the existing grade chain unless a
  follow-up wires ColorLook there explicitly.
