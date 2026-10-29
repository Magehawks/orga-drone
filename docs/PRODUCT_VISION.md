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
preview; local MP4 export with configurable resolution and a Standard / High / Best quality choice, including photo-only
stories at 720/1080; after export, open
or reveal the MP4 on desktop; optional sequential soundtrack playlist (up to 8
local songs; project-level lead-in; loop when there is one song) in preview and
export; one video section can repeat forward until a soundtrack with a known
duration ends (hard cuts, a short forward crossfade, or a cinematic blend of 0.5–5.0 s; the soundtrack plays once); Title Cards; basic visual transitions; basic per-clip image
adjustment for photos and videos (brightness, contrast, saturation, warmth); a linear
saturation ramp on video clips from that grade toward black and white; soundtrack
coverage with one draggable project-level start on the Story time canvas).

It is **not** a professional video editor, mission planner, airspace tool, cloud
sync service, or generic drone administration suite.

**Short positioning:** “Organize drone footage, metadata and flights in one
local-first application — and prepare memories to share.”

The app opens on Home: the Orga Drone logo when the library is empty or no
saved preview is available, otherwise one already cached local thumbnail.
The same sidebar reaches the library, Studio, the flight map, and Settings
(dark, light, or custom theme; German or English; thumbnail and map-tile
cache only). Studio opens a project gallery. Choosing a project or creating
one opens the editor. Original files, projects, and exports are not deleted
from Settings.

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
| Timeline product UI | **Available now** (Browse year/month/day groups by recording date; filters stay when you leave and come back, sit on the left, and can limit DJI, camera, or other files without showing empty buckets; the flight map can hide stored place names and filter drone, camera, or both, and both includes unclear files; missing or non-calendar dates called out; page size 50/100/200). This is not the Studio editor timeline. |

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
| Remove selected Story clip | **Available now** (trash button beside Cut, Delete from the Story track when no dialog is open, and a right-click menu; photos, videos, and Title Cards; the inspector action stays; the file, library row, and other projects stay; one Undo step puts the clip back) |
| Remove a cut | **Available now** (right-click the boundary for Remove cut, or the following clip for Merge with previous; only when both clips are the same file, the source ranges meet within 0.001 s in forward order, and speed, volume, grade, masks, overlays, and the other clip settings can be kept; otherwise the action stays disabled and says why; one Undo step restores the two clips) |
| Reuse original footage | **Available now** (a cut or trimmed video keeps an Original entry in the left Story list; the entry stays after those clips are removed and after the app restarts; opening it uses the existing preview and Source in / Source out; dragging it onto the Story or Add scene inserts a new clip with empty effects; a right-click on a video clip can still add a scene immediately after that clip; the file is not copied; photos and title cards do not gain an Original entry; one Undo step removes the added clip) |
| Studio Undo / Redo | **Available now** (curved-arrow toolbar buttons, Ctrl+Z / Ctrl+Y; one step per edit, and one step per completed slider or drag; Redo clears after a new edit; history is not kept after the app restarts; source files stay unchanged) |
| Video section repeat (in/out range, 1×–8×) | **Available now** (video clips; story duration grows with each play; preview and MP4 include the repeats at the same speed; not slow motion, a seamless loop, or reverse playback) |
| Forward repeat to soundtrack | **Available now** (one video section repeats forward until a soundtrack with a known once-through duration ends; the soundtrack plays once and does not restart or blend at each join; the last play is trimmed, and a remainder under 0.05 s is omitted; joins are hard cuts, or an optional forward crossfade of 0.5–2.0 s that overlaps the end of one play with the start of the next; a short section clamps that overlap, and a section that cannot hold it stays a hard cut; the crossfade does not match frames and can show a double image; the same loop effect also applies to a manual 1–8 repeat with no soundtrack; cinematic blend is a longer forward overlap of 0.5–5.0 s with a linear or smooth opacity curve and can show doubled objects when the views differ; an experimental local seam search can narrow the repeated range when confident and otherwise keeps the original range as a hard cut without claiming a seamless join; unknown duration is not guessed; not reverse, ping-pong, optical flow, or frame interpolation) |
| Basic per-clip image adjustment (brightness, contrast, saturation, warmth) | **Available now** (photo and video clips; preview approximates export; not a color grade) |
| Local `.cube` LUT + confirmed D-Log M conversion | **Available now** (user-supplied LUT only; never auto from SRT; preview approximates grade, LUT on export) |
| Video saturation ramp (color toward black and white) | **Available now** (one linear range per video clip; start and end time; 100% keeps the current grade and 0% is black and white; preview approximates export; not a keyframe editor) |
| Timed text, shape, and image overlays | **Available now** (up to 8 per photo or video clip; None / Fade in / Fade out / Slide in; preview approximates export; not a motion tracker) |
| Rectangular privacy masks (blur, pixelate) | **Available now** (up to 8; rectangular, not tracking; on a video clip each mask is a timed bar on the one Effekt lane and is off outside that bar; photos have no Effekt lane; preview matches the MP4) |
| Per-clip zoom and pan (static crop, or start/end motion) | **Available now** (1×–3×; on a video clip the zoom is a timed bar on the same Effekt lane and is 1× outside that bar; photos have no Effekt lane; preview matches the MP4; not tracking or a keyframe editor) |
| Flight map overlay | **Available now** (optional per photo or video clip; route and moving marker from GPS already stored; OpenStreetMap tiles when they can be fetched and cached locally, otherwise a plain panel; tiles are not bundled; drag and resize inside the picture; empty state without GPS; preview and MP4) |
| Optional telemetry HUD | **Available now** (one preset on a video clip when a sibling DJI SRT has timed cues; elapsed source time and relative altitude; speed and home distance stay unavailable; preview and MP4; not a goggles display or tracking) |
| Slow motion on a selected video section (0.5×, 0.25×, or 1× to reset) | **Available now** (a Verlangsamen bar on the one Effekt lane; 0.5× or 0.25× only inside the bar; removing the bar returns that range to 1×; preview and MP4 match; source audio on a slowed bar is muted; not optical-flow interpolation or fast-forward) |
| Transition markers (Cut, Fade through black, Crossfade) | **Available now** (preview + MP4; duration 0.1–2.0 s; labeled boundary overlays) |
| Inspector object heading, selection vs playhead-active, tabs, resizable width | **Available now** (Clip, Image, Effects, and Overlays group the existing controls; the inspector, the media browser, and the Story tracks can be dragged and the size is kept in this browser; not a professional NLE) |
| Title Cards | **Available now** (generated Story items: title, optional subtitle, duration, dark/light/accent; preview + MP4) |
| Optional sequential soundtrack playlist (up to 8 local songs; per-song volume/fades; project-level lead-in; loop when N=1) | **Available now** (preview + MP4 export; desktop picker; the whole bed can start later with silence before it; coverage spans on the Story time canvas) |
| Local MP4 export (configurable resolution up to source max) | **Available now** (desktop save dialog; suggested filename includes the selected resolution, e.g. `_1080p` or `_4k`, and stays put once edited; Standard / High / Best quality next to resolution, High by default; optional music mix; photo-only stories at 720/1080; Cancel export stops the running encode and leaves existing files in place) |
| Open / reveal exported MP4 after success | **Available now** (Windows desktop; process-local last export) |
| Further light editing (curves, freeform masks, keyframes, tracking), extra transition types | **Later** |
| Independent per-song placement, trimming, or waveforms | **Later** |

