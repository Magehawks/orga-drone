# Orga Drone – Agent Context

## Product (today)

Orga Drone is an **open-source, local-first drone media library** with flight
metadata, telemetry, map exploration, and a **Studio** memory-editor UI
(manual order + estimated runtime + simple video Cut + slow motion on a selected video section + persisted project title;
multiple local Studio projects; synced Story preview playback; local MP4 export
with configurable resolution (suggested filename includes that resolution; Cancel export stops the running encode); after export, Open video / Show in folder on
Windows desktop; optional sequential soundtrack playlist (up to 8 local songs)
in preview and MP4 export; Title Cards as generated Story items; basic rendered
visual transitions with labeled boundary overlays; basic per-clip image
adjustment for photos and videos (brightness, contrast, saturation, warmth; preview approximates
export); a linear saturation ramp on video clips (start and end time, from the current grade
toward black and white); Inspector headings that
distinguish selection from the playhead-active clip; time-based Story canvas
with Fit to story / zoom; read-only soundtrack coverage on that canvas).

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

Treat social share destinations, AI-assisted storytelling,
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
| Library | Where are my memories? | Import/scan (unchanged files skip metadata extraction by size + mtime; offline roots keep catalog entries), metadata, GPS, sessions/flows, dupes, user-managed albums |
| Browse | What do I want to tell? | Filters, map, favorites, rule-based Ask; page size 50/100/200; bulk add of the current page to Studio; chronological Timeline (year/month/day by recording date; missing dates called out; not the Studio editor timeline) |
| Studio | How do I want to tell this story? | Select, order, estimate, Cut, persisted title; multiple local projects (Projects switcher; Clear Studio is Story-scoped); synced preview; time-based Story canvas (Fit/zoom); labeled transitions; Inspector names the selection; local MP4 export (resolution in the suggested filename; Cancel stops a running encode, including photo-only stories at 720/1080); optional sequential soundtrack playlist (up to 8 songs; loop when there is one song) with time-proportional coverage on the Story canvas; Title Cards; Cut / Fade through black / Crossfade; basic per-clip image adjustment (brightness, contrast, saturation, warmth); a linear video saturation ramp from that grade toward black and white; timed text, shape, and image overlays (up to 8 per photo or video clip; Fade in, Fade out, Slide in); rectangular blur and pixelate privacy masks (up to 8 per photo or video clip, fixed for the whole clip); per-clip zoom and pan (1×–3×, optional start/end motion); slow motion at 0.5× or 0.25× for a selected section of a video clip (1× resets that section; source audio on a slowed section is muted); video section repeat (in/out range, 1×–8×, same speed); optional telemetry HUD on a video clip with a sibling DJI SRT (elapsed time and relative altitude; speed and home distance stay unavailable); optional flight map (route and synced marker from GPS already stored for the clip, on a plain background; no map tiles; drag and resize; empty state without GPS) |
| Share | How do I share? | Local files on disk; Studio MP4 export with optional soundtrack playlist; Open video / Show in folder after export (Windows) |

## Available now (implemented)

The application helps users:

- import and organize drone (and related) photos and videos from local folders
  (a rescan skips metadata extraction when file size and mtime are unchanged;
  when a source folder cannot be listed, its catalog entries stay and the UI marks that source offline)
- extract DJI and standard media metadata (EXIF, filenames, SRT where present)
- group media into **flows** (FAT32 split parts) and heuristic **flight sessions**
- visualize GPS points and tracks on OpenStreetMap-based maps
- filter, browse (page size 50/100/200; bulk add of the current page to Studio; chronological Timeline grouped by recording date), and detect likely duplicate files (heuristics; no auto-delete)
- collect media in **library albums** (`albums` / `album_items`): create, rename, and delete named albums; add or remove media; one file can belong to several albums; references survive a rescan and stay listed when the file is offline; albums are separate from Studio projects and do not modify files on disk
- collect selected media in a **Studio** workspace (non-destructive
  `studio_projects` / `studio_clips`; multiple local edit projects with
  browser/switcher; editable persisted title; manual order and
  estimated runtime; simple video Cut via source start/end; video section repeat
  (in/out range played 1×–8× at the same speed; story duration, preview, and MP4
  include each play); Creator Studio UI
  with preview/Story track/inspector; Story preview plays photos/videos in sync
  with the playhead; time-based Story canvas (Fit to story / zoom; shared
  ruler/playhead mapping); labeled transition overlays and Inspector headings
  that distinguish selection from playhead-active clips; Title Cards as generated Story items (title, subtitle,
  duration, solid background; preview + MP4); basic visual transitions
  (Cut, Fade through black, Crossfade) in preview and MP4; basic per-clip
  image adjustment for photos and videos (brightness, contrast, saturation, warmth; preview approximates
  export); a linear saturation ramp on video clips (start and end time, from the current grade toward black and white; preview approximates
  export); timed text, shape, and image overlays with Fade in, Fade out, and Slide in; rectangular blur and pixelate privacy masks on photo and video clips
  (up to 8; fixed for the whole clip; preview approximates export); per-clip zoom and pan (1×–3×, optional start/end motion; preview matches
  the exported frame); optional flight map on photo and video clips (stored GPS route and a marker synced to the clip clock, plain background, no third-party map tiles, drag and resize inside the picture, empty state when GPS is missing; preview and MP4); optional telemetry HUD on a video clip when a sibling DJI SRT has timed cues (elapsed source time and relative altitude in preview and MP4; speed and home distance stay unavailable; gaps stay blank); slow motion at 0.5× or 0.25× on a selected section of a video clip
  (1× resets that section; neighboring sections keep their speed; source audio on a slowed
  section is muted; preview and MP4 share the speed and the longer duration; not optical-flow
  interpolation or fast-forward); local MP4 export with configurable
  resolution on desktop (suggested filename includes that resolution, e.g. `_1080p` or `_4k`), including photo-only stories at 720/1080; Cancel export stops the running encode; after a successful export, Open video / Show in folder
  on Windows; an optional sequential soundtrack playlist of up to 8 local songs
  in preview and export, shown as time-proportional coverage spans on the Story time
  canvas; loop still repeats a single song to Story end). The open project is
  named in the Studio header; **Projects** opens the local project list;
  **Clear Studio** lives on the Story toolbar and empties clips only.
