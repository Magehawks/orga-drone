# 2.4.0 execution checkpoint

Updated: 2026-11-13. Integration branch `develop` at `88c79e9`
(`feat(studio): add blur dissolve and soft directional wipes (#301) (#401)`).

GitHub has no milestone objects. This inventory is the issue list from the
2.4.0 execution directive plus `gh issue list --search "2.4.0"`. A merged PR
is not acceptance.

## Issue inventory

| Issue | Feature | State | PR | Acceptance | Blocker | Next action |
|---|---|---|---|---|---|---|
| #184 | Independent SFX timeline | VERIFY | #395, #396, #400 merged `2c1108a` | Local onefolder WebView2 E2E PASS. Evidence `docs/planning/184-local-packaged-e2e.json`. GitHub release-ZIP admission NOT_RUN. | PO acceptance | Leave #184 open. |
| #211 | Animated color grading | VERIFY | existing color-animation modules on develop | Presets exist. WebView2 start/mid/end vs MP4 frame-parity is not evidenced. | Full frame-parity E2E | Do not claim #211 done. |
| #267 | Packaged Windows E2E | VERIFY | local onefolder run recorded in #400 | Local WebView2 journey PASS. GitHub release-ZIP admission NOT_RUN. | PR to `main` admission | Do not call the local run a release admission. |
| #273 | Secure pairing | VERIFY | #403 | Threat model only. No production pairing, no stored key. Same-user process risk remains. | Reviewed security contract | Do not ship pairing. |
| #274 | Connect assistant settings UX | BLOCKED | — | — | Depends on #273 approval | Wait. |
| #275 | Shared action contract and E2E | VERIFY | matrix exists | Packaged assistant journey NOT_RUN. | Packaged E2E | Keep extending contracts with real actions. |
| #281 | Shared audio/overlay actions | VERIFY | #397 merged | Packaged journey set one SFX volume to 0.35 through `sfx.update`. Full artifact audit NOT_RUN. | PO acceptance | Do not close #281. |
| #283 | Real drone footage fixtures | READY | — | Opt-in local media only; nothing committed | — | Privacy-safe manifest, no source media in git. |
| #284 | Parallel development and release gates | READY | — | — | — | After packaged E2E evidence. |
| #293 | Open Media Journey acceptance | VERIFY | #387 merged | API + synthetic evidence. Packaged EXE journey NOT_RUN. | Packaged dispatch | Do not close on unit tests. |
| #294 | HSL/LUT playback on forward loop | VERIFY | Phase A on develop | Phase B loop playback parity is not a 2.4.0 blocker unless promised. | Phase B only if PO promises loop parity | Do not start a playback-clock rewrite. |
| #295 | Studio UX acceptance | READY | — | Discovery/audit, not a new editor | — | Read the issue and deliver the approved audit outcome. |
| #297 | Local object removal | DONE | #398 merged `e397c26` | PO accepted the NO-GO. No removal UI. OpenCV is not packaged for this purpose. | — | Do not reopen as a feature. |
| #298 | Local motion tracking | VERIFY | #402 | Synthetic optical-flow spike. Recommendation NO-GO for a 2.4.0 tracker. Real footage NOT_RUN. | PO acceptance of the NO-GO | Do not ship a tracker or package OpenCV. |
| #299 | Subject Focus | READY | — | — | — | After #298 spike evidence. |
| #300 | Portrait auto-reframing | VERIFY | manual Ken Burns crop already in `studio_frame.py` | Automatic detection is forbidden. Subject following waits on #298. | #298 evidence | Do not add a second crop model. |
| #301 | Drone-friendly transitions | VERIFY | #401 merged `88c79e9` | Blur dissolve and four soft wipes landed. Packaged WebView2 for these transitions is NOT_RUN. | PO acceptance | Do not reimplement. Do not add more transition types. |
| #302 | Dehaze alternatives | BLOCKED | — | FFmpeg-only dehaze is NO-GO | A feasible local alternative still has to be chosen | Do not claim a shipping dehaze. |
| #317 | Windows RC/MOTW | READY | — | NOT_RUN | Release approval | Maintainer step. Do not publish. |
| #320 | Strict color parity | VERIFY | closed on GitHub | Closed is not acceptance evidence in this checkpoint | — | Re-read the closed issue before any new parity work. |
| #325 | Timelapse target duration | VERIFY | #404 | Target-duration draft drives decoded MP4 evidence (trimmed+music, 1080p). Journey smoke now adds clips in a fixed red-then-blue order. Packaged WebView2 Timelapse Inspector is NOT_RUN. | PO acceptance | Do not build a second speed engine. |
| #331 | Source/Story clocks | VERIFY | #392 ADR 0037 merged `0cb3d35` | ADR accepted | — | Region work landed in #332. |
| #332 | Bounded speed-ramp region | VERIFY | #394 merged `9f927d4` | Packaged E2E NOT_RUN. PO has not accepted the issue. | PO acceptance | Do not reimplement. |
| #333 | Timelapse/ramp conflict | VERIFY | #389 merged | Confirm UI merged. Issue may still be open if acceptance is wider. | — | Re-read before more code. |
| #351 | Color persistence/recovery | VERIFY | #399 | Staged copy and atomic replace. Canonical writes and startup refusal stay disabled. | PO re-review / merge | Do not enable canonical writes. |
| #352 | Managed SDR LUT contract | VERIFY | #405 | Read-only transfers and tetrahedral 3D LUT sampling. Legacy import/export unchanged. Managed parity gate NOT_RUN. | PO review; #351 before canonical writes | Do not wire into export yet. |
| #353 | Managed primaries | VERIFY | #406 | Read-only exposure/balance/contrast/tone/saturation. Kelvin/tint and tonal-slider mapping unpublished. | PO review; Kelvin/tint vectors | Do not write canonical grades. |
| #354 | Managed curve operators | VERIFY | this branch | Read-only RGB/luma/hue/saturation curves. No UI. No canonical writes. | PO review | Do not bake unbounded spatial ops. |
| #355 | Managed wheels/HSL | VERIFY | this branch | Read-only wheels-v1 and managed HSL adapters. Legacy modules unchanged. | PO review | No canonical writes. |
| #356–#366 | Color Workspace remainder | READY | — | Continue after #351 and prior color PRs. | #351 verification | No silent legacy conversion. |

