# Studio UX Concept

**Status:** Concept only — not implemented. Do not treat this document as Available
product behavior.

**Audience:** Product and engineering contributors before writing further Studio code.

**Related:** [`PRODUCT_VISION.md`](PRODUCT_VISION.md), [`ROADMAP.md`](ROADMAP.md),
ADR 0001 / 0002 (Studio persistence and order/duration).

---

## 1. Product philosophy

orga-drone is not a professional video editor.

It helps people transform adventures into memories they can easily relive and
share. Studio is where a **story** is created — not where files are managed.

### Story First Editing

Instead of opening a timeline, users begin with their **story**.

They arrange moments, name chapters, and only enter editing when something needs
a precise change. The timeline is a tool for exceptions, not the default home.

**Litmus test:** If a new contributor opens Studio and their first thought is
“Where are the editing tools?”, the UX has failed. Their first thought should
be: “What story do I want to tell?”

### Design principles

| Principle | Meaning in Studio |
|-----------|-------------------|
| Story before editing | Story Mode is default; Edit Mode is opt-in |
| Defaults before configuration | Sensible durations, one music slot, few choices |
| Memories before files | Labels, sessions, chapters — not paths and codecs |
| Simple before powerful | Hobby users first; pro NLEs stay for pro work |
| Local first | Create and export on the user’s machine |

### Inspiration (not copies)

- **iMovie:** approachable defaults, story-friendly language
- **DaVinci Resolve:** clear structure (preview / tracks / inspector)
- **orga-drone identity:** flight sessions as first-class story blocks; drone
  adventure language; never a clone of either tool

### What Studio must not become

Premiere, DaVinci, CapCut, Final Cut — feature-heavy NLEs. No endless tool
palettes, no multi-track complexity as the entry experience, no “pro” identity.

---

## 2. User journey

```text
Adventure
    ↓
Capture
    ↓
Library          (import, scan, organize)
    ↓
Browse           (rediscover: search, map, favorites, sessions)
    ↓
Studio           (create the story)
    ↓
Share            (export / hand off a file friends can open)
    ↓
Relive
```

### How users arrive at Studio

1. In **Browse** or **Detail**, select memories (today: add items; later: sessions
   as wholes).
2. Open **Studio**.
3. Land in **Story Mode** — “I am creating something.”
4. Optionally enter **Edit Mode** for one block.
5. **Export** / share the result.

### Emotional target

| Wrong feeling | Right feeling |
|---------------|---------------|
| “I am managing media.” | “I am telling my story.” |
| Another Browse grid with Remove | A workspace with chapters and a destination |
| Timeline anxiety | Story first; timeline only when needed |

---

## 3. Story Mode (default)

First screen after opening Studio. No visible timeline. No editing complexity.

### Purpose

Answer: **What is my story made of, and in what order?**

### Primary objects

- **Story** — the whole piece (title, estimated duration, music, export)
- **Story block** — a chapter or beat (media, session, or group)
- **Music** — optional single soundtrack (concept; not Available today)

### Example (conceptual)

```text
Summer Vacation 2026                         Est. 00:12:40

  ☀  Arrival              4 photos · 0:12
  🚁  Flight Session      12 clips · 08:34
  🏖  Beach                6 photos · 0:18
  🌅  Sunset               1 video · 01:02
  🎵  Music                Soft acoustic · 03:00 (loop/trim later)

  [ Play story ]                    [ Export Story ]
```

### User can

- Reorder story blocks (drag)
- Rename story blocks
- Add / remove media (or whole sessions) into blocks
- Play a rough story preview (concept)
- Export the story

### User should not see by default

- Multi-track timeline
- Keyframes, effects racks, color wheels
- File paths as primary labels
- A grid that only says “Remove”

### Relationship to today’s implementation

**Available now** is closer to a flat ordered list of media cards with duration
estimates. Story Mode is the **target UX** that reframes that list as chapters
and sessions — not another Browse page.

---

## 4. Edit Mode

Entered only when the user needs precision.

### Entry

- Double-click a story block, or
- Explicit **Edit** control on a block

### Exit

- Done / Back to story — returns to Story Mode with changes kept for that block

### Layout (target)

