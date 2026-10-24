# Browse retrieval audit

Issue [#104](https://github.com/Magehawks/orga-drone/issues/104). Grounded in the
current Browse, World map, detail, and Dashboard UI. This is a validation of
paths that already exist. It does not add a second filter system, a scene
search, or a new map.

Five retrieval tasks are walked below. One predicate bug is fixed in this
change. The other gaps stay documented so Browse is not redesigned from an
audit.

## Surfaces a person can use today

| Goal | Control | Where |
| --- | --- | --- |
| Phrase | Ask the library | Browse form. Rule parser in `src/orga_drone/search/__init__.py`. Placeholder: “videos from Malta vacation, photos November 2025”. |
| Name, tag, note, place text | Search | Same form. Placeholder: “Filename, tags, notes…”. |
| When | From / To, and month or year inside Ask | Date inputs, or phrases such as “photos November 2025”. |
| Aircraft | Drone dropdown | Exact `drone_model` values already in the library. Separate Source dropdown: Drone or Other devices. |
| On a map | World map | Markers for files with both latitude and longitude. List toggle “Show without location”. |
| A flight | Session badge and Session filter | Multi-clip sessions collapse to one Browse row. The filter is only “multi-clip” or “single-clip”. There is no session list. |
| A memory | Favorite, stars, notes, tags | Dashboard Favorites links to `/browse?favorite=yes`. Tags and notes are edited on the detail page. |

Ask and the explicit fields are combined in the Browse handler
(`merge_search` in `app.py`). An explicit kind, date, or Search box wins over
the same field parsed from the phrase. The text that actually runs is
`effective_q()`: Search words, place words, and tag words, AND-ed. Each word
must occur in the filename, path, drone model, user tags, notes, auto tags, or
place JSON (`db._media_list_filters`).

Auto tags written at scan time are the year, `YYYY-MM`, and, when both
coordinates exist, the offline city, district, region, and country
(`auto_tags.py`, `geocode`). They are not a description of the scene.

## Task 1 — Sunset at the lake

**Result: fail**, unless the person already wrote those words into tags or notes.

Phrase tried: `sunset at the lake`.

| Parsed field | Value |
| --- | --- |
| kind, dates, favorite | empty |
| place and free text | `sunset at lake` |
| text that is queried | `sunset at lake sunset at lake` |

“the” is a stopword. “at” is not, so the library must contain the substrings
`sunset`, `at`, and `lake`. Place and free text are the same words, so each
word is required twice; that does not change the match. Nothing in the scan
stores time of day or a scene. A lake flight is findable when the offline
place name contains “lake”, or when the person tagged it. The map cannot be
asked for a sunset. It only shows coordinates.

Success path that already works: open the file once, put `sunset` and `lake`
in Tags or Notes, then use Search. That reuses the existing text match.

## Task 2 — Vacation in a known place (Malta)

**Result: partial.** A place name works. The English vacation example in the
placeholder does not, unless both language tags are stored.

| Phrase | What Browse requires |
| --- | --- |
| `videos from Malta` | kind video, and the substring `malta` (place JSON, auto tag, filename, notes, or user tag) |
| `photos November 2025` | kind photo, recorded date inside November 2025 |
| `videos from Malta vacation` | kind video, and all of `malta`, `vacation`, and `urlaub` |

The English word “vacation” is stored as the tags `vacation` and `urlaub`
(`parse_natural_query`). Those tags are AND-ed with the place, not offered as
alternatives. A file whose offline country is Malta, with no user tag, matches
“Malta” and misses “Malta vacation”. The German phrase “malta urlaub” matches
a file tagged `malta` and `urlaub`, which is what `tests/test_search.py`
covers today.

The World map does not search by country. Zoomed out, “By place” groups are
rounded coordinates (`placeKey` in `worldmap.js`), not the city name. The city
is visible as read-only auto-tag chips on the card and on the detail page.
Those chips are not filters.

Success path: Search `Malta`, or Ask `videos from Malta`, after a scan that
had GPS. Add a user tag only when the place name is missing.

## Task 3 — This aircraft

**Result: success** from the Drone dropdown. Ask is the weaker path.

The dropdown lists `distinct_drones()` and filters with `drone_model = ?`.
Source “Drone” versus “Other devices” is a separate switch on `source_type`.
The detail page also shows Camera. Camera is not a Browse filter.

Ask `Avata 2` does not select the dropdown. It becomes a text search for
`avata` and `2`. The digit matches many filenames. Use the dropdown.

Files with an empty drone model show an em dash on the card and are not listed
in the dropdown. They can still be separated with Source when `source_type`
was set at scan time.

## Task 4 — The favorite flight

**Result: partial.** A heart on one file works. A heart on “the flight” does
not.

Dashboard Favorites and Browse “Favorites only” use the same favorite flag on
the media row. Multi-clip sessions are collapsed to session position 0, and
the favorite test is applied to that surviving row. A heart on a later clip of
the same session is saved on the detail page and does not appear in Browse or
on the Dashboard rail.

Ask `favorites` sets favorite and no extra words. That matches the dropdown.
Ask `favorite flight` also requires the substring `flight` in the filename,
path, tags, notes, or place. The word is not connected to the Session filter.
The Session filter only means “more than one clip” or “one clip”. It does not
list flights by place or date. Opening a multi-clip card and choosing
“Complete flight” is how the grouped clips are played.

Success path: heart the first clip of the session (the one Browse shows), then
Dashboard → Favorites → Show all, or Browse → Favorite → Favorites only.

## Task 5 — No GPS and no SRT

**Result: the file stays in the library, with explicit gaps.** One Browse bug
made the “Without GPS” combination lie. That bug is fixed here.

What the UI does when latitude and longitude are missing:

- Browse list shows an em dash in the GPS column. The grid has no place chips
  from geocoding. Year and month auto tags still appear when `recorded_at` is
  set.
- Detail shows Has SRT as No, altitude as an em dash, and omits the Location
  block entirely (`show_map` is false unless both coordinates exist). There is
  no sentence that says why the map is missing.
- World map draws no marker. With “Show without location” on (the default),
  the file is listed under “Without location”. That side list is capped at
  200 rows (`/api/geo/media`, `include_noloc`).
- Ask cannot find it by place, because no place tags were written.

Session grouping does not require SRT. Clips in the same flow stay together.
Other clips join when the idle gap is at most 3 minutes, and up to 20 minutes
when altitude does not show a landing (`group/sessions.py`). Missing
timestamps do not join, except inside one flow. SRT only decides the gap
between 3 and 20 minutes.

### Fix in this change

`has_gps is False` appended `latitude IS NULL OR longitude IS NULL` without
parentheses. SQL binds AND more tightly than OR, so the kind, drone, and
session-collapse conditions applied only to the left side of the OR. Browse
with Video and Without GPS therefore included a photo that had a latitude and
a null longitude.

The predicate is now parenthesized, matching `list_geo_media`. With GPS was
already both columns non-null and was left as it is. Covered by
`test_browse_without_gps_respects_kind`.

## Left as they are

These are real misses. They are not fixed here, because each one is a product
choice or a second behavior change, and the issue asks for the smallest fix
after the audit.

| Gap | Why it waits |
| --- | --- |
| A filtered empty Browse page says “No media yet” and offers “Add folder” (`templates/index.html`). The Dashboard already separates an empty library from an empty recent list. | Copy and empty-state change. Do it as its own slice after this audit. |
| English “vacation” / “holiday” / “trip” also require the tag `urlaub`. | The AND is what the current tests lock in for token search. An OR synonym needs its own tests and should not land beside the GPS fix. |
| “at” and other scene words are literal required substrings. | Scene understanding is out of scope. Tags and notes remain the way to name a sunset. |
| Favorite on a later session clip is hidden by collapse. | Changing which row represents a flight is a Browse behavior change, not a broken parenthesis. |
| Map groups labeled “By place” are coordinate buckets. Place names stay on auto tags. | Relabeling or joining city names is a map change. The issue excludes a new map provider and a Browse redesign. |
| Auto-tag chips are not links. | A chip that sets Search would be a new control. Search already matches the same text. |

## Click path to confirm tonight

1. Browse → Video, GPS → Without GPS. A photo that only has a latitude must
   stay out. A video with no coordinates must stay in. A video with both
   coordinates must stay out. Reset, then GPS → With GPS, and confirm the
   reverse.
2. Open a file with no coordinates. Detail has Has SRT = No and no Location
   map. World map → the file is under “Without location”, not as a marker.
   Turn the toggle off and the side list drops that group.
3. Ask `videos from Malta` on a file whose place or tags contain Malta.
   Then Ask `videos from Malta vacation` and expect a miss unless `vacation`
   and `urlaub` are both stored. Search `Malta` still hits the place.
4. Drone dropdown for the aircraft. Do not use Ask for the model name.
5. Heart the first clip of a multi-clip session. Dashboard → Favorites, and
   Browse → Favorites only, show that flight. A heart on a later clip of the
   same session does not.
6. Ask `sunset at the lake` on an untagged library. Expect no scene match.
   Put the words in notes, Apply Search, and the file appears.
