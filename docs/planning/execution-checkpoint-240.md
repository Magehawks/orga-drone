# 2.4.0 execution checkpoint

Updated: 2026-11-12. Integration branch `develop` at `e397c26`
(`docs(discovery): measure local object-removal limits (#297) (#398)`).

GitHub has no milestone objects. This inventory is the issue list from the
2.4.0 execution directive plus `gh issue list --search "2.4.0"`. A merged PR
is not acceptance.

## Issue inventory

| Issue | Feature | State | PR | Acceptance | Blocker | Next action |
|---|---|---|---|---|---|---|
| #184 | Independent SFX timeline | VERIFY | #395, #396 merged. #400 open, CI green | Local onefolder WebView2 E2E PASS (two SFX, music, waveforms, drag/trim, undo, export). GitHub release-ZIP admission NOT_RUN; that workflow runs only on pull requests to `main`. | PO review of #400. Do not close on the local run. | Leave #184 open. |
| #211 | Animated color grading | VERIFY | existing color-animation modules on develop | Presets, manual keys, LUT strength fade, undo/persistence exist. WebView2 start/mid/end vs MP4 with a user `.cube`, ease-in-out, and highlights/shadows/blacks are not evidenced. | Full frame-parity E2E | Do not claim #211 done. Next slice needs a bounded parity gap, not a second engine. |
| #267 | Packaged Windows E2E | VERIFY | local onefolder run recorded in #400 | Local WebView2 journey PASS. GitHub release-ZIP admission NOT_RUN. | That admission runs only for a pull request to `main` | Do not call the local run a release admission. |
| #273 | Secure pairing | READY | — | Production pairing not started. The bounded security spike is approved. | A reviewed security contract before production pairing | Do not implement production pairing. |
| #274 | Connect assistant settings UX | BLOCKED | — | — | Depends on #273 approval | Wait. |
| #275 | Shared action contract and E2E | VERIFY | matrix exists | A documentation matrix does not complete the issue. Color/library/project/timeline/music contracts have tests. Packaged assistant journey NOT_RUN. | Packaged E2E | Keep extending contracts with real actions (SFX in this checkpoint's PR). |
| #281 | Shared audio/overlay actions | VERIFY | #397 merged | SFX actions are on develop. The local packaged journey set one SFX volume to 0.35. Full clip-audio and overlay artifact audit NOT_RUN. | PO acceptance | Do not close #281. |
| #283 | Real drone footage fixtures | READY | — | Opt-in local media only; nothing committed | — | Privacy-safe manifest, no source media in git. |
| #284 | Parallel development and release gates | READY | — | — | — | After packaged E2E evidence. |
| #293 | Open Media Journey acceptance | VERIFY | #387 merged | API + synthetic evidence. Packaged EXE journey NOT_RUN. | Packaged dispatch | Do not close on unit tests. |
| #294 | HSL/LUT playback on forward loop | VERIFY | Phase A on develop | Backend refuses proxies for repeats and forward loop. Playing loop names HSL/wheels/LUT omission. Phase B loop playback parity is explicitly not a 2.4.0 blocker unless promised. | Phase B only if PO promises loop parity | Do not start a playback-clock rewrite. |
| #295 | Studio UX acceptance | READY | — | Discovery/audit, not a new editor | — | Read the issue and deliver the approved audit outcome. |
| #297 | Local object removal | DONE | #398 merged `e397c26` | PO accepted the NO-GO. No removal UI. OpenCV is not packaged for this purpose. | — | Do not reopen as a feature. |
| #298 | Local motion tracking | VERIFY | spike approved | Bounded OpenCV feasibility only. Not a shipping tracker. | — | Deliver spike evidence, do not ship a tracker. |
| #299 | Subject Focus | READY | — | — | — | After #298 spike evidence. |
| #300 | Portrait auto-reframing | VERIFY | manual Ken Burns crop already in `studio_frame.py` | Issue says a later milestone and forbids automatic detection. Manual crop/pan exists. Subject following waits on the #298 spike. | #298 evidence, then an explicit follow implementation | Do not add a second crop model. |
| #301 | Drone-friendly transitions | IN_PROGRESS | this branch amends ADR 0010 | Blur dissolve and four soft wipes share crossfade occupancy, preview, and xfade export. Luma wipe, whip pan, and zoom/spin stay out. Packaged WebView2 and a real MP4 for these types are NOT_RUN. | PO review | Do not add more transition types. |
| #302 | Dehaze alternatives | BLOCKED | — | FFmpeg-only dehaze is NO-GO | A feasible local alternative still has to be chosen | Do not claim a shipping dehaze. |
| #317 | Windows RC/MOTW | READY | — | NOT_RUN | Release approval | Maintainer step. Do not publish. |
| #320 | Strict color parity | VERIFY | closed on GitHub | Closed is not acceptance evidence in this checkpoint | — | Re-read the closed issue before any new parity work. |
| #325 | Timelapse target duration | VERIFY | inspector already on develop | PO approved the bounded MVP. Target-duration math already exists. Packaged Windows and exported MP4 evidence for this control are NOT_RUN. | That evidence | Do not build a second speed engine. |
| #331 | Source/Story clocks | VERIFY | #392 ADR 0037 merged `0cb3d35` | ADR accepted | — | Region work landed in #332. |
| #332 | Bounded speed-ramp region | VERIFY | #394 merged `9f927d4` | Focused Python/JS tests passed before merge. Packaged E2E NOT_RUN. PO has not accepted the issue. | PO acceptance | Do not reimplement. |
| #333 | Timelapse/ramp conflict | VERIFY | #389 merged | Confirm UI merged. Issue may still be open if acceptance is wider. | — | Re-read before more code. |
| #351 | Color persistence/recovery | IN_PROGRESS | #399 open | Backup/restore helper exists. Canonical database file is not created. Startup refusal is not switched on. Production canonical writes stay disabled. | PO review, then verified backup before any canonical write | Do not enable canonical writes. |
| #352–#366 | Color Workspace | READY | — | ADR 0035 accepted. Read-only contracts only until #351 safeguards are verified. | #351 verification | Do not write canonical grades. |

## Open pull requests

- #399 grade backup. Canonical writes stay disabled.
- #400 packaged SFX E2E. Local onefolder WebView2 PASS. GitHub CI green after the `placed` annotation. GitHub release-ZIP admission NOT_RUN.
- #301 drone transitions, this branch. Preview/export unit tests passed. Packaged evidence NOT_RUN.

## Worktrees

- `issue-184-sfx-wave` — `feat/184-sfx-waveform` (PR #396). Do not add commits unless review asks.
- `issue-281-sfx-actions` — `feat/281-sfx-actions` from `6c38d24`. Active.
- Older worktrees for #332 and #184 drag match merged commits. Do not keep editing them.

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

Request PO review of #400 now that CI is green. Do not describe the GitHub release-ZIP admission as passed. After this transition PR, continue #298 feasibility evidence and the #273 security spike. Do not enable canonical grade writes.
