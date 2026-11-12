# 2.4.0 execution checkpoint

Updated: 2026-11-12. Integration branch `develop` at `6c38d24`
(`feat(studio): drag and resize SFX clips on the timeline (#184) (#395)`).

GitHub has no milestone objects. This inventory is the issue list from the
2.4.0 execution directive plus `gh issue list --search "2.4.0"`. A merged PR
is not acceptance.

## Issue inventory

| Issue | Feature | State | PR | Acceptance | Blocker | Next action |
|---|---|---|---|---|---|---|
| #184 | Independent SFX timeline | VERIFY | #391 lane, #395 drag merged, #396 waveform open | Drag/trim/keyboard on develop. Waveform + measured ffmpeg PCM mix in #396, CI green. Packaged Windows E2E NOT_RUN. Issue still open. | PO merge of #396 before a package can include waveforms | Leave #396 open. Do not close #184. |
| #211 | Animated color grading | VERIFY | existing color-animation modules on develop | Presets, manual keys, LUT strength fade, undo/persistence exist. WebView2 start/mid/end vs MP4 with a user `.cube`, ease-in-out, and highlights/shadows/blacks are not evidenced. | Full frame-parity E2E | Do not claim #211 done. Next slice needs a bounded parity gap, not a second engine. |
| #267 | Packaged Windows E2E | READY | — | NOT_RUN in this session | Needs a package built from integrated develop | After #396 merges, build from develop with isolated app data. |
| #273 | Secure pairing | BLOCKED | — | Production pairing not started | Security-architecture approval before production implementation. Bounded spike is the only allowed step. | Do not implement production pairing. |
| #274 | Connect assistant settings UX | BLOCKED | — | — | Depends on #273 approval | Wait. |
| #275 | Shared action contract and E2E | VERIFY | matrix exists | A documentation matrix does not complete the issue. Color/library/project/timeline/music contracts have tests. Packaged assistant journey NOT_RUN. | Packaged E2E | Keep extending contracts with real actions (SFX in this checkpoint's PR). |
| #281 | Shared audio/overlay actions | IN_PROGRESS | music + `clip.audio.edit` + `clip.overlays.edit` on develop; SFX commands in the current branch | Music/clip-audio/overlay API tests exist. SFX had UI routes only. Packaged Windows artifact check NOT_RUN. | Packaged export evidence | Land SFX project actions, then exported artifact check. |
| #283 | Real drone footage fixtures | READY | — | Opt-in local media only; nothing committed | — | Privacy-safe manifest, no source media in git. |
| #284 | Parallel development and release gates | READY | — | — | — | After packaged E2E evidence. |
| #293 | Open Media Journey acceptance | VERIFY | #387 merged | API + synthetic evidence. Packaged EXE journey NOT_RUN. | Packaged dispatch | Do not close on unit tests. |
| #294 | HSL/LUT playback on forward loop | VERIFY | Phase A on develop | Backend refuses proxies for repeats and forward loop. Playing loop names HSL/wheels/LUT omission. Phase B loop playback parity is explicitly not a 2.4.0 blocker unless promised. | Phase B only if PO promises loop parity | Do not start a playback-clock rewrite. |
| #295 | Studio UX acceptance | READY | — | Discovery/audit, not a new editor | — | Read the issue and deliver the approved audit outcome. |
| #297 | Local object removal | READY | — | Research/feasibility unless the issue text is an implementation | — | Read acceptance before any code. |
| #298 | Local motion tracking | VERIFY | spike approved | Bounded OpenCV feasibility only. Not a shipping tracker. | — | Deliver spike evidence, do not ship a tracker. |
| #299 | Subject Focus | READY | — | — | — | After #298 spike evidence. |
| #300 | Portrait auto-reframing | READY | — | — | — | Read acceptance; reuse framing, no new engine. |
| #301 | Drone-friendly transitions | VERIFY | #390 discovery merged | Discovery GO for blur dissolve + soft directional wipe. Luma wipe and zoom/spin are NO-GO for V1. ADR 0010 still says wipes stay Later. | ADR 0010 amendment or an explicit implementation approval before shipping new types | Do not ship transitions against ADR 0010. |
| #302 | Dehaze alternatives | BLOCKED | — | FFmpeg-only dehaze is NO-GO | A feasible local alternative still has to be chosen | Do not claim a shipping dehaze. |
| #317 | Windows RC/MOTW | READY | — | NOT_RUN | Release approval | Maintainer step. Do not publish. |
| #320 | Strict color parity | VERIFY | closed on GitHub | Closed is not acceptance evidence in this checkpoint | — | Re-read the closed issue before any new parity work. |
| #325 | Timelapse target duration | BLOCKED | #389 confirm merged; target-duration MVP not approved | Issue text: discovery first, implementation needs explicit PO approval. Not a current-release blocker per the issue. | PO GO/NO-GO on the target-duration MVP | Do not code the MVP. |
| #331 | Source/Story clocks | VERIFY | #392 ADR 0037 merged `0cb3d35` | ADR accepted | — | Region work landed in #332. |
| #332 | Bounded speed-ramp region | VERIFY | #394 merged `9f927d4` | Focused Python/JS tests passed before merge. Packaged E2E NOT_RUN. PO has not accepted the issue. | PO acceptance | Do not reimplement. |
| #333 | Timelapse/ramp conflict | VERIFY | #389 merged | Confirm UI merged. Issue may still be open if acceptance is wider. | — | Re-read before more code. |
| #351 | Color persistence/recovery | BLOCKED | — | — | ADR 0035 and the persistence/backup/downgrade approval | Do not migrate `effect_settings`. |
| #352–#366 | Color Workspace | BLOCKED | — | — | Same gate as #351 | Do not start a second grade model. |

## Open pull requests

- #396 `feat/184-sfx-waveform` at `7242d96`. CI success, mergeable. Does not close #184. Packaged Windows E2E NOT_RUN. Do not merge without PO authorization.

## Worktrees

- `issue-184-sfx-wave` — `feat/184-sfx-waveform` (PR #396). Do not add commits unless review asks.
- `issue-281-sfx-actions` — `feat/281-sfx-actions` from `6c38d24`. Active.
- Older worktrees for #332 and #184 drag match merged commits. Do not keep editing them.

## PO decisions already received

- ADR 0037 approved and merged.
- #298 bounded OpenCV spike approved. Not a product tracker.
- #302 FFmpeg-only dehaze is NO-GO.
- Do not merge or release without explicit authorization.

## Pending approvals (asked once here; do not repeat)

1. ADR 0035 Color Workspace architecture, before #351–#366.
2. #351 backup, recovery, and downgrade strategy.
3. #273 security architecture, before production pairing.
4. #325 target-duration MVP GO/NO-GO (the issue requires it).
5. ADR 0010 follow-up: ship blur dissolve and soft directional wipe, or keep them Later.

## Exact next task

Finish and open the SFX Control API PR from `feat/281-sfx-actions`. Then continue the next READY issue that does not wait on #396 or the approvals above (#295 audit, or #300/#297 after reading their acceptance). Do not build the Windows package until #396 is merged if the package is supposed to include waveforms.
