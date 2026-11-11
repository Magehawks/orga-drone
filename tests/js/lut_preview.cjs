// Execute the production functions with controlled network, decode and clock.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync('src/orga_drone/static/js/studio.js', 'utf8');
function section(start, end) { return script.split(start)[1].split(end)[0]; }
const source = 'const previewLutStill' + section('const previewLutStill', 'function canvasFilterFrom') +
  'function neutralColorLook' + section('function neutralColorLook', 'function writeColorLook');
const still = { hidden: true, removeAttribute() {}, naturalWidth: 320, naturalHeight: 180 };
const chip = { addEventListener() {} };
let timers = new Map(), nextTimer = 1, requests = [], decodes = [];
let proxySrc = "";
const context = {
  root: { dataset: {} }, document: { getElementById: id => id.endsWith('still') ? still : chip },
  window: { setTimeout: f => { const id = nextTimer++; timers.set(id, f); return id; }, clearTimeout: id => timers.delete(id) },
  state: { playing: false }, colorComparison: null, reuseDraft: null,
  readColorAnimation: () => null, readImageAdjust: clip => JSON.parse(clip.dataset.imageAdjust || '{}'),
  readHsl: clip => {
    try {
      const parsed = JSON.parse(clip.dataset.hsl || '');
      if (parsed && parsed.ranges) return parsed;
    } catch (_) { /* neutral */ }
    return { ranges: {} };
  },
  hslIsNeutral: hsl => !hsl || !hsl.ranges ||
    Object.values(hsl.ranges).every(v => !v.hue && !v.saturation && !v.luminance),
  readColorWheels: () => ({ wheels: {} }),
  colorWheelsIsNeutral: () => true,
  lutProxySrcFor: () => proxySrc,
  lutWebglCanHandle: () => false,
  lutWebglReadyFor: () => false,
  lutProxyEligible: () => false,
  previewVideo: null, previewVideoB: null, previewImage: null, previewImageB: null,
  clipForPreviewMedia: media => media === context.previewImageB ? context.outgoing : clip, lutProxyActiveFor: () => false,
  previewLutFrameFor: () => null,
  playbackSpeed: () => 1, slowBarOf: () => null, speedRampOf: () => null, schedulePreviewBlit() {}, drawPrivacyMasks() {},
  previewIsFullscreen: () => false, syncFullscreenControl() {},
  refreshColorGradeSummaryFor() {}, updateColorGradeSummary() {},
  colorSaveChain: Promise.resolve(), imageSaveChain: Promise.resolve(),
  hslSaveChain: Promise.resolve(), msgHslChipPlaying: 'Playing without HSL preview',
  colorWheelsSaveChain: Promise.resolve(), msgColorWheelsChipPlaying: 'Playing without color grading preview',
  msgWheelNeutral: 'Neutral',
  resolveAt: () => null,
  URL: { createObjectURL: blob => blob.id, revokeObjectURL() {} },
  Image: class { constructor() { this.hidden = true; this.naturalWidth = 320; this.naturalHeight = 180; } removeAttribute() {} decode() { return new Promise((resolve, reject) => decodes.push({ resolve, reject })); } },
  AbortController, Number, JSON, Math,
  fetch: (url, options) => new Promise(resolve => requests.push({ url, options, resolve })),
};
vm.createContext(context); vm.runInContext(source, context);
const clip = { dataset: { studioId: '1', kind: 'video', colorLook: JSON.stringify({ creative_lut: 'a', creative_strength: 100 }) } };
proxySrc = '/api/studio/1/playback-proxy?lut_proxy=1';
context.scheduleLutPreviewStill(clip, 1);
assert.equal(timers.size, 0, 'proxy keeps its video frame instead of a soft still');
assert.equal(requests.length, 0, 'proxy does not request a JPEG still');
assert.equal(still.hidden, true);
proxySrc = "";
const tick = () => new Promise(resolve => setImmediate(resolve));
async function fire() { const callbacks = [...timers.values()]; timers.clear(); for (const f of callbacks) await f(); }
async function reply(request, id) { request.resolve({ ok: true, status: 200, blob: async () => ({ id }) }); await tick(); }
(async () => {
  for (const strength of [0, 50, 100]) {
    clip.dataset.colorLook = JSON.stringify({ creative_lut: 'a', creative_strength: strength });
    assert.equal(context.readColorLook(clip).creative_strength, strength);
  }
  context.scheduleLutPreviewStill(clip, 1);
  context.scheduleLutPreviewStill(clip, 1);
  assert.equal(timers.size, 1, 'identical redraws keep one debounce');
  await fire(); assert.equal(requests.length, 1);
  assert.equal(requests[0].options.cache, 'no-store');
  context.scheduleLutPreviewStill(clip, 2);
  await reply(requests[0], 'stale');
  assert.equal(decodes.length, 0, 'old response rejected during debounce');
  await fire(); await reply(requests[1], 'second');
  assert.equal(still.hidden, true, 'wait for decode');
  context.scheduleLutPreviewStill(clip, 3);
  decodes[0].resolve(); await tick();
  assert.equal(still.hidden, true, 'old decoded result rejected');
  await fire(); await reply(requests[2], 'third'); decodes[1].resolve(); await tick();
  assert.equal(still.src, 'third'); assert.equal(still.hidden, false);
  context.scheduleLutPreviewStill(clip, 3); assert.equal(timers.size, 0, 'completed frame deduplicates');
  context.state.playing = true; context.scheduleLutPreviewStill(clip, 3);
  assert.equal(still.hidden, true); assert.equal(chip.textContent, 'Playing without color file');
  context.state.playing = false; context.scheduleLutPreviewStill(clip, 3); await fire();
  await reply(requests[3], 'after-pause');
  clip.dataset.colorLook = '{}'; context.scheduleLutPreviewStill(clip, 3);
  decodes[2].resolve(); await tick(); assert.equal(still.hidden, true, 'removal invalidates decode');
  clip.dataset.colorLook = JSON.stringify({ creative_lut: 'a', creative_strength: 100 });
  clip.dataset.imagePreviewDirty = '1';
  context.scheduleLutPreviewStill(clip, 4); await fire();
  assert.equal(requests.length, 4, 'unsaved slider input cannot fetch persisted grade');
  assert.equal(chip.textContent, 'Updating picture…');
  // Successful persistence invalidates even an otherwise identical desired key.
  clip.dataset.imagePreviewDirty = '0'; context.clearLutPreviewStill();
  let finishSave;
  context.imageSaveChain = new Promise(resolve => { finishSave = resolve; });
  context.scheduleLutPreviewStill(clip, 4);
  const pendingFire = fire(); await tick();
  assert.equal(requests.length, 4, 'wait for pending save');
  finishSave(); await pendingFire;
  assert.equal(requests.length, 5);
  context.reuseDraft = {}; context.clearLutPreviewStill();
  await reply(requests[4], 'draft-stale');
  context.scheduleLutPreviewStill(clip, 5); await fire();
  assert.equal(requests.length, 5, 'draft never schedules Story LUT frames');
  assert.equal(still.hidden, true);
  context.reuseDraft = null;
  // The image save chain now lives in studio/inspector/image-save.js. Keep the
  // preview contract here: a stale response cannot overwrite newer input, and
  // the post-save refresh requests a fresh frame.
  const { createImageAdjustSaver } = await import(
    '../../src/orga_drone/static/js/studio/inspector/image-save.js'
  );
  const imageSaver = createImageAdjustSaver({
    getClipById: studioId => (String(studioId) === '1' ? clip : null),
    readAdjust: context.readImageAdjust,
    writeAdjust: (target, adjust, persisted) => {
      target.dataset.imageAdjust = JSON.stringify(adjust);
      target.dataset.imagePreviewDirty = persisted ? '0' : '1';
      context.clearLutPreviewStill();
    },
    isSelected: () => false,
    refreshPreview: () => context.scheduleLutPreviewStill(clip, 4),
    setSaved: () => {},
    fetchImpl: (url, options) => context.fetch(url, options),
    readJson: async response => response.body,
  });
  clip.dataset.imageAdjust = JSON.stringify({ exposure: 25 });
  clip.dataset.imagePreviewDirty = '1';
  context.scheduleLutPreviewStill(clip, 4); await fire();
  assert.equal(requests.length, 5, 'held input does not read old persisted settings');
  let finishPatch;
  const getFrame = context.fetch;
  context.fetch = (url, options) => options.method === 'PATCH'
    ? new Promise(resolve => { finishPatch = resolve; }) : getFrame(url, options);
  const saving = imageSaver.queue('1');
  context.imageSaveChain = saving;
  await tick();
  clip.dataset.imageAdjust = JSON.stringify({ exposure: 35 });
  clip.dataset.imagePreviewDirty = '1';
  finishPatch({ ok: true, body: { ok: true, image: { exposure: 25 } } }); await saving;
  assert.equal(context.readImageAdjust(clip).exposure, 35, 'save response cannot overwrite newer input');
  assert.equal(clip.dataset.imagePreviewDirty, '1');
  const latestSave = imageSaver.queue('1');
  context.imageSaveChain = latestSave;
  await tick();
  finishPatch({ ok: true, body: { ok: true, image: { exposure: 35 } } }); await latestSave;
  assert.equal(clip.dataset.imagePreviewDirty, '0');
  await fire(); assert.equal(requests.length, 6, 'saved adjustment always requests fresh frame');
  const drawn = [], transforms = [];
  Object.assign(context, {
    previewLayerReady: media => media && !media.hidden,
    contentRect: (w, h, sw, sh) => ({ x: 0, y: 0, w, h }),
    canvasFilterFrom: text => text,
    previewGradeSource: media => media,
  });
  vm.runInContext('function readPreviewTransform' + section('function readPreviewTransform', 'function previewLayerReady') +
    'function drawPreviewLayer' + section('function drawPreviewLayer', 'function ensurePreviewBlit'), context);
  const ctx = { save() {}, restore() {}, translate: (...v) => transforms.push(v),
    scale: (...v) => transforms.push(v), drawImage: (...v) => drawn.push({ v, filter: ctx.filter }) };
  const media = { hidden: false, videoWidth: 640, videoHeight: 360,
    style: { opacity: '0.5', transform: 'translate(12px, -4px) scale(2)', filter: 'contrast(1.5)' } };
  context.drawPreviewLayer(ctx, media, 640, 360, still);
  assert.equal(drawn[0].v[0], still, 'visible compositor uses LUT pixels');
  assert.equal(drawn[0].filter, 'none', 'rendered grade is not applied twice');
  assert.deepEqual(transforms, [[12, -4], [2, 2]], 'original clip framing survives');
  assert.equal(ctx.globalAlpha, 0.5, 'transition opacity survives');
  const comparison = { hidden: false, naturalWidth: 320, naturalHeight: 180, src: 'before' };
  context.colorComparison = { pictureFor: () => comparison };
  context.previewLutFrameFor = () => { throw new Error('Before must bypass the graded WebGL frame'); };
  context.drawPreviewLayer(ctx, media, 640, 360, still);
  assert.equal(drawn.at(-1).v[0], comparison, 'comparison wins over a graded still/proxy');
  assert.equal(drawn.at(-1).filter, 'none', 'Before receives no CSS grade');
  context.colorComparison = null;
  context.previewLutFrameFor = () => null;
  context.drawPreviewLayer(ctx, media, 640, 360, still);
  assert.equal(drawn.at(-1).v[0], still, 'release immediately restores the original still owner');
  // Exercise the compositor entry guard, not only its layer drawing helper.
  vm.runInContext('function paintPreviewBlit' + section('function paintPreviewBlit', 'function schedulePreviewBlit'), context);
  const blit = { hidden: true, getContext: () => ctx };
  Object.assign(ctx, { setTransform() {}, fillRect() {} });
  const loading = { ...media, hidden: false, complete: false,
    videoWidth: 0, videoHeight: 0, naturalWidth: 0, naturalHeight: 0,
    classList: { contains: () => false } };
  const absent = { ...loading, hidden: true };
  Object.assign(context, {
    ensurePreviewBlit: () => blit,
    previewFrame: { clientWidth: 640, clientHeight: 360, dataset: {} },
    previewBackingRatio: () => 1,
  });
  vm.runInContext('function previewLayerReady' + section('function previewLayerReady', 'let previewGradeScratch'), context);
  const actualStillFor = context.renderedPreviewStillFor;
  const decodedGrade = { ...still, hidden: false, classList: { contains: () => false } };
  for (const layer of ['primary', 'secondary']) {
    context.visiblePrimaryMedia = () => layer === 'primary' ? loading : absent;
    context.visibleSecondaryMedia = () => layer === 'secondary' ? loading : absent;
    context.renderedPreviewStillFor = picture => picture === loading ? decodedGrade : null;
    drawn.length = 0;
    context.paintPreviewBlit();
    assert.equal(blit.hidden, false, layer + ' decoded grade survives loading raw photo');
    assert.equal(drawn.length, 1);
    assert.equal(drawn[0].v[0], decodedGrade);
    assert.equal(drawn[0].filter, 'none');
    assert.equal(ctx.globalAlpha, 0.5);
  }
  context.renderedPreviewStillFor = () => null;
  context.paintPreviewBlit();
  assert.equal(blit.hidden, true, 'no ready raw or rendered layer hides canvas');
  context.renderedPreviewStillFor = actualStillFor;
  context.previewLayerReady = picture => picture && !picture.hidden;
  // Photo frames are static across Story time, including playback and pause.
  context.imageSaveChain = Promise.resolve();
  context.fetch = getFrame;
  for (const format of ['jpg', 'png']) {
    for (const look of [
      ...[0, 50, 100].map(creative_strength => ({ creative_lut: 'a', creative_strength })),
      { conversion_lut: 'a', conversion_confirmed: true, input_profile: 'custom' },
    ]) {
      context.clearLutPreviewStill();
      clip.dataset = { studioId: 'photo-' + format, kind: 'photo',
        streamUrl: '/source.' + format, colorLook: JSON.stringify(look) };
      context.state.playing = true;
      const before = requests.length;
      context.scheduleLutPreviewStill(clip, 0.1);
      await fire();
      assert.equal(requests.length, before + 1, format + ' LUT requested during playback');
      await reply(requests.at(-1), format + JSON.stringify(look));
      decodes.at(-1).resolve(); await tick();
      assert.equal(still.hidden, false, format + ' graded frame remains visible while playing');
      for (let t = 0; t < 100; t++) context.scheduleLutPreviewStill(clip, t / 30);
      context.state.playing = false;
      context.scheduleLutPreviewStill(clip, 2);
      await fire();
      assert.equal(requests.length, before + 1, 'unchanged playback and pause reuse decoded photo');
      assert.equal(still.hidden, false, 'pause without seeking retains grade');
    }
  }
  // Both composited photo layers own independent cancellation/cache state.
  const outgoing = { dataset: { ...clip.dataset, studioId: 'outgoing', streamUrl: '/other.png' } };
  context.outgoing = outgoing;
  const start = requests.length;
  context.schedulePhotoOverlapStill(outgoing, 1);
  await fire(); await reply(requests.at(-1), 'outgoing-graded');
  decodes.at(-1).resolve(); await tick();
  context.previewImage = {}; context.previewImageB = {};
  assert.equal(context.renderedPreviewStillFor(context.previewImageB).src, 'outgoing-graded');
  assert.equal(context.renderedPreviewStillFor(context.previewImage), still);
  context.clearLutPreviewStill(clip);
  assert.equal(context.renderedPreviewStillFor(context.previewImageB).src, 'outgoing-graded',
    'editing incoming photo does not invalidate outgoing');
  context.schedulePhotoOverlapStill(outgoing, 2); await fire();
  assert.equal(requests.length, start + 1, 'outgoing frame reused across overlap ticks');
  outgoing.dataset.imageAdjust = JSON.stringify({ contrast: 20 });
  context.schedulePhotoOverlapStill(outgoing, 2); await fire();
  assert.equal(requests.length, start + 2, 'grade edit invalidates photo');
  await reply(requests.at(-1), 'stale-outgoing');
  outgoing.dataset.streamUrl = '/replacement.jpg';
  context.schedulePhotoOverlapStill(outgoing, 2);
  decodes.at(-1).resolve(); await tick();
  assert.equal(context.renderedPreviewStillFor(context.previewImageB), null, 'photo change rejects stale decode');
  await fire(); await reply(requests.at(-1), 'replacement'); decodes.at(-1).resolve(); await tick();
  context.clearVideoLutPreviewStill();
  assert.equal(context.renderedPreviewStillFor(context.previewImageB).src, 'replacement',
    'video WebGL readiness preserves outgoing photo');
  context.schedulePhotoOverlapStill({ dataset: { kind: 'video' } }, 0);
  assert.equal(context.renderedPreviewStillFor(context.previewImageB), null, 'mixed transition removes stale photo layer');
  // Unconfirmed conversion stays inactive; it must not create a new color path.
  context.clearLutPreviewStill();
  clip.dataset.colorLook = JSON.stringify({ conversion_lut: 'a', conversion_confirmed: false });
  const unconfirmedCount = requests.length;
  context.scheduleLutPreviewStill(clip, 0); await fire();
  assert.equal(requests.length, unconfirmedCount);
  clip.dataset.colorLook = JSON.stringify({ creative_lut: 'a', creative_strength: 100 });
  context.scheduleLutPreviewStill(clip, 0); await fire();
  await reply(requests.at(-1), 'retained-at-boundary'); decodes.at(-1).resolve(); await tick();
  context.alignLutStillOwners(outgoing, clip);
  context.outgoing = clip;
  assert.equal(context.renderedPreviewStillFor(context.previewImageB).src, 'retained-at-boundary',
    'outgoing photo moves layers without waiting for another render');
  context.scheduleLutPreviewStill(outgoing, 0); // new incoming still is pending
  assert.equal(chip.textContent, 'Updating picture…');
  context.alignLutStillOwners(clip, null); // seek back to cached previous primary
  context.scheduleLutPreviewStill(clip, 1);
  context.schedulePhotoOverlapStill(null, 0);
  assert.notEqual(chip.textContent, 'Updating picture…', 'promoted cached photo restores its status');
  context.alignLutStillOwners(outgoing, clip);
  context.outgoing = clip;
  // Masks and compositor sample the same rendered picture during playback.
  const maskDraws = [];
  Object.assign(context, {
    lutWebglCanvasFor: () => null,
    sourceWindowForMask: () => ({ x: 0, y: 0, w: 320, h: 180 }),
    effectAmount: () => 2,
    maskModel: { blurFraction: 0.1 },
  });
  vm.runInContext('function paintPrivacyMask' + section('function paintPrivacyMask', 'function drawMaskCanvas'), context);
  context.state.playing = true;
  const maskContext = { save() {}, restore() {}, beginPath() {}, rect() {}, clip() {},
    drawImage: picture => maskDraws.push(picture) };
  context.paintPrivacyMask(maskContext, context.previewImageB,
    { effect: 'blur', x: 0, y: 0, w: 0.5, h: 0.5, strength: 50 },
    { width: 640, height: 360 }, 640, 360);
  assert.equal(maskDraws[0].src, 'retained-at-boundary', 'mask uses graded outgoing pixels');
  const beforeMask = { hidden: false, naturalWidth: 320, naturalHeight: 180, src: 'before-mask' };
  const gradedWebgl = { width: 320, height: 180, src: 'graded-webgl' };
  context.state.playing = false;
  context.colorComparison = { pictureFor: () => beforeMask };
  context.lutWebglCanvasFor = () => gradedWebgl;
  const scratchDraws = [];
  context.maskScratch = { getContext: () => ({ clearRect() {}, drawImage: picture => scratchDraws.push(picture) }) };
  context.maskModel.pixelFraction = 0.1;
  for (const effect of ['blur', 'pixelate']) {
    context.paintPrivacyMask(maskContext, context.previewImageB,
      { effect, x: 0.2, y: 0.2, w: 0.3, h: 0.3, strength: 50 },
      { width: 640, height: 360 }, 640, 360);
    const sampled = effect === 'blur' ? maskDraws.at(-1) : scratchDraws.at(-1);
    assert.equal(sampled, beforeMask, `${effect} samples Before instead of an already graded WebGL canvas`);
  }
  context.colorComparison = null;
  context.paintPrivacyMask(maskContext, context.previewImageB,
    { effect: 'blur', x: 0.2, y: 0.2, w: 0.3, h: 0.3, strength: 50 },
    { width: 640, height: 360 }, 640, 360);
  assert.equal(maskDraws.at(-1), gradedWebgl, 'release restores normal WebGL mask pixels');
  context.lutWebglCanvasFor = () => null;
  context.state.playing = true;
  context.reuseDraft = {};
  assert.equal(context.renderedPreviewStillFor(context.previewImageB), null);
  context.reuseDraft = null;
  context.clearLutPreviewStill();
  outgoing.dataset.appliedType = 'crossfade';
  context.outgoing = outgoing;
  Object.assign(context, {
    forwardLoopActive: () => false, sectionRepeats: () => 1,
    gradePreviewElement() {}, clips: () => [outgoing, clip], clipDuration: () => 3,
  });
  vm.runInContext('function applyPreviewGrades' + section('function applyPreviewGrades', 'const previewLutStill'), context);
  const preloadCount = requests.length;
  context.applyPreviewGrades({ clip: outgoing, localS: 0, index: 0 });
  await fire();
  assert.equal(requests.length, preloadCount + 2, 'idle owner prepares next crossfade photo once');
  for (const request of requests.slice(preloadCount)) {
    await reply(request, request.url);
    decodes.at(-1).resolve(); await tick();
  }
  for (let i = 0; i < 100; i++) {
    context.applyPreviewGrades({ clip, overlapClip: outgoing, localS: i / 100,
      overlapLocalS: 2 + i / 100, index: 1 });
  }
  await fire();
  assert.equal(requests.length, preloadCount + 2, 'both decoded resources transfer without tick or boundary renders');
  assert.ok(context.renderedPreviewStillFor(context.previewImage));
  assert.ok(context.renderedPreviewStillFor(context.previewImageB));
  for (const failure of [409, 500, 'decode']) {
    context.clearLutPreviewStill();
    const failedCount = requests.length;
    context.scheduleLutPreviewStill(clip, 0); await fire();
    if (failure === 'decode') {
      await reply(requests.at(-1), 'broken-image');
      decodes.at(-1).reject(new Error('decode failed')); await tick();
    } else {
      requests.at(-1).resolve({ ok: false, status: failure }); await tick();
    }
    const failedStatus = chip.textContent;
    for (let i = 0; i < 100; i++) context.scheduleLutPreviewStill(clip, i / 30);
    await fire();
    assert.equal(requests.length, failedCount + 1, 'failed photo is not retried on clock ticks');
    assert.equal(chip.textContent, failedStatus, 'failure remains visible');
    assert.equal(context.retryFailedPhotoStills(), true, 'explicit pause/seek retries failed photo');
    context.scheduleLutPreviewStill(clip, 0); await fire();
    assert.equal(requests.length, failedCount + 2, 'explicit retry can request again');
  }
  console.log('LUT preview lifecycle passed');
  const photo = { hidden: true, style: {} };
  const outgoingPhoto = { hidden: false, style: { opacity: '1' } };
  const video = { hidden: false, style: { opacity: '0.77' }, pause() {} };
  let stoppedHit;
  const pausedContext = {
    state: { playing: true, projectTimeS: 3.001 },
    previewImage: photo, previewImageB: outgoingPhoto, previewVideo: video,
    previewVideoB: null, previewTitlecard: null, previewTitlecardB: null, previewFadeBlack: null,
    clipAudio: null, stopWallClock() {}, clearCrossfadePreload() {}, pauseMusicAudio() {},
    setToggleLabel() {}, retryFailedPhotoStills: () => false,
    resolveAt: t => ({ clip, localS: t - 2 }),
    loopOverlapS: () => 0, prepareOutgoingCrossfade: () => false,
    applyPreviewGrades: hit => { stoppedHit = hit; },
    syncAnnotations() {}, drawPrivacyMasks() {}, drawFlightMap() {}, applyFramePreview() {},
    syncHud() {}, schedulePreviewBlit() {}, syncFullscreenControl() {},
    previewIsFullscreen: () => false,
  };
  vm.createContext(pausedContext);
  vm.runInContext('function pausePlayback' + section('function pausePlayback', 'function updatePlayheadChrome') +
    'function applyTransitionPreview' + section('function applyTransitionPreview', '// A CSS-sized video'), pausedContext);
  pausedContext.pausePlayback();
  assert.equal(outgoingPhoto.hidden, true, 'pause past photo overlap removes outgoing photo');
  assert.equal(video.style.opacity, '', 'pause past overlap restores full incoming opacity');
  assert.equal(stoppedHit.localS, 1.001, 'composite uses frozen Story timestamp');
  assert.equal(pausedContext.state.playing, false);
  outgoingPhoto.hidden = false;
  pausedContext.state.projectTimeS = 2.4;
  pausedContext.resolveAt = t => ({ clip, overlapClip: outgoing, crossfadeProgress: t - 2 });
  pausedContext.showOutgoingLayer = () => {};
  pausedContext.pausePlayback();
  assert.ok(Math.abs(Number(video.style.opacity) - 0.4) < 1e-9,
    'pause inside photo overlap refreshes frozen transition progress');
  outgoingPhoto.hidden = true;
  stoppedHit = null;
  pausedContext.pausePlayback();
  assert.equal(stoppedHit, null, 'video-only pause keeps its existing update path');
})().catch(err => { console.error(err); process.exitCode = 1; });
