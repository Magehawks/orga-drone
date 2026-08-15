# Roadmap

Status language:

| Label | Meaning |
|-------|---------|
| **Available** | Implemented in the current tree / releases |
| **Next** | Plausible near-term work; not committed |
| **Later** | Longer-term vision; aspirational |
| **Not planned as identity** | Explicitly not product positioning |

Update this file when priorities change. Do not describe Next/Later items
as shipping features in README, marketing, or UI copy.

Product north star: `docs/PRODUCT_VISION.md` (journey + four areas).

## Available (today)

See `README.md` → “Current feature status” and `docs/PRODUCT_VISION.md`.

Highlights:

- Local folder library + SQLite index + browse
- DJI-oriented parsing (strongest path) + thinner generic media support
- Flows, heuristic sessions, maps, rule-based Ask the library
- User meta (stars/favorites/tags/notes), rename/merge, spot GeoJSON
- Heuristic duplicates, DE/EN UI, Windows desktop build path
- Library scan progress (live phase/counters during full rescan)
- Studio workspace (Creator Studio UI: browser, preview, transport, Story track,
  music slot, inspector, export dialog; persisted: `studio_projects` +
  `studio_clips` with editable title, order, estimated runtime, video Cut via
  source start/end; project browser/switcher for multiple local edit projects;
  synced Story preview playback; local MP4 export with
  configurable resolution; after success, Open video / Show in folder on
  Windows; one optional local music track in preview and export; Title Cards
  as generated Story items; basic rendered visual transitions; time-based
  Story canvas with Fit to story / zoom; read-only soundtrack coverage on
  that canvas)

## Next (possible near-term)

Not scheduled commitments — candidate improvements toward the **Studio MVP
(target)** journey and core library quality:

1. Export cancel / abort during long renders
2. **Incremental or cheaper rescans** (clearer scan progress is available)
3. **Broader multi-brand parsers** beyond DJI-first depth
4. **Library albums** for organizing media sets (Studio already has multiple
   local edit projects; albums are a separate library concern)
5. **CI-built installers** (tests/releases automation; multi-OS later)
6. Online geocoding providers (place tags are offline today)

Do **not** treat WhatsApp / YouTube / etc. integrations as near-term without a
dedicated product slice. Local MP4 export, optional music-in-export, and
open/reveal of the finished file already exist on Windows desktop.

## Later (vision)

- Studio: light editing, extra transition types, Inspector/selection clarity
  (Issue #34) — not a professional NLE
- Plugin / extension hooks for parsers and exports
- Optional opt-in community sharing of flight spots
- Social / messenger share destinations beyond “local file”
- Weather and airspace context
- Creator exports (e.g. DaVinci Resolve and other tools)
- Battery and equipment analytics
- Automatic highlight / quality suggestions
- AI-assisted storytelling or semantic search **only if** they solve a concrete
  library / memory problem (never as product identity alone)

## Not planned as product identity

- Semantic / LLM search as the core product story
- Cloud-required accounts or mandatory upload
- Full mission planning / airspace control suite
- Auto-deleting “duplicates”
- Competing with Premiere / DaVinci / CapCut as a pro NLE

## How work enters the repo

1. Product intent is written as a **Product Spec** (problem, scope, non-goals).
2. **Product-Spec-Reviewer** checks the spec against code and vision docs
   (`docs/PRODUCT_VISION.md` journey filter).
3. When the slice has meaningful UI/interaction work, **Product-UX-Designer**
   audits the current interaction model and proposes alternatives. PM then
   selects a concept. UX does not file implementation issues.
4. After approval, **Engineering-Planner** produces a technical plan
   (prefer Cursor Plan Mode for research-first planning).
5. The main Cursor agent **implements** against the approved plan.
6. **Implementation-Reviewer** reviews diff, tests, risks, and docs before commit.

Canonical agent roles live under `.cursor/agents/`.
