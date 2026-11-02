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
  state: { playing: false }, compareBeforeAfter: false, reuseDraft: null,
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
  previewVideo: null, previewVideoB: null, lutProxyActiveFor: () => false,
  previewLutFrameFor: () => null,
  playbackSpeed: () => 1, slowBarOf: () => null, schedulePreviewBlit() {}, drawPrivacyMasks() {},
  colorSaveChain: Promise.resolve(), imageSaveChain: Promise.resolve(),
  hslSaveChain: Promise.resolve(), msgHslChipPlaying: 'Playing without HSL preview',
  colorWheelsSaveChain: Promise.resolve(), msgColorWheelsChipPlaying: 'Playing without color grading preview',
  msgWheelNeutral: 'Neutral',
  resolveAt: () => null,
  URL: { createObjectURL: blob => blob.id, revokeObjectURL() {} },
  Image: class { decode() { return new Promise((resolve, reject) => decodes.push({ resolve, reject })); } },
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
  console.log('LUT preview lifecycle passed');
})().catch(err => { console.error(err); process.exitCode = 1; });
