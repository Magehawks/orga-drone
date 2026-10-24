# Discovery: cross-drive archives at library scale (issue #99)

Discovery only. This note does not change import behavior and it is not a
claim that Orga Drone already supports 20k-file archives.

Measured on 2026-10-24 against commit `49b1612` with
`docs/discovery/issue-99-cross-drive-benchmark.py`. Raw numbers are in
`docs/discovery/issue-99-measurements.json`. Paths and filenames from the
installed library are not in that file.

This is the cross-drive slice coordinated with #94. #95 and #96 are the
implementation issues the timings point at. Nothing here was implemented.

## What was actually measured

| Run | What it is | What it is not |
| --- | --- | --- |
| Installed catalog, read-only count | 5 roots, 17,485 media rows (16,790 photos, 695 videos), 89 Studio clips, 0 favorites, SQLite 10,543,104 bytes | Not a rescan. The application database was not written. |
| Throwaway rescan of those same roots | Full `scan_root` into a new SQLite file. 17,480 media rows (16,791 photos, 689 videos), SQLite 10,620,928 bytes | Not a second rescan. Not a NAS. The live database was left untouched, so the 89 Studio clips were not re-checked there. |
| Synthetic 20,000-file library | 8×8 JPEG files, DJI-style names, no EXIF GPS, 100 files per folder, two roots | Not drone footage and not 20,000 real files. |
| 80 stub videos | 160×90 H.264, about 0.5 s, 1,800 bytes, copied | Not drone video. |
| Nine larger synthetic JPEGs | Six 1920×1080 and three 3840×2160 solid-color files | Not camera originals. |
| Unavailable-root fixture | Local directories removed, emptied, or deleted mid-scan | Not a USB eject and not a NAS disconnect. |

The installed catalog is under the 20k bar in the issue (17,485 media rows).
No 20k+ real archive was recruited. A second full rescan was measured only on
the synthetic library.

## Hardware

- Windows, Python 3.12.3, AMD Ryzen 7 5700X (8 cores / 16 threads), 34,278,871,040 bytes RAM
- C: Samsung SSD 850 EVO 500GB (SATA SSD). G: is another partition of that same disk.
- D: WDC WD20EZRZ-00Z5HB0 2TB (SATA HDD). This disk held the large installed root and the synthetic second root.
- E: Samsung SSD 990 EVO Plus 2TB (NVMe). Not used.
- F: Samsung SSD 990 EVO Plus 1TB (NVMe). Two installed roots.
- H: Samsung SSD 860 EVO 1TB (SATA SSD). Not used.
- I: optical drive, `Path.exists()` false in 0.012 s.
- No drive of type removable or network was present. No volume was ejected.

`ffprobe` was not on PATH. Video probing used the bundled `ffmpeg`.

## Installed library, throwaway rescan

`scan_all_roots` was not pointed at the application database. Each existing
root was scanned with `scan_root` into `.issue99-bench/installed-library.sqlite3`,
which the harness deleted afterward.

| Root | Drive | Assets | Photos | Videos | Other | Seconds | Discover | Index | Group |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | F: NVMe | 679 | 480 | 4 | 190 live sidecars, 5 non-video | 325.792 | 0.777 | 324.752 | 0.262 |
| 2 | C: SSD | 2 | 2 | 0 | 0 | 0.642 | 0.006 | 0.475 | 0.161 |
| 3 | D: HDD | 16,913 | 16,289 | 624 | 0 | 1,784.122 | 16.135 | 1,767.238 | 0.725 |
| 4 | C: SSD | 0 | 0 | 0 | 0 | 0.057 | 0.001 | 0.014 | 0.041 |
| 5 | F: NVMe | 157 | 20 | 61 | 0 (8 multi-clip flows, 14 sessions) | 78.181 | 0.153 | 77.913 | 0.114 |

Indexing is the scan. On the HDD root it was 1,767 s of 1,784 s. Grouping
stayed under a second at 16,913 assets. Discovery of that root was 16 s.

Average wall time per asset (measured total / measured asset count, not a
separate photo-vs-video timer):

- D: HDD mixed root: 0.105 s
- F: root 1 (many live-photo sidecars): 0.480 s
- F: root 5 (61 videos of 157 assets): 0.498 s

The throwaway media count (17,480) is 5 below the installed media count
(17,485). That gap was not reconciled file by file. Live sidecars and
non-video containers are assets, not media rows; that explains assets versus
media inside a root, not the 5-row gap between the two databases.

Browse queries on the throwaway database:

| Query | Result | Fastest of 3 |
| --- | --- | --- |
| `count_media` | 17,077 collapsed browse rows | 0.010 s |
| `list_media(limit=50)` | 50 | 0.002 s |
| `list_media(limit=200)` | 200 | 0.005 s |
| `list_media()` with no limit | 17,077 | 0.392 s (one call) |

