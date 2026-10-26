#!/bin/bash
# Build a static Windows ffmpeg.exe from the tarballs named in SHA256SUMS.
# Run from an MSYS2 mingw64 shell. The compiler is a general-purpose tool and
# is not part of the corresponding source of the linked libraries.
set -euo pipefail
export PATH="/mingw64/bin:${PATH}"
cd "$(dirname "$0")"
ROOT="$(pwd)"
WORK="${WORK:-/tmp/orga-ffmpeg-gpl-build}"
PREFIX="${PREFIX:-${WORK}/prefix}"
JOBS="${JOBS:-$(nproc)}"
rm -rf "$WORK"
mkdir -p "$WORK" "$PREFIX"
while read -r expect name; do
  [ -n "${expect}" ] || continue
  case "$expect" in \#*) continue ;; esac
  file="${ROOT}/tarballs/${name}"
  got="$(sha256sum "$file" | awk '{print $1}')"
  if [ "$got" != "$expect" ]; then
    echo "hash mismatch for ${name}" >&2
    echo "expected ${expect}" >&2
    echo "got      ${got}" >&2
    exit 1
  fi
  tar -xf "$file" -C "$WORK"
done < "${ROOT}/SHA256SUMS"

export CPPFLAGS="-I${PREFIX}/include"
export LDFLAGS="-L${PREFIX}/lib"
export PKG_CONFIG_PATH="${PREFIX}/lib/pkgconfig"
export CFLAGS="-O2"
export CXXFLAGS="-O2"

cd "${WORK}/zlib-1.3.1"
./configure --prefix="${PREFIX}" --static
make -j"${JOBS}"
make install

cd "${WORK}/libpng-1.6.49"
./configure --prefix="${PREFIX}" --enable-static --disable-shared
make -j"${JOBS}"
make install

cd "${WORK}/freetype-2.13.3"
./configure --prefix="${PREFIX}" --enable-static --disable-shared \
  --with-zlib=yes --with-png=yes --with-bzip2=no --with-brotli=no --with-harfbuzz=no
make -j"${JOBS}"
make install

cd "${WORK}/harfbuzz-15.0.0"
meson setup build \
  --prefix="${PREFIX}" \
  --default-library=static \
  --buildtype=release \
  -Dfreetype=enabled \
  -Dglib=disabled \
  -Dgobject=disabled \
  -Dcairo=disabled \
  -Dicu=disabled \
  -Dtests=disabled \
  -Ddocs=disabled \
  -Dintrospection=disabled \
  -Dutilities=disabled
ninja -C build
ninja -C build install

cd "${WORK}/x264-b35605ace3ddf7c1a5d67a2eb553f034aef41d55"
./configure --prefix="${PREFIX}" --enable-static --disable-cli --enable-pic --disable-opencl
make -j"${JOBS}"
make install

cd "${WORK}/ffmpeg-7.1"
./configure \
  --prefix="${PREFIX}" \
  --target-os=mingw32 \
  --arch=x86_64 \
  --enable-gpl \
  --enable-version3 \
  --enable-static \
  --disable-shared \
  --disable-debug \
  --disable-doc \
  --disable-ffplay \
  --enable-libx264 \
  --enable-libfreetype \
  --enable-libharfbuzz \
  --pkg-config-flags=--static \
  --extra-cflags="-I${PREFIX}/include" \
  --extra-ldflags="-L${PREFIX}/lib -static"
make -j"${JOBS}"
make install

mkdir -p "${ROOT}/bin" "${ROOT}/licenses"
cp -f "${PREFIX}/bin/ffmpeg.exe" "${ROOT}/bin/ffmpeg.exe"
cp -f "${PREFIX}/bin/ffprobe.exe" "${ROOT}/bin/ffprobe.exe"
cp -f "${WORK}/ffmpeg-7.1/COPYING.GPLv3" "${ROOT}/licenses/ffmpeg-GPLv3.txt"
cp -f "${WORK}/x264-b35605ace3ddf7c1a5d67a2eb553f034aef41d55/COPYING" "${ROOT}/licenses/x264-GPL.txt"
cp -f "${WORK}/freetype-2.13.3/docs/FTL.TXT" "${ROOT}/licenses/freetype-FTL.txt"
cp -f "${WORK}/harfbuzz-15.0.0/COPYING" "${ROOT}/licenses/harfbuzz-COPYING.txt"
cp -f "${WORK}/zlib-1.3.1/LICENSE" "${ROOT}/licenses/zlib-LICENSE.txt"
cp -f "${WORK}/libpng-1.6.49/LICENSE" "${ROOT}/licenses/libpng-LICENSE.txt"
{
  echo "gcc $(gcc -dumpfullversion) $(gcc -dumpmachine)"
  echo "nasm $(nasm -v | head -n 1)"
  sha256sum "${ROOT}/bin/ffmpeg.exe" "${ROOT}/bin/ffprobe.exe"
  "${ROOT}/bin/ffmpeg.exe" -hide_banner -version
} > "${ROOT}/BUILD-RESULT.txt"
echo BUILD_OK
