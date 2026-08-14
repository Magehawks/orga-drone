# Orga Drone – Agent Context

## Product (today)

Orga Drone is an **open-source, local-first drone media library** with flight
metadata, telemetry, map exploration, and a **Studio** memory-editor UI
(manual order + estimated runtime + simple video Cut + persisted project title;
synced Story preview playback; no MP4
export yet).

It indexes photos and videos on the user’s machine, extracts DJI and standard
media metadata, groups split clips and heuristic flight sessions, and shows
locations on a map. It is **not** primarily a flight-log tool, mission planner,
video editor, or generic drone administration suite.

Canonical narrative and journey: `docs/PRODUCT_VISION.md`.

## Longer-term vision (not current product status)

Help people **organize, rediscover, create and share** the memories behind their
adventures — through Library, Browse, Studio, and Share — without becoming a
professional video editor in the current product scope.

Professional creator/post-production workflows may be a long-term ambition.
They may influence clean architecture boundaries, but must not be treated as
shipping behavior or used to inflate a current milestone without an approved issue.

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
| Studio | How do I want to tell this story? | Select, order, estimate, Cut, persisted project title; synced preview; music/export stubs |
| Share | How do I share? | Local files on disk; Studio MP4 export = target MVP |

## Available now (implemented)

The application helps users:

- import and organize drone (and related) photos and videos from local folders
- extract DJI and standard media metadata (EXIF, filenames, SRT where present)
- group media into **flows** (FAT32 split parts) and heuristic **flight sessions**
- visualize GPS points and tracks on OpenStreetMap-based maps
- filter, browse, and detect likely duplicate files (heuristics; no auto-delete)
- collect selected media in a **Studio** workspace (non-destructive
  `studio_projects` / `studio_clips`; editable persisted title; manual order and
  estimated runtime; simple video Cut via source start/end; Creator Studio UI
  with preview/Story track/inspector; Story preview plays photos/videos in sync
  with the playhead; music/export remain stubs only — no render pipeline)
- keep ownership of data through local SQLite indexing (media files stay on disk)

## Limitations (honest)

- Library scan is a **full rescan** per root (not incremental).
- Flight sessions are **heuristic** (time gaps + optional SRT altitude/GPS).
- Duplicate detection uses **metadata heuristics**, not content hashing.
- Non-DJI support is useful but thinner than DJI/Avata 2–oriented paths.
- “Ask the library” is a **deterministic rule-based** phrase parser (DE/EN),
  not an LLM or semantic search system.
- There is **no** multi-project albums model, plugin API, Studio
  music-in-export/MP4 export, or CI-built multi-OS installer pipeline
  in the current tree. Studio remains a single workspace.

## Product principles

1. Local-first and privacy-friendly
2. Open source
3. Useful without cloud accounts
4. Drone-specific rather than generic media management alone
5. Storytelling and creator workflows with simplicity first; professional depth may evolve incrementally
6. Clear workflows over feature clutter
7. Prefer modular design; do not claim plugins until they exist
8. Optional intelligent features must solve a real user problem
9. Do not add AI merely for marketing, and do not label rule-based features as AI
10. Prefer small, complete user-journey slices
11. Limit the current scope, not the long-term vision

## Possible future capabilities (roadmap / vision)

- Studio MVP target: optional music, simple MP4 export, share local result
- projects or albums for organizing media sets
- plugin architecture and community integrations
- semantic search or other optional intelligent features (only if justified)
- automatic highlight / quality suggestions
- weather and airspace context
- creator exports (e.g. DaVinci Resolve and other tools)
- deeper creator/post-production workflows when justified by real users
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

## Positioning

**Current product (preferred):**

“A local-first drone media library with flight metadata, telemetry, map
exploration, and a Studio memory-editor UI.”

**Short alternative:**

“Organize drone footage, metadata and flights in one local-first application —
and prepare memories to share.”

**Longer-term vision (separate from current claims):**

“An open-source platform for drone media, flight intelligence and creator workflows.”

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
9. Implement only issues that have passed the required product/engineering gates unless the human explicitly waives the process.
10. Keep implementation and independent review roles separate.

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
| Agent workflow | `docs/AGENT_WORKFLOW.md` |
| ADRs | `docs/decisions/` |
| Cursor rules | `.cursor/rules/` |
| Specialized agents | `.cursor/agents/` |

Keep this file aligned with `docs/PRODUCT_VISION.md` when product truth changes.

## Agent roles and gates

GitHub issues and pull requests are the handoff boundary between roles. The canonical state machine is documented in `docs/AGENT_WORKFLOW.md`.

1. **PM Product Gate** — `product-spec-reviewer`
   - validates user problem, target user, milestone fit, simplest useful slice, acceptance criteria and explicit non-scope
   - read-only
   - must return `PM_APPROVED` before normal CTO handoff
2. **CTO Engineering Gate** — `engineering-planner`
   - validates architecture, compatibility, data/migration impact, performance, security and test strategy
   - read-only
   - must return `CTO_APPROVED` before `ready-for-dev`
3. **Developer** — main Cursor implementation agent
   - implements only the approved issue
   - runs Ruff, MyPy and pytest and updates docs/i18n when required
4. **Independent Review Gate** — `implementation-reviewer`
   - reviews issue + diff + tests independently
   - read-only; never fixes its own findings
   - returns `REVIEW_APPROVED`, `REVIEW_CHANGES_REQUESTED`, or `REVIEW_ARCHITECTURE_CONCERN`
5. **Human Product Owner**
   - performs realistic product testing
   - is the final merge gate

Typical flow:

```text
Idea → PM → CTO → ready-for-dev → Developer → PR → Independent Review
     → (changes → Developer → Review) → human-test → Human merge decision
```

Do not automate the final human product test or merge decision. After three developer/reviewer correction loops, escalate to the human instead of looping indefinitely.