17,480 media rows versus 17,077 browse rows is the session collapse in
`list_media` (403 rows not shown as their own cards). Paged browse at the
shipping page sizes is milliseconds. The unbounded list is what `GET /` uses
for recent items and favorites; that HTTP route was timed only on the
synthetic catalog (below), not on this library.

Thumbnails are not built during scan. The first `ensure_thumbnail` for 10
photos and 3 videos from this library took 1.872 s, 13/13 succeeded. That
sample was not split by kind, and the other ~17k files were not thumbnailed.

Working set after this section was about 193 MB, with a process peak of
292 MB. The peak includes later work in the same process, so it is not a
peak for this rescan alone. Peak sampled at the end of the HDD root was
251 MB.

### Side effects seen on stderr, not counted in the JSON

- While the HDD root was scanning, Pillow printed `DecompressionBombWarning`
  for an image of 108,000,000 pixels (Pillow's warning threshold is
  89,478,485). The scan continued. Whether that image was indexed was not
  checked separately.
- `reverse_geocoder` spawned a process that failed to import SciPy
  (`ImportError`: the paging file is too small). The in-process geocode sample
  earlier in the same run resolved one public coordinate in 2.968 s cold and
  0.002 s cached. Place tags on the library files were not counted, so this
  note does not say how many GPS photos missed a place tag.

## Synthetic 20,000 tiny JPEGs, two drives

10,000 files on C: (SSD) and 10,000 on D: (HDD). Fixture writes took 5.085 s
and 4.840 s. A discover-only walk of both trees, before the timed scan, took
1.838 s for 20,000 files, so the scan walk below was not a cold directory cache.
No reboot and no cache flush were done.

| | Seconds | Per file |
| --- | --- | --- |
| First `scan_all_roots` | 941.475 | 0.0471 |
| Second full rescan | 1,023.683 | 0.0512 |

First scan phases:

| Root | Drive | Discover | Index | Group |
| --- | --- | --- | --- | --- |
| 10,000 files | C: SSD | 5.761 | 461.475 | 0.281 |
| 10,000 files | D: HDD | 6.332 | 467.300 | 0.302 |

The HDD and the SSD indexed these tiny files at almost the same rate. For
this fixture the per-file SQLite commits and Pillow open dominate the disk.
The second scan was slower, not faster: 1,023.683 s versus 941.475 s. A
no-op rescan re-parses and rewrites every row.

SQLite grew to 14,106,624 bytes after the first scan and 14,200,832 bytes
after the rescan. Working set after the first scan was 217 MB. Process peak
at the end of the whole harness was 292 MB.

Paged queries on this database: count 0.010 s, page 50 in 0.001 s, page 100
in 0.002 s, page 200 in 0.004 s, a deep page of 50 in 0.013 s. An unbounded
`list_media()` returned all 20,000 rows in 0.511 s. The first page had 50
distinct ids.

In-process `TestClient` against this synthetic database (not the real library,
and not WebView2):

| Request | Status | Seconds | Body bytes |
| --- | --- | --- | --- |
| `GET /browse?page_size=50` | 200 | 0.106 | 90,790 |
| `GET /browse?page_size=200` | 200 | 0.036 | 334,045 |
| `GET /browse?page=40&page_size=200` | 200 | 0.085 | 338,915 |
| `GET /` | 200 | 0.458 | 7,526 |

`ensure_thumbnail` for the first 50 tiny JPEGs took 0.098 s cold and 0.021 s
cached. The following 50 `GET /media/{id}/thumb` calls took 0.414 s and all
returned 200. Those HTTP gets ran after the cold `ensure_thumbnail` pass, so
they are cache hits plus TestClient overhead.

Nine larger synthetic JPEGs, with no GPS: `parse_media_file` 0.012 s/file,
`ensure_thumbnail` 0.040 s/file. That is a decode cost the 8×8 fixture does
not show. It was not multiplied up to 20,000.

## Video probe cost

80 stub MP4s, one root, `scan_root`: 20.149 s, 0.2519 s/file. SQLite for that
run was 163,840 bytes.

Five-call microbench on one 1,800-byte stub:

| Call | Seconds per call |
| --- | --- |
| `scan_video_header` | 0.0017 |
| `probe_video_streams` (`ffmpeg -i`, because `ffprobe` was missing) | 0.0953 |
| `probe_video_with_ffprobe` (no `ffprobe` binary; the time is the lookup) | 0.0318 |
| `parse_media_file` | 0.0355 |

`scan_root` calls the stream probe and then `parse_media_file`, so a video
pays for more than one process spawn. These per-call times were not scaled
to a 20k video library. Real video files were not timed apart from the mixed
roots above.

