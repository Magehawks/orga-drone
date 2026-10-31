// Colour-wheel still lifecycle: schedule, dirty guard, stale response.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync('src/orga_drone/static/js/studio.js', 'utf8');
function section(start, end) { return script.split(start)[1].split(end)[0]; }
const source =
  'const COLOR_WHEEL_IDS' + section('const COLOR_WHEEL_IDS', '// Peak-normalized') +
  'const previewLutStill' + section('const previewLutStill', 'function canvasFilterFrom') +
  'function neutralColorLook' + section('function neutralColorLook', 'function writeColorLook');
const still = { hidden: true, removeAttribute() {}, naturalWidth: 320, naturalHeight: 180 };
const chip = {};
let timers = new Map(), nextTimer = 1, requests = [], decodes = [];
const context = {
  root: { dataset: {} },
  document: { getElementById: id => id.endsWith('still') ? still : chip },
  window: {
    setTimeout: f => { const id = nextTimer++; timers.set(id, f); return id; },
    clearTimeout: id => timers.delete(id),
  },
  state: { playing: false }, compareBeforeAfter: false, reuseDraft: null,
  readColorAnimation: () => null,
  readImageAdjust: clip => JSON.parse(clip.dataset.imageAdjust || '{}'),
  readHsl: () => ({ ranges: {} }),
  hslIsNeutral: () => true,
  lutProxySrcFor: () => "",
  lutWebglReadyFor: () => false,
  lutProxyPreparingFor: () => false,
  msgLutChipProxyPreparing: 'Preparing color preview',
  previewVideo: null, previewVideoB: null, lutProxyActiveFor: () => false,
  playbackSpeed: () => 1, slowBarOf: () => null,
  schedulePreviewBlit() {}, drawPrivacyMasks() {},
  colorSaveChain: Promise.resolve(), imageSaveChain: Promise.resolve(),
  hslSaveChain: Promise.resolve(), msgHslChipPlaying: 'Playing without HSL preview',
  colorWheelsSaveChain: Promise.resolve(),
  msgColorWheelsChipPlaying: 'Playing without color grading preview',
  msgWheelNeutral: 'Neutral',
  resolveAt: () => null,
  URL: { createObjectURL: blob => blob.id, revokeObjectURL() {} },
  Image: class { decode() { return new Promise(resolve => decodes.push({ resolve })); } },
  AbortController, Number, JSON, Math,
  fetch: (url, options) => new Promise(resolve => requests.push({ url, options, resolve })),
};
vm.createContext(context);
vm.runInContext(source, context);
const clip = {
  dataset: {
    studioId: '9', kind: 'video', sourceIn: '0', sourceOut: '4',
    colorLook: '{}', imageAdjust: '{}', saturationRamp: '{}', hsl: '{"ranges":{}}',
  },
};
const tick = () => new Promise(resolve => setImmediate(resolve));
async function fire() {
  const callbacks = [...timers.values()];
  timers.clear();
  for (const callback of callbacks) await callback();
}
async function reply(request, id) {
  request.resolve({ ok: true, status: 200, blob: async () => ({ id }) });
  await tick();
}
(async () => {
  context.scheduleLutPreviewStill(clip, 1);
  assert.equal(timers.size, 0, 'neutral wheels keep the ordinary video path');
  clip.dataset.colorWheels = JSON.stringify({ wheels: { shadows: { x: 0.4, y: -0.2 } } });
  context.scheduleLutPreviewStill(clip, 1);
  assert.equal(timers.size, 1, 'wheels schedule the shared rendered still');
  await fire();
  assert.equal(requests.length, 1);
  assert.match(requests[0].url, /\/api\/studio\/9\/preview-frame/);

  clip.dataset.colorWheelsPreviewDirty = '1';
  context.scheduleLutPreviewStill(clip, 2);
  assert.equal(requests.length, 1, 'unsaved wheel input never fetches persisted settings');

  clip.dataset.colorWheelsPreviewDirty = '0';
  context.clearLutPreviewStill();
  context.scheduleLutPreviewStill(clip, 2);
  await fire();
  assert.equal(requests.length, 2);

  clip.dataset.colorWheels = JSON.stringify({ wheels: { midtones: { x: -0.3, y: 0.5 } } });
  context.scheduleLutPreviewStill(clip, 2);
  await reply(requests[1], 'stale-wheels');
  assert.equal(decodes.length, 0, 'older wheel response is rejected before decode');
  await fire();
  assert.equal(requests.length, 3);
  await reply(requests[2], 'current-wheels');
  assert.equal(decodes.length, 1);
  decodes[0].resolve();
  await tick();
  assert.equal(still.src, 'current-wheels');
  assert.equal(still.hidden, false);

  context.state.playing = true;
  context.scheduleLutPreviewStill(clip, 2);
  assert.equal(chip.textContent, 'Playing without color grading preview; pause or seek to see it');
  console.log('Colour-wheel preview lifecycle passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
