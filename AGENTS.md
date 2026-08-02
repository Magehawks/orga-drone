# Orga Drone – Agent Context

## Product (today)

Orga Drone is an **open-source, local-first drone media library** with
flight metadata, telemetry and map exploration.

It indexes photos and videos on the user’s machine, extracts DJI and
standard media metadata, groups split clips and heuristic flight
sessions, and shows locations on a map. It is **not** primarily a
flight-log tool, mission planner, or generic drone administration suite.

## Longer-term vision (not current product status)

An open-source platform for drone media, flight intelligence and creator
workflows.

Treat everything under this vision as **planned or aspirational** unless
the codebase already implements it. Never present vision items as
shipping features.

## Core user problem

Drone pilots accumulate large amounts of footage across SD cards, drives
and folders. Existing tools often focus on editing, generic photo
management, or basic flight logs. They rarely provide a coherent
local-first workflow for drone-specific media and metadata.

## Available now (implemented)

The application helps users:

- import and organize drone (and related) photos and videos from local folders
- extract DJI and standard media metadata (EXIF, filenames, SRT where present)
- group media into **flows** (FAT32 split parts) and heuristic **flight sessions**
- visualize GPS points and tracks on OpenStreetMap-based maps
- filter, browse, and detect likely duplicate files (heuristics; no auto-delete)
- keep ownership of data through local SQLite indexing (media files stay on disk)

## Limitations (honest)

- Library scan is a **full rescan** per root (not incremental).
- Flight sessions are **heuristic** (time gaps + optional SRT altitude/GPS).
- Duplicate detection uses **metadata heuristics**, not content hashing.
- Non-DJI support is useful but thinner than DJI/Avata 2–oriented paths.
- “Ask the library” is a **deterministic rule-based** phrase parser (DE/EN),
  not an LLM or semantic search system.
- There is **no** projects/albums model, plugin API, or CI-built multi-OS
  installer pipeline in the current tree.

## Product principles

1. Local-first and privacy-friendly
2. Open source
3. Useful without cloud accounts
4. Drone-specific rather than generic media management
5. Clear workflows over feature clutter
6. Prefer modular design; do not claim plugins until they exist
7. Optional intelligent features must solve a real user problem
8. Do not add AI merely for marketing, and do not label rule-based features as AI

## Possible future capabilities (roadmap / vision)

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

## Positioning

**Current product (preferred):**

“A local-first drone media library with flight metadata, telemetry and
map exploration.”

**Short alternative:**

“Organize drone footage, metadata and flights in one local-first
application.”

**Longer-term vision (separate from current claims):**

“An open-source platform for drone media, flight intelligence and
creator workflows.”

Avoid exaggerated descriptions such as:

- revolutionary AI platform
- complete mission-control system
- industry-leading solution

## Development expectations

Before changing code:

1. Inspect the existing implementation.
2. Distinguish current behavior from planned features.
3. Preserve compatibility unless a breaking change is justified.
4. Prefer small, reviewable changes.
5. Add or update tests where appropriate.
6. Update documentation when behavior changes.
7. Do not invent technologies or architecture that are not present.

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
