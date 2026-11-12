# ADR 0036: Separate Studio sound-effects (SFX) lane

- **Status:** Accepted
- **Date:** 2026-11-12
- **Deciders:** Issue #184

## Context

ADR 0008 keeps project music as one sequential soundtrack playlist. Creators
still need fire, wind, ambience and other one-shot sounds placed freely on the
Story clock without turning music into a DAW. Issue #184 requires an independent
SFX lane with local files, trim, volume/mute, simple fades, preview/export mix,
undo/redo and save/reopen — without modifying source audio.

## Decision

1. Reuse `studio_audio_clips` with `lane = 'sfx'` (same path exception as music).
2. Add placement/trim columns used only by SFX: `start_s` (Story time),
   `source_in_s`, `source_out_s`. Music rows keep defaults and ignore them.
3. SFX clips are independently placed; they may overlap each other and the
   music bed. Music stays sequential (ADR 0008 / 0026).
4. Cap the SFX lane (16 clips). Loop is unused for SFX (always one-shot).
5. Export mixes SFX onto the Story audio after the existing music mix when
   present, using `amix … normalize=0`. Document that stacked loud beds can
   clip; creators lower volume to compensate.
6. Story undo/redo snapshots include SFX rows so timeline edits restore.
7. UI/API live in dedicated modules/routes (`sfx.*`); `studio.js` only
   orchestrates.

## Consequences

- Schema migration is required; older builds ignore unknown columns / `sfx` rows.
- Music free-placement remains Later (product vision); this ADR does not change it.
- Gain strategy is documented, not an automatic limiter.
- Waveform drawing may be MVP labels first; timing must still match export.