## Unavailable roots

Local fixture only. Favorites and Studio clips were created on two of the
roots before the failure cases.

| Case | Result |
| --- | --- |
| Directory removed, then `scan_all_roots` | `error: missing`. Media stayed at 30. Favorite and Studio clip stayed. Studio item still `available` because the media row was still there. |
| Same path kept as an empty directory, then `scan_all_roots` | Media and assets went from 30 to 0. Favorite row and Studio clip stayed. That Studio item became `available: false`. |
| Those files restored, then `scan_all_roots` | 30 media rows again. Favorite relinked. Studio item `available` again. The removed root was still reported missing. |
| Directory removed, then `scan_root` directly | No exception. Media went from 20 to 0. `scan_root` does not use the missing-root guard that `scan_all_roots` uses. It still calls `clear_root_media`. |
| Files deleted from the progress callback once indexing had finished 10 files | No exception. 40 media rows were written and 0 files were left on disk. The scan had already collected the paths, then cleared the previous index, then indexed the remembered paths. |

`Path.exists()` in a child process:

| Target | Result |
| --- | --- |
| Missing local folder | false in 0.000 s |
| `\\localhost\orga-drone-issue99-missing` | false in 0.005 s |
| `\\192.0.2.1\orga-drone-issue99` (unroutable test address) | still running at 20 s, child killed |
| `I:\` (empty optical drive) | false in 0.012 s |

The product `scan_all_roots` calls `Path.exists()` with no timeout. A dead UNC
root can block a scan for at least 20 s. A mounted share that disconnects
during a copy was not tested.

## Top 3 bottlenecks

1. **Per-file indexing on a full rescan.** On every large run the indexing
   phase was almost the entire scan (1,767 s of 1,784 s on the real HDD root;
   about 929 s of 941 s on the 20k tiny JPEGs). Grouping and paged browse were
   not the cost. The second scan of the tiny library did not get cheaper.
   Smallest remedy is #96: a documented fingerprint (size, mtime, path) that
   skips parse and rewrite for unchanged files, and still reconciles adds,
   edits, and confirmed deletes. Batching the per-file SQLite commits would
   help a first import; that is an implementation detail for the #96 slice,
   not a separate product feature from this note.

2. **A subprocess per video, sometimes more than one.** Stub videos cost
   0.25 s each, and `probe_video_streams` alone was 0.095 s of `ffmpeg -i`.
   Roots that were mostly video or live-photo sidecars averaged 0.48–0.50 s
   per asset, against 0.047 s for a tiny JPEG and 0.105 s for the mixed HDD
   root. Smallest remedy is the same #96 skip for unchanged videos, plus one
   probe per file whose result is stored on the row. This run did not compare
   a single-probe patch.

3. **A missing root and an empty root are different, and only one of them is
   safe.** `scan_all_roots` keeps the catalog when the directory is gone, and
   wipes it when the directory exists and has no media. `scan_root` wipes even
   when the directory is gone. A dead UNC `exists()` call blocked for the
   whole 20 s timeout. Smallest remedy is #95: do not treat "path missing" or
   "path exists but a disconnect could not be ruled out" as a confirmed
   delete; keep favorites, tags, and Studio clips; mark the source offline;
   put a bound on the existence check. The fixture showed that restoring the
   same names relinks the favorite and the Studio clip after an empty-directory
   wipe. That relink is not a substitute for refusing the wipe.

#94 stays open as the parent discovery. This note does not close it. The NAS
disconnect/reconnect case #94 asks for was not run.

## What remains for a human

- A real archive of 20,000 or more photos and videos was not available. The
  installed catalog is 17,485 media rows and was rescanned once into a
  throwaway database.
- No USB eject, no removable volume, and no NAS. The empty-directory case is
  a local stand-in for a mount point that stays visible with no files.
- The UNC result is a killed 20 s `exists()`, not a share that drops mid-scan.
- Thumbnail time for the whole library, and WebView2 with decoded thumbs, were
  not measured.
- Photo time versus video time inside the 1,784 s HDD root was not instrumented
  separately.
- Place-tag loss from the SciPy paging-file error was not counted.
- The 5-row gap versus the installed media count was not reconciled.
- Directory caches were warm. A cold boot or a cold NAS read was not measured.
- The real library was not rescanned a second time. Only the synthetic 20k
  library was.

Re-run from the repository root:

```text
python docs/discovery/issue-99-cross-drive-benchmark.py
```

The harness reads the installed library roots if that database exists, writes
only a throwaway SQLite file, and deletes its fixtures on the way out,
including `D:\orga-drone-issue-99-bench` when D: is the second fixed disk.
It does not modify the application database. Expect on the order of an hour
on this machine if the installed library is included with `--photo-count 20000`.
