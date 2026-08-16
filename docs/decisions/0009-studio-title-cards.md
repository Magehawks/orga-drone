# ADR 0009: Studio Title Cards as generated timeline items

- **Status:** Accepted
- **Date:** 2026-08-14
- **Deciders:** Issue #26

## Context

Studio stories needed a short heading (trip name, place, chapter) without
leaving Orga Drone. A project-level cover field would not allow cards between
clips. Existing `studio_clips` rows are media references with a required
`media_path`. A fake path would be marked unavailable on rescan. ffmpeg
`drawtext` is a poor source of truth: bundled binaries often lack libfreetype,
and user text is unsafe in filter graphs.

## Decision

1. Model Title Cards as **generated Story items in `studio_clips`** with
   `item_kind='title_card'`. `media_path` and `identity_key` are NULL. Structured
   columns store title, subtitle, duration, and background id. Do not store
   rendered PNG/MP4 as project data. Do not reuse `effect_settings`.
2. Media rows keep `item_kind='media'` (default). A CHECK enforces the two
   shapes. Relink/repath/`is_in_studio` skip generated rows. Title Cards are
   always available and survive library rescan.
3. Preview is an HTML overlay with hardcoded preset colors (not live UI theme).
   Export rasterizes an ephemeral Pillow still in the export temp dir, then
   reuses the existing photo-segment encode (`-loop 1`). No `drawtext`.
4. Photo-only projects still do not unlock resolution (ADR 0005). If a project
   has **no video heights** but **at least one Title Card**, offer **720 and
   1080** only (default 1080). Mixed video + cards still use video heights.

## Alternatives considered

1. **Project cover field** — cannot sit between clips or be reordered.
2. **Sentinel `media_path` (`titlecard://…`)** — rescan/export treat it as
   missing media.
3. **Separate `studio_title_cards` table** — splits the ordered Story list
   from photos/videos (reorder, playhead, concat).
4. **ffmpeg `drawtext`** — font/filter-escaping risk; not the source of truth.

## Consequences

- Positive: First-class timeline cards; existing media projects migrate as
  `item_kind='media'`; export stays on the ffmpeg encoder boundary.
- Negative / trade-offs: Preview HTML vs Pillow still is same intent, not
  pixel-identical. Generated-only export is capped at 1080. System sans font
  required for export (`title_card_font_missing` if none).
- Follow-up: overlays, image backgrounds, and extra type columns can ALTER ADD
  without parsing pixels.
