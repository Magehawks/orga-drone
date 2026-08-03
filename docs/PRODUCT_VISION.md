# Product Vision

This document is the **product source of truth** for Orga Drone.
`AGENTS.md` summarizes the same constraints for agents; keep them aligned.

## Current product (shipping claim)

Orga Drone is an **open-source, local-first drone media library** with
flight metadata, telemetry and map exploration.

It indexes photos and videos on the user’s machine, extracts DJI and
standard media metadata, groups split clips and heuristic flight
sessions, and shows locations on a map.

It is **not** primarily a flight-log tool, mission planner, video editor,
airspace tool, cloud sync service, or generic drone administration suite.

### Short positioning

“Organize drone footage, metadata and flights in one local-first
application.”

## Longer-term vision (aspirational)

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

## Target users

- hobby drone pilots
- content creators
- photographers and videographers
- professional operators with large local media libraries

## Product principles

1. Local-first and privacy-friendly
2. Open source
3. Useful without cloud accounts
4. Drone-specific rather than generic media management
5. Clear workflows over feature clutter
6. Prefer modular design; do not claim plugins until they exist
7. Optional intelligent features must solve a real user problem
8. Do not add AI merely for marketing, and do not label rule-based features as AI

## Available now (implemented)

- import and organize drone (and related) photos and videos from local folders
- extract DJI and standard media metadata (EXIF, filenames, SRT where present)
- group media into **flows** (FAT32 split parts) and heuristic **flight sessions**
- visualize GPS points and tracks on OpenStreetMap-based maps
- filter, browse, and detect likely duplicate files (heuristics; no auto-delete)
- collect selected media in a **Studio** workspace (single curation list; not
  projects/albums, export, or editing)
- keep ownership of data through local SQLite indexing (media files stay on disk)

See `README.md` for the detailed feature status table.

## Honest limitations

- Library scan is a **full rescan** per root (not incremental).
- Flight sessions are **heuristic** (time gaps + optional SRT altitude/GPS).
- Duplicate detection uses **metadata heuristics**, not content hashing.
- Non-DJI support is useful but thinner than DJI/Avata 2–oriented paths.
- “Ask the library” is a **deterministic rule-based** phrase parser (DE/EN),
  not an LLM or semantic search system.
- There is **no** multi-project albums model, plugin API, or CI-built multi-OS
  installer pipeline in the current tree. Studio is a single light workspace.

## Claims to avoid

- revolutionary AI platform
- complete mission-control system
- industry-leading solution
- presenting roadmap items as available features

## Spec hygiene

When writing or reviewing a product spec:

1. Separate **now** vs **later**.
2. Name the user problem and success criteria.
3. State non-goals explicitly.
4. Check claims against `README.md` feature status and the codebase.
5. Prefer small, shippable slices over platform promises.
