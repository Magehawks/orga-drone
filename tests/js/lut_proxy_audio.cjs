// Custom clip-audio rules with the experimental LUT proxy (#228).
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync('src/orga_drone/static/js/studio.js', 'utf8');
function section(start, end) { return script.split(start)[1].split(end)[0]; }
const source =
  'function clipOffsetFromMediaTime' + section('function clipOffsetFromMediaTime', 'function videoSrcFor') +
  'function readClipAudio' + section('function readClipAudio', 'function makeAudioBar') +
  'function syncClipAudio' + section('function syncClipAudio', 'function applyClipPlayback');
let proxyActive = true;
const audio = {
  dataset: {}, paused: false, currentTime: 0, src: '', volume: 1,
  playCount: 0, pauseCount: 0,
  play() { this.playCount += 1; this.paused = false; return Promise.resolve(); },
  pause() { this.pauseCount += 1; this.paused = true; },
};
const context = {
  lutProxyActiveFor: () => proxyActive,
  clipAudioEl: () => audio,
  previewVideo: null,
  state: { volume: 0.8 },
  sourceInS: clip => Number(clip.dataset.sourceIn || 0),
  sourceOutS: clip => Number(clip.dataset.sourceOut || 10),
  playbackSpeed: () => 1,
  slowBarOf: () => null,
  speedAtSource: () => 1,
  sourceToStory: (clip, offset) => offset,
  Number, JSON, Math,
};
vm.createContext(context);
vm.runInContext(source, context);
function reset() {
  audio.dataset = {};
  audio.paused = false;
  audio.currentTime = 0;
  audio.src = '';
  audio.volume = 1;
  audio.playCount = 0;
  audio.pauseCount = 0;
}
function call(clip, video) {
  context.previewVideo = video;
  context.syncClipAudio(video, clip);
}
const custom = {
  dataset: {
    kind: 'video', streamUrl: '/media/1/stream', sourceIn: '5', sourceOut: '9',
    clipAudio: JSON.stringify({
      active: true, source_in_s: 8, source_out_s: 10, place_s: 0.5,
    }),
  },
};
const plain = {
  dataset: {
    kind: 'video', streamUrl: '/media/1/stream', sourceIn: '5', sourceOut: '9',
    clipAudio: 'null',
  },
};
const video = { currentTime: 1.2, paused: false, muted: false, volume: 1 };

proxyActive = true;
reset();
call(plain, video);
assert.equal(video.muted, false, 'proxy audio remains the only track');
assert.equal(video.volume, 0.8);
assert.equal(audio.playCount, 0);
assert.ok(audio.pauseCount > 0);

reset();
call(custom, video);
assert.equal(video.muted, true, 'proxy picture is muted when custom audio is used');
assert.equal(audio.src, '/media/1/stream');
assert.ok(Math.abs(audio.currentTime - 8.7) < 0.001, 'trim target uses proxy-local time');
assert.equal(audio.volume, 0.8);
assert.equal(audio.playCount, 1);

reset();
const late = { currentTime: 5, paused: false, muted: false, volume: 1 };
call(custom, late);
assert.equal(late.muted, true);
assert.equal(audio.playCount, 0, 'outside the audible trim window stays silent');
assert.ok(audio.pauseCount > 0);

proxyActive = false;
reset();
const sourceVideo = { currentTime: 6.2, paused: false, muted: false, volume: 1 };
call(custom, sourceVideo);
assert.equal(sourceVideo.muted, true);
assert.ok(Math.abs(audio.currentTime - 8.7) < 0.001, 'ordinary source path unchanged');
assert.equal(audio.playCount, 1);
console.log('lut proxy audio rules ok');
