# Orga Drone – Agent Context

## Product (today)

Orga Drone is an **open-source, local-first drone media library** with flight
metadata, telemetry, map exploration, and a **Studio** memory-editor UI
(manual order + estimated runtime + simple video Cut by number or by dragging a video clip's left and right edges on the Story timeline + slow motion on a selected video section + a forward repeat of one video section until a known soundtrack ends (hard cuts, or an optional forward crossfade; the soundtrack plays once) + persisted project title;
multiple local Studio projects; synced Story preview playback; local MP4 export
with configurable resolution and a Standard / High / Best quality choice (CRF 23 / 20 / 17; Best uses the slow x264 preset and takes longer; suggested filename includes that resolution; an existing file is never replaced, a taken name is saved as the next free numbered file, and that name is shown after export; Cancel export stops the running encode); after export, Open video / Show in folder on
Windows desktop; optional sequential soundtrack playlist (up to 8 local songs;
project-level silent lead-in) in preview and MP4 export; Title Cards as generated Story items; basic rendered
visual transitions with labeled boundary overlays; basic per-clip image
adjustment for photos and videos (brightness, contrast, saturation, warmth; preview approximates
export); a linear saturation ramp on video clips (start and end time, from the current grade
toward black and white); Inspector headings that
distinguish selection from the playhead-active clip; time-based Story canvas
with Fit to story / zoom; soundtrack coverage with one draggable project-level
start on that canvas).

The app opens on a Home screen. An empty library shows the Orga Drone logo and
starts in the existing folder import. When a recent file already has a local
thumbnail and is still on disk, that image is the hero; a missing or offline
file falls back to the logo without decoding video at startup. A sidebar
(Home, media library, Studio, flight map, sources, albums, duplicates, and
Settings at the bottom) stays on those areas. On a narrow window the same
destinations use the existing bottom bar. Settings stores the existing dark,
light, or custom theme and German or English, and can clear only the thumbnail
and map-tile caches. There is no separate Back control: Home is a direct link,
and detail pages keep their own return links. Studio edits already saved in
the database stay when you leave; Undo and Redo still exist only for the
running session.

