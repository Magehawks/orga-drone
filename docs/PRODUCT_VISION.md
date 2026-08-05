# orga-drone Product Vision

This document is the **product source of truth** for Orga Drone.
`AGENTS.md` summarizes the same constraints for agents; keep them aligned.

Status language used below:

| Label | Meaning |
|-------|---------|
| **Available now** | Implemented in the current tree / releases |
| **Studio MVP (target)** | First complete Create → Share journey; not fully shipped yet |
| **Later** | Aspirational; never present as shipping |

## Vision statement

**orga-drone helps people organize, rediscover, create and share the memories
behind their adventures.**

## Current shipping claim

Orga Drone is an **open-source, local-first drone media library** with flight
metadata, telemetry, map exploration, and a **Studio** memory-editor UI
(order + estimated runtime; synced Story preview playback; no MP4 export yet).

It is **not** a professional video editor, mission planner, airspace tool, cloud
sync service, or generic drone administration suite.

**Short positioning:** “Organize drone footage, metadata and flights in one
local-first application — and prepare memories to share.”

Treat everything labeled Studio MVP (target) or Later as **planned** unless the
codebase already implements it.

---

## Why orga-drone exists

Most people do not fly a drone because they enjoy managing files.

They fly a drone because they experienced something beautiful.

A mountain hike. A family vacation. A sunset. A walk with friends. A weekend
adventure.

Photos and videos are only a way to preserve those moments.

orga-drone exists to help people transform those captured moments into memories
they can easily relive and share.

It is **not** intended to become another professional video editor.

Its goal is to make the complete journey from adventure to sharing as simple and
enjoyable as possible.

---

## The user journey

Every feature should improve one step of this journey.

```text
Adventure
    ↓
Capture
    ↓
Import
    ↓
Organize
    ↓
Rediscover
    ↓
Create
    ↓
Share
    ↓
Relive
```

If a feature does not improve this journey, it probably does not belong in
orga-drone.

---

## The four product areas

### 1. Library

**Purpose:** Store and organize media.

**Answers:** “Where are my memories?”

| Responsibility | Status |
|----------------|--------|
| Import / scan | **Available now** (full rescan per root) |
| Metadata (EXIF, DJI, SRT, …) | **Available now** |
| GPS | **Available now** |
| Sessions / flows | **Available now** (heuristic) |
| Duplicate detection | **Available now** (heuristics; no auto-delete) |
| File management (rename, merge under roots) | **Available now** |
| AI indexing | **Later** — only if justified; do not label rule-based Ask/auto-tags as AI |

### 2. Browse

**Purpose:** Rediscover memories.

**Answers:** “What do I want to tell?”

| Responsibility | Status |
|----------------|--------|
| Search / filters / favorites | **Available now** |
| Map | **Available now** |
| Sessions / flows in UI | **Available now** |
| Rule-based “Ask the library” | **Available now** (not an LLM) |
| Timeline product UI | **Later** (today: date filters and sessions, not a timeline editor) |

### 3. Studio

**Purpose:** Transform selected memories into a story.

Studio is **not** another media library or file manager. It is the creative
workspace. It should stay approachable for casual users and never require
professional video-editing knowledge.

**Answers:** “How do I want to tell this story?”

| Responsibility | Status |
|----------------|--------|
| Select media / add to Studio | **Available now** |
| Arrange order | **Available now** |
| Estimated runtime (photo duration planning) | **Available now** |
| Persisted Studio project title (non-destructive project/clip model) | **Available now** |
| Creator Studio layout (preview, Story track, inspector) | **Available now** (UI foundation) |
| Synced Story preview (playhead ↔ active clip ↔ media) | **Available now** |
| Simple video Cut (split Story item at playhead; source in/out offsets) | **Available now** |
| Transition markers / one music slot (UI state only) | **Available now** (not rendered / not exported) |
| Export dialog stub | **Available now** (no render pipeline) |
| Build a story (real music in export, transitions, editing) | **Studio MVP (target)** / **Later** |
| Export MP4 | **Studio MVP (target)** |

### 4. Share

**Purpose:** Allow users to share memories with others.

Sharing is the final step of the journey.

