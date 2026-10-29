# ADR 0026: Project-level soundtrack lead-in

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** Issue #183

## Context

ADR 0008 keeps Studio music as one sequential playlist rather than a DAW.
Hobby pilots still need a simple way to leave Story audio or silence before
that playlist begins.

## Decision

Persist one non-negative `music_start_s` value on `studio_projects`, defaulting
to zero for existing projects. It moves the complete sequential playlist bed
later without changing song order or source files. Preview, timeline coverage,
Undo/Redo, and MP4 export use the same offset. Export delays the prepared music
bed and trims its audible duration at Story end.

## Consequences

- Existing projects retain their current soundtrack timing.
- One drag moves the whole bed; songs cannot overlap or move independently.
- Waveforms, trimming, free placement, and a general audio timeline remain out
  of scope.