It indexes photos and videos on the user’s machine, extracts DJI and standard
media metadata, groups split clips and heuristic flight sessions, and shows
locations on a map. A photo or video detail page keeps the preview and the
Single clip / Complete flight switch with the picture on the left. The tabs
stay on the right on a desktop window. Info holds the date, drone, and the
other file facts together with rating, tags, notes, albums, rename, and flow
merge. Location holds the map and GPS when coordinates exist. Studio is Share.
Photo brightness, contrast, saturation, and warmth are Image. Export is its own
tab. A video has no Image tab. It can export that one file locally:
best quality, or a WhatsApp, Instagram, or TikTok preset saved on disk
(nothing is posted). A photo export can set brightness, contrast, saturation,
and warmth from −100 to 100. Neutral keeps today's file, including a
best-quality copy of the original bytes when that is the current result. A
moved slider grades the pixels with the Studio adjustment math and then
applies the preset. The grade is saved for that photo and stays across leaving
the page, a restart, and a rescan that matches the same file. Reset returns
neutral. Best quality can be JPEG or PNG. A neutral JPEG still copies the
original bytes when that is today's result. PNG re-encodes. The library file
is not modified. A video stays an MP4 from the Studio encoder and does not get
these sliders. It is **not** primarily a flight-log tool, mission planner,
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
| Library | Where are my memories? | Import/scan (unchanged files skip metadata extraction by size + mtime; offline roots keep catalog entries), metadata, GPS, sessions/flows, dupes, user-managed albums; a photo or video detail page keeps the preview and Single clip / Complete flight with the picture on the left and the tabs on the right on a desktop window; Info holds date, drone, and the other file facts with rating, tags, notes, albums, rename, and flow merge; Location holds the map and GPS when coordinates exist; Studio is Share; photo image adjustment is Image; export is Export; a video has no Image tab |
| Browse | What do I want to tell? | Filters stay when you leave and return from the sidebar, and sit on the left; a single drone model hides the drone picker; DJI, camera, and other are separate filters and empty buckets stay hidden; the flight map can hide place names and show drone, camera, or both (both includes unclear files); page size 50/100/200; bulk add of the current page to Studio; chronological Timeline (year/month/day by recording date; missing dates called out; not the Studio editor timeline) |
| Studio | How do I want to tell this story? | Select, order, estimate, Cut, persisted title; multiple local projects (gallery from the sidebar; Clear Studio is Story-scoped); synced preview; time-based Story canvas (Fit/zoom); labeled transitions; Inspector names the selection; local MP4 export (resolution in the suggested filename; existing files are never replaced; a taken name is saved as the next free numbered file and shown after export; Cancel stops a running encode, including photo-only stories at 720/1080); optional sequential soundtrack playlist (up to 8 songs; loop when there is one song) with time-proportional coverage on the Story canvas; Title Cards; Cut / Fade through black / Crossfade; basic per-clip image adjustment (brightness, contrast, saturation, warmth); optional local ``.cube`` LUT import with confirmed D-Log M conversion (never automatic; preview approximates grade, LUT on export); Quick Looks that replace the four basic sliders plus a preview-only before/after compare; advanced tonal sliders (highlights, shadows, blacks) with restrained colorlevels on export; optional restrained sharpen and denoise (default off); a linear video saturation ramp from that grade toward black and white; timed text, shape, and image overlays (up to 8 per photo or video clip; Fade in, Fade out, Slide in); rectangular blur and pixelate privacy masks (up to 8 per photo or video clip, timed bars on one Effekt lane; selectable and removable in the preview and inspector); per-clip zoom and pan (1×–3×, optional start/end motion); slow motion at 0.5× or 0.25× for a selected section of a video clip (1× resets that section; source audio on a slowed section is muted); video section repeat (in/out range, 1×–8×, same speed); one video section can repeat forward until a soundtrack with a known duration ends (hard cuts; soundtrack plays once; last play trimmed; unknown duration is not guessed); optional telemetry HUD on a video clip with a sibling DJI SRT (elapsed time and relative altitude; speed and home distance stay unavailable); optional flight map (route and synced marker from GPS already stored for the clip, on a plain background; no map tiles; drag and resize; the default box is a smaller undistorted square and opacity is adjustable; empty state without GPS); session Undo/Redo for Story edits (Ctrl+Z / Ctrl+Y, cleared when the app restarts) |
| Share | How do I share? | Local files on disk; Studio MP4 export with optional soundtrack playlist; Open video / Show in folder after export (Windows); one photo or video from its detail page (best quality, or a local WhatsApp / Instagram / TikTok file — nothing is uploaded or posted; a photo is a still; brightness, contrast, saturation, and warmth at −100…100, neutral 0, sit on the Image tab with the Studio grade, and the Export tab applies that saved grade; neutral best quality still copies the original bytes when that is today's result; a moved slider grades pixels then applies the preset; the grade is saved for that photo across a restart and a matching rescan; reset returns neutral; best quality can be JPEG or PNG; the library file is not modified; a video is an MP4 at the highest existing resolution or 1080×1920 with the picture fitted inside the frame, without those sliders) |

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
  estimated runtime; simple video Cut via source start/end, including dragging the left edge (Source in) and right edge (Source out) of a video clip on the Story timeline, staying inside the file, with one drag as one Undo step; a trash button beside Cut, the Delete key from the Story track when no dialog is open, and a right-click menu remove the selected Story clip (the file stays; Undo puts it back); a right-click on the cut boundary or the following clip can remove that cut when the two clips are the same file, meet in forward order, and share compatible settings (otherwise the action stays disabled and explains why; one Undo step splits them again); a cut or trimmed video keeps an Original entry in the Story browser for that file (it stays after those clips are removed and after a restart; opening it marks a range on the existing preview, and dragging it onto the Story or Add scene inserts a new clip with empty effects; a right-click on a video clip can still add another scene immediately after that clip; the file is not copied; one Undo step removes the added clip); video section repeat
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
  export); timed text, shape, and image overlays with Fade in, Fade out, and Slide in; rectangular blur and pixelate privacy masks (up to 8, not tracking), zoom (1×–3×), and slow motion (0.5× or 0.25×) are timed bars on one Effekt lane for a video clip; outside a bar that effect is off, and removing the bar clears it; photos have no Effekt lane; preview matches the MP4; optional flight map on photo and video clips (stored GPS route and a marker synced to the clip clock, OpenStreetMap tiles when they can be fetched and cached locally, otherwise a plain panel, drag and resize inside the picture, empty state when GPS is missing; the default box is a smaller undistorted square and opacity is adjustable; preview and MP4); optional telemetry HUD on a video clip when a sibling DJI SRT has timed cues (elapsed source time and relative altitude in preview and MP4; speed and home distance stay unavailable; gaps stay blank); a slowed bar stays at 0.5× or 0.25× and mutes that section's source audio; preview and MP4 share the longer duration; not optical-flow interpolation or fast-forward; a video clip's embedded audio plays in preview and in the MP4 at 1× and is shown on its own story audio lane, where the bar can be dragged in time and its edges shorten only the sound while the picture's edge handles still trim the picture, and the source file is not modified; local MP4 export with configurable
  resolution and a Standard / High / Best quality choice on desktop (suggested filename includes that resolution, e.g. `_1080p` or `_4k`), including photo-only stories at 720/1080; an existing file is never replaced, and a taken name is saved as the next free numbered file (`name_1`, `name_2`, …) which the success banner shows; Cancel export stops the running encode; after a successful export, Open video / Show in folder
  on Windows; an optional sequential soundtrack playlist of up to 8 local songs
  in preview and export, shown as time-proportional coverage spans on the Story time
  canvas; the whole bed can start later after a silent lead-in; loop still repeats
  a single song to Story end). One video section can instead repeat forward until that soundtrack’s once-through duration ends: the soundtrack plays once and is not restarted at each video join, the last play is trimmed (a remainder under 0.05s is omitted), and the joins are hard cuts, or an optional forward crossfade (0.5–2.0 s, clamped on a short section) that does not match frames. The same loop effect also applies to a manual 1–8 repeat with no soundtrack. Cinematic blend is a longer forward overlap (0.5–5.0 s, linear or smooth opacity) and can show doubled objects when the views differ. An experimental local seam search can narrow that repeated range when it is confident; otherwise the original range stays a hard cut, and the search does not claim a seamless join. If the soundtrack duration cannot be determined, that repeat is not applied. Undo and Redo (curved arrows, Ctrl+Z / Ctrl+Y) restore the last Story edit in this session; restarting the app clears that history and opens the last saved Story. Source files are not modified. The open project is
  named in the Studio header; **Studio** in the sidebar opens the project gallery, and **Back to projects** returns there;
  **Clear Studio** lives on the Story toolbar and empties clips only.
