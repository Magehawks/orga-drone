# 2.4.0 execution checkpoint

Updated: 2026-11-12. Integration branch `develop` at `f4e688a`
(`feat(control): place Studio sound effects through shared actions (#281) (#397)`).
#396 and #397 are merged.

GitHub has no milestone objects. This inventory is the issue list from the
2.4.0 execution directive plus `gh issue list --search "2.4.0"`. A merged PR
is not acceptance.

## Issue inventory

| Issue | Feature | State | PR | Acceptance | Blocker | Next action |
|---|---|---|---|---|---|---|
| #184 | Independent SFX timeline | VERIFY | #391, #395, #396 merged (`1c929bd`) | Local onefolder WebView2 run PASS: two SFX clips, music, painted waveforms, drag to 1.97 s, keyboard trim, undo/redo, reopen, export audio peak 0.412. Evidence `docs/planning/184-local-packaged-e2e.json`. GitHub ZIP admission NOT_RUN (that workflow runs on PRs to `main`). | PO acceptance | Do not close #184 on the local run alone. |
| #211 | Animated color grading | VERIFY | existing color-animation modules on develop | Presets, manual keys, LUT strength fade, undo/persistence exist. WebView2 start/mid/end vs MP4 with a user `.cube`, ease-in-out, and highlights/shadows/blacks are not evidenced. | Full frame-parity E2E | Do not claim #211 done. Next slice needs a bounded parity gap, not a second engine. |
| #267 | Packaged Windows E2E | VERIFY | local onefolder from `f4e688a` | Same run as #184. Isolated data dir. Not the GitHub admission artifact. | ZIP admission on a PR to `main` | Do not publish. |
| #273 | Secure pairing | READY | — | Bounded security spike approved. Preferred design: per-connection credentials, DPAPI, user approval, revocation. Production pairing still needs a reviewed contract. | Production implementation | Write the threat-model spike. Do not ship pairing. |
| #274 | Connect assistant settings UX | BLOCKED | — | — | Depends on #273 approval | Wait. |
| #275 | Shared action contract and E2E | VERIFY | matrix exists | A documentation matrix does not complete the issue. Color/library/project/timeline/music contracts have tests. Packaged assistant journey NOT_RUN. | Packaged E2E | Keep extending contracts with real actions (SFX in this checkpoint's PR). |
| #281 | Shared audio/overlay actions | VERIFY | #397 merged `f4e688a` | Packaged WebView2 journey set one SFX volume to 0.35 through `sfx.update` and the export still decoded. Clip audio and overlay artifact checks beyond that command are not in this run. | PO acceptance | Do not close #281 yet. |
| #283 | Real drone footage fixtures | READY | — | Opt-in local media only; nothing committed | — | Privacy-safe manifest, no source media in git. |
| #284 | Parallel development and release gates | READY | — | — | — | After packaged E2E evidence. |
| #293 | Open Media Journey acceptance | VERIFY | #387 merged | API + synthetic evidence. Packaged EXE journey NOT_RUN. | Packaged dispatch | Do not close on unit tests. |
| #294 | HSL/LUT playback on forward loop | VERIFY | Phase A on develop | Backend refuses proxies for repeats and forward loop. Playing loop names HSL/wheels/LUT omission. Phase B loop playback parity is explicitly not a 2.4.0 blocker unless promised. | Phase B only if PO promises loop parity | Do not start a playback-clock rewrite. |
| #295 | Studio UX acceptance | READY | — | Discovery/audit, not a new editor | — | Read the issue and deliver the approved audit outcome. |
| #297 | Local object removal | VERIFY | #398 updated `9a8d136` | Moving-camera before/after PNGs, shadow kept, synthetic flicker 0, align 2.238 s. Real footage NOT_RUN. NO-GO for a tool. | PO re-review | Do not add a removal UI or package OpenCV. |
| #298 | Local motion tracking | VERIFY | spike approved | Bounded OpenCV feasibility only. Not a shipping tracker. | — | Deliver spike evidence, do not ship a tracker. |
| #299 | Subject Focus | READY | — | — | — | After #298 spike evidence. |
| #300 | Portrait auto-reframing | VERIFY | manual Ken Burns crop already in `studio_frame.py` | Issue says a later milestone and forbids automatic detection. Manual crop/pan exists. Subject following waits on the #298 spike. | #298 evidence, then an explicit follow implementation | Do not add a second crop model. |
| #301 | Drone-friendly transitions | READY | #390 discovery merged | PO GO for blur dissolve and one soft directional wipe. ADR 0010 must be amended in the same implementation. Luma wipe and zoom/spin stay out. | Amend ADR 0010 before the new type ids ship | Implement those two types with preview and export. |
| #302 | Dehaze alternatives | BLOCKED | — | FFmpeg-only dehaze is NO-GO | A feasible local alternative still has to be chosen | Do not claim a shipping dehaze. |
| #317 | Windows RC/MOTW | READY | — | NOT_RUN | Release approval | Maintainer step. Do not publish. |
| #320 | Strict color parity | VERIFY | closed on GitHub | Closed is not acceptance evidence in this checkpoint | — | Re-read the closed issue before any new parity work. |
| #325 | Timelapse target duration | VERIFY | inspector and `studio_timelapse.py` already on develop | PO GO for the bounded MVP. Target-duration math, trim, limits, preview, and ramp confirmation already exist. Packaged Windows and exported MP4 evidence for this control are NOT_RUN. | Do not build a second speed engine | Compare the inspector with the acceptance list before adding code. |
| #331 | Source/Story clocks | VERIFY | #392 ADR 0037 merged `0cb3d35` | ADR accepted | — | Region work landed in #332. |
| #332 | Bounded speed-ramp region | VERIFY | #394 merged `9f927d4` | Focused Python/JS tests passed before merge. Packaged E2E NOT_RUN. PO has not accepted the issue. | PO acceptance | Do not reimplement. |
| #333 | Timelapse/ramp conflict | VERIFY | #389 merged | Confirm UI merged. Issue may still be open if acceptance is wider. | — | Re-read before more code. |
| #351 | Color persistence/recovery | IN_PROGRESS | #399 open (`e5c830e`) | ADR 0035 accepted. Backup/restore helper verified. Canonical writes and startup refusal are not enabled. | PO merge, then wire startup only with the canonical file | Do not migrate existing grades. |
| #352–#366 | Color Workspace | IN_PROGRESS | #352 managed LUT math on this branch | ADR 0035 accepted. Read-only sRGB/BT.709 transfers and 3D LUT sampling. Canonical writes stay disabled. Export still uses the legacy LUT parser. Managed parity gate NOT_RUN. | #351 verification before any canonical write | Do not write canonical grades. |