- keep ownership of data through local SQLite indexing (media files stay on disk)

## Limitations (honest)

- A library rescan still walks each listable root and rebuilds flows and sessions.
  Unchanged files (same size and mtime) skip metadata extraction. This is not
  a content hash. If a source drive or folder cannot be listed, that scan keeps
  the root's catalog entries and user metadata, and the UI marks them offline.
  Scanning again after the folder is connected updates those entries without
  adding duplicate rows. Files removed from a folder that can still be listed
  are dropped on the next scan. Scan never deletes files, favorites, tags,
  notes, or Studio clips.
- Flight sessions are **heuristic** (time gaps + optional SRT altitude/GPS).
- Duplicate detection uses **metadata heuristics**, not content hashing.
- Non-DJI support is useful but thinner than DJI/Avata 2–oriented paths.
- “Ask the library” is a **deterministic rule-based** phrase parser (DE/EN),
  not an LLM or semantic search system.
- Browse Timeline groups the local index by recording date (year, month, day).
  Missing or non-calendar dates stay in a Date unknown group. It is not the
  Studio story timeline, and it does not recognize faces or search by meaning.
- Library albums are local named references only. There are no shared albums,
  cloud sync, or automatic albums.
- There is **no** plugin API or multi-OS installer
  pipeline in the current tree. A Windows onefolder zip can be built in
  GitHub Actions; a maintainer publishes the GitHub Release only after the
  MOTW smoke test (`packaging/README.md`). A Windows itch.io butler process
  is documented for a Draft/Restricted test channel and is not a public paid
  launch. ZIP installs do not receive itch.io app updates. About shows the
  installed version. An optional startup check, off by default, reports a
  newer published Windows release and links to it; it does not download,
  install, or run when disabled. It is not an in-app updater, an
  MSIX installer, or a macOS/Linux build. Studio supports multiple local
  edit projects, Title Cards, an optional sequential soundtrack playlist
  (up to 8 local songs; loop for a one-song playlist), a
  time-based Story canvas with Fit/zoom, labeled transition overlays, Inspector
  headings that distinguish selection from playhead-active clips, read-only
  time-proportional soundtrack coverage on that canvas, basic rendered visual
  transitions, basic per-clip image adjustment, a linear video saturation ramp (not a keyframe editor), timed text, shape, and
  image overlays, rectangular blur/pixelate privacy masks (not tracking or a
  legal anonymization guarantee), per-clip zoom and pan (not tracking or a
  keyframe editor), an optional flight map that draws the stored GPS route on a plain background (no downloaded or bundled map tiles; not live tracking), and an optional telemetry HUD (not a goggles display, not
  tracking, and not a substitute for fields the SRT parser does not record), and slow motion
  at 0.5× or 0.25× for a selected video section (source audio on that section is muted;
  not optical-flow interpolation, fast-forward, reverse, or a speed curve).
  A video clip can repeat its in/out range up to 8 times at the same speed
  (not a seamless or reverse loop). Not a professional effects editor, color grade, or NLE.

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

- plugin architecture and community integrations
- semantic search or other optional intelligent features (only if justified)
- automatic highlight / quality suggestions
- weather and airspace context
- creator exports (e.g. DaVinci Resolve and other tools)
- deeper creator/post-production workflows when justified by real users
- battery and equipment analytics
- additional drone manufacturers via dedicated parsers
- cheaper directory walks than a full root walk, content-hash change detection,
  and multi-OS / MSIX installers
- itch.io Windows convenience channel via butler (documented test process;
  not a public launch; no custom in-app updater)

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
   - must return `PM_APPROVED` before UX (when UI) or CTO (when UX is not required)
   - after UX discovery, PM selects the product direction on the same issue
2. **UX Discovery** — `product-ux-designer`
   - usability and interaction design when the slice has meaningful UI work
   - read-only; alternatives, trade-offs, explicit non-scope; no application code
   - does **not** create implementation issues
   - skip for simple bug fixes, backend-only work, CI/tooling, and migrations without user-facing impact
3. **CTO Engineering Gate** — `engineering-planner`
   - validates architecture, compatibility, data/migration impact, performance, security and test strategy
   - read-only
   - must return `CTO_APPROVED` before `ready-for-dev`
4. **Developer** — main Cursor implementation agent
   - implements only the approved issue
   - runs Ruff, MyPy and pytest (including the PR journey smoke; CI reports it as its own check — `docs/PR_E2E.md`) and updates docs/i18n when required
5. **Independent Review Gate** — `implementation-reviewer`
   - reviews issue + diff + tests independently
   - read-only; never fixes its own findings
   - returns `REVIEW_APPROVED`, `REVIEW_CHANGES_REQUESTED`, or `REVIEW_ARCHITECTURE_CONCERN`
6. **Human Product Owner**
   - performs realistic product testing
   - is the final merge gate

Typical flow:

```text
Idea → PM → UX (if UI/interaction) → PM selects concept → CTO
     → ready-for-dev → Developer → PR → Independent Review
     → (changes → Developer → Review) → human-test → Human merge decision
```

Do not automate the final human product test or merge decision. After three developer/reviewer correction loops, escalate to the human instead of looping indefinitely.