- keep ownership of data through local SQLite indexing (media files stay on disk)

## Limitations (honest)

- A library rescan still walks each listable root and rebuilds flows and sessions.
  Unchanged files (same size and mtime) skip metadata extraction. This is not
  a content hash. A sibling SRT is re-read when its size or mtime changes.
  If a source drive or folder cannot be listed, that scan keeps
  the root's catalog entries and user metadata, and the UI marks them offline.
  A child folder that cannot be listed keeps the entries already stored under it.
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
  image overlays, and one Effekt lane whose timed bars are zoom, blur, pixelate, and slow motion (not tracking, not a keyframe editor, and not a legal anonymization guarantee), an optional flight map that draws the stored GPS route on OpenStreetMap tiles when online (tiles are cached locally and are not bundled; a plain panel when a tile cannot be fetched; the default box is a smaller undistorted square and opacity is adjustable; not live tracking), and an optional telemetry HUD (not a goggles display, not
  tracking, and not a substitute for fields the SRT parser does not record), and slow motion
  only inside its Effekt-lane bar at 0.5× or 0.25× (source audio on that bar is muted;
  not optical-flow interpolation, fast-forward, reverse, or a speed curve).
  A video clip can repeat its in/out range up to 8 times at the same speed
  (hard cuts, not reverse). Separately, one video section can repeat forward
  until a soundtrack with a known duration ends. The soundtrack plays once and
  does not restart at each join. The last play is trimmed to that duration; a
  remainder under 0.05s is omitted. Joins are hard cuts, or an optional forward
  crossfade of 0.5–2.0 s (short sections are clamped; both plays keep moving
  forward; not frame matching, optical flow, or interpolation). Not reverse or
  ping-pong. Unknown soundtrack duration is not guessed. Dragging a Story video's left or right edge changes that clip's source range and stays inside the file. It does not snap, and it does not change a neighbor's source range or effects. Photos, title cards, and videos with an unknown duration have no edge handles. Studio undo is kept only for the running session. Not a professional effects editor, color grade, or NLE.

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