## Open pull requests

- #398 `feat/297-removal-spike` at `9a8d136`. Moving-camera evidence added. NO-GO for a Studio tool. Awaiting PO re-review.
- #399 `feat/351-grade-backup` at `e5c830e`. Backup/restore helper and ADR 0035 acceptance. Canonical writes stay off.

## Worktrees

- `issue-184-packaged-e2e` — harness and local onefolder at `dist/orga-drone/orga-drone.exe`. Isolated run data is outside the repo.
- `issue-297-removal-spike` — PR #398.
- `issue-351-grade-backup` — PR #399.

## PO decisions already received

- ADR 0035 accepted. No canonical production writes until #351 safeguards are verified.
- #351 backup, checksum, user-only permissions, and tested restore are the approved strategy.
- #273 bounded security spike approved. Production pairing stays gated.
- #325 target-duration MVP is GO. Do not duplicate the inspector that is already on develop.
- #301 GO for blur dissolve and one soft directional wipe, after amending ADR 0010.
- #298 remains a feasibility spike, not a product tracker.
- #302 FFmpeg-only dehaze is NO-GO.
- Do not merge or release without explicit authorization.

## Exact next task

#352 adds read-only managed SDR transfer and 3D LUT sampling. It does not change legacy import or export, and it does not enable canonical writes. Packaged managed-color evidence remains NOT_RUN. Do not merge without PO approval.
