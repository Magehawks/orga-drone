# Product UX Discovery — End-to-end discoverability

## Status

UX_RECOMMENDED

Related issue: [#106](https://github.com/Magehawks/orga-drone/issues/106).

This is discovery only. It does not select a concept, file implementation
issues, or change application code.

## Method

**Expert-review-only.** Five moderated sessions were not recruited, so there
are no task times, completion rates, or consented quotes. Every finding below
is either:

- **Evidence** — behavior, label, or state present in the UI on branch
  `issue-86-studio-ken-burns` (commit `49b1612`), read from templates,
  `messages.json`, and the interaction scripts those screens load, or
- **Hypothesis** — a predicted first-time failure. Hypotheses are marked and
  are not treated as observed user data.

No personal library was opened. Empty, error, and success states are taken
from the templates and scripts, not from a screenshot pass. ASCII maps below
describe that UI. They are not a redesign.

Reviewed surfaces: Dashboard, Browse, media detail, World map, Library
(folder admin), Duplicates (nav only), Studio editor and project landing.
Default language in config is German (`ORGA_DRONE_LANG` default `de`).
English is the source string. Desktop primary nav shows at widths above
900px; a bottom nav replaces it at 900px and below.

## User task

A DJI/FPV hobby pilot with a few hundred local files, or a travel creator
who does not use a professional editor, needs to answer one question:

How do folders, flights, the map, and a Studio project become one shareable
memory?

The journey they are trying to complete:

```text
Import → Organize → Rediscover → Create → Share
```

Albums (#100) and a Library timeline (#101) are not in the product. This
review only says where they would sit later so they do not collide with
Studio projects or the Story canvas.

## Observed problem

The journey exists in the product, but the navigation names a different set
of objects than the journey uses. A new person meets six peers (Dashboard,
Browse, World map, Library, Studio, Duplicates) before anyone explains that
Library is folder administration, Browse is the media, a Session is a flight,
a Flow is a split recording, and a Studio project is one story.

Evidence for that split:

- Primary nav order in `base.html`: Dashboard, Browse, World map, Library,
  Studio, Duplicates. Bottom nav drops Duplicates and shortens World map to
  Map.
- The Library page title is “Manage libraries”. Its job is add / scan /
  remove folders. Media browsing is a different route.
- German catalog: Browse → “Medien”, Library → “Bibliothek”, World map →
  “Weltkarte”, bottom-nav Map → “Karte”. Session, Sessions, Flow, and Flows
  stay English. Story stays “Story”. Studio stays “Studio”.
- Grid badges say “N clips” or “N parts” (`clips` / `parts`). The words
  Session and Flow appear in filters, list columns, and stats, not on the
  badge. The only plain-language definition is on the media detail page:
  “A session groups recordings from takeoff to landing. Split flow parts
  stay together.”

## UX diagnosis

Discoverability fails at the names, not because a screen is missing.

1. **Library means three things.** The tagline is “Drone video library”
   (German: “Drohnenvideo-Bibliothek”). The nav item Library opens folder
   administration. “Ask the library” (German: “Bibliothek fragen”) searches
   media. Photos are first-class, but the tagline says video.
2. **Organize and Rediscover use insider words.** Session and Flow are
   correct domain terms and are already implemented. They are not taught
   where the counts first appear (Dashboard and Browse stats, grid badges,
   filter row).
3. **Create uses three names for one edit.** The open object is a Project
   (title field, Projects dialog). The timeline and inspector call it a
   Story. Destructive copy says Clear Studio, while the confirm says the
   clips leave “this Story” and the project remains. Favorites are a third
   selection that can also be added from inside Studio.
4. **Feedback stops at the screen that produced it.** Scan progress is a
   blocking overlay on Library and then reloads that folder table. A bad
   folder path returns to Library with no message. A Browse filter that
   matches nothing uses the same empty state as a library with no files.
   Adding one item from Browse does not say which project received it.

Studio selection grammar, the Story canvas, and the project switcher are
already specified in closed issues #32, #34, #37, and #39. This review does
not reopen them. Filter layout concepts stay in closed issue #6. What is
left is the cross-screen vocabulary.

## Design principles

- Name the object the person is holding (folder, flight, story), and keep
  the technical term in a second line when it is still useful.
- One next step after each success. Scan ends by offering media. Add ends
  by naming the project. Export already names the file.
- Do not add Albums, a Library timeline, or a new home until the current
  names stop colliding.
- Studio stays a memory editor. Do not teach it as a second library.
- German and English must name the same objects. Loanwords are fine when
  they are explained once (Studio, Story). Unexplained loanwords are not
  (Flow on a German filter).

## Current information architecture

```text
App header (desktop)
  orga-drone · “Drone video library”
  Dashboard | Browse | World map | Library | Studio | Duplicates
  Dark | Light | Custom | About | de | en

Bottom nav (≤900px) — Duplicates omitted, World map shortened to Map
  Dashboard | Browse | Map | Library | Studio

Dashboard (/)
  empty roots → Welcome + Add folder
  has roots   → Welcome + Browse media + World map
                Favorites rail, Recent rail
                if zero files: “No media yet” as well
                link: Manage library folders

Browse (/browse)                         ← rediscover media
  stats: Videos, Photos, Sessions, Flows, Roots
  Ask the library + Search + date + sort
  + drone, kind, source, GPS, Session, Flow, Favorite
  Apply / Reset · Grid | List · page size 50/100/200
  current-page checkboxes → Add selected to Studio
  per card: Add to Studio | In Studio
  empty (any cause): “No media yet” + Add folder

Media detail (/media/:id)
  Single clip | Complete flight
  metadata, favorite, tags, notes
  Studio: add or “In Studio” + Open Studio
  session/flow explanation and clip list
  missing file: “File not found on disk — check that the library folder is connected.”
  optional map + track

World map (/map)
  viewport filters the list
  zoom < 10 groups By place; zoom ≥ 10 groups By day
  “Show without location” on by default
  open item → detail (Back to map)
  no date, drone, session, or Studio action on this page

Library (/library)                       ← folder admin, not the grid
  Folder path + Browse… + optional label + Add folder
  Scan all · per row: Scan, Remove (confirm “OK?”)
  scan overlay while ?scan_job= is present
  invalid path: redirect here, no alert

Studio (/studio)
  no project → project landing (New project, list)
  open project → editor
    global header remains on desktop
    second bar: Back to Browse, project title, Projects, Export
    left: Story | Favorites, Add media from Browse, Add title card
    preview, transport, Story + Soundtrack canvas, inspector
  ≤900px: primary nav hidden and bottom nav also hidden
  Export MP4 needs the desktop save dialog
```

Dashboard, Browse, and media detail are the rediscovery loop. Library is
import. Map is a place view of the same media. Studio is create. Share is
the Export dialog plus Open video / Show in folder on Windows. There is no
Albums object and no Library timeline.

## Journey map (what exists today)

| Step | Person’s question | Screen that answers it | Gap (evidence) |
|------|-------------------|------------------------|----------------|
| Import | Did my folder come in? | Library add + scan overlay | Overlay blocks the app, then returns to the folder table. No “see the media” step. Invalid path is silent. |
| Organize | What is a flight versus a split file? | Detail “Complete flight” / session hint | Grid and filters show counts without that sentence. |
| Rediscover | Where was this, and when? | Browse dates and drone; Ask chips; Map place/day groups | No place control on Browse. Map has no date or drone. Filter miss looks like an empty library. |
| Create | Which story am I editing? | Studio project title + Projects | Add from Browse does not name the project. Clear Studio sounds global. |
| Share | Where is the MP4? | Export dialog, then Open video / Show in folder | Path is present on desktop. Browser fallback can open Studio and then be told export needs the desktop app. |
| Relive | Play it again | Detail player, map track, Studio preview | Playback works. It is not labeled as a step, which is fine. |

## Task findings

### 1. Add a folder and understand scan status

**Evidence.** Add folder posts to `/library/add`. A directory that exists
starts a scan and redirects to `/library?scan_job=…`. The overlay then shows
Scanning, Discovering media, Indexing media with “Processed {processed} of
{discovered}”, Grouping flows and sessions, then Scan completed, and reloads
Library. Scan failed stays up about 2.5s with the job error. A second scan
while one is running shows “A library scan is already running…”. The native
folder button explains when the desktop picker is unavailable.

**Evidence.** A path that is not an existing directory redirects to
`/library` with no alert (`library_add`). Remove asks `confirm('OK?')` in
English, including when the UI is German. Last scanned shows a timestamp or
Never. There is no scan indicator on Dashboard or Browse. Completion does
not navigate to Browse.

**Hypothesis.** A first-time user can start a scan and still not know when
it is safe to look at files, because success returns them to the folder
table they just filled in. A typo in the path looks like “nothing happened.”

### 2. Find a flight by date, device, and place; tell a session from a flow

**Evidence.** Browse has From/To dates, a Drone select, and Source (Drone /
Other devices). Those filters apply only after Apply, except page size,
which submits immediately. Ask the library is a deterministic DE/EN parser
(dates, video/photo, favorites, leftover words as place/search). It shows
“Interpreted as” chips. It is not a semantic search. There is no Place
select. Place is visible on the detail page as a read-only auto tag, and on
the map as group headings.

**Evidence.** Session versus flow:

| Surface | What the person sees |
|---------|----------------------|
| Dashboard / Browse stats | Bare counts labeled Sessions and Flows |
| Grid badge | “3 clips” if the session has multiple videos, otherwise “2 parts” if the flow does. Session wins when both are multi. |
| List columns | Session and Flow, or an em dash |
| Filters | “Only multi-clip sessions”, “Only multi-clip flows” (German mixes “Flows” into “Nur Mehrfach-Clips (Flows)”) |
| Detail | The one explanatory sentence, plus Single clip / Complete flight |

**Hypothesis.** “3 clips” is readable and “3 parts” is not, until someone
opens the detail hint. German users get English Flow in the filter name.
Place search will be tried in Ask or on the map; both can work, and neither
is labeled as the place tool.

### 3. Select several items and move them to Studio

**Evidence.** Checkboxes are “Select for Studio” (the accessible name does
not include the filename). They are disabled when that path is already in
the open project, and the card button reads In Studio. The bulk button
“Add selected to Studio” stays disabled until at least one box is checked.
The count hint is the number only. Bulk submit adds the current page and
flashes “Added N to Studio (M already there).” It does not name the project.
A single Add to Studio from Browse returns to Browse with no flash; the
button becomes In Studio. If no project is open, add redirects to
`/studio?msg=studio_need_project` and the landing says to pick or create a
project. The last opened project, or the newest if none was stored, opens
automatically once one exists.

**Hypothesis.** “In Studio” is clear only after the first success. Before
that, nothing on the card says the items will land in “Your story” rather
than in a new album-like set. Page-limited bulk add will surprise someone
who thinks the checkbox selects the whole filter (#101 is not required to
fix the label; the button can say “this page”).

### 4. Resume a Studio project and export an MP4

**Evidence.** Opening Studio with a project shows that project. Projects
lists others with Open, Rename, and Delete project. The title field is
labeled Project. Export is disabled with an empty story. The dialog is
“Export memory”, with resolution and filename, then Export MP4, progress,
Cancel export, and on Windows success Open video and Show in folder. Export
and the music picker state that they need the desktop app when the save
dialog is unavailable.

**Evidence.** Clear Studio sits on the Story toolbar. Its confirm is
“Remove all clips from this Story? This does not delete the project or your
files.” Delete project is a different control inside Projects and does warn
that media files stay. Desktop Studio keeps the full app header and adds a
second bar (Back to Browse, Projects, Export). At ≤900px both the primary
nav and the bottom nav are hidden, so Studio’s only way out is Back to
Browse or the logo.

**Hypothesis.** Resume and export are findable for someone who already
knows Projects and Export. The likely miss is Clear Studio, which sounds
like it deletes the project, and the narrow window, which hides every other
area.

Closed issues #32, #34, #37, and #39 already cover timeline clarity,
inspector selection versus playhead (“Now playing”), the music lane, and
the project switcher. Those controls are present. They are out of scope
here except where their names leak into the rest of the app.

### 5. Offline or missing drive (future #95)

**Evidence today, not a shipped offline catalog.** Media detail, when the
file cannot be played, says “File not found on disk — check that the library
folder is connected.” Studio marks a clip Unavailable and keeps the row.
Browse has no matching badge in the card template. #95 (preserve catalog
entries when drives are offline) is open and is not current behavior. This
review does not specify that feature.

**Hypothesis.** Until #95 exists, a disconnected drive looks like a broken
file on detail and like a gap in Browse. Copy can be shared later; the
catalog behavior cannot be promised from this UI.

### 6. Would Library albums (#100) differ from Studio projects?

**Not in the product.** Nothing in the nav, Browse, or Studio is an album.

The current Studio project is a non-destructive ordered story with a title,
cuts, and an MP4 export. Favorites are a yes/no flag, not a collection.
Folders are scan roots.

A later album should answer “which memories belong together?” and should
live under rediscovery (with Browse and, later, the timeline). A Studio
project should keep answering “how do I tell this story?”. Using one word
for both will recreate the Library/Browse collision.

Suggested pair, when #100 is specified, not built here:

| Object | Verb | Does not |
|--------|------|----------|
| Album | Collect | Reorder a timeline or export an MP4 |
| Studio project | Tell | Become the place files are stored |

### 7. Where would a Library timeline (#101) belong?

**Not in the product.** Browse already sorts and filters by date. The map
groups by day when zoomed in. Studio already has a time canvas (Fit to
story, zoom, ruler, playhead) whose job is editing.

A Library timeline should be a read-only rediscovery view under Browse:
scroll by capture date, open a flight, then add to a project. It should not
be a second editor and should not be named Timeline inside Studio. Studio’s
canvas should keep the name Story.

| | Browse timeline (later, #101) | Studio Story canvas (now) |
|--|-------------------------------|----------------------------|
| Question | What happened that day? | How long is this story? |
| Edit | No | Order, cut, transitions |
| Empty | “No media in this range” | “Your story is empty” |

## Keyboard, focus, and state notes

**Evidence.**

- `:focus-visible` draws an accent outline on the app, including bottom-nav
  links and form fields. Studio project title uses `:focus`.
- There is no skip link. The header (theme, About, language, six
  destinations) is in tab order before the page task.
- The scan overlay is `role="status"`, `aria-live="polite"`, covers the
  viewport (`pointer-events: all`), and sets `overflow: hidden`. It has no
  Cancel. Keyboard users cannot reach Browse while it is up.
- Studio transport buttons have accessible names (Play, Previous clip, Cut
  clip, and so on). The playhead is a `role="slider"` and moves with Arrow
  Left/Right, Home, and End only while it is focused. No other global
  shortcut (including Space-to-play from an unfocused preview) is registered
  in `studio.js`.
- The map container is `role="application"`. The list is a normal aside.
- Bulk checkboxes share one accessible name, “Select for Studio”.
- About, Export, and Projects use `<dialog>`. Remove-folder does not; it
  uses a native confirm with the English word OK.
- Language controls are the codes `de` and `en` inside a group labeled
  Language. Choosing one navigates home (`/`), dropping the current page.
- Empty / loading / error that are actually distinct: scan phases and scan
  failure; Studio “Your story is empty” versus “No Studio projects yet”;
  map “No GPS media in this area” and “Loading…”; detail missing-file hint;
  Studio Unavailable. Browse does not distinguish no files from no filter
  matches. Library does not distinguish a rejected path from a quiet form.

## Terminology (DE / EN) that affects the journey

| English source | German catalog | Risk |
|----------------|----------------|------|
| Browse | Medien | Clearer than Browse. Desktop English still says Browse. |
| Library | Bibliothek | Sounds like the media. The page is folder admin. |
| Ask the library | Bibliothek fragen | Sounds like the folder page. |
| World map / Map | Weltkarte / Karte | Two names for one destination. |
| Session / Flow | Session / Flow | Unexplained on first sight. German does not translate Flow. |
| clips / parts | Clips / Teile | Badge text. “Teile” does not say split recording. |
| Studio / Story / Project | Studio / Story / Projekt | Three labels, one edit. |
| Clear Studio | Studio leeren | Sounds larger than “clear this story”. |
| Drone video library | Drohnenvideo-Bibliothek | Hides photos. |
| In Studio | Im Studio | Does not name the project. |

## Concept A — Rename the current rooms

Keep every route. Change the words and the one-line explanations.

```text
Header
  Dashboard | Media | Map | Folders | Studio
  (Duplicates moves under Folders. Not a sixth peer.)

Folders (today’s /library)
  Title: Folders
  After a successful scan: [Browse media] beside the folder row
  Bad path: alert “That folder was not found.”
  Remove: translated confirm that names the folder

Media (today’s /browse)
  First-visit note, dismissible, three lines:
    Folder — where files are scanned
    Session — one flight, takeoff to landing
    Flow — one recording split into parts
  Badges: “3 clips · session” or “2 parts · flow”
  Empty library ≠ empty filter (Reset on the filter empty only)
  Add selected: “Add this page to {project title}”

Studio
  Clear story   (same action as today’s Clear Studio)
  In-project chip on Media cards: “In {project title}”
  Narrow width: keep Back, and add Map + Folders as text links
  so Studio is not a dead end under 900px
```

**Benefits.** Matches the journey without moving pages. German can translate
Folders → Ordner, Media → Medien (already the Browse translation), Map →
Karte. Session/Flow stay, with a glossary line.

**Drawbacks.** Dashboard and Media still overlap (recent and favorites live
on Dashboard). Five destinations remain. People who learned “Library” in
docs and issues need the old word mentioned once (“Folders, previously
Library”).

**Complexity.** Copy, nav labels, empty states, one post-scan link, badge
text. No new models.

**Scope risk.** Low if Duplicates only moves and no album or timeline UI is
added. Medium if the glossary becomes a tour.

## Concept B — Make Media the home

```text
Header
  Media | Map | Studio

Media page
  top: recent + favorites (today’s Dashboard rails)
  then the current filters and grid
  menu on that page: Folders · Duplicates
  later, same menu, not now: Albums (#100) · Timeline (#101)

Studio
  unchanged editor
  Back goes to Media
  Projects stays the list of stories
```

Dashboard `/` redirects to Media, or remains a thin first-run screen only
when there are zero folders.

**Benefits.** The nav matches Import (inside Media → Folders), Rediscover
(Media and Map), and Create (Studio). Albums and a timeline have an obvious
parent later. Narrow Studio only has to return to Media.

**Drawbacks.** Dashboard fans lose a tab. Docs, deep links, and the current
“Welcome” hero move. Larger than a copy change, still no new capability.
First-run must not become a blank grid with no Add folder.

**Complexity.** Route and layout merge of Dashboard into Browse. Higher
regression surface (filters, return-to-browse, stats).

**Scope risk.** Medium. Easy to “improve” into a new home and delay the
copy fixes. Do not start this until Concept A’s names are accepted.

## Recommendation

Prefer **Concept A** as the next product decision. The collision is the
vocabulary and the missing next step, and Concept A fixes that on the
screens that already exist. Concept B is the cleaner long-term map and
should wait until PM wants Media to be the home. Neither concept builds
#100 or #101.

Do not rename Studio’s Story canvas to Timeline. That name stays reserved
for a future Browse view (#101).

## Smallest later slices

These are proposals for PM to file after choosing a concept. This review
does not open them.

| ID | Slice | Journey | Depends on | Do not include |
|----|--------|---------|------------|----------------|
| P0-a | Nav labels: Media, Map, Folders; move Duplicates under Folders; one glossary line for session vs flow; badges say session or flow | Rediscover | Concept A accepted | New pages, albums, timeline |
| P0-b | Scan handoff: “Browse media” when a scan completes; alert when the path is not a folder; translated remove confirm | Import | None | Incremental scan, progress on every page |
| P0-c | Name the open project on Add / In Studio / bulk flash; rename Clear Studio to Clear story; say “this page” on bulk add | Create | None | Project picker on every card, multi-select across pages |
| P0-d | Browse empty state: no folders vs no matches, with Reset on the latter | Rediscover | None | New filters (#6 stays the filter-layout reference) |
| P1-a | Place: a read-only place chip on Browse using the place already stored on the item, linking to the map | Rediscover | P0-d so a miss is not “no media” | New geocoder, map filters for date/drone |
| P1-b | When specifying #100, one comparison sentence in Folders and in Projects: album collects, project tells | Organize vs Create | #100 product spec | Building albums in the discoverability slice |
| P1-c | When specifying #101, place it under Media as a read-only date view; keep the Studio canvas named Story | Rediscover vs Create | #101 product spec | Editing on that timeline |
| P1-d | After #95, reuse the detail “folder connected” sentence on Browse and Studio for missing files | Relive | #95 behavior | A new offline product in this slice |
| P1-e | Skip link; include the filename in “Select for Studio”; do not hide every destination inside narrow Studio | Accessibility | P0-a if nav labels change | A shortcut cheat-sheet, NLE keybindings |

P0-a through P0-d are independent enough to ship separately. P0-a is the
one that makes the others understandable.

## Priority

| Finding | Severity | How often (hypothesis) | Effort | Journey |
|---------|----------|------------------------|--------|---------|
| Library / Browse / Ask name collision | P0 | Every first session | Small copy | Import and rediscover |
| Session vs flow unlabeled; Flow untranslated in German | P0 | Every multi-clip flight | Small copy | Organize |
| Studio add and Clear Studio do not name the story | P0 | Every create session | Small copy | Create |
| Filter miss and bad path look like silence or an empty library | P0 | Whenever search fails | Small | Import and rediscover |
| Scan success does not lead to the media | P1 | Every new folder | Small | Import |
| Map vs World map; Duplicates as a peer; narrow Studio has no nav | P1 | Narrow windows; first look at the header | Small | All |
| Place only via Ask or the map | P1 | Place-based recall | Medium if it grows past a chip | Rediscover |
| Offline catalog | P1, blocked | Unplugged drives | Belongs to #95 | Relive |
| Albums vs projects, Library timeline vs Story | P1 later | When those issues start | Spec only now | Do not build here |

Frequency is a hypothesis. Severity is from task blockage in the current
UI, not from a user count.

## Explicit non-scope

- No implementation in this issue.
- No wholesale redesign, no new theme, no onboarding tour with more than
  the three glossary lines in Concept A.
- No albums, no Library timeline, no plugins, no cloud share, no AI
  labeling of Ask.
- No change to session/flow grouping rules, scan architecture, or Studio
  editing (cut, transitions, masks, framing, music, export encode).
- No rework of filter layout (#6), Story canvas behavior (#32), inspector
  selection (#34), music lane (#37), or the project switcher mechanics
  (#39).
- No claim that #95, #100, or #101 already ship.

## CTO questions

- Can “In {title}” and the bulk flash use the open project title already
  loaded for Browse, without a new query per card?
- Confirm invalid `/library/add` is only a redirect today, so an error
  flash is a small route change.
- Confirm Clear Studio is story-scoped in the data model (it is in the
  confirm copy) so a rename does not imply a schema change.
- Narrow Studio hides both navs because `.studio-app` sets
  `.bottom-nav { display: none }` and the 900px rule hides `.primary-nav`.
  A text-link escape should not reintroduce the full header inside the
  editor.
- German catalog lives in `messages.json`. Flow, Session, and Story are
  currently identical to English. Any rename has to land in both catalogs
  in the same slice.

## Handoff

PM selects Concept A, Concept B, or a smaller cut of A (labels only). CTO
reviews feasibility after that selection. Do not start implementation from
this document. Do not file the slices above from this role.

## Related issues

| Issue | How this review uses it |
|-------|-------------------------|
| #6 (closed) | Filter layout research. Not repeated. Empty-state and Apply remain the discoverability notes. |
| #32, #34, #37, #39 (closed) | Studio timeline, inspector, music lane, project switcher. Treated as shipped. Only cross-app names (Clear Studio, In Studio) are in scope. |
| #95 (open) | Offline catalog. Current UI only has the detail missing-file sentence and Studio Unavailable. |
| #100 (open) | Albums are not shipped. Keep them off the Studio project. |
| #101 (open) | Library timeline is not shipped. Put it under Media later. Do not rename the Story canvas. |
