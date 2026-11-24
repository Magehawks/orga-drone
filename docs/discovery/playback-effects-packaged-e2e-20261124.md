# Packaged WebView2 E2E — playback / transitions / LUT (#294 / #301 / #211)

Date: 2026-11-24  
Branch: `feat/playback-effects-complete-211-294-301`  
Develop baseline: `572d6e6` (includes #569 Phase B)  
EXE: clean-venv PyInstaller `dist-playback-effects/orga-drone/orga-drone.exe`  
Harness: `packaging/e2e/windows_e2e.py --local`  
Evidence JSON: `acceptance-evidence/playback-effects-e2e/20261124-170507/evidence.json`

## Journey results

| Journey | Result | Notes |
|---|---|---|
| playback | PASS | currentTime advanced while playing |
| timeline_transitions | PASS | `crossfade`, `blur_dissolve`, `soft_wipe_left` persisted/applied; no fallback cut |
| lut_parity | PASS | synthetic `.cube` preview vs export means within harness tolerance |
| undo_redo_timeline | PASS | |
| export / export_1080p | PASS | |
| Overall evidence.result | **pass** | |

## Explicitly NOT claimed

- Real private drone footage (no private media in tree)
- Pixel-identical soft-wipe / blur dissolve preview vs export (ADR 0010 approximation; prior Story soft-wipe NO-GO unchanged)
- Whip / luma / zoom / motion-match (blocked; normalize → cut)
- Color-accurate loop playback while color-animation / speed≠1 / clip-audio is active (fail-closed proxy policy)

## Reproduction

```powershell
python -m venv .venv-playback
.\.venv-playback\Scripts\python.exe -m pip install -e ".[dev]" pyinstaller
.\.venv-playback\Scripts\pyinstaller.exe packaging\orga-drone.spec --noconfirm --clean --distpath dist-playback-effects --workpath build-playback-effects
$exe = Resolve-Path dist-playback-effects\orga-drone\orga-drone.exe
$ffmpeg = Resolve-Path packaging\third_party\ffmpeg-gpl\bin\ffmpeg.exe
.\.venv-playback\Scripts\python.exe packaging\e2e\windows_e2e.py --local --exe $exe --output-dir acceptance-evidence\playback-effects-e2e\<run> --ffmpeg $ffmpeg --head-sha (git rev-parse HEAD) --base-sha (git rev-parse origin/develop) --merge-sha (git rev-parse HEAD) --tree-sha (git rev-parse 'HEAD^{tree}') --pr-number 0 --repository Magehawks/orga-drone
```
