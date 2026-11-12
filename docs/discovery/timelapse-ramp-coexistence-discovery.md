# Discovery: Timelapse and variable speed-ramp coexistence (#333)

Status: **Option A approved and implemented** (explicit replace confirm).
Product Owner selected Option A; see the Timelapse editor confirm path and
`CONFIRM_REPLACE_RAMP` soft gate. Option B remains deferred behind #331.

## Current behavior (verified on develop, `studio_timelapse.py`)

- Timelapse Apply writes a **flat ADR 0034 speed ramp** through the existing
  `/speed-ramp` path (`flat_timelapse_payload`). There is no separate
  Timelapse state: a Timelapse IS a ramp after Apply.
- `timelapse_conflict` blocks Apply when any of these is active:
  1. an existing **variable speed ramp** (`has_ramp`),
  2. **section repeats** > 1,
  3. **forward loop** (`loop_to_soundtrack`).
  Each block ships an actionable DE/EN message telling the user exactly what
  to remove first. No partial mutation happens on conflict
  (`test_unsupported_ratios_and_conflicts_do_not_mutate`).

## Option analysis

### Option A — Replace with explicit confirm (recommended)

Timelapse keeps blocking only when it would **lose user work silently**
(repeats, loop). An existing **variable ramp** becomes replaceable with an
explicit confirmation step: the Apply dialog shows the current ramp summary
(range, shape, presets) and the resulting flat ramp; Apply proceeds only
after an explicit confirmation ("Replaces the existing speed ramp" — DE:
"Ersetzt die vorhandene Geschwindigkeitsrampe").

- Pros: smallest surface (one confirm state in the existing dialog); no new
  timing model; the ramp lane stays single-owner (ADR 0034's one-bar
  invariant is preserved — flat and variable still never coexist); the
  current conflict messages already do 80% of this.
- Cons: a confirm replaces the current hard block — users lose the old ramp
  (mitigated by Undo: ramp edits are story-history covered).

### Option B — Variable + flat regions coexist

Multiple timed-effect regions on the one Effekt lane (variable ramp region +
flat Timelapse region) under one timing adapter.

- Pros: more expressive.
- Cons: contradicts the current **one-bar-per-effect** lane model; needs the
  unified timed-effect model (#331) FIRST, plus export/preview parity work
  for region composition; risk of overlapping-region semantics (priority?
  multiplication? clamping?). This is a significantly larger architecture
  slice and must wait for #331.

## Recommendation

**Option A** (replace with explicit confirm). It resolves the user problem
("must remove a ramp first") without new timing semantics, keeps ADR 0034's
single-lane invariant, and can ship as a small UX slice with focused tests
(confirm flow, conflict messages unchanged for repeats/loop, undo restores
the previous ramp). Option B is deferred behind #331 with an explicit note
that regional coexistence needs the shared timing model first.

## Implementation sketch (for the follow-up issue, NOT implemented here)

- `timelapse_conflict` gains a `confirm_replace` path for `has_ramp` only;
  repeats/loop stay hard blocks.
- Inspector: Apply button shows the replacement confirm; DE/EN strings.
- Tests: replace-with-confirm persists the flat ramp; Undo restores the
  variable ramp; repeats/loop still blocked; no partial mutation.

Related: #325 (shipped), ADR 0034, #331 (dependency for Option B).
