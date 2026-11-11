# Color Scopes engine tap (#366)

Status: **Stop condition applied — no live media tap shipped.**
Branch owner for this preparatory PR: Cursor (PO-assigned follow-up).
Blocked serial dependency: [#359](https://github.com/Magehawks/orga-drone/issues/359)
(FFmpeg still/proxy/export render-plan and declared capture-plane adapters).
UI consumer: [#362](https://github.com/Magehawks/orga-drone/issues/362) /
[`COLOR_SCOPES_UI.md`](COLOR_SCOPES_UI.md).
Contract: [ADR 0035](../decisions/0035-color-workspace-contract.md),
[`COLOR_WORKSPACE_CONTRACT.md`](COLOR_WORKSPACE_CONTRACT.md) § Scope tap.

## Pixel-source audit (develop @ merge of #371 + #350)

| Candidate | Contains applied grade? | Matches clip post-grade / pre-frame tap? | Verdict |
| --- | --- | --- | --- |
| CSS `filter` on `<video>`/`<img>` | Approximate image-adjust only; not HSL/wheels/LUT export path | No — browser filter ≠ BT.709 post-grade plane | **Reject** |
| `previewBlitCanvas` | Often yes for visible picture | No — includes framing transform, letterbox fit, DPR scaling, optional crossfade composite | **Reject** as clip tap |
| LUT/HSL WebGL canvas | LUT/HSL subset when eligible | Partial; untagged sRGB-ish GPU readback; not declared adapter plane | **Reject** until #359 tags capture |
| Server LUT/HSL still JPEG | Graded by FFmpeg still path when ready | JPEG quantized; seeks new stills; not a continuous tap; contract forbids per-tick still spam | **Reject** as live tap |
| Playback proxy MP4 | Graded when prepared | Browser-decoded, untagged; playing without proxy shows ungraded decode | **Reject** |
| `#350` `RenderPlan` | Plan only | No pixel buffer / no adapter capture yet | **Not a source** |
| `#359` declared adapter capture | Required | Contract: post-grade/post-output-transform plane with explicit profile/transfer | **Required** |

### Why a blit/`getImageData` “live” tap would be dishonest

Sampling the display blit would present framed/composited/CSS-approximated
pixels as if they were the ADR clip `clip-post-grade` BT.709 tap. During
playback without a ready LUT proxy the blit often shows **ungraded** decode
plus CSS approximations. That violates the PO stop condition: no apparent live
tap on ungegraded or divergent pixels.

## Adapter interface (for #359 to implement)

Module: `static/js/studio/scopes/engine-tap.js`

```text
probeScopeTapCapability(snapshot) -> {
  available: boolean,
  reason: string,           // machine code when unavailable
  tapId: "clip-post-grade" | "project-composite",
  notes: string[]
}

assertTaggedRgbProvenance(descriptor) -> { profile, transfer, captureStage, capturePlane, tapId }
buildScopeFrameFromTaggedRgb(descriptor) -> ScopeFrameV1
  // No silent defaults. Producer must supply every provenance field below.

createScopeTapController({ panel, getView, getCapability, now, minIntervalMs })
  -> { sync(), tryPublish(frame), getStatus(), destroy() }
```

### Required producer provenance (no defaults)

| Field | Requirement |
| --- | --- |
| `profile` / `transfer` | Explicit `"bt709"` |
| `captureStage` | `clip-post-grade-pre-frame` or `project-composite` |
| `capturePlane` | `bt709-encoded-rgba` |
| `tapId` | Must match `captureStage` |
| `projectId` / `clipId` / `gradeRevision` / `contextDigest` | Non-empty strings |
| `frameIndex` / `ptsNum` / `ptsDen` | Explicit safe integers (`ptsDen >= 1`) |
| `roi` / `sampleFactor` | Explicit; subsample must not pretend full-res |
| `straightAlpha` / `legalRange` | Explicit booleans |
| `width` / `height` / `stride` / `channels` / `rgb` | Explicit buffer geometry |

`captureStage` / `capturePlane` are validated at the adapter boundary pending any
ADR extension of ScopeFrameV1 itself; they are not invented from the builder name.

Rules:

1. Controllers may call `panel.injectFrame` only when `sourceKind === "engine-tap"`
   and capability `available === true`.
2. Controllers must call `panel.syncView()` on clip/seek/grade/project changes
   and reset publish throttling; stale identity is rejected before a successful publish.
3. Subsampling must set `sampleFactor` and never claim full-resolution reference.
4. No new public HTTP endpoint; no grade/export writes; no `#320` changes.
5. Until #359 publishes a tagged capture plane, `probeScopeTapCapability`
   returns `available: false`, reason `awaiting-render-adapter-359`.
6. `renderAdapterReady: true` alone never qualifies a buffer or sets `available`.

## Delivered in this PR

- Capability probe that refuses current preview candidates.
- `buildScopeFrameFromTaggedRgb` for independently testable frame construction
  once a tagged buffer exists.
- `createScopeTapController` orchestration with rate limit / drop metrics.
- Studio mounts the controller; live disclosure stays unavailable.
- Docs + unit/E2E evidence; live media accuracy remains **NOT_RUN**.

## Explicitly not delivered

- Live analysis of user media.
- Renderer/export/plan adapter changes (#359).
- Backend pixel pipelines or new APIs.
- Second scope UI or second accumulate implementation.
