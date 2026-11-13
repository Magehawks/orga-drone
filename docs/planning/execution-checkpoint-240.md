# 2.4.0 execution checkpoint

Updated: 2026-11-13. Integration branch `develop` includes `#401` and `#402`.

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
| #295 | Studio UX acceptance | VERIFY | #411 | Discovery recommends Concept C: keep shipped hybrid ramp, declutter Speed panel. Packaged WebView2 NOT_RUN. | PO selection of Concept C | Do not rebuild the speed engine. |
| #297 | Local object removal | DONE | #398 merged `e397c26` | PO accepted the NO-GO. No removal UI. OpenCV is not packaged for this purpose. | — | Do not reopen as a feature. |
| #298 | Local motion tracking | VERIFY | #402 merged | Synthetic optical-flow spike. Recommendation NO-GO for a 2.4.0 tracker. Real footage NOT_RUN. | PO acceptance of the NO-GO | Do not ship a tracker or package OpenCV. |
| #299 | Subject Focus | READY | — | — | — | After #298 spike evidence. |
| #300 | Portrait auto-reframing | VERIFY | manual Ken Burns crop already in `studio_frame.py` | Automatic detection is forbidden. Subject following waits on #298. | #298 evidence | Do not add a second crop model. |
| #301 | Drone-friendly transitions | VERIFY | #401 merged `88c79e9` | Blur dissolve and four soft wipes landed. Packaged WebView2 for these transitions is NOT_RUN. | PO acceptance | Do not reimplement. Do not add more transition types. |
| #302 | Dehaze alternatives | BLOCKED | — | FFmpeg-only dehaze is NO-GO | A feasible local alternative still has to be chosen | Do not claim a shipping dehaze. |
| #317 | Windows RC/MOTW | READY | — | NOT_RUN | Release approval | Maintainer step. Do not publish. |
| #320 | Strict color parity | VERIFY | closed on GitHub | Closed is not acceptance evidence in this checkpoint | — | Re-read the closed issue before any new parity work. |
| #325 | Timelapse target duration | VERIFY | #404 | Target-duration draft drives decoded MP4 evidence. Journey smoke uses fixed red-then-blue clip order. Packaged WebView2 Timelapse Inspector is NOT_RUN. | PO acceptance | Do not build a second speed engine. |
| #331 | Source/Story clocks | VERIFY | #392 ADR 0037 merged `0cb3d35` | ADR accepted | — | Region work landed in #332. |
| #332 | Bounded speed-ramp region | VERIFY | #394 merged `9f927d4` | Packaged E2E NOT_RUN. PO has not accepted the issue. | PO acceptance | Do not reimplement. |
| #333 | Timelapse/ramp conflict | VERIFY | #389 merged | Confirm UI merged. Issue may still be open if acceptance is wider. | — | Re-read before more code. |
| #351 | Color persistence/recovery | VERIFY | #399 | Staged copy and atomic replace. Canonical writes and startup refusal stay disabled. Helper-only; does not close #351. | PO acceptance; wire only with verified safeguards | Do not enable canonical writes. |
| #352 | Managed SDR LUT contract | VERIFY | #405 | Read-only transfers and tetrahedral 3D LUT sampling. Legacy import/export unchanged. Managed parity gate NOT_RUN. | Preview/export wiring; #351 before canonical writes | Do not claim #352 complete. |
| #353 | Managed primaries | VERIFY | #406 | Read-only exposure/balance/contrast/tone/saturation. Kelvin/tint unpublished. | Kelvin/tint vectors; UI/render | Do not claim #353 complete. |
| #354 | Managed curve operators | VERIFY | #407 | Read-only RGB/luma/hue/saturation curves. No UI. | UI/render wiring | Do not claim #354 complete. |
| #355 | Managed wheels/HSL | VERIFY | #408 | Read-only wheels-v1 and managed HSL. Legacy modules unchanged. | UI/render wiring | Do not claim #355 complete. |
| #356 | Managed grading masks | VERIFY | #409 | Read-only linear/radial/brush mattes. No privacy-mask replacement. No tracking. | UI/render wiring | Do not claim #356 complete. |
| #357 | Managed qualifiers | VERIFY | #410 | Read-only RGB/HSL/luma qualifiers and eyedropper metadata. | UI/render wiring | Do not claim #357 complete. |
| #358–#366 | Color Workspace remainder | READY | — | Continue after #351 and prior color foundations. | #351 verification | No silent legacy conversion. No canonical writes. |

## Open pull requests

Integration cycle in progress against `develop` at `88c79e9`. Canonical writes stay disabled. Packaged WebView2 and GitHub release-ZIP admission remain NOT_RUN where noted above.

## PO decisions already received

- ADR 0035 accepted. Canonical writes stay disabled until #351 safeguards are verified.
- ADR 0037 approved and merged.
- #297 NO-GO accepted. No removal UI and no packaged OpenCV for that purpose.
- #301 GO merged via #401. Packaged WebView2 for transitions remains NOT_RUN.
- #325 target-duration MVP is GO. Do not build a second speed engine.
- #351 backup strategy approved. Production canonical writes stay off until backup and restore are verified and wired.
- #273 bounded security spike approved. Production pairing stays gated.
- #298 bounded OpenCV spike approved. Not a product tracker. NO-GO for 2.4.0 shipping tracker.
- #302 FFmpeg-only dehaze is NO-GO.
- #295 Concept C recommended: declutter Speed panel; keep hybrid ramp.
- Do not merge to `main` or publish a release without explicit authorization.

## Exact next task

Finish the review/integration cycle for open 2.4.0 PRs into `develop`. Keep canonical Color Workspace writes disabled. Do not treat partial foundations as issue completion. Packaged WebView2 and GitHub release-ZIP admission remain NOT_RUN.
