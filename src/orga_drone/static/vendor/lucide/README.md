# Lucide icons (vendored)

Studio transport and editing controls use **Lucide** SVG icons.

| Item | Value |
|------|--------|
| Package | [`lucide-static`](https://www.npmjs.com/package/lucide-static) |
| Version | 0.469.0 |
| License | ISC |
| Upstream | https://lucide.dev |
| Path | `src/orga_drone/static/vendor/lucide/` |

Assets:

- Individual SVGs for reference / updates
- `sprite.svg` — `<symbol id="lucide-…">` sheet used by the Studio UI

Do **not** load Lucide from a CDN at runtime. Refresh icons by re-downloading the same version (or bump the version here and in `sprite.svg` when upgrading).

Mapped Studio controls:

| Control | Lucide id |
|---------|-----------|
| Play | `play` |
| Pause | `pause` |
| Skip to start | `chevrons-left` |
| Previous clip | `skip-back` |
| Next clip | `skip-forward` |
| Skip to end | `chevrons-right` |
| Scissors (cut reserved) | `scissors` |
| Trash / remove | `trash-2` |
| Volume | `volume-2` |
| Fullscreen | `fullscreen` |
| Plus / add | `plus` |
| Export | `download` |
| Save | `save` |
