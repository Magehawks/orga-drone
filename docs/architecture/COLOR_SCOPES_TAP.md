# Color Scopes engine tap (#366)

Status: **Live managed-preview tap shipped for managed-sdr-v1 grades.**
Producer: `static/js/studio/scopes/preview-tap.js` (`managed-preview-frame-v1`).
UI consumer: [#362](https://github.com/Magehawks/orga-drone/issues/362) /
[`COLOR_SCOPES_UI.md`](COLOR_SCOPES_UI.md).
Contract: [ADR 0035](../decisions/0035-color-workspace-contract.md),
[`COLOR_WORKSPACE_CONTRACT.md`](COLOR_WORKSPACE_CONTRACT.md) § Scope tap.
Render plane: [#359](https://github.com/Magehawks/orga-drone/issues/359) CPU
preview-frame (same grade path as export stills).

## Pixel-source audit

| Candidate | Contains applied grade? | Matches clip post-grade / pre-frame tap? | Verdict |
| --- | --- | --- | --- |
| CSS `filter` on `<video>`/`<img>` | Approximate image-adjust only | No | **Reject** |
| `previewBlitCanvas` | Often yes for visible picture | No — framing, letterbox, DPR, composite | **Reject** |
| LUT/HSL WebGL canvas | Subset when eligible | Untagged / approximate bake | **Reject** |
| Raw JPEG still as continuous tap | Graded | JPEG quantized; per-tick spam forbidden | **Reject** as undeclared continuous source |
| Playback proxy MP4 | Graded when prepared | Untagged browser decode | **Reject** |
| `managed-preview-frame-v1` via `/preview-frame` | Yes (managed-sdr-v1) | Yes — tagged BT.709 post-grade/pre-frame; JPEG transport + downsample disclosed via `sampleFactor` / notes | **Accepted producer** |

### Why a blit/`getImageData` “live” tap would be dishonest

Sampling the display blit would present framed/composited/CSS-approximated
pixels as if they were the ADR clip `clip-post-grade` BT.709 tap. That remains
forbidden. The managed producer never samples the blit.

## Adapter interface

Module: `static/js/studio/scopes/engine-tap.js` + `preview-tap.js`

```text
probeScopeTapCapability(snapshot) -> {
  available: boolean,
  reason: string,
  tapId: "clip-post-grade" | "project-composite",
  notes: string[]
}

// available === true only when snapshot.taggedCapturePlane matches
// managed-preview-frame-v1 with bt709 profile/transfer and
// clip-post-grade-pre-frame / bt709-encoded-rgba.

assertTaggedRgbProvenance(descriptor) -> { profile, transfer, captureStage, capturePlane, tapId }
buildScopeFrameFromTaggedRgb(descriptor) -> ScopeFrameV1
createScopeTapController({ panel, getView, getCapability, now, minIntervalMs })
createManagedPreviewScopeProducer({ getView, getSourceTimeS, fetchPreviewJpeg, decodeJpegToRgba, tryPublish, ... })
```

Rules:

1. Controllers may call `panel.injectFrame` only when `sourceKind === "engine-tap"`
   and capability `available === true`.
2. Controllers must call `panel.syncView()` on clip/seek/grade/project changes
   and reset publish throttling; stale identity is rejected before a successful publish.
3. Subsampling must set `sampleFactor` and never claim full-resolution reference.
4. No new public HTTP endpoint; reuses `/api/studio/{id}/preview-frame`.
5. `renderAdapterReady: true` alone never qualifies a buffer or sets `available`.
6. Display blit / CSS / untagged WebGL / undeclared JPEG candidates stay refused
   in the capability notes even when the managed producer is active.
7. Producer uses generation tokens to drop stale async results after seek/clip/grade change.
8. Seek tokens are part of the scope view digest so reverse scrubs clear the prior frame.
9. Playback refresh is rate-limited (`playIntervalMs`, default 500 ms) to avoid still spam.
10. `sampleFactor` is applied once by accumulate on the full decoded buffer (no second shrink).
11. `/preview-frame` returns `X-Orga-Grade-Revision` and `X-Orga-Preview-Time-S`; clients may
    pass `expected_revision` and must bind PTS to the quantized server time.

## Delivered

- Capability probe that accepts only `managed-preview-frame-v1` tagged planes.
- Preview producer that decodes graded preview-frame JPEGs into ScopeFrameV1.
- Studio wiring: managed grade revision/context digest, sync on view change.
- Unit tests for probe, downsample, stale generation, controller publish.
- Display blit / CSS / untagged GPU remain refused.

## Explicit limitations

- Transport is JPEG (quantization disclosed); not a full-resolution linear reference.
- Continuous high-rate playback scopes are throttled; not a free-running GPU tap.
- Packaged Windows WebView2 live-pixel latency/memory budgets: measure in E2E
  evidence (`PASS`/`FAIL`/`NOT_RUN`).
- Project-composite tap is not implemented in this slice.
