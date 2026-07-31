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

## Available (today)

See `README.md` → “Current feature status” and `docs/PRODUCT_VISION.md`.

Highlights:

- Local folder library + SQLite index + browse
- DJI-oriented parsing (strongest path) + thinner generic media support
- Flows, heuristic sessions, maps, rule-based Ask the library
- User meta (stars/favorites/tags/notes), rename/merge, spot GeoJSON
- Heuristic duplicates, DE/EN UI, Windows desktop build path
- Library scan progress (live phase/counters during full rescan)

## Next (possible near-term)

Not scheduled commitments — candidate improvements:

1. **Incremental or cheaper rescans** (clearer scan progress is available)
2. **Broader multi-brand parsers** beyond DJI-first depth
3. **Projects or albums** for organizing media sets
4. **ffmpeg telemetry burn-in** into a short preview export
5. **CI-built installers** (tests/releases automation; multi-OS later)
6. Online geocoding providers (place tags are offline today)

## Later (vision)

- Plugin / extension hooks for parsers and exports
- Optional opt-in community sharing of flight spots
- Weather and airspace context
- Creator exports (e.g. DaVinci Resolve and other tools)
- Battery and equipment analytics
- Automatic highlight / quality suggestions
- Semantic search or other optional intelligent features **only if** they
  solve a concrete library problem

## Not planned as product identity

- Semantic / LLM search as the core product story
- Cloud-required accounts or mandatory upload
- Full mission planning / airspace control suite
- Auto-deleting “duplicates”

## How work enters the repo

1. Product intent is written as a **Product Spec** (problem, scope, non-goals).
2. **Product-Spec-Reviewer** checks the spec against code and vision docs.
3. After approval, **Engineering-Planner** produces a technical plan
   (prefer Cursor Plan Mode for research-first planning).
4. The main Cursor agent **implements** against the approved plan.
5. **Implementation-Reviewer** reviews diff, tests, risks, and docs before commit.

Canonical agent roles live under `.cursor/agents/`.