```text
+------------------------------------------------------------------+
|  ← Story   |  Block: Flight Session          |  [Export]         |
+------------------------------------------------------------------+
|                                                                  |
|                     LARGE PREVIEW                                |
|                                                                  |
+------------------------------------------------------------------+
|  VIDEO |====|====|====|====|====|====|====|====|====|====|====| |
|  AUDIO |~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~| |
+------------------------------------------------------------------+
| Toolbar: Split · Music · Transition · Title · Export             |
+---------------------------+--------------------------------------+
|                           |  Inspector                           |
|                           |  duration · transition · title …     |
+---------------------------+--------------------------------------+
```

### Tracks (minimal)

| Track | Role |
|-------|------|
| One video track | Clips / photos in this block (or expanded session) |
| One audio track | Optional music / keep source audio policy (product later) |

No nested compound timelines for MVP-era Edit Mode.

### Inspector (right)

Only properties for the **selected** item: duration (photos), transition in/out,
title text (later), mute/source audio (later). Defaults preferred over dense forms.

---

## 5. Wireframes (ASCII)

### 5.1 Story Mode — empty

```text
+------------------------------------------------------------------+
| Studio                                      [ Browse ] [ Export ]|
+------------------------------------------------------------------+
|                                                                  |
|              Your story is empty                                 |
|                                                                  |
|   Add memories from Browse, or drop a flight session here.       |
|                                                                  |
|              [ Go to Browse ]                                    |
|                                                                  |
+------------------------------------------------------------------+
```

### 5.2 Story Mode — with blocks

```text
+------------------------------------------------------------------+
| Studio · Summer Vacation 2026          Est. 00:12:40  [Export]   |
+------------------------------------------------------------------+
|                                                                  |
|  ≡  ☀ Arrival ..................................... 0:12  [Edit] |
|  ≡  🚁 Flight Session · 12 clips .................. 08:34 [Edit] |
|  ≡  🏖 Beach ....................................... 0:18  [Edit] |
|  ≡  🌅 Sunset ...................................... 01:02 [Edit] |
|                                                                  |
|  🎵 Music · none yet ....................... [ Add music ]       |
|                                                                  |
|  [ Play story ]                                                  |
+------------------------------------------------------------------+
| Hint: Drag ≡ to reorder. Double-click a block to edit.           |
+------------------------------------------------------------------+
```

### 5.3 Edit Mode — session expanded

```text
+------------------------------------------------------------------+
| ← Story | Flight Session (12 clips)              [ Done ][Export]|
+------------------------------------------------------------------+
| Preview                                                          |
| +--------------------------------------------------------------+ |
| |                                                              | |
| |                    [ playing clip 3/12 ]                     | |
| |                                                              | |
| +--------------------------------------------------------------+ |
+------------------------------------------------------------------+
| V |--1--|--2--|--3*--|--4--|--------------|--12--|               |
| A |~~~~~~~~~~~~~~~~ music ~~~~~~~~~~~~~~~~~~~~~~~|               |
|     Split   Music   Transition   Title   Export                  |
+----------------------+-------------------------------------------+
| Clips                | Inspector                                 |
| 1 DJI_0001  0:42     | Clip 3                                    |
| 2 DJI_0002  0:38     | Duration 0:41 (read-only video)           |
| 3 DJI_0003  0:41 ◀   | Transition: Fade                          |
| ...                  |                                           |
+----------------------+-------------------------------------------+
```

### 5.4 Export affordance (Story Mode)

```text
+--------------------------------------+
| Export Story                         |
| Format: MP4 · 1080p · 30fps (fixed)  |
| Transition: Fade ▾                   |
| [ Cancel ]              [ Export ]   |
+--------------------------------------+
```

(Export details are product-spec territory; this UX only shows **where** export
lives: Story Mode primary CTA, Edit Mode secondary.)

---

## 6. Interaction flow

```text
Browse / Detail
    │  Add to Studio (item or session)
    ▼
Story Mode
    │
    ├─ Reorder blocks (drag)
    ├─ Rename block
    ├─ Add / remove media in a block
    ├─ Play story (rough)
    ├─ Add music (optional)
    ├─ Export Story ──────────────────► Share / open file
    │
    └─ Edit (double-click / Edit)
            ▼
        Edit Mode
            │  Split · Transition · Title · Music · Preview
            │  Done
            ▼
        Story Mode (updated block)
```

### Gesture summary

| Action | Story Mode | Edit Mode |
|--------|------------|-----------|
| Reorder | Drag block handle | Drag clips on video track |
| Open detail editing | Double-click / Edit | — |
| Back | — | Done → Story |
| Export | Primary button | Toolbar Export |
| Expand flight session | Double-click block (or expand control) | Already clip-level if expanded |

---

## 7. Flight Session concept