| Example | Status |
|---------|--------|
| Local file / folder | **Available now** (media on disk; spot GeoJSON download) |
| Simple Studio MP4 export | **Studio MVP (target)** |
| WhatsApp, Signal, LinkedIn, Reddit, YouTube, … | **Later** destinations after a local export exists |

---

## Design philosophy

### Simplicity first

Every feature should reduce complexity. Default behavior is preferred over
endless configuration.

### Storytelling over editing

orga-drone is built to tell stories — not to compete with Premiere, DaVinci
Resolve, or CapCut. Professional creators should continue using professional
tools. orga-drone focuses on helping everyone else.

### Local first

Media belongs to the user. The application should work completely offline. Cloud
functionality may exist in the future but must never become mandatory.

### Memories over files

Users care about experiences — not filenames, folder structures, or codecs. The
UI should speak the language of memories rather than technical implementation
where possible, without hiding honest technical limits in docs.

### Small, complete slices

Features should be developed as complete user journeys. Avoid isolated technical
capabilities that provide no end-user value.

### Additional product principles

1. Open source
2. Useful without cloud accounts
3. Drone-specific rather than generic media management alone
4. Prefer modular design; do not claim plugins until they exist
5. Optional intelligent features must solve a real user problem
6. Do not add AI merely for marketing, and do not label rule-based features as AI

---

## Available now (implemented)

See `README.md` for the detailed feature status table. In short:

- Import and organize drone (and related) photos and videos from local folders
- Extract DJI and standard media metadata; flows and heuristic flight sessions
- Maps, filters, favorites, rule-based Ask the library, heuristic duplicates
- **Studio:** single workspace with Creator Studio UI (browser, preview,
  transport, Story track, music slot, inspector, export dialog stub). Persisted
  today: `studio_projects` + `studio_clips` (editable project title; order;
  estimated runtime; optional video source start/end after Cut). Story preview
  plays photos/videos in sync with the playhead. Transitions, music, and export
  remain UI stubs — no render pipeline yet. Media files are referenced, never
  copied or modified.
- Local SQLite index; media files stay on disk

## Honest limitations

- Library scan is a **full rescan** per root (not incremental).
- Flight sessions are **heuristic**.
- Duplicate detection uses **metadata heuristics**, not content hashing.
- Non-DJI support is thinner than DJI-oriented paths.
- “Ask the library” is a **deterministic rule-based** phrase parser (DE/EN), not
  an LLM or semantic search system.
- There is **no** multi-project albums model, plugin API, Studio
  music-in-export/MP4 export, or CI-built multi-OS installer pipeline in the
  current tree.

## Studio MVP (target)

The first **complete** Studio MVP is achieved when a user can:

1. Import media.
2. Rediscover memories.
3. Select photos, videos or complete flight sessions.
4. Open Studio.
5. Arrange the story.
6. Add one optional music track.
7. Export a simple MP4.
8. Share the result with family or friends.

If users can complete this journey without opening another application, that MVP
is successful. Real music-in-export and MP4 rendering (steps 6–8) are **not**
Available now; Studio already exposes UI stubs for those steps.

## What orga-drone is NOT

orga-drone is not Adobe Premiere, DaVinci Resolve, CapCut, or Final Cut Pro. It
intentionally avoids becoming a feature-heavy professional editor.

Also avoid shipping claims such as: revolutionary AI platform, complete
mission-control system, or industry-leading solution.

## Future direction

Future development should remain focused on storytelling. Possible areas
(**Later** unless shipped):

- Better Studio (music, simple transitions, light editing, export)
- Simple timeline improvements
- AI-assisted storytelling **only if** justified by a real user problem
- Plugins
- Sharing destinations beyond local files
- Collaboration

Every new feature should answer:

> Does this help users transform an experience into a memory they can easily share?

If the answer is “yes”, it belongs in orga-drone. If not, it should probably stay
outside the project.

## Spec hygiene

When writing or reviewing a product spec:

1. Separate **now** vs **Studio MVP (target)** vs **later**.
2. Name the user problem and success criteria.
3. State non-goals explicitly.
4. Check claims against `README.md` feature status and the codebase.
5. Prefer small, shippable slices over platform promises.

## Agent rule

Before implementing any feature, verify that it supports the product vision in
this file. If it does not, challenge the requirement before writing code.
