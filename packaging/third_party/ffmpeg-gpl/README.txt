Pinned Windows GPL FFmpeg used by the Orga Drone release candidate.

Why this build exists
The Studio encoder calls libx264 with preset veryfast, native AAC, and the
built-in filters drawtext, overlay, xfade, zoompan, boxblur, eq, hue, fade,
scale, pad, fps, format, setparams, amix, afade, and anullsrc. It also passes
-filter_complex_script and -filter_script:v. FFmpeg 7.1 still has those script
options. An LGPL build without libx264 cannot run the current encoder command
and would change the encoded video. This build keeps libx264 and libfreetype.

What is corresponding source
The tarballs in tarballs/ are the exact bytes named by SHA256SUMS:
- FFmpeg 7.1
- x264 commit b35605ace3ddf7c1a5d67a2eb553f034aef41d55
- FreeType 2.13.3
- HarfBuzz 15.0.0 (required by FFmpeg 7.1 drawtext, together with FreeType)
- zlib 1.3.1
- libpng 1.6.49
build-win64.sh is the build script. It verifies those hashes before compiling.
No further patches are applied. Licenses copied by the script land in licenses/.

What is not a license gap
MSYS2 MinGW gcc, nasm, make, and binutils are general-purpose tools used
unmodified. Their package versions are recorded in BUILD-RESULT.txt when a
build finishes. They are not linked library source. Bit-for-bit reproduction
on another machine is not claimed.

bin/ffmpeg.exe is the executable this script produced. ffprobe.exe is not
committed. The Windows release workflow copies ffmpeg.exe over the collected
imageio-ffmpeg binary when the file is present. Without it, the gyan.dev 7.1
binary remains and the sale gate stays NO-GO.
