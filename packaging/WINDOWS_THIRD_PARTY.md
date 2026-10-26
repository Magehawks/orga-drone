# Windows third-party evidence for v2.0.1

This note records what was inspected. It is not a compliance certificate
and not legal advice. The project license stays the MIT License.

## What v2.0.1 actually shipped

GitHub Release [v2.0.1](https://github.com/Magehawks/orga-drone/releases/tag/v2.0.1)
(`dc76af4`) is public and has **no assets**. There is no Windows
PyInstaller zip for v2.0.1. The tag workflow that would have built one was
cancelled before it uploaded a zip.

## Local onefolder from the v2.0.1 tree

On 2026-10-26 a Windows onefolder was built from this branch. `src/` is the
same as `dc76af4`. The only bundle change before notices is that the spec
also collects `reverse_geocoder` data files. The frozen copy says
`__version__ = "2.0.1"`. The ffmpeg executable is
`ffmpeg-win-x86_64-v7.1.exe`, 87638016 bytes, SHA256

```text
2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3
```

`rg_cities1000.csv` is at `_internal/reverse_geocoder/rg_cities1000.csv`.
`python packaging/windows_third_party.py write` then `verify-zip` on that
folder's zip printed `NO-GO` and exited 2. `dist-info-without-license.txt`
was empty. The notices folder contains the GPLv3 text, the gyan README,
PyInstaller `COPYING.txt`, the reverse-geocoder sources and LGPL-2.1 text,
the Leaflet 1.9.4 BSD-2-Clause text, the Lucide 0.469.0 ISC text, and
`GEONAMES_ATTRIBUTION.txt`. It does not contain FFmpeg's corresponding
source. This zip was not uploaded and is not a GitHub Release asset.

An earlier local folder from commit `1293622` still says
`__version__ = "2.0.0"` and is not this build. Its ffmpeg path was:

`dist-main/orga-drone/_internal/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe`

SHA256 (same bytes as the imageio-ffmpeg 0.6.0 wheel in the build
environment):

```text
2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3
```

`ffmpeg -version` on that file:

```text
ffmpeg version 7.1-essentials_build-www.gyan.dev Copyright (c) 2000-2024 the FFmpeg developers
built with gcc 14.2.0 (Rev1, Built by MSYS2 project)
configuration: --enable-gpl --enable-version3 --enable-static --disable-w32threads --disable-autodetect --enable-fontconfig --enable-iconv --enable-gnutls --enable-libxml2 --enable-gmp --enable-bzlib --enable-lzma --enable-zlib --enable-libsrt --enable-libssh --enable-libzmq --enable-avisynth --enable-sdl2 --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxvid --enable-libaom --enable-libopenjpeg --enable-libvpx --enable-mediafoundation --enable-libass --enable-libfreetype --enable-libfribidi --enable-libharfbuzz --enable-libvidstab --enable-libvmaf --enable-libzimg --enable-amf --enable-cuda-llvm --enable-cuvid --enable-dxva2 --enable-d3d11va --enable-d3d12va --enable-ffnvcodec --enable-libvpl --enable-nvdec --enable-nvenc --enable-vaapi --enable-libgme --enable-libopenmpt --enable-libopencore-amrwb --enable-libmp3lame --enable-libtheora --enable-libvo-amrwbenc --enable-libgsm --enable-libopencore-amrnb --enable-libopus --enable-libspeex --enable-libvorbis --enable-librubberband
```

`ffmpeg -buildconf` repeats those `--enable` / `--disable` flags, including
`--enable-gpl`, `--enable-version3`, `--enable-static`, and `--enable-libx264`.

## Package versions in that build

| Piece | Version | What the package itself says | What the onefolder contained |
| --- | --- | --- | --- |
| imageio-ffmpeg | 0.6.0 | `License: BSD-2-Clause`. `LICENSE` copyright line: `Copyright (c) 2019-2025, imageio`. The 0.6.0 README describes wheels that include an ffmpeg executable and does not state that executable's license. | `imageio_ffmpeg-0.6.0.dist-info/LICENSE` is present. Python sources of the wrapper are present. |
| ffmpeg binary inside that wheel | 7.1 essentials, www.gyan.dev | The binary prints the copyright and configuration above. | The exe is at `_internal/imageio_ffmpeg/binaries/`. No FFmpeg source tree, no GPL text, and no offer of corresponding source is in the folder. |
| reverse_geocoder | 1.5.1 | Wheel `METADATA` says `License: lgpl`. The wheel has no `LICENSE` file. `__init__.py` has an author name and no copyright or license header. | PyInstaller put `__init__.py` and `cKDTree_MP.py` in the PYZ archive (bytecode). `rg_cities1000.csv` (7,851,524 bytes in the wheel) was not in the onefolder. |

Upstream `https://github.com/thampiman/reverse-geocoder` `master` `LICENSE`,
retrieved 2026-10-26, is the GNU Lesser General Public License version 2.1.
That branch's `setup.py` says version 1.5.1 and `license='lgpl'`.
The tag URL `v1.5.1/LICENSE` returned 404. The wheel was not shown to be
that git revision. The verbatim upstream text is stored at
`packaging/third_party/reverse-geocoder-LGPL-2.1.txt` so a later zip can
carry it. Storing it does not prove the wheel matches that file.

## What FFmpeg's own page says about these flags

[ffmpeg.org/legal.html](https://ffmpeg.org/legal.html), retrieved 2026-10-26,
says FFmpeg is LGPL 2.1 or later unless GPL parts are used, and that if
those parts are used the GPL applies to all of FFmpeg. The same page names
libx264 as a GPL library and says a build used under its LGPL checklist is
compiled without `--enable-gpl`. This binary is configured with
`--enable-gpl`, `--enable-version3`, `--enable-static`, and
`--enable-libx264`.

Orga Drone starts that executable as a separate process
(`src/orga_drone/ffmpeg_bin.py`). This note does not decide whether that
makes the rest of the application a GPL work. It does record that the
executable being redistributed was built with those flags, and that the
corresponding source of this gyan.dev build was not in the folder.

The BSD-2-Clause text for imageio-ffmpeg requires its copyright and
conditions to stay with that package. That text was in the onefolder. It
does not license the ffmpeg executable.

## Identity of the FFmpeg binary

`ffmpeg.exe` inside
`https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip`
(published 2024-09-30, tag `7.1`) has the same size (87638016) and the same
SHA256 as the imageio-ffmpeg 0.6.0 Windows binary. That release says the
FFmpeg source is commit `b08d7969c5`. The package README says **GPL v3** and
lists external library versions, including `x264 v0.164.3192` and
`x265 4.0-6-ga009ec077`. imageio-binaries stores the same bytes
(`ffmpeg-win-x86_64-v7.1.exe`, renamed 2025-01-16 in `f8f64710`).

Those files are copied into `packaging/third_party/`. They identify the
binary. They are not the corresponding source: the static link also contains
the listed libraries, and the zip has neither their source trees nor the
build scripts. GPLv3 section 6c's written offer applies only to occasional
noncommercial distribution and only when the binary was received with such
an offer. This binary was not. A paid itch.io download cannot use that offer.
No written offer is made here.

7.1.1 was published later (2025-03-12) and is a different source commit.
The library versions inside `ffmpeg -version` (`libavcodec 61.19.100` and
the rest) stay the same across the 7.1 point releases, so the version line
alone does not identify the commit. The hash match does.

## reverse-geocoder wheel

`__init__.py` and `cKDTree_MP.py` in reverse_geocoder 1.5.1 are byte-identical
to `thampiman/reverse-geocoder` master on 2026-10-26
(`64b4a629…` and `932e77d7…`). That tree's `LICENSE` is LGPL-2.1. The wheel
does not ship it. The sources have no copyright header. A normal interpreter
with the wheel resolves `(48.137154, 11.576124)` offline to Munich, DE,
because `rg_cities1000.csv` sits beside the package. The earlier onefolder
did not collect that CSV. The spec now collects reverse-geocoder data files.
GeoNames' export page says the data is under a Creative Commons attribution
license and allows commercial use. The dump readme at
`https://download.geonames.org/export/dump/readme.txt`, retrieved 2026-10-26,
says the gazetteer extract files are CC BY 4.0. The wheel CSV has no license
header and was not hash-matched to a dated dump, so that readme is not proof
for these exact bytes.

## Other bundled pieces

`leaflet.js` matches unpkg `leaflet@1.9.4` `dist/leaflet.js`
(SHA256 `db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a`).
The BSD-2-Clause text from tag `v1.9.4` is stored and copied into the notices.
Each individual Lucide SVG matches `lucide-static` 0.469.0. `sprite.svg` is
assembled in this repository. The ISC text from tag `0.469.0` is copied into
the notices.

`leaflet.markercluster.js`, `MarkerCluster.css`, and
`MarkerCluster.Default.css` match unpkg `leaflet.markercluster` 1.5.2 and
1.5.3 `dist`. They do not match 1.5.1. Both tags carry the same
`MIT-LICENCE.txt` (Copyright 2012 David Leaver). That text is copied into
the notices.

Every bundled Outfit and Sora woff2 matches `@fontsource/outfit` 5.2.5 and
`@fontsource/sora` 5.2.5 `files/*-latin-*-normal.woff2`. Both IBM Plex Mono
files match `@fontsource/ibm-plex-mono` 5.2.6. Those three packages contain
the same `LICENSE` bytes, the SIL Open Font License 1.1, with the header
"Google Inc." The file does not name reserved font names. It is copied into
the notices.

## Corresponding source search

Searched on 2026-10-26: the GitHub release tag `7.1` (six binary archives;
the tag tree is only `README.md`), the essentials zip (executables, generated
HTML docs, libvpx presets, `LICENSE`, `README.txt`), and
`https://www.gyan.dev/ffmpeg/builds/`. **Corresponding source: no.**
The FFmpeg commit and the library version strings are identified.
`x264 v0.164.3192` has no commit id. bzlib, fontconfig, gmp, gnutls, iconv,
libxml2, lzma, and zlib are in the configuration and absent from the version
list. No suite revision, ini, patches, or build log for 2024-09-30 was found.
Current `media-autobuild_suite` master is not that build. The gap is written
to `ffmpeg-7.1-essentials-SOURCE-GAP.txt`. A draft request to `builds@gyan.dev`
is `ffmpeg-7.1-essentials-SOURCE-REQUEST.txt`. It has not been sent. Neither
file clears the gate.

## itch.io sale

**NO-GO.**

A sale of a Windows build of this application on itch.io is not supported
by the evidence above:

1. The public v2.0.1 GitHub Release still has no Windows zip. A local
   onefolder from that source tree was built and checked. `verify-zip`
   exited 2. That zip was not published.
2. The matched gyan.dev 7.1 essentials binary is GPL v3 and statically links
   libraries such as libx264. The FFmpeg commit and the library version list
   are known. Their source trees and the build scripts are not in the zip.
   The GPLv3 text and the gyan README are identity evidence. A general
   upstream link is not corresponding source, and GPLv3 section 6c does not
   cover a paid itch.io copy.
3. reverse-geocoder's two Python files match upstream master and that
   LICENSE is LGPL-2.1. The frozen copy is still bytecode, so replacement
   was not demonstrated. The CSV is in the onefolder. A separate frozen
   probe printed `CSV_EXISTS True` and then stopped with WinError 1455
   (page file too small) before a place result. That error is a machine
   limit, not a license blocker. The same call in the interpreter returned
   Munich, DE. The current GeoNames dump readme says CC BY 4.0; the wheel
   CSV was not hash-matched to a dump.
4. PyInstaller's COPYING.txt, including the bootloader exception, is copied
   into the notices. The verdict lists that exception, the separate-process
   question, the LGPL replacement question, and the unmatched GeoNames file
   as open legal questions. Those lines do not change the verdict, and a
   technical GO would not be a legal opinion. Every bundled dist-info in
   the local v2.0.1 onefolder had a LICENSE or COPYING file. A file being
   present is not a review of its terms. Markercluster 1.5.2/1.5.3 and the
   matched Fontsource OFL text are now included.

`packaging/windows_third_party.py` writes these notices into a future
onefolder and makes `verify-zip` exit 2 while the verdict is NO-GO. The
Windows release workflow stops before uploading that zip. Exit 2 is the
missing proof. It is not a finding that a different build would be lawful.
