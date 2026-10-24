# orga-drone Product Vision

This document is the **product source of truth** for Orga Drone.
`AGENTS.md` summarizes the same constraints for agents; keep them aligned.

Status language used below:

| Label | Meaning |
|-------|---------|
| **Available now** | Implemented in the current tree / releases |
| **Studio MVP** | First complete local Create → Share journey; **Available now** on Windows desktop (social upload destinations remain Later) |
| **Later** | Aspirational; never present as shipping |

## Vision statement

**orga-drone helps people organize, rediscover, create and share the memories
behind their adventures.**

## Current shipping claim

Orga Drone is an **open-source, local-first drone media library** with flight
metadata, telemetry, map exploration, and a **Studio** memory-editor UI
(order + estimated runtime; multiple local Studio projects; synced Story
preview; local MP4 export with configurable resolution, including photo-only
stories at 720/1080; after export, open
or reveal the MP4 on desktop; optional sequential soundtrack playlist (up to 8
local songs; loop when there is one song) in preview and
export; Title Cards; basic visual transitions; basic per-clip image
adjustment for photos and videos (brightness, contrast, saturation, warmth); a linear
saturation ramp on video clips from that grade toward black and white; read-only soundtrack
coverage on the Story time canvas).

It is **not** a professional video editor, mission planner, airspace tool, cloud
sync service, or generic drone administration suite.

**Short positioning:** “Organize drone footage, metadata and flights in one
local-first application — and prepare memories to share.”

Treat everything labeled Later as **planned** unless the codebase already
implements it. The Studio MVP local journey (import → arrange → optional music
→ MP4 → open/reveal the file) is **Available now** on Windows desktop.

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
| Import / scan | **Available now** (listable roots rescan in place; unchanged files skip metadata extraction by size + mtime; an unlistable source keeps its catalog entries and is marked offline) |
| Metadata (EXIF, DJI, SRT, …) | **Available now** |
| GPS | **Available now** |
| Sessions / flows | **Available now** (heuristic) |
| Duplicate detection | **Available now** (heuristics; no auto-delete) |
| File management (rename, merge under roots) | **Available now** |
| User-managed albums | **Available now** (local named references across flights and folders; one file can be in several albums; separate from Studio; no shared, cloud, or automatic albums) |
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
| Timeline product UI | **Available now** (Browse year/month/day groups by recording date; existing filters; missing or non-calendar dates called out; page size 50/100/200). This is not the Studio editor timeline. |

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
| Multiple local Studio projects (browser, switch, rename, delete) | **Available now** |
| Creator Studio layout (preview, Story track, inspector) | **Available now** (UI foundation) |
| Time-based Story canvas (Fit to story / zoom, shared ruler and playhead) | **Available now** (UI state only; not a professional NLE) |
| Synced Story preview (playhead ↔ active clip ↔ media) | **Available now** |
| Simple video Cut (split Story item at playhead; source in/out offsets) | **Available now** |
| Video section repeat (in/out range, 1×–8×) | **Available now** (video clips; story duration grows with each play; preview and MP4 include the repeats at the same speed; not slow motion, a seamless loop, or reverse playback) |
| Basic per-clip image adjustment (brightness, contrast, saturation, warmth) | **Available now** (photo and video clips; preview approximates export; not a color grade) |
| Video saturation ramp (color toward black and white) | **Available now** (one linear range per video clip; start and end time; 100% keeps the current grade and 0% is black and white; preview approximates export; not a keyframe editor) |
| Timed text, shape, and image overlays | **Available now** (up to 8 per photo or video clip; None / Fade in / Fade out / Slide in; preview approximates export; not a motion tracker) |
| Rectangular privacy masks (blur, pixelate) | **Available now** (up to 8 per photo or video clip; fixed for the whole clip; preview approximates export) |
| Per-clip zoom and pan (static crop, or start/end motion) | **Available now** (photo and video clips; 1×–3×; preview matches the exported frame; not tracking or a keyframe editor) |
| Transition markers (Cut, Fade through black, Crossfade) | **Available now** (preview + MP4; duration 0.1–2.0 s; labeled boundary overlays) |
| Inspector object heading, selection vs playhead-active | **Available now** (not a professional NLE) |
| Title Cards | **Available now** (generated Story items: title, optional subtitle, duration, dark/light/accent; preview + MP4) |
| Optional sequential soundtrack playlist (up to 8 local songs; per-song volume/fades; loop when N=1) | **Available now** (preview + MP4 export; desktop picker; read-only coverage spans on the Story time canvas) |
| Local MP4 export (configurable resolution up to source max) | **Available now** (desktop save dialog; suggested filename includes the selected resolution, e.g. `_1080p` or `_4k`, and stays put once edited; optional music mix; photo-only stories at 720/1080; Cancel export stops the running encode and leaves existing files in place) |
| Open / reveal exported MP4 after success | **Available now** (Windows desktop; process-local last export) |
| Further light editing (curves, freeform masks, keyframes, tracking), extra transition types | **Later** |
| Music-lane time mapping | **Later** |