### 4. Share

**Purpose:** Allow users to share memories with others.

Sharing is the final step of the journey.

| Example | Status |
|---------|--------|
| Local file / folder | **Available now** (media on disk; spot GeoJSON download) |
| Simple Studio MP4 export | **Available now** (local file; resolution and quality choice; optional music) |
| One photo or video from its detail page | **Available now** (local file only: best quality, or a WhatsApp, Instagram, or TikTok preset; nothing is uploaded or posted; a photo stays an image and a video stays an MP4) |
| Open video / Show in folder after Studio export | **Available now** (Windows desktop; also after a detail-page export) |
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
- **Detail page:** the picture stays on the left. On a desktop window the tabs
  stay on the right, so the picture and the open tab are on one screen. A very
  narrow window may stack them. Single clip / Complete flight stays with the
  picture. Info holds the date, drone, and the other file facts together with
  rating, tags, notes, albums, rename, and flow merge. Studio sits in Share.
  Photo brightness, contrast, saturation, and warmth sit in Image (sliders, grade
  preview, and reset). Export sits in its own tab (preset, JPEG or PNG, and the
  export action). The map, coordinates, and spot download sit in Location when
  GPS exists; without GPS that tab stays hidden. One panel at a time. A video
  has no Image tab. Tab order is Info, Location, Share, Image, Export.
