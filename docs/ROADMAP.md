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
  music slot, inspector, export stub; persisted: order + estimated runtime;
  no real playback/render pipeline yet)

## Next (possible near-term)

Not scheduled commitments — candidate improvements toward the **Studio MVP
(target)** journey and core library quality:

1. **Studio simple MP4 export** (local file; progress/cancel) after order + duration
2. **Optional one music track** for Studio export (still no pro editor)
3. **Open / reveal exported file** on desktop (share step without social APIs)
4. **Incremental or cheaper rescans** (clearer scan progress is available)
5. **Broader multi-brand parsers** beyond DJI-first depth
6. **Projects or albums** for organizing media sets (Studio is a first slice)
7. **CI-built installers** (tests/releases automation; multi-OS later)
8. Online geocoding providers (place tags are offline today)

Do **not** treat WhatsApp / YouTube / etc. integrations as near-term without a
dedicated product slice. Local MP4 (or file) first.

## Later (vision)

- Studio: simple transitions, light editing, timeline improvements
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
3. After approval, **Engineering-Planner** produces a technical plan
   (prefer Cursor Plan Mode for research-first planning).
4. The main Cursor agent **implements** against the approved plan.
5. **Implementation-Reviewer** reviews diff, tests, risks, and docs before commit.

Canonical agent roles live under `.cursor/agents/`.
