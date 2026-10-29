# Orga Drone – short user help

Plain-language help for hobby pilots and families. These pages describe
**what the current app can do**, not future plans.

Writing style: [UX writing standard](../UX_WRITING.md) ([#186](https://github.com/Magehawks/orga-drone/issues/186)).

| Question | Page |
| --- | --- |
| How do I start and import folders? | [Getting started](getting-started.md) |
| How do I find and organize footage? | [Library and Browse](library-browse.md) |
| How do I use the flight map? | [Map](map.md) |
| How do I build a short Story? | [Studio](studio.md) |
| How do I save a video or photo? | [Export](export.md) |
| Where are settings and common problems? | [Settings and troubleshooting](settings-troubleshooting.md) |

Developer and architecture docs stay under `docs/` outside this folder.

## Release maintenance checklist

When a release changes user-visible behavior:

1. Update the matching page here with the new UI names.
2. Keep DE/EN UI strings and these pages aligned.
3. Remove or rewrite any step that no longer matches the shipping app.
4. Never list roadmap features as available.
