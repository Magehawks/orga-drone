// Persisted HSL/wheel edits must rebuild the playback proxy, not only the still.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync('src/orga_drone/static/js/studio.js', 'utf8');
function section(start, end) { return script.split(start)[1].split(end)[0]; }
const source =
  'function writeHsl' + section('function writeHsl', 'const COLOR_WHEEL_IDS') +
  'function writeColorWheels' + section('function writeColorWheels', '// Peak-normalized');
let prepared = [];
const context = {
  clearLutPreviewStill() {},
  setLutPreviewChip() {},
  scheduleLutProxyPrepare: clip => prepared.push(clip.dataset.studioId),
  msgLutChipUpdating: 'Updating',
  hslIsNeutral: value => !value || !value.ranges ||
    Object.values(value.ranges).every(item => !item.hue && !item.saturation && !item.luminance),
  colorWheelsIsNeutral: value => !value || !value.wheels ||
    Object.values(value.wheels).every(item => !item.x && !item.y),
  neutralHslAdjust: () => ({ ranges: {} }),
  neutralColorWheels: () => ({ wheels: {} }),
  JSON, Boolean,
};
vm.createContext(context);
vm.runInContext(source, context);
const clip = { dataset: { studioId: '7', kind: 'video' } };
const hsl = { ranges: { red: { hue: 30, saturation: 0, luminance: 0 } } };
const wheels = { wheels: { shadows: { x: 0.2, y: -0.1 } } };
context.writeHsl(clip, hsl, false);
assert.equal(prepared.length, 0, 'an unsaved slider move does not rebuild the proxy');
context.writeHsl(clip, hsl, true);
assert.deepEqual(prepared, ['7'], 'saving HSL schedules a fresh playback proxy');
prepared = [];
context.writeColorWheels(clip, wheels, false);
assert.equal(prepared.length, 0);
context.writeColorWheels(clip, wheels, true);
assert.deepEqual(prepared, ['7'], 'saving wheels schedules a fresh playback proxy');
const photo = { dataset: { studioId: '8', kind: 'photo' } };
prepared = [];
context.writeColorWheels(photo, wheels, true);
assert.equal(prepared.length, 0, 'photos do not build playback proxies');
console.log('HSL/wheel playback proxy refresh ok');