### 4. Share

**Purpose:** Allow users to share memories with others.

Sharing is the final step of the journey.

| Example | Status |
|---------|--------|
| Local file / folder | **Available now** (media on disk; spot GeoJSON download) |
| Simple Studio MP4 export | **Available now** (local file; resolution choice; optional music) |
| Open video / Show in folder after Studio export | **Available now** (Windows desktop) |
| WhatsApp, Signal, LinkedIn, Reddit, YouTube, … | **Later** destinations after a local export exists |
| itch.io Windows convenience build | **Later** (butler process documented for a Draft/Restricted test; no public paid launch; no in-app updater; ZIP copies do not auto-update) |

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
- Browse Timeline: chronological year/month/day groups of indexed photos and
  videos (local recording dates only; Date unknown when a date is missing or
  not a calendar day; same filters and page size as the grid). Not the Studio
  story timeline.
- **Library albums:** local named collections (`albums` / `album_items`). Create,
  rename, and delete an album; add or remove media; the same file can sit in
  more than one album. Membership survives a rescan and stays listed when
  the file is offline. Albums do not modify files and are not Studio projects.
  No shared albums, cloud sync, or automatic albums.
- **Studio:** local project browser and switcher over `studio_projects` /
  `studio_clips` (create, open, rename, delete; last-opened restored). Creator
  Studio UI (browser, preview, transport, Story track, soundtrack playlist, inspector,
  export dialog) for the open project. The open project title is labeled as the
  current Project; **Projects** opens the same local list used on the empty
  landing. **Export** stays the share action; **Clear Studio** is on the Story
  toolbar and empties clips only (not the project or soundtrack). The Story track
  is a shared time canvas
  (Fit to story / zoom; ruler, clips and playhead share one mapping; zoom is
  UI state, not project data). Selected Story objects are distinct from the
  playhead-active clip; transition chips show Cut / Fade / Crossfade and name
  neighbors in the Inspector. Persisted today: editable project title;
  order; estimated runtime; optional video source start/end after Cut. A video
  clip can play that in/out range again, up to 8 times, at the same speed;
  the Story length, preview, and MP4 include each play. Story
  preview plays photos/videos/Title Cards in sync with the playhead. Local MP4
  export with configurable resolution (desktop), including photo-only stories at
  720/1080. Title Cards persist as generated
  `studio_clips` (not media files). An optional sequential soundtrack playlist
  (up to 8 local songs) persists with the project, plays in preview, and is mixed
  into export. Coverage is shown as read-only, time-proportional spans on the
  Story time canvas (same Fit/zoom mapping; not trim/slip/waveform editing). Loop still applies
  only to a one-song playlist. Visual transitions (Cut, Fade through black,
  Crossfade) persist per outgoing clip
  and render in preview and MP4. Photo and video clips can store a basic image adjustment
  (brightness, contrast, saturation, warmth) on that Story clip; preview
  approximates the exported picture and is not a color-managed grade. A video clip
  can also animate that saturation across a start and end time inside the clip,
  from the current grade toward black and white. Photo and video clips
  can carry up to 8 timed text, shape, or image overlays, with Fade in, Fade out,
  or Slide in. Photo and
  video clips can also store up to 8 rectangular privacy masks (blur or
  pixelate) for the whole clip. Masks use the fitted picture, so letterboxing
  does not move them. The same
  clips can store a zoom and focal point (1×–3×), including a start and an end
  so the frame moves across the clip. At 1× the existing fit is unchanged.
  Preview uses the same window as MP4 export. This is not tracking or a
  keyframe editor. Media
  files are referenced, never copied or modified.
