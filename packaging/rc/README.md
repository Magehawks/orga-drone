# Local Windows manual RC package

This is a local acceptance tool, not a release workflow. It does not tag, merge,
upload, change the app version, or publish anything. The Product Owner records
the human decision in the [German checklist](../../docs/validation/MANUAL_RC_DE.md).

## Build and package

Use Python 3.12, an isolated editable install with the repository requirements,
and PyInstaller 6.22.3, as described in [packaging](../README.md). From the repo
root in PowerShell:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$rcSha = git rev-parse HEAD
python -m PyInstaller packaging/orga-drone.spec --noconfirm --clean --workpath build/rc-build --distpath dist/rc-build
python packaging/rc/package_manual_rc.py --bundle dist/rc-build/orga-drone --analysis-toc build/rc-build/orga-drone/Analysis-00.toc --build-sha $rcSha --output-dir build/manual-rc-package
python packaging/windows_third_party.py verify-zip build/manual-rc-package/orga-drone-manual-rc-$($rcSha.Substring(0,7)).zip
python packaging/rc/smoke_manual_rc.py --package-dir build/manual-rc-package --output-dir build/manual-rc-smoke
```

Use fresh output directories; no existing candidate is replaced. The packager
checks current-checkout module origins, source-byte parity and absence of user
data/media. It copies the available pinned FFmpeg exactly as the documented
release workflow does, writes notices/corresponding sources, packages, verifies
ZIP CRC and compares every extracted file's SHA-256. If the pinned binary is
unavailable, it retains the wheel encoder and records the actual notice verdict;
do not interpret that as distribution approval.

`rc-build.json` and the ZIP checksum sidecar identify the candidate. The ZIP
contains `RC_BUILD.json`, the German checklist, two explicitly synthetic creative
test cubes, the unchanged onefolder app and `Start-Manual-RC.cmd`. It contains no
user footage or existing project database. It is procedurally reproducible from
the recorded commit/environment; no bit-for-bit reproducible-build claim is made.

## Isolation and gates

After extracting, **start `Start-Manual-RC.cmd`**, not the EXE directly. The
starter uses `manual-test-data` beside itself and an ephemeral loopback port,
forces the desktop path and disables E2E/CDP. Closing/reopening through that
starter preserves only this test library. Do not move an existing user database
into it. Exports must use new paths; source media stays where it is.

The smoke runner runs existing packaged synthetic probes sequentially, including
creative and conversion LUT stages. Its local functional metadata has PR/run 0
and no Actions artifact digest: it **cannot be used as main-admission evidence**.
The conversion smoke uses a synthetic SDR fixture and a custom input profile;
it does not validate a DJI D-Log M conversion file.

The runner deliberately returns non-zero while a strict quality gate is failed
or a human/MOTW gate is not tested. Read `smoke-summary.json`: successful process
exit of an individual diagnostic is not a timing/color parity pass. The old
3/255 strict LUT gate, the existing baseline-aware bounded fixture gate, and the
one-frame timing gate are reported separately. #316's real-DJI timing failure
remains failed; a green low-resolution synthetic trace does not supersede it.

Programmatic extraction does **not** test Mark-of-the-Web propagation. The
Explorer extraction/native-dialog/1080p/soundtrack/relaunch checklist in
[packaging/README.md](../README.md) remains mandatory before any later explicitly
authorized publication. Never treat `NOT TESTED` or human acceptance pending as
a release GO.
