# Windows third-party evidence for v2.0.1

This note records what was inspected. It is not a compliance certificate
and not legal advice. The project license stays the MIT License.

## What v2.0.1 actually shipped

GitHub Release [v2.0.1](https://github.com/Magehawks/orga-drone/releases/tag/v2.0.1)
(`dc76af4`) is public and has **no assets**. There is no Windows
PyInstaller zip for v2.0.1. The tag workflow that would have built one was
cancelled before it uploaded a zip.

## What was inspected instead

A local onefolder built on 2026-10-26 from commit `1293622` (parent of the
version bump; the only later change on `dc76af4` is the version string).
The frozen `src` copy still says `__version__ = "2.0.0"`. This folder is
not the GitHub Release artifact:

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

## itch.io sale

**NO-GO.**

A sale of a Windows build of this application on itch.io is not supported
by the evidence above:

1. v2.0.1 published no Windows zip, so there is no v2.0.1 binary to sell.
2. The onefolder that matches the current Windows build inputs contains a
   GPL-configured ffmpeg 7.1 binary without corresponding source.
3. reverse-geocoder is LGPL only as far as the wheel metadata and an
   unproven match to upstream master. The frozen copy is bytecode, and
   replacing it was not demonstrated.
4. The other bundled packages (including PyInstaller, pythonnet, numpy,
   scipy, Pillow, and pywebview) were not audited. Their presence blocks
   any claim about the whole zip.

`packaging/windows_third_party.py` writes these notices into a future
onefolder and makes `verify-zip` exit 2 while the verdict is NO-GO. The
Windows release workflow stops before uploading that zip. Exit 2 is the
missing proof. It is not a finding that a different build would be lawful.
