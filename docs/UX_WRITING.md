# Orga Drone UX writing standard

- **Issue:** [#186](https://github.com/Magehawks/orga-drone/issues/186)
- **Audience:** Hobby drone pilots and families (German and English UI)
- **Applies to:** Library, Browse, detail, Map, Studio, Export, Settings, dialogs,
  empty states, errors, and future UI copy

## Rules

1. **One control, one meaning.** Labels are short and action-oriented.
2. **Tooltips explain only that control** (about 5–15 words). Never a full workflow.
3. **Prefer a clear label** over many tooltips.
4. **No jargon** in the UI: no FFmpeg, CRF, filter graphs, internal IDs, or marketing hype.
5. **Errors:** what happened + one next step. Details stay in logs.
6. **Disabled controls:** say why in one short phrase. Never promise unshipped features.
7. **DE/EN stay parallel** — same meaning, same UI name order where possible.
8. **Accessible names** match the visible label (aria-label ≈ button text).

## Examples

| Weak | Better |
| --- | --- |
| Soften | Softens the selected area |
| Timeline zoom | Zooms the timeline for finer cuts |
| Export spot | Saves this flight spot to share |
| File not found | The file is missing. Choose a new location. |

## Review checklist (every UI PR)

- [ ] Labels readable without a tooltip
- [ ] Tooltip (if any) ≤ two short sentences and matches shipped behavior
- [ ] Error offers a next step when possible
- [ ] No roadmap wording as if the feature already works
- [ ] DE and EN catalogs updated together
- [ ] Screen-reader / aria text not more technical than the visible label

## Priority audit themes (ongoing)

Confusing or technical strings to prefer fixing first when touched:

- Studio edge / cut / transition limits
- Export quality (Standard / High / Best) — describe outcome, not CRF numbers
- Offline / missing file states
- Mask, zoom, and soundtrack controls
- Map “estimated” ground speed vs HUD “not available”

Do not mass-rewrite every string in one PR; improve when editing that surface.
