// Automatic LUT proxy preparation: no flag, no manual button (#231).
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync('src/orga_drone/static/js/studio.js', 'utf8');
function section(start, end) { return script.split(start)[1].split(end)[0]; }
const source =
  'function lutProxyEligible' + section('function lutProxyEligible', 'function imageSrcFor') +
  'const lutProxyPrepare' + section('const lutProxyPrepare', 'function canvasFilterFrom');
const timers = [];
const requests = [];
let look = { conversion_lut: '', creative_lut: 'a', creative_strength: 100, conversion_confirmed: false };
let hsl = { ranges: {} };
let colorWheels = { wheels: {} };
let clipAudio = null;
const context = {
  readColorLook: () => look,
  readHsl: () => hsl,
  hslIsNeutral: value => !value || !value.ranges ||
    Object.values(value.ranges).every(item => !item.hue && !item.saturation && !item.luminance),
  readColorWheels: () => colorWheels,
  colorWheelsIsNeutral: value => !value || !value.wheels ||
    Object.values(value.wheels).every(item => !item.x && !item.y),
  lutWebglCanHandle: () => false,
  readClipAudio: () => clipAudio,
  playbackSpeed: () => 1,
  slowBarOf: () => null,
  sectionRepeats: () => 1,
  forwardLoopActive: () => false,
  readColorAnimation: () => null,
  readSaturationRamp: () => ({ enabled: false }),
  state: { selected: { type: 'clip', id: '1' }, activeStudioId: null },
  playheadDragging: false,
  window: {
    setTimeout: callback => { timers.push(callback); return timers.length; },
    clearTimeout: () => {},
  },
  fetch: (url, options) => new Promise(resolve => requests.push({ url, options, resolve })),
  setLutPreviewChip() {},
  syncPreviewMedia() { context.syncCount += 1; },
  syncCount: 0,
  String, JSON, Math,
};
vm.createContext(context);
vm.runInContext(source, context);
const clip = {
  dataset: {
    kind: 'video', studioId: '1', colorLook: '{}', imageAdjust: '{}',
    sourceIn: '0', sourceOut: '3', saturationRamp: '', playbackSpeed: '1',
  },
};
const settle = () => new Promise(resolve => setImmediate(resolve));
async function fire() {
  const pending = timers.splice(0);
  for (const callback of pending) callback();
  await settle();
}
function reply(request, url) {
  request.resolve({ ok: true, json: async () => ({ url }) });
}
(async () => {
  context.scheduleLutProxyPrepare(clip, 0);
  context.scheduleLutProxyPrepare(clip, 0);
  assert.equal(context.lutProxyPreparingFor(clip), true);
  assert.equal(timers.length, 1, 'repeated selection keeps the pending timer');
  await fire();
  assert.equal(requests.length, 1);
  reply(requests[0], '/proxy/100');
  await settle();
  assert.equal(clip.dataset.lutProxyUrl, '/proxy/100');

  // A burst of LUT strength changes keeps one render in flight and coalesces
  // later edits into a single follow-up render for the newest settings.
  requests.length = 0;
  clip.dataset.lutProxyUrl = '';
  look = { ...look, creative_strength: 50 };
  clip.dataset.colorLook = JSON.stringify(look);
  context.scheduleLutProxyPrepare(clip, 0);
  await fire();
  assert.equal(requests.length, 1);
  look = { ...look, creative_strength: 75 };
  clip.dataset.colorLook = JSON.stringify(look);
  context.scheduleLutProxyPrepare(clip, 0);
  look = { ...look, creative_strength: 100 };
  clip.dataset.colorLook = JSON.stringify(look);
  context.scheduleLutProxyPrepare(clip, 0);
  await fire();
  assert.equal(requests.length, 1, 'no second render starts while one is running');
  reply(requests[0], '/proxy/stale');
  await settle();
  assert.equal(clip.dataset.lutProxyUrl, '', 'stale response cannot activate');
  await fire();
  assert.equal(requests.length, 2, 'one final render uses the newest settings');
  reply(requests[1], '/proxy/final');
  await settle();
  assert.equal(clip.dataset.lutProxyUrl, '/proxy/final');

  // A selected but non-active clip must not reload the active picture.
  requests.length = 0;
  context.syncCount = 0;
  context.state.activeStudioId = '2';
  clip.dataset.lutProxyUrl = '';
  look = { ...look, creative_strength: 40 };
  clip.dataset.colorLook = JSON.stringify(look);
  context.scheduleLutProxyPrepare(clip, 0);
  await fire();
  reply(requests[0], '/proxy/selected-only');
  await settle();
  assert.equal(clip.dataset.lutProxyUrl, '/proxy/selected-only');
  assert.equal(context.syncCount, 0, 'selected-only completion does not reload');

  // The active clip picks up the new proxy immediately.
  requests.length = 0;
  context.syncCount = 0;
  context.state.activeStudioId = '1';
  clip.dataset.lutProxyUrl = '';
  look = { ...look, creative_strength: 30 };
  clip.dataset.colorLook = JSON.stringify(look);
  context.scheduleLutProxyPrepare(clip, 0);
  await fire();
  reply(requests[0], '/proxy/active');
  await settle();
  assert.equal(clip.dataset.lutProxyUrl, '/proxy/active');
  assert.equal(context.syncCount, 1, 'active completion refreshes the preview');

  // Ineligible clips do not request a proxy.
  requests.length = 0;
  timers.length = 0;
  clipAudio = { sourceIn: 1, sourceOut: 2, place: 0 };
  context.scheduleLutProxyPrepare(clip, 0);
  await fire();
  assert.equal(requests.length, 0, 'custom audio falls back');
  clipAudio = null;

  // No color adjustment means no proxy request.
  look = { conversion_lut: '', creative_lut: '', creative_strength: 100, conversion_confirmed: false };
  clip.dataset.colorLook = JSON.stringify(look);
  hsl = { ranges: {} };
  clip.dataset.hsl = JSON.stringify(hsl);
  colorWheels = { wheels: {} };
  clip.dataset.colorWheels = JSON.stringify(colorWheels);
  context.scheduleLutProxyPrepare(clip, 0);
  await fire();
  assert.equal(requests.length, 0, 'neutral color means no proxy');

  // HSL-only and wheels-only clips still need rendered playback colors.
  hsl = { ranges: { red: { hue: 40, saturation: 20, luminance: 0 } } };
  clip.dataset.hsl = JSON.stringify(hsl);
  context.scheduleLutProxyPrepare(clip, 0);
  await fire();
  assert.equal(requests.length, 1, 'HSL-only prepares a playback proxy');
  reply(requests[0], '/proxy/hsl');
  await settle();
  assert.equal(clip.dataset.lutProxyUrl, '/proxy/hsl');
  assert.equal(context.videoSrcFor(clip), '/proxy/hsl', 'HSL-only playback uses the proxy');

  requests.length = 0;
  hsl = { ranges: {} };
  clip.dataset.hsl = JSON.stringify(hsl);
  colorWheels = { wheels: { midtones: { x: 0.5, y: 0 } } };
  clip.dataset.colorWheels = JSON.stringify(colorWheels);
  context.scheduleLutProxyPrepare(clip, 0);
  await fire();
  assert.equal(requests.length, 1, 'wheels-only prepares a playback proxy');
  reply(requests[0], '/proxy/wheels');
  await settle();

  // A changed HSL must supersede the cached proxy for the same LUT.
  requests.length = 0;
  clip.dataset.lutProxyUrl = '/proxy/wheels';
  colorWheels = { wheels: {} };
  clip.dataset.colorWheels = JSON.stringify(colorWheels);
  look = { creative_lut: 'a', creative_strength: 100, input_profile: 'rec709', conversion_lut: '', conversion_confirmed: false };
  clip.dataset.colorLook = JSON.stringify(look);
  hsl = { ranges: { blue: { hue: -20, saturation: 0, luminance: 10 } } };
  clip.dataset.hsl = JSON.stringify(hsl);
  context.scheduleLutProxyPrepare(clip, 0);
  assert.equal(clip.dataset.lutProxyUrl, '', 'HSL change drops the stale proxy');
  await fire();
  assert.equal(requests.length, 1);
  console.log('lut proxy auto preparation ok');
})().catch(error => { console.error(error); process.exitCode = 1; });
