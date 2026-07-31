# orga-drone 1.6.0

Prebuilt Windows binaries are **not** stored in git.

Download the release assets from:

**https://github.com/Magehawks/orga-drone/releases/tag/v1.6.0**

Artifact: `orga-drone-windows-x64.zip` (onefolder build: `orga-drone.exe` + dependencies).

## Added

- Live scan progress
- Better user feedback during long scans

## Changed

- Library scans now run asynchronously

## Fixed

- UI no longer appears frozen during scans

If video browsing feels heavy under Windows Defender, exclude the unzipped
`orga-drone` folder (see `packaging/README.md`).
