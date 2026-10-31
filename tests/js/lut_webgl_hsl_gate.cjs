// WebGL LUT preview must fall back while HSL or colour wheels are active.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync('src/orga_drone/static/js/studio.js', 'utf8');
function section(start, end) { return script.split(start)[1].split(end)[0]; }
const source = 'function lookHasLut' + section('function lookHasLut', 'function lutRendererFor');
let hslNeutral = true;
let wheelsNeutral = true;
const context = {
  window: { OrgaLutPreview: { supported: true } },
  readColorAnimation: () => null,
  readHsl: () => ({ ranges: {} }),
  hslIsNeutral: () => hslNeutral,
  readColorWheels: () => ({ wheels: {} }),
  colorWheelsIsNeutral: () => wheelsNeutral,
  readColorLook: () => ({ conversion_lut: '', creative_lut: 'a', creative_strength: 100 }),
  Boolean, Array,
};
vm.createContext(context);
vm.runInContext(source, context);
const clip = { dataset: { kind: 'video' } };
assert.equal(context.lutWebglCanHandle(clip), true, 'plain LUT clip may use WebGL');
hslNeutral = false;
assert.equal(context.lutWebglCanHandle(clip), false, 'HSL clip uses still/proxy fallback');
hslNeutral = true;
wheelsNeutral = false;
assert.equal(context.lutWebglCanHandle(clip), false, 'wheel clip uses still/proxy fallback');
wheelsNeutral = true;
assert.equal(context.lutWebglCanHandle(clip), true);
console.log('WebGL HSL/wheel fallback gate passed');
