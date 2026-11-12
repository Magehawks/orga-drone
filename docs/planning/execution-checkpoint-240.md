# 2.4.0 execution checkpoint

Updated: 2026-11-12. Integration branch `develop` at `2c1108a`
(`test(e2e): verify packaged SFX lane and control actions (#184) (#400)`).

GitHub has no milestone objects. This inventory is the issue list from the
2.4.0 execution directive plus `gh issue list --search "2.4.0"`. A merged PR
is not acceptance.

## Issue inventory

| Issue | Feature | State | PR | Acceptance | Blocker | Next action |
|---|---|---|---|---|---|---|
| #184 | Independent SFX timeline | VERIFY | #395, #396, #400 merged `2c1108a` | Local onefolder WebView2 E2E PASS: two SFX clips, music, waveforms, drag, trim, undo, export. Evidence `docs/planning/184-local-packaged-e2e.json`. GitHub release-ZIP admission NOT_RUN. | PO acceptance | Leave #184 open. |
| #211 | Animated color grading | VERIFY | existing color-animation modules on develop | Presets, manual keys, LUT strength fade, undo/persistence exist. WebView2 start/mid/end vs MP4 with a user `.cube`, ease-in-out, and highlights/shadows/blacks are not evidenced. | Full frame-parity E2E | Do not claim #211 done. Next slice needs a bounded parity gap, not a second engine. |
| #267 | Packaged Windows E2E | VERIFY | local onefolder run recorded in #400 | Local WebView2 journey PASS. GitHub release-ZIP admission NOT_RUN. | That admission runs only for a pull request to `main` | Do not call the local run a release admission. |
| #273 | Secure pairing | READY | — | Bounded security spike approved. Preferred design: per-connection credentials, DPAPI, user approval, revocation. Production pairing still needs a reviewed contract. | Production implementation | Write the threat-model spike. Do not ship pairing. |
| #274 | Connect assistant settings UX | BLOCKED | — | — | Depends on #273 approval | Wait. |
| #275 | Shared action contract and E2E | VERIFY | matrix exists | A documentation matrix does not complete the issue. Color/library/project/timeline/music contracts have tests. Packaged assistant journey NOT_RUN. | Packaged E2E | Keep extending contracts with real actions. |
| #281 | Shared audio/overlay actions | VERIFY | #397 merged | Packaged WebView2 journey set one SFX volume to 0.35 through `sfx.update`. Full clip-audio and overlay artifact audit NOT_RUN. | PO acceptance | Do not close #281. |
| #283 | Real drone footage fixtures | READY | — | Opt-in local media only; nothing committed | — | Privacy-safe manifest, no source media in git. |
| #284 | Parallel development and release gates | READY | — | — | — | After packaged E2E evidence. |
| #293 | Open Media Journey acceptance | VERIFY | #387 merged | API + synthetic evidence. Packaged EXE journey NOT_RUN. | Packaged dispatch | Do not close on unit tests. |
| #294 | HSL/LUT playback on forward loop | VERIFY | Phase A on develop | Backend refuses proxies for repeats and forward loop. Playing loop names HSL/wheels/LUT omission. Phase B loop playback parity is explicitly not a 2.4.0 blocker unless promised. | Phase B only if PO promises loop parity | Do not start a playback-clock rewrite. |
| #295 | Studio UX acceptance | READY | — | Discovery/audit, not a new editor | — | Read the issue and deliver the approved audit outcome. |
| #297 | Local object removal | DONE | #398 merged `e397c26` | PO accepted the NO-GO. No removal UI. OpenCV is not packaged for this purpose. | — | Do not reopen as a feature. |
| #298 | Local motion tracking | VERIFY | spike approved | Bounded OpenCV feasibility only. Not a shipping tracker. | — | Deliver spike evidence, do not ship a tracker. |
| #299 | Subject Focus | READY | — | — | — | After #298 spike evidence. |
| #300 | Portrait auto-reframing | VERIFY | manual Ken Burns crop already in `studio_frame.py` | Issue says a later milestone and forbids automatic detection. Manual crop/pan exists. Subject following waits on the #298 spike. | #298 evidence, then an explicit follow implementation | Do not add a second crop model. |
| #301 | Drone-friendly transitions | VERIFY | #401 | Blur dissolve and four soft wipes share crossfade occupancy. Smooth easing stays on crossfade only. Real FFmpeg MP4 frames distinguish hblur from a left wipe. Packaged WebView2 is NOT_RUN. | PO re-review after green CI | Do not add more transition types. |
| #302 | Dehaze alternatives | BLOCKED | — | FFmpeg-only dehaze is NO-GO | A feasible local alternative still has to be chosen | Do not claim a shipping dehaze. |
| #317 | Windows RC/MOTW | READY | — | NOT_RUN | Release approval | Maintainer step. Do not publish. |
| #320 | Strict color parity | VERIFY | closed on GitHub | Closed is not acceptance evidence in this checkpoint | — | Re-read the closed issue before any new parity work. |
| #325 | Timelapse target duration | VERIFY | inspector already on develop | PO approved the bounded MVP. Target-duration math already exists. Packaged Windows and exported MP4 evidence for this control are NOT_RUN. | That evidence | Do not build a second speed engine. |
| #331 | Source/Story clocks | VERIFY | #392 ADR 0037 merged `0cb3d35` | ADR accepted | — | Region work landed in #332. |
| #332 | Bounded speed-ramp region | VERIFY | #394 merged `9f927d4` | Focused Python/JS tests passed before merge. Packaged E2E NOT_RUN. PO has not accepted the issue. | PO acceptance | Do not reimplement. |
| #333 | Timelapse/ramp conflict | VERIFY | #389 merged | Confirm UI merged. Issue may still be open if acceptance is wider. | — | Re-read before more code. |
| #351 | Color persistence/recovery | IN_PROGRESS | #399 | Staged copy and atomic replace. Canonical writes and startup refusal stay disabled. | PO re-review after green CI | Do not enable canonical writes. |
| #352–#366 | Color Workspace | READY | — | ADR 0035 accepted. Read-only contracts only until #351 safeguards are verified. | #351 verification | Do not write canonical grades. |

## Open pull requests

- #399 grade backup. Canonical writes stay disabled. Restore uses a verified sibling and `os.replace`.
- #401 drone transitions. Smooth easing stays on crossfade. Real MP4 frames for blur dissolve and a left wipe. Packaged WebView2 NOT_RUN.

## Worktrees

- `issue-301-transitions` — PR #401.
- `issue-351-grade-backup` — PR #399.
- `issue-184-packaged-e2e` — merged as #400. Do not keep editing it.

## PO decisions already received

- ADR 0035 accepted. Canonical writes stay disabled until #351 safeguards are verified.
- ADR 0037 approved and merged.
- #297 NO-GO accepted. No removal UI and no packaged OpenCV for that purpose.
- #301 GO for blur dissolve and one soft directional wipe family, after amending ADR 0010.
- #325 target-duration MVP is GO. The inspector already exists.
- #351 backup strategy approved. Production canonical writes stay off until backup and restore are verified.
- #273 bounded security spike approved. Production pairing stays gated.
- #298 bounded OpenCV spike approved. Not a product tracker.
- #302 FFmpeg-only dehaze is NO-GO.
- Do not merge or release without explicit authorization.

## Exact next task

#400 is merged at `2c1108a`. Local WebView2 E2E is PASS. GitHub release-ZIP admission remains NOT_RUN. #401 and #399 address the PO review findings and wait for green CI before re-review. Next implementation is the #298 feasibility spike, then the #273 security spike. Do not enable canonical grade writes.