Flight sessions are a **unique orga-drone strength**. They must feel first-class
in Studio, not like a bag of anonymous files.

### Default: one story block

A complete flight session enters Story Mode as **one block**:

```text
🚁 Flight Session
   12 clips · 08:34
```

Users can tell “the flight” as a single beat in the vacation story without
managing twelve cards.

### Expand

Double-click (or explicit expand) opens the session into **individual clips**
inside Edit Mode (or an expanded Story sub-list — prefer Edit Mode for clip
surgery).

Collapse returns to one block; clip-level edits (split, order within session)
persist when collapsed where possible.

### Why this matters

- Matches how pilots remember flights (one takeoff → landing)
- Differentiates orga-drone from generic photo story apps
- Reduces Story Mode clutter for multi-clip sessions

### Relationship to Library / Browse

Sessions remain defined by library heuristics. Studio **references** a session
as a block; it does not redefine flight detection.

---

## 8. Timeline concept

The timeline appears **only in Edit Mode**.

### Constraints (by design)

- One video track
- One audio track
- No nested sequences for early Studio
- Photos use planned duration (Studio duration); videos use source duration
- No multi-layer composites, no effect stacks as default UI

### Mental model

```text
Story Mode  = outline of chapters (blocks)
Edit Mode   = fine cut of one chapter (timeline)
```

The timeline is subordinate to the story outline. Users should never be forced
to “learn the timeline” to export a simple memory reel.

### Scrubbing / playhead

Simple playhead over the single video track; preview follows playhead. No
multi-viewer complexity.

---

## 9. Toolbar philosophy

**Less is the brand.**

Edit Mode toolbar contains only:

| Tool | Intent |
|------|--------|
| **Split** | Cut at playhead |
| **Music** | Attach / replace the one soundtrack |
| **Transition** | Fade / crossfade between adjacent items |
| **Title** | Simple on-screen text (later-friendly) |
| **Export** | Leave Edit Mode path to share |

### Explicitly out of the toolbar

Color wheels, speed ramps, keyframes, generators, multi-cam, captions suites,
third-party effect browsers, “more tools” overflow that becomes a second NLE.

If a tool is not needed for a hobby story export, it does not belong on the bar.

### Story Mode chrome

Even leaner: story title, estimate, Play, Export, add music. Editing verbs wait
for Edit Mode.

---

## 10. Future roadmap (UX sequencing)

Ordered so each step still feels like Story First Editing. Labels match
product status language — **none of this is a shipping claim**.

| Stage | UX outcome |
|-------|------------|
| **A — Reframe (near)** | Story Mode layout over today’s ordered list: chapter titles, session blocks, Play/Export affordances (even if Play/Export are stubs) |
| **B — Sessions as blocks** | Add whole flight session as one block; expand to clips |
| **C — Edit Mode v1** | Preview + one video track + Split + photo duration; Done back to Story |
| **D — Export** | Story Mode “Export Story” → local MP4 (see export product specs) |
| **E — Music** | One optional track; Audio row in Edit Mode |
| **F — Transitions / Title** | Fade/crossfade + simple title in inspector/toolbar |
| **G — Play story** | Rough continuous preview in Story Mode |
| **Later** | Polish, more share destinations, never pro-NLE feature parity |

### Implementation progress

| Slice | Status |
|-------|--------|
| **A1 — Story Mode shell reframe** | Done in tree (UI/copy/layout only): Story Mode label, “Your story”, vertical story blocks, quieter remove, no Play/Export stubs. Persistence/reorder/duration unchanged. |
| A2+ (sessions-as-blocks, Edit Mode, …) | Not started |

### Guardrails for future PRs

1. New Studio UI must answer: “Does this help tell a story?” not “Does this look
   like Browse?”
2. Do not ship timeline-first navigation.
3. Do not add toolbar items without removing or justifying scope.
4. Challenge specs that skip Story Mode or treat Studio as a second library.
5. Keep Available vs target language honest in README / vision when slices land.

---

## Appendix: Contrast with current Studio UI

| Current (technical MVP) | Target (this concept) |
|-------------------------|------------------------|
| Flat media cards | Story blocks / chapters |
| Remove as primary action | Reorder, rename, Edit, Export |
| Feels like Browse | Feels like Create |
| Order + duration estimate | Story outline + estimate + modes |
| No session-as-block | Flight session = one block by default |
| No Edit Mode | Timeline only after Edit |

This gap is intentional: pause implementation, align on UX, then build toward
Story First Editing in small complete slices.