- Local SQLite index; media files stay on disk

## Honest limitations

- A library rescan still walks each listable root and rebuilds flows and sessions.
  Unchanged files (same size and mtime) skip metadata extraction. This is not
  a content hash. A source that cannot be listed is not treated as a deleted
  library: catalog entries stay and are marked offline until the folder is
  connected and scanned again. Files removed from a folder that can still be
  listed are dropped on the next scan. Scan never deletes files, favorites,
  tags, notes, or Studio clips.
- Flight sessions are **heuristic**.
- Duplicate detection uses **metadata heuristics**, not content hashing.
- Non-DJI support is thinner than DJI-oriented paths.
- “Ask the library” is a **deterministic rule-based** phrase parser (DE/EN), not
  an LLM or semantic search system.
- Browse Timeline groups indexed media by recording date. It does not edit
  video, recognize faces, or search by meaning. Missing dates stay in
  Date unknown.
- Library albums are local named references only (no shared albums, cloud
  sync, or automatic albums). There is **no** plugin API or multi-OS installer
  pipeline in the current tree. A Windows onefolder zip can be built in
  GitHub Actions; a maintainer publishes the GitHub Release only after the
  MOTW smoke test (`packaging/README.md`). About shows the installed version.
  An optional startup check, off by default, can report a newer published
  Windows release and opens its release page. It does not download or install,
  and it does not run while offline or when the setting is off. It is not an
  in-app updater, an
  MSIX installer, or a macOS/Linux build. Studio supports multiple local
  edit projects, Title Cards, an optional sequential soundtrack playlist
  (up to 8 local songs; loop for a one-song playlist), a time-based Story
  canvas with Fit/zoom, labeled transition overlays, Inspector selection
  headings, read-only time-proportional soundtrack coverage on that canvas,
  basic rendered visual transitions, basic per-clip image adjustment, a linear
  video saturation ramp (not a keyframe editor), timed text,
  shape, and image overlays, rectangular blur/pixelate privacy masks (fixed for
  the clip; not tracking), and per-clip zoom and pan (1×–3×, optional start/end
  motion; preview matches the exported frame; not tracking or a keyframe editor;
  not a professional grade or NLE). A video section repeat plays an in/out
  range up to 8 times at the same speed (not slow motion, not a seamless or
  reverse loop).

## Studio MVP (local Create → Share)

The first complete Studio MVP is a user who can:

1. Import media.
2. Rediscover memories.
3. Select photos, videos or complete flight sessions.
4. Open Studio.
5. Arrange the story.
6. Add optional soundtrack songs.
7. Export a simple MP4.
8. Share the result with family or friends.

Steps 1–7 plus local-file share (open or reveal the MP4 on Windows) are
**Available now**. Social / messenger upload destinations remain **Later**.
Rendered extra transition types and audio crossfades remain **Later**.

## What orga-drone is NOT

orga-drone is not Adobe Premiere, DaVinci Resolve, CapCut, or Final Cut Pro. It
intentionally avoids becoming a feature-heavy professional editor.

Also avoid shipping claims such as: revolutionary AI platform, complete
mission-control system, or industry-leading solution.

## Future direction

Future development should remain focused on storytelling. Possible areas
(**Later** unless shipped):

- Better Studio (light editing, extra transition types)
- Music-lane time mapping
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

1. Separate **now** vs **later**. The local Studio Create → Share journey is
   Available now; do not describe it as unshipped.
2. Name the user problem and success criteria.
3. State non-goals explicitly.
4. Check claims against `README.md` feature status and the codebase.
5. Prefer small, shippable slices over platform promises.

## Agent rule

Before implementing any feature, verify that it supports the product vision in
this file. If it does not, challenge the requirement before writing code.
