# Discovery: Find specific scenes in archived video without cloud upload

- **Issue:** [#102](https://github.com/Magehawks/orga-drone/issues/102)
- **Date:** 2026-10-24
- **Status:** Discovery only. No implementation commitment.
- **Tree checked:** `issue-86-studio-ken-burns` at `49b1612`

## Question

How can a small creator team, or a drone / action-camera videographer, locate a
specific scene inside archived local video without uploading that video to a
cloud service?

## Method

No interviews were run for this note. The Reddit thread cited on the issue
(`r/VideoEditors`, “how are you organizing and searching massive…”) did not
return post text from this environment (network security block), so this note
does not quote it.

The issue states the external problem as multiple multi-terabyte disks and
difficulty locating specific footage from old projects. The five queries below
are **representative retrieval tasks** for that problem and for the audience
named on the issue. They are not transcripts and not a user study.

Each query was checked against the current Browse / Ask path, not against a
proposed index:

- Rule-based Ask parser: `src/orga_drone/search/__init__.py` (`parse_natural_query`)
- Browse filters and the same list query: `src/orga_drone/app.py` (`/browse`, `POST /api/search`)
- What text match covers: `Database._media_list_filters` in `src/orga_drone/db/__init__.py`
- File metadata, sessions, flows, user notes: schema and scan/group code cited below

Ask the library is a **deterministic DE/EN phrase parser**. It is not a model
and it does not search embeddings. This note does not call that parser AI.

## What retrieval exists today

Search returns **library files** (and, after Browse collapse, often only the
first clip of a multi-video session or flow). It does not return a timestamp
inside a file.

| Signal | Available now | Limit |
| --- | --- | --- |
| Recorded date | From / To filters. Ask reads a year, a month name plus year, or an ISO date. | File `recorded_at` only. A scene in the middle of a long file has no date of its own. |
| Place | Offline reverse geocode of **one GPS point** per file (photo EXIF, video header, or SRT start) into `place_json` and auto-tags (city, district, region, country, plus `YYYY` and `YYYY-MM`). Ask turns leftover words into the same text match. | The flight path in `track_json` is not searched. A place flown over later in the clip is invisible unless that word is in the filename, path, tags, or notes. |
| Tags and notes | User tags and free-text notes on the detail page. Text search matches them. Ask also maps vacation / holiday / trip / Urlaub / Reise onto tag tokens. | Empty until a person types them. Notes are per file path, not per timestamp. |
| Favorites and stars | Favorite filter. Ask recognizes favorite / Favorit. Stars are a sort, not a query phrase. | They mark a file the user already chose. |
| Device | Drone dropdown is an exact `drone_model` match. Source is drone vs other. A drone name typed into Ask or Search can match `drone_model` by substring. | `camera_model` is stored and shown on the detail page. It is **not** in the text-search columns and **not** in the drone dropdown. |
| Sessions | Heuristic flight groups: soft gap 3 minutes, hard gap 20 minutes, plus optional SRT altitude / GPS hints (`src/orga_drone/group/sessions.py`). Browse can keep multi-clip sessions or single clips. Detail “Complete flight” plays the clips in order. | Session title is generated from the first filename and **rebuilt on every rescan**. It is not user-edited and not part of text search. Ask has no session phrase. |
| Flows | FAT32 split parts of one recording. | Same collapse rule as sessions: search hits on a later part can disappear (see below). |
| Albums | Not in this tree. | Roadmap lists library albums as a possible later library feature. Studio projects are edit projects, not albums, and are not a scene index. |
| Map | GPS point and track for exploration. | Does not answer “what is in the frame”. |

Text search (`q`, and Ask’s effective text) is a substring match, all tokens
required, against filename, path, `drone_model`, user tags, notes, auto-tags,
and `place_json`.

**Collapse gap.** For a session with more than one video, Browse keeps the
row at session position 0 (photos still show). The text predicate is applied
to that same row. A tag or note that exists only on a later clip in the
session does not surface the session. The same pattern applies to a later
part of a multi-clip flow when the session collapse does not apply.

**Studio is not a scene index.** A Story clip can store `source_start` /
`source_end` so an export uses part of a file. Those offsets belong to one
local edit project. Browse does not search them, and they are not labels for
the library.

## Five representative queries

Expected results assume the files are already imported by a full folder scan.
“Solved” here means the user can land on the right **file or flight**. A
scene timestamp is called out separately.

### 1. June 2024 Malta flights on the Avata

**Query:** videos from the June 2024 Malta trip, shot on the Avata.

**Expected result:** video files with `recorded_at` in June 2024, place text
Malta (or a folder / filename / note that says Malta), and drone model
matching Avata.

**Today:** Ask `videos June 2024 Malta` sets kind=video, date bounds
2024-06-01..2024-06-30, and text token `Malta`. The drone dropdown, or the
extra token `Avata` in Search / Ask, matches `drone_model`. Place matches
only if offline geocode, the path, or a note contains Malta.

**Verdict:** Solved at **file** level when that place text exists. The result
is the flight files, not a moment inside them.

### 2. The sunset clip I already marked

**Query:** the favorite clip I tagged sunset.

**Expected result:** files with favorite set and `sunset` in user tags, notes,
filename, or path.

**Today:** Favorite filter (or Ask `favorite`) plus Search `sunset`. Ask does
not treat “sunset” as a special word; it becomes ordinary text match, which
is enough if the user already wrote it. An unlabeled sunset frame inside a
long flight does not match.

**Verdict:** Solved at **file** level **after** a person labeled that file.
Not a way to discover an unlabeled scene.

### 3. The middle of the coastal flight, not the split card parts

**Query:** the continuous coastal flight, in clip order, without treating
each FAT32 part as a separate memory.

**Expected result:** one heuristic session (takeoff to landing) whose split
parts stay in one flow, opened as Complete flight so the user can scrub in
order.

**Today:** Session grouping and flow grouping do this when timestamps (and
optional SRT) fit the gaps above. Browse “Only multi-clip sessions” narrows
the list. There is no session name to search, and no control that means
“the middle minute”.

**Verdict:** **Partial.** The flight group can be found. A scene inside it
cannot.

### 4. The lighthouse entering the frame

**Query:** about 40 seconds in last year’s coastal video, starting when the
lighthouse comes into frame.

**Expected result:** one file and a start time.

**Today:** Year plus a place or path token can list candidate files. Nothing
indexes frame content. `track_json` is telemetry, not a picture of a
lighthouse. A note such as `lighthouse 00:02:14` is searchable as text and
returns the **file**; the detail player does not seek to that note. A Studio
cut can hold the range only inside a story the user already built.

**Verdict:** **Not solved.**

### 5. The price discussion on the March GoPro card

**Query:** the interview moment where the price is discussed, on the GoPro
card from the March job, somewhere in a multi-terabyte archive.

**Expected result:** a spoken span inside one file.

**Today:** A March date filter works. Source “Other devices” separates
non-drone files. The word GoPro matches only if it appears in filename, path,
`drone_model`, tags, notes, auto-tags, or place — not in `camera_model`.
Speech is not indexed. Albums do not exist; a folder name in the path is the
closest project grouping.

**Verdict:** **Not solved.** This is archive speech search. It is the generic
media-library scope the issue says to avoid.

### Score

| Level | Queries |
| --- | --- |
| File, with data the scan or the user already stored | 1 and 2 |
| Flight group only | 3 |
| Scene inside a file | none (4 and 5 fail) |

Albums could not be used. Device helps for drones. An action-camera model
string does not.

## Options the issue asked to compare

### Manual scene bookmarks

A person marks a file, a time, and a short label. Later, text search finds
that label and the player opens at that time.

- **Finds unlabeled pictures or speech:** No. It only recalls moments someone
  already marked.
- **Privacy:** The label and a number of seconds would sit in the local
  SQLite index, same trust boundary as notes. No frames copied, no upload.
- **Performance:** One small row per mark. No transcode and no pass over
  multi-terabyte video. Opening a mark is a seek in the existing player.
- **Fit:** A library memory pin. It is not a Studio cut and not an album.
  It does **not** answer the cold-archive problem in queries 4 and 5.

Typing the same label into today’s notes is a weaker version of this: search
finds the file, and the user seeks by hand. Collapse can hide that note when
it lives on a later clip of a multi-video session.

### Local model index (embeddings or transcription)

A local index of frames or speech, with no cloud upload.

- **Finds unlabeled pictures or speech:** Only after a decode and index pass,
  and only for the kinds of similarity or words that pass covers. It still
  fails quietly on anything the model misses.
- **Privacy:** Pixels or transcripts would be read and stored as derived data
  on disk. Weights are a large local download. “Local” avoids upload; it does
  not avoid a second copy of content-derived data.
- **Performance:** A first index of multi-terabyte video is a long CPU/GPU
  job and extra disk. The library scan is already a full rescan per root, so
  repeating that work on every scan fights the current cost model.
- **Fit:** Out of scope for this issue. The roadmap already places semantic
  search in Later, and not as product identity. Shipping it would move Orga
  Drone toward a general media archive.

## Recommendation

**No-go.** Do not build scene search, embeddings, a local model index,
speech transcription, cloud search, or transcoding for search.

Dates, places, tags, drone, sessions, and notes already answer file and
flight questions when the user can name a date, a place, a device, or a
label they wrote. They answer **none** of the scene-level queries. The pain
on the issue is footage the person has **not** already labeled inside large
local disks. Manual bookmarks miss that pain; they solve a different job
(“open a moment I marked”). Leave bookmarks unscheduled. Albums, if they are
specified later, would still be file sets, not scenes.

**Privacy of this no-go:** search stays on the local index and on text the
user typed. No frames or files are sent away for search.

**Performance of this no-go:** no extra index and no decode pass on top of
the full rescan.

Adjacent file-level gap, not a scene feature and not a request to build it
here: `camera_model` is visible on the detail page and omitted from Browse
text search, so action-camera bodies are harder to filter than drones.

## Workaround with the current app

1. Narrow Browse by From / To, drone, source, GPS, and favorite.
2. Use Ask for short phrases such as `videos June 2024 Malta` or
   `favoriten 2024`. Read the “Interpreted as” chips; the parser is rules,
   not a description of the picture.
3. Use Search for filename, folder, drone model, tags, notes, and place.
4. If a moment matters, write a label and a timecode in that clip’s notes,
   on the clip Browse will actually show (session position 0, or a photo).
   Search the label, then seek in the player.
5. Use the map and Complete flight to scrub a known flight in order.
6. Use Studio Cut only when the goal is a story export, not library recall.

## Non-goals (this issue)

- No embeddings, model indexing, or transcription
- No cloud upload or cloud search
- No video transcoding for an index
- No new Browse behavior, schema, or tests in this change
