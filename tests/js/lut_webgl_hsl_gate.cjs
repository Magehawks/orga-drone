// WebGL LUT preview must fall back while HSL or colour wheels are active.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const policyPromise = import('../../src/orga_drone/static/js/studio/proxy-policy.js');

(async () => {
  const policy = await policyPromise;
  const script = fs.readFileSync('src/orga_drone/static/js/studio.js', 'utf8');
  function section(start, end) { return script.split(start)[1].split(end)[0]; }
  const source = 'function colorAnimationKeys' + section('function colorAnimationKeys', 'function lutRendererFor');
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
    evaluateLutWebglHandling: policy.evaluateLutWebglHandling,
    createManagedGradePreviewCache: () => ({
      readManagedGrade: () => null,
      writeManagedGrade: () => {},
      ensureCached: async () => null,
      cacheFillResult: () => false,
    }),
    fetchGrade: async () => null,
    probeManagedGpuCapabilities: () => ({ supported: false, mode: "cpu" }),
    managedBakeUrl: () => "",
    managedColorEditor: null,
    Boolean, Array, String,
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
})().catch(error => { console.error(error); process.exitCode = 1; });