## Open pull requests

- #399 grade backup. Canonical writes stay disabled.
- #402 tracking spike. NO-GO for a production tracker.
- #403 pairing spike. No production pairing.
- #404 target-duration export evidence. Journey clip order fixed. Packaged Timelapse Inspector NOT_RUN.
- #405 managed LUT sampling. Not wired to export.
- #406 managed primaries. Kelvin/tint unpublished.
- This branch: managed wheels/HSL for #355. No UI.
- `issue-354-curves` — PR #407.

## Worktrees

- `issue-354-curves` — managed curves.
- `issue-325-timelapse` — PR #404.
- `issue-351-grade-backup` — PR #399.
- `issue-298-tracking` — PR #402.
- `issue-273-pairing-spike` — PR #403.
- `issue-352-managed-lut` — PR #405.
- `issue-353-primaries` — PR #406.
- `issue-301-transitions` / `issue-184-packaged-e2e` — merged. Do not keep editing them.

## PO decisions already received

- ADR 0035 accepted. Canonical writes stay disabled until #351 safeguards are verified.
- ADR 0037 approved and merged.
- #297 NO-GO accepted. No removal UI and no packaged OpenCV for that purpose.
- #301 GO for blur dissolve and one soft directional wipe family; merged via #401.
- #325 target-duration MVP is GO. Do not build a second speed engine.
- #351 backup strategy approved. Production canonical writes stay off until backup and restore are verified.
- #273 bounded security spike approved. Production pairing stays gated.
- #298 bounded OpenCV spike approved. Not a product tracker.
- #302 FFmpeg-only dehaze is NO-GO.
- Do not merge or release without explicit authorization.

## Exact next task

#355 adds read-only wheels-v1 and managed HSL. No UI and no canonical writes. Continue #356 masks next. Packaged Timelapse Inspector and GitHub release-ZIP admission remain NOT_RUN. Do not merge without PO approval.
