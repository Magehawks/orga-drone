# 2.4.0 execution checkpoint

Updated: 2026-11-24. Integration branch `develop` includes `#401`, `#402`, `#403`, and later merges through `ed22c9d`. Tracking/Dehaze close-out: `docs/discovery/298-302-acceptance-closeout.md`.

GitHub has no milestone objects. This inventory is the issue list from the
2.4.0 execution directive plus `gh issue list --search "2.4.0"`. A merged PR
is not acceptance.

## Issue inventory

| Issue | Feature | State | PR | Acceptance | Blocker | Next action |
|---|---|---|---|---|---|---|
| #184 | Independent SFX timeline | VERIFY | #395, #396, #400 merged `2c1108a` | Local onefolder WebView2 E2E PASS. Evidence `docs/planning/184-local-packaged-e2e.json`. GitHub release-ZIP admission NOT_RUN. | PO acceptance | Leave #184 open. |
| #211 | Animated color grading | VERIFY | existing color-animation modules on develop | Presets exist. WebView2 start/mid/end vs MP4 frame-parity is not evidenced. | Full frame-parity E2E | Do not claim #211 done. |
| #267 | Packaged Windows E2E | VERIFY | local onefolder run recorded in #400 | Local WebView2 journey PASS. GitHub release-ZIP admission NOT_RUN. | PR to `main` admission | Do not call the local run a release admission. |
| #273 | Secure pairing | VERIFY | #403 merged | Threat model only. No production pairing, no stored key. Same-user process risk remains. | Reviewed security contract | Do not ship pairing. |
| #274 | Connect assistant settings UX | BLOCKED | — | — | Depends on #273 approval | Wait. |
| #275 | Shared action contract and E2E | VERIFY | matrix exists | Packaged assistant journey NOT_RUN. | Packaged E2E | Keep extending contracts with real actions. |
| #281 | Shared audio/overlay actions | VERIFY | #397 merged | Packaged journey set one SFX volume to 0.35 through `sfx.update`. Full artifact audit NOT_RUN. | PO acceptance | Do not close #281. |
| #283 | Real drone footage fixtures | READY | — | Opt-in local media only; nothing committed | — | Privacy-safe manifest, no source media in git. |
| #284 | Parallel development and release gates | READY | — | — | — | After packaged E2E evidence. |
| #293 | Open Media Journey acceptance | VERIFY | #387 merged | API + synthetic evidence. Packaged EXE journey NOT_RUN. | Packaged dispatch | Do not close on unit tests. |
| #294 | HSL/LUT playback on forward loop | VERIFY | Phase A on develop | Phase B loop playback parity is not a 2.4.0 blocker unless promised. | Phase B only if PO promises loop parity | Do not start a playback-clock rewrite. |
| #295 | Studio UX acceptance | VERIFY | #411 | Discovery recommends Concept C: keep shipped hybrid ramp, declutter Speed panel. Packaged WebView2 NOT_RUN. | PO selection of Concept C | Do not rebuild the speed engine. |
| #297 | Local object removal | DONE | #398 merged `e397c26` | PO accepted the NO-GO. No removal UI. OpenCV is not packaged for this purpose. | — | Do not reopen as a feature. |
| #298 | Local motion tracking | DONE (discovery NO-GO) | #305, #402 + close-out | Spike NO-GO for 2.4.0 tracker. Real footage NOT_RUN. Close-out matrix recorded. | PO close acknowledgment | Close #298 as completed discovery. Do not ship a product tracker. OpenCV for other CV features is not tracking approval. |
| #299 | Subject Focus | BLOCKED | — | No implementation. Requires approved shared tracking foundation after #298 NO-GO. | #298 shipping foundation | Keep open. Do not implement. |
| #300 | Portrait auto-reframing | BLOCKED (tracked follow) | manual Ken Burns in `studio_frame.py` | Automatic detection forbidden. Tracked follow blocked on #298. Manual framing remains. | Approved tracking foundation | Keep open. Do not add a second crop model or auto-follow. |
| #301 | Drone-friendly transitions | VERIFY | #401 merged `88c79e9` | Blur dissolve and four soft wipes landed. Packaged WebView2 for these transitions is NOT_RUN. | PO acceptance | Do not reimplement. Do not add more transition types. |
| #302 | Dehaze alternatives | DONE (discovery NO-GO) | #304, #309 + close-out | FFmpeg-only dehaze NO-GO on real fixtures. Close-out matrix recorded. | Future PO-approved R&D issue | Close #302 as completed discovery. Do not claim a shipping dehaze. |
| #317 | Windows RC/MOTW | READY | — | NOT_RUN | Release approval | Maintainer step. Do not publish. |
| #320 | Strict color parity | VERIFY | closed on GitHub | Closed is not acceptance evidence in this checkpoint | — | Re-read the closed issue before any new parity work. |
| #325 | Timelapse target duration | VERIFY | #404 merged | Target-duration draft drives decoded MP4 evidence. Journey smoke uses fixed red-then-blue clip order. Packaged WebView2 Timelapse Inspector is NOT_RUN. | PO acceptance | Do not build a second speed engine. |
| #331 | Source/Story clocks | VERIFY | #392 ADR 0037 merged `0cb3d35` | ADR accepted | — | Region work landed in #332. |
| #332 | Bounded speed-ramp region | VERIFY | #394 merged `9f927d4` | Packaged E2E NOT_RUN. PO has not accepted the issue. | PO acceptance | Do not reimplement. |
| #333 | Timelapse/ramp conflict | VERIFY | #389 merged | Confirm UI merged. Issue may still be open if acceptance is wider. | — | Re-read before more code. |
| #351 | Color persistence/recovery | VERIFY | #399 merged | Staged copy and atomic replace. Canonical writes and startup refusal stay disabled. Helper-only; does not close #351. | PO acceptance; wire only with verified safeguards | Do not enable canonical writes. |
| #352 | Managed SDR LUT contract | VERIFY | #405 merged | Read-only transfers and tetrahedral 3D LUT sampling. Legacy import/export unchanged. Managed parity gate NOT_RUN. | Preview/export wiring; #351 before canonical writes | Do not claim #352 complete. |
| #353 | Managed primaries | VERIFY | #406 merged | Read-only exposure/balance/contrast/tone/saturation. Kelvin/tint unpublished. | Kelvin/tint vectors; UI/render | Do not claim #353 complete. |
| #354 | Managed curve operators | VERIFY | #407 merged | Read-only RGB/luma/hue/saturation curves. No UI. | UI/render wiring | Do not claim #354 complete. |
| #355 | Managed wheels/HSL | VERIFY | #408 merged | Read-only wheels-v1 and managed HSL. Legacy modules unchanged. | UI/render wiring | Do not claim #355 complete. |
| #356 | Managed grading masks | VERIFY | #409 merged | Read-only linear/radial/brush mattes. No privacy-mask replacement. No tracking. | UI/render wiring | Do not claim #356 complete. |
| #357 | Managed qualifiers | VERIFY | #410 merged | Read-only RGB/HSL/luma qualifiers and eyedropper metadata. | UI/render wiring | Do not claim #357 complete. |
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
- #298/#302 discovery close-out matrix recorded in `docs/discovery/298-302-acceptance-closeout.md`. Close discovery issues independently; keep #299/#300 open and blocked.
- #295 Concept C recommended: declutter Speed panel; keep hybrid ramp.
- Do not merge to `main` or publish a release without explicit authorization.

## Exact next task

PO: acknowledge #298/#302 discovery close-out and close those issues when ready. Keep #299/#300 open and blocked. Do not start a product tracker, Subject Focus, tracked reframe, or Dehaze slider without a new approved implementation issue. Keep canonical Color Workspace writes disabled. Packaged WebView2 and GitHub release-ZIP admission remain NOT_RUN.
