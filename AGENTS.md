# Orga Drone – Agent Context

## Product (today)

Orga Drone is an **open-source, local-first drone media library** with flight
metadata, telemetry, map exploration, and a **Studio** memory-editor UI
(manual order + estimated runtime; preview/timeline chrome without real
playback or export).

It indexes photos and videos on the user’s machine, extracts DJI and standard
media metadata, groups split clips and heuristic flight sessions, and shows
locations on a map. It is **not** primarily a flight-log tool, mission planner,
video editor, or generic drone administration suite.

Canonical narrative and journey: `docs/PRODUCT_VISION.md`.

## Longer-term vision (not current product status)

Help people **organize, rediscover, create and share** the memories behind their
adventures — through Library, Browse, Studio, and Share — without becoming a
professional video editor.

Treat Studio music/export, social share destinations, AI-assisted storytelling,
plugins, and similar items as **planned or aspirational** unless the codebase
already implements them. Never present vision items as shipping features.

## Core user problem

People fly drones for experiences, not for managing files. Footage piles up
across SD cards, drives, and folders. Existing tools often focus on editing,
generic photo management, or basic flight logs. They rarely provide a coherent
local-first path from adventure → organize → rediscover → create → share.

## User journey (product filter)

```text
Adventure → Capture → Import → Organize → Rediscover → Create → Share → Relive
```

Before implementing a feature, verify it improves this journey (see
`docs/PRODUCT_VISION.md`). If it does not, challenge the requirement.

## Four product areas (summary)

| Area | Question | Today (honest) |
|------|----------|----------------|
| Library | Where are my memories? | Import/scan, metadata, GPS, sessions/flows, dupes |
| Browse | What do I want to tell? | Filters, map, favorites, rule-based Ask |
| Studio | How do I want to tell this story? | Select, order, estimate; Creator UI with stub playback/music/export |
| Share | How do I share? | Local files on disk; Studio MP4 export = target MVP |

## Available now (implemented)

The application helps users:

- import and organize drone (and related) photos and videos from local folders
- extract DJI and standard media metadata (EXIF, filenames, SRT where present)
- group media into **flows** (FAT32 split parts) and heuristic **flight sessions**
- visualize GPS points and tracks on OpenStreetMap-based maps
- filter, browse, and detect likely duplicate files (heuristics; no auto-delete)
- collect selected media in a **Studio** workspace (single list with manual
  order and estimated runtime; Creator Studio UI with preview/Story track/
  inspector; playback, music, and export are UI stubs only — no render pipeline)
- keep ownership of data through local SQLite indexing (media files stay on disk)

## Limitations (honest)

- Library scan is a **full rescan** per root (not incremental).
- Flight sessions are **heuristic** (time gaps + optional SRT altitude/GPS).
- Duplicate detection uses **metadata heuristics**, not content hashing.
- Non-DJI support is useful but thinner than DJI/Avata 2–oriented paths.
- “Ask the library” is a **deterministic rule-based** phrase parser (DE/EN),
  not an LLM or semantic search system.
- There is **no** multi-project albums model, plugin API, real Studio
  playback/music-in-export/MP4 export, or CI-built multi-OS installer pipeline
  in the current tree. Studio remains a single workspace.

## Product principles

1. Local-first and privacy-friendly
2. Open source
3. Useful without cloud accounts
4. Drone-specific rather than generic media management alone
5. Storytelling over professional editing; simplicity first
6. Clear workflows over feature clutter
7. Prefer modular design; do not claim plugins until they exist
8. Optional intelligent features must solve a real user problem
9. Do not add AI merely for marketing, and do not label rule-based features as AI
10. Prefer small, complete user-journey slices

## Possible future capabilities (roadmap / vision)

- Studio MVP target: optional music, simple MP4 export, share local result
- projects or albums for organizing media sets
- plugin architecture and community integrations
- semantic search or other optional intelligent features (only if justified)
- automatic highlight / quality suggestions
- weather and airspace context
- creator exports (e.g. DaVinci Resolve and other tools)
- battery and equipment analytics
- additional drone manufacturers via dedicated parsers
- incremental scanning and CI-built installers

These are future directions. Never describe them as already available.

## Target users

- hobby drone pilots
- content creators
- photographers and videographers
- professional operators with large local media libraries
- anyone who wants to turn drone (and related) adventures into shareable memories
  without learning a pro editor

## Positioning

**Current product (preferred):**

“A local-first drone media library with flight metadata, telemetry, map
exploration, and a Studio memory-editor UI.”

**Short alternative:**

“Organize drone footage, metadata and flights in one local-first application —
and prepare memories to share.”

**Longer-term vision (separate from current claims):**

“orga-drone helps people organize, rediscover, create and share the memories
behind their adventures.”

Avoid exaggerated descriptions such as:

- revolutionary AI platform
- complete mission-control system
- industry-leading solution

## Development expectations

Before changing code:

1. Inspect the existing implementation.
2. Distinguish current behavior from planned features (`docs/PRODUCT_VISION.md`).
3. Verify the change supports the user journey; challenge it if not.
4. Preserve compatibility unless a breaking change is justified.
5. Prefer small, reviewable changes.
6. Add or update tests where appropriate.
7. Update documentation when behavior changes.
8. Do not invent technologies or architecture that are not present.

## Communication style

Documentation should be:

- precise
- technically credible
- understandable to non-experts
- free of hype and empty AI terminology
- explicit about what exists today and what is planned

### Language for agent-written artifacts

Write **pull request titles and bodies**, **commit messages**, **issue comments
and docs updates drafted by agents**, and **release notes when agents draft
them** in **English**.

User-facing chat with the human may still follow the user’s language preference
(e.g. German). That preference does **not** apply to the repository artifacts
listed above.

## Canonical project docs

| Topic | Path |
|-------|------|
| Product vision | `docs/PRODUCT_VISION.md` |
| Roadmap | `docs/ROADMAP.md` |
| Architecture | `docs/ARCHITECTURE.md` |
| ADRs | `docs/decisions/` |
| Cursor rules | `.cursor/rules/` |
| Specialized agents | `.cursor/agents/` |

Keep this file aligned with `docs/PRODUCT_VISION.md` when product truth changes.

## Cursor agent roles

The main Cursor agent **implements**. Use these project subagents for gated work:

1. **Product-Spec-Reviewer** (`.cursor/agents/product-spec-reviewer.md`) — review a product spec against the codebase; no code changes.
2. **Engineering-Planner** (`.cursor/agents/engineering-planner.md`) — turn an approved spec into a technical plan (research first / Plan Mode).
3. **Implementation-Reviewer** (`.cursor/agents/implementation-reviewer.md`) — review changes, tests, risks, and docs before commit.

Typical flow: Spec → Product-Spec-Reviewer → Engineering-Planner → implement → Implementation-Reviewer → commit (only when explicitly requested).
