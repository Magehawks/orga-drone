// Colour-wheel pointer math and clamping used by the real Studio script.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync('src/orga_drone/static/js/studio.js', 'utf8');
function section(start, end) { return script.split(start)[1].split(end)[0]; }
const source = 'const COLOR_WHEEL_IDS' + section('const COLOR_WHEEL_IDS', '// Peak-normalized');
const context = {
  clearLutPreviewStill() {},
  setLutPreviewChip() {},
  msgLutChipUpdating: 'Updating picture',
  msgWheelNeutral: 'Neutral',
  Number, JSON, Math,
};
vm.createContext(context);
vm.runInContext(source, context);
const rect = { left: 0, top: 0, width: 200, height: 200 };
const near = (actual, expected, epsilon = 0.0002) => {
  assert.ok(Math.abs(actual - expected) <= epsilon, `${actual} != ${expected}`);
};
const same = (actual, expected) => assert.equal(JSON.stringify(actual), JSON.stringify(expected));

const center = context.colorWheelPointFromRect(100, 100, rect);
same(center, { x: 0, y: 0 });
const right = context.colorWheelPointFromRect(200, 100, rect);
same(right, { x: 1, y: 0 });
const bottom = context.colorWheelPointFromRect(100, 200, rect);
same(bottom, { x: 0, y: 1 });
const corner = context.colorWheelPointFromRect(200, 200, rect);
near(corner.x, Math.SQRT1_2);
near(corner.y, Math.SQRT1_2);
const tiny = context.colorWheelPointFromRect(101, 100, rect);
near(tiny.x, 0.01);
near(tiny.y, 0);
same(context.normalizeColorWheelPoint({ x: 2, y: 0 }), { x: 1, y: 0 });
same(context.normalizeColorWheelPoint({ x: 3, y: 4 }), { x: 0.7071, y: 0.7071 });
assert.equal(context.colorWheelStatusText({ x: 0, y: 0 }), 'Neutral');
assert.equal(context.colorWheelStatusText({ x: 1, y: 0 }), '0\u00b0 \u00b7 100%');
const clip = { dataset: { colorWheels: JSON.stringify({ wheels: {
  shadows: { x: 2, y: 0 },
  midtones: { x: 0.4, y: -0.2 },
  highlights: { x: 'x', y: 0.5 },
} }) } };
const wheels = context.readColorWheels(clip);
same(wheels.wheels.shadows, { x: 1, y: 0 });
same(wheels.wheels.midtones, { x: 0.4, y: -0.2 });
same(wheels.wheels.highlights, { x: 0, y: 0.5 });
assert.equal(context.colorWheelsIsNeutral(context.neutralColorWheels()), true);
assert.equal(context.colorWheelsIsNeutral(wheels), false);
console.log('Colour-wheel pointer math passed');