- **Detail-page export:** one photo or one video as a local file (best quality, or a
  WhatsApp, Instagram, or TikTok preset). Nothing is uploaded or posted. A photo
  stays an image. Brightness, contrast, saturation, and warmth
  (−100…100, neutral 0) are set on the Image tab with the Studio adjustment math
  and applied by the Export tab. Neutral keeps today's
  file, including a best-quality copy of the original bytes when that is the
  current result. A moved slider grades the pixels and then applies the preset.
  The library file is not modified. Preview approximates the exported picture
  the same way Studio preview does. The grade is saved on that photo and stays
  after leaving the page, restarting, and a rescan that can match the same file.
  Reset returns it to neutral. Best quality can be saved as JPEG or PNG. A
  neutral JPEG best-quality export still copies the original bytes when that is
  today's result. PNG and a moved slider re-encode. A video stays an MP4 from
  the Studio encoder and does not get these sliders.
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
  order; estimated runtime; optional video source start/end after Cut. Dragging the left or right edge of a video clip on the Story timeline changes that same source start or end and stays inside the file. A video
  clip can play that in/out range again, up to 8 times, at the same speed;
  the Story length, preview, and MP4 include each play. Story
  preview plays photos/videos/Title Cards in sync with the playhead. Local MP4
  export with configurable resolution and quality (desktop), including photo-only stories at
  720/1080. Title Cards persist as generated
  `studio_clips` (not media files). An optional sequential soundtrack playlist
  (up to 8 local songs) persists with the project, plays in preview, and is mixed
  into export. The whole sequential bed can start later after a project-level
  silent lead-in. Coverage is shown as time-proportional spans on the
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
  keyframe editor. The same clips can show an optional flight map: the GPS
  route already stored for that clip, and a marker that follows the clip
  clock. When OpenStreetMap tiles can be fetched they are cached locally and
  drawn under that route; otherwise the panel stays plain. Tiles are not
  bundled. The box uses the fitted picture, can be
  dragged and resized inside the frame, and is saved with the Story clip.
  The default box is a smaller undistorted square, and opacity is adjustable.
  A clip with no GPS shows an empty
  panel. This is not live tracking. A video clip can also turn on one telemetry HUD when a
  sibling DJI SRT has timed cues. It shows elapsed source time and relative
  altitude where the parser has `rel_alt`. Speed and home distance are marked
  unavailable because that parser does not record them. Gaps stay blank.
  Preview and MP4 use the same windows. This is not a goggles display or
  tracking. A selected section of a video clip can play at 0.5× or 0.25×
  (1× restores that section). The rest of the clip keeps its speed, and the Story
  gets longer by the same amount in preview and in the MP4. Source audio on a
  slowed section is muted. The effect holds the source frames; it does not invent
  frames between them, and it is not fast-forward or reverse. Media
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
  headings, time-proportional soundtrack coverage with one project-level start on that canvas,
  basic rendered visual transitions, basic per-clip image adjustment, a linear
  video saturation ramp (not a keyframe editor), timed text,
  shape, and image overlays. Zoom, blur, pixelate, and slow motion are timed bars on one Effekt lane (1×–3× zoom, rectangular masks up to 8, slow motion only at 0.5× or 0.25×; off outside the bar; photos have no lane; not tracking or a keyframe editor),
  an optional flight map (stored GPS route and synced marker on OpenStreetMap
  tiles when online, otherwise a plain panel; tiles are cached locally and are
  not bundled; the default box is a smaller undistorted square and opacity is adjustable; not live tracking), and an optional telemetry HUD on a
  video clip with a sibling DJI SRT (elapsed time and relative altitude only; not a
  goggles display or tracking; not a professional grade or NLE). A selected section
  of a video clip can use slow motion at 0.5× or 0.25× inside its Effekt-lane bar (removing the bar returns that range to 1×;
  source audio on the slowed bar is muted; not optical-flow interpolation,
  fast-forward, or reverse). A video clip's embedded audio plays in preview and in the MP4 at 1× and is shown on its own story audio lane. That bar can be dragged in time, and its edges shorten only the sound; the picture's edge handles still trim the picture. The source file is not modified. A video section repeat plays an in/out range up to 8
  times at the same speed (hard cuts, not reverse). Separately, one video
  section can repeat forward until a soundtrack with a known duration ends.
  The soundtrack plays once and does not restart or blend at each join. The last play
  is trimmed; a remainder under 0.05s is omitted. Joins are hard cuts, or an optional
  forward crossfade (0.5–2.0 s, shortened when the section is short). That crossfade
  keeps both plays moving forward. It does not match the frames, and a different
  start and end can show a double image. Unknown soundtrack duration is not guessed.

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
- Independent per-song music placement, trimming, or waveforms
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
