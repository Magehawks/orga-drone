// Source/proxy selection and time mapping for the experimental LUT proxy (#223).
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync('src/orga_drone/static/js/studio.js', 'utf8');
const source = script.split('function lutProxyEligible')[1].split('function imageSrcFor')[0];
let customAudio = null;
const context = {
  root: { dataset: {} },
  state: { selected: { type: 'clip', id: '1' }, activeStudioId: null },
  loadedVideoSrc: '',
  playbackSpeed: () => 1,
  slowBarOf: () => null,
  sectionRepeats: () => 1,
  forwardLoopActive: () => false,
  readColorAnimation: () => null,
  readSaturationRamp: () => ({ enabled: false }),
  readColorLook: () => ({
    input_profile: 'custom', conversion_lut: '', creative_lut: 'a',
    creative_strength: 100, conversion_confirmed: false,
  }),
  readClipAudio: () => customAudio,
  String, Math, Array,
};
vm.createContext(context);
vm.runInContext('function lutProxyEligible' + source, context);
const clip = {
  dataset: {
    kind: 'video',
    studioId: '1',
    lutProxyUrl: '/api/studio/1/playback-proxy',
    streamUrl: '/media/1/stream',
    proxyUrl: '/media/1/proxy',
    hasProxy: '0',
  },
};
assert.equal(context.videoSrcFor(clip), clip.dataset.lutProxyUrl, 'selected clip uses proxy');
const otherClip = {
  dataset: {
    kind: 'video', studioId: '2', lutProxyUrl: '/api/studio/2/playback-proxy',
    streamUrl: '/media/2/stream', hasProxy: '0',
  },
};
context.state.selected = { type: 'clip', id: '2' };
assert.equal(context.videoSrcFor(clip), '/media/1/stream', 'proxy -> original');
context.state.activeStudioId = '1';
assert.equal(context.videoSrcFor(clip), clip.dataset.lutProxyUrl, 'active clip uses proxy without selection');
context.state.activeStudioId = null;
assert.equal(context.videoSrcFor(otherClip), otherClip.dataset.lutProxyUrl, 'original -> proxy');
context.state.selected = { type: 'clip', id: '1' };
assert.equal(context.videoSrcFor(otherClip), '/media/2/stream', 'proxy -> original (reverse)');
assert.equal(context.videoSrcFor(clip), clip.dataset.lutProxyUrl, 'proxy -> proxy selection');
context.playbackSpeed = () => 0.5;
assert.equal(context.videoSrcFor(clip), '/media/1/stream', 'slow motion falls back');
context.playbackSpeed = () => 1;
context.slowBarOf = () => ({ start: 0, end: 1 });
assert.equal(context.videoSrcFor(clip), '/media/1/stream', 'slow bar falls back');
context.slowBarOf = () => null;
context.sectionRepeats = () => 2;
assert.equal(context.videoSrcFor(clip), '/media/1/stream', 'repeat falls back');
context.sectionRepeats = () => 1;
context.readColorAnimation = () => ({ keys: [{ t: 0 }, { t: 1 }] });
assert.equal(context.videoSrcFor(clip), '/media/1/stream', 'animated look falls back');
context.readColorAnimation = () => null;
context.readSaturationRamp = () => ({ enabled: true });
assert.equal(context.videoSrcFor(clip), '/media/1/stream', 'saturation ramp falls back');
context.readSaturationRamp = () => ({ enabled: false });
assert.equal(context.videoSrcFor(clip), clip.dataset.lutProxyUrl);
customAudio = { sourceIn: 0.5, sourceOut: 2.5, place: 0 };
assert.equal(context.videoSrcFor(clip), '/media/1/stream', 'custom clip audio falls back');
customAudio = null;

assert.equal(context.clipMediaTarget(clip, 1, 5), 6, 'source media uses source in offset');
context.loadedVideoSrc = clip.dataset.lutProxyUrl;
assert.equal(context.clipMediaTarget(clip, 1, 5), 1, 'proxy uses clip-local offset');
assert.equal(context.clipOffsetFromMediaTime(clip, 1, 5), 1, 'proxy clock maps from zero');
context.loadedVideoSrc = '';
assert.equal(context.clipOffsetFromMediaTime(clip, 6, 5), 1, 'source clock subtracts source in');
clip.dataset.hasProxy = '1';
clip.dataset.lutProxyUrl = '';
assert.equal(context.videoSrcFor(clip), '/media/1/proxy', 'missing proxy falls back');
console.log('lut proxy mapping ok');
