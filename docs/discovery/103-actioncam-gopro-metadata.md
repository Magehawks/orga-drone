# Discovery: Actioncam archive workflow and GoPro metadata

Issue: [#103](https://github.com/Magehawks/orga-drone/issues/103)

Audit date: 2026-10-24

Tree: `issue-103-actioncam-gopro` at base `49b1612` (`Add per-clip Studio zoom and pan…` on `issue-86-studio-ken-burns`).

This note is a discovery record. It does not add GoPro telemetry parsing, and it does not change Library or Studio behavior.

## Result

No GoPro camera file is in this repository, so this audit cannot report metadata measured from a real sample. Import → browse → Studio was not executed on a GoPro clip. The sections below separate three kinds of evidence:

1. Repository inventory (what files exist).
2. Code paths and one existing synthetic JPEG test (what the current app does when those bytes are present).
3. Unmeasured camera-file behavior (explicitly not filled in).

## Sample inventory

Searched the tree for video and photo fixtures (`*.mp4`, `*.mov`, `*.mkv`, `*.m4v`, `*.lrv`, `*.thm`, `*.jpg`, `*.jpeg`).

| Found | Role |
| --- | --- |
| `media/libary_orga_drone.jpg`, `media/home_orga_drone.jpg`, `media/details_orga_drone.jpg` | App screenshots. Not camera originals. Not parsed for this audit. |
| `tests/fixtures/studio-export-chained-xfade-timebase-fail.ffmpeg.txt` | ffmpeg stderr fixture for Studio export. Not a camera file. |
| No `.mp4`, `.mov`, `.lrv`, `.thm`, or GPMF payload | No GoPro (or other actioncam) camera sample is checked in. |

The only GoPro strings in tests are arguments to a Pillow-written JPEG. That test is cited below. It is not a camera file and it is not a stand-in for GoPro video, chapter files, or sidecars.

**Blocker for the sample-file acceptance criterion:** supported and unsupported metadata cannot be listed from a real GoPro clip until a maintainer supplies one photo and one video (and any sidecars that camera actually wrote). This document does not guess those tag values.

## Evidence that was executed

`tests/test_generic_media.py::test_exif_gps_brand_agnostic` was run from this worktree on 2026-10-24 (`6 passed`, including the `GoPro` / `HERO12 Black` parameter). The test writes a 64×64 JPEG with Pillow EXIF, then calls `parse_exif` and `parse_media_file`. For `make="GoPro"`, `model="HERO12 Black"` the test asserts:

| Field | Value asserted by the test |
| --- | --- |
| GPS | About 47.1 N, 8.5 E (the coordinates the test wrote) |
| `recorded_at` | `2024-06-15 12:30:00` from `DateTimeOriginal` |
| `exif_make` | `GoPro` |
| `camera_model` | `HERO12 Black` |
| `drone_model` | `Camera` (`NON_DJI_CAMERA_LABEL`) |
| `source_type` | `camera` |
| `sequence`, `mode` | `None` (the filename is `vacation.jpg`, which is not a DJI name) |

That is the full GoPro-related measurement in this repo. It shows the still-photo EXIF path can keep Make, Model, date, and GPS when those EXIF tags exist. It does not show what a GoPro camera writes into a JPEG or an MP4.

Filename strings were also passed to `classify_ext` and `parse_filename`. No file bytes were read. These names are not files in the tree and are not claimed to be a verified camera naming scheme:

| Name string | `classify_ext` | Included by `iter_media_files` | Date and sequence from the filename |
| --- | --- | --- | --- |
| `GOPR0001.MP4`, `GH010001.MP4`, `GX010001.MP4` | `video` | Yes (`.mp4`) | Both empty. The only filename parser is `DJI_YYYYMMDDHHMMSS_NNNN_MODE`. |
| `GOPR0001.JPG` | `photo` | Yes (`.jpg`) | Both empty. Date would have to come from EXIF or mtime. |
| `GL010001.LRV`, `GOPR0001.THM`, `clip.360` | `other` | No | Not scanned. |
| `GOPR0001.LRF` | `proxy` | Yes, as a `.lrf` asset, not as library video/photo | Both empty. |

## Import → browse → Studio (code path)

Not run on a GoPro file. For any file the scanner accepts, the path is:

1. **Import.** Library → Add folder calls `scan_root`, which is a full rescan of that root. `iter_media_files` keeps only `.mp4`, `.mov`, `.mkv`, `.m4v`, `.jpg`, `.jpeg`, `.dng`, `.png`, `.webp`, `.heic`, `.heif`, `.lrf`, and `.srt`.
2. **Index.** Photos and videos become library rows. `.lrf` and `.srt` are assets/sidecars, not browse clips. A same-stem `.mov` next to a same-directory HEIC/JPG still is treated as an iPhone Live Photo sidecar and is omitted from the library. A video extension with no real motion stream is stored as an asset and omitted from the library.
3. **Browse.** The grid and table list `video` and `photo`. The source filter has two choices: Drone (`source_type = drone`) and Other devices (everything else, including `camera`, `phone`, and `unknown`). There is no actioncam or GoPro filter. The card label is `drone_model` (`Camera` in English, `Kamera` in German when that label was stored). The model string is not on the card. Browse text search matches filename, path, `drone_model`, tags, notes, and place. It does not match the `camera_model` column, so a model string such as the one stored by the synthetic test is not a search term unless it also appears in the filename.
4. **Detail.** Date, Drone (`drone_model`), Camera (`camera_model`), sequence, Has SRT, and Has LRF. Playback is `GET /media/{id}/stream` (`FileResponse`, HTTP range). Thumbnails come from `ensure_thumbnail`.
5. **Studio.** `POST /media/{id}/studio/add` requires an open Studio project, then stores that library file on the project. Browse can also add the current page. Preview streams the same library file. There is no brand branch in add or preview.

A GoPro photo that matches the synthetic EXIF case would be browsable and addable. A GoPro video is addable only after it is indexed as `video`. Whether a real GoPro video indexes with a useful date, label, duration, or GPS was not measured.

## Metadata the code can read

### Stills (JPEG/PNG/WebP/HEIC/HEIF/DNG)

`parse_exif` reads Make, Model, `DateTimeOriginal` (else `DateTime`), and GPS latitude, longitude, and altitude when those EXIF tags are present. Make `GOPRO` is in the camera-make set, so `source_type` becomes `camera` and the library label becomes `Camera` plus the Model string on the detail page.

Unsupported for stills, because the code never reads them: a telemetry track, chapter index, or any non-EXIF sidecar. DNG is opened through Pillow; this audit did not open a DNG.

### Videos (MP4/MOV/M4V/MKV)

Date, in order:

1. DJI filename timestamp, if the name matches.
2. A byte scan of the first 2_000_000 bytes for `creation_time` / `creationdate` (and the same pattern with `_` or `-`) followed within 32 characters by a datetime.
3. If ffprobe is available and the date is still empty: format/stream tags `creation_time`, `com.apple.quicktime.creationdate`, or `date`.
4. Else filesystem mtime.

ffprobe is the system binary, or a sibling of the ffmpeg binary. The bundled imageio-ffmpeg build often has ffmpeg and no ffprobe. Without ffprobe, only steps 1, 2, and 4 apply.

GPS, in order:

1. ISO 6709 text in that same 2_000_000-byte scan.
2. A sibling `.srt` / `.SRT`, parsed as a DJI SRT (latitude/longitude and `rel_alt` / `abs_alt`).
3. If ffprobe is available and GPS is still empty: tags `location`, `location-eng`, `com.apple.quicktime.location.iso6709`, or any other tag value that matches ISO 6709.

Camera label on video: the header scan sets `drone_model` / `camera_model` only for `DJI FC####` and `DJI Avata 2`. ffprobe tags are not copied into Make or Model. A video with none of those DJI strings stays `drone_model = None`, `camera_model = None`, `source_type = unknown`. Browse then shows an em dash, not `Camera`.

Duration: sibling SRT cue end, else ffprobe format duration. No ffprobe and no SRT leaves duration empty. Studio can still hold the clip; estimated runtime for that clip is then empty unless something else supplies a duration later.

There is no GPMF, `gpmd`, or other GoPro telemetry reader. This audit did not see a camera file, so it does not claim that GoPro GPS lives only in that track, and it does not recommend writing that parser.

### Grouping

**Flows** (`group_clips_into_flows`) join a later video to the previous one only when the previous file is at least 3.4 GiB (`3.4 * 1024**3`), the later `recorded_at` is 0 to 300 seconds after the previous `recorded_at` (start-to-start, not the idle gap), and, if both clips have a sequence number, the later sequence is exactly previous + 1. Sequence numbers are set only by the DJI filename. Clips with `sequence = None` skip that check. Whether two large files would form a flow is therefore a size and start-time question. It was not measured on camera files.

**Sessions** use the idle gap from the previous clip’s end (`recorded_at + duration`, or `recorded_at` when duration is missing) to the next start. A gap of at most 3 minutes joins. A gap above 20 minutes splits. Between those, SRT altitude and GPS stability can split a session. Without an SRT, only the time rules apply. Photos can attach within 5 minutes of a session’s span. These rules are drone-flight heuristics. They are not an actioncam chapter model.

### Thumbnails, proxies, playback

| Step | Behavior in code | Measured on a GoPro file |
| --- | --- | --- |
| Photo thumbnail | Pillow resize of the still | No |
| Video thumbnail | One ffmpeg frame at 0.5 s, written as a JPEG. If ffmpeg fails, a placeholder with the filename. | No |
| Proxy used for the thumbnail and for “Preview quality (LRF)” | Same-stem `.LRF` / `.lrf` only (`find_proxy`) | No |
| Has LRF / Has SRT on the detail page | Same stem, those suffixes only | No |
| `.lrv`, `.thm`, `.360` | Not scanned, not proxies, not in the rename sibling list (`.mp4`, `.mov`, `.jpg`, `.jpeg`, `.lrf`, `.srt`, `.dng`, `.png`, `.mkv`) | No |
| Playback | Original file via `/media/{id}/stream`, including Studio preview | No |

## Smallest follow-up

One issue, and no telemetry parser:

**Title:** Sample-gated regression for one GoPro photo and one GoPro video.

**Why this slice:** Generic JPEG/MP4 import, browse, and Studio add already exist. The open question is which date, label, GPS, duration, grouping, sidecar, and thumbnail results a real camera file produces. A parser written before that measurement would be guessing tag names.

**Acceptance criteria for that issue:**

- Add `tests/fixtures/gopro/README.md` naming the files and the license under which they may be committed.
- If the camera originals cannot be redistributed, the test skips when `tests/fixtures/gopro/` (or a documented local path) is absent, and CI stays green without those files.
- When the files are present, run `scan_root` on a directory that contains one JPEG and one MP4, plus any sidecar that was actually beside them.
- Expected values are copied from an inspection of those files (EXIF and ffprobe output stored next to the test). They must not be copied from this discovery note.
- Assert only: indexed kind, `recorded_at`, `drone_model`, `camera_model`, `source_type`, latitude null or equal to the oracle, duration null or equal to the oracle, flow id membership equal to the oracle, and `add_studio_item` accepting the row.
- Thumbnail assertion only when ffmpeg is installed: a JPEG cache file exists. Do not assert pixels.
- Out of scope: GPMF, a GPS track, chapter UI, other camera brands, cloud, Quik replacement.

After that oracle exists, open at most one product issue for the first gap the oracle shows that the current pipeline can fill without a new telemetry format. In that order, and only if the oracle shows it:

1. ffprobe already returns a make or model tag and `probe_video_with_ffprobe` discards it, so video rows stay unlabeled.
2. A same-stem proxy uses an extension other than `.lrf`, so thumbnails always decode the full video.
3. Two chapter files stay ungrouped and their names or timestamps show a stable rule the flow grouper does not implement.

Do not open a GoPro telemetry issue from this audit.

## Non-goals (unchanged)

Full GoPro Quik replacement, parsers for every action camera, and cloud libraries. Those stay out of scope.
