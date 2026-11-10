// Live WebGL LUT blocks fullscreen; baked proxy playback stays allowed.
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const script = fs.readFileSync("src/orga_drone/static/js/studio.js", "utf8");
function section(start, end) {
  return script.split(start)[1].split(end)[0];
}
const source =
  "function liveLutBlocksFullscreen" +
  section("function liveLutBlocksFullscreen", "function syncFullscreenControl");

let canHandle = false;
let proxyActive = false;
let hasLut = false;
const videoClip = { dataset: { kind: "video" } };
const context = {
  lutWebglCanHandle: () => canHandle,
  lutProxyActiveFor: () => proxyActive,
  lookHasLut: () => hasLut,
  readColorLook: () => ({}),
  window: { OrgaLutPreview: { supported: true } },
};
vm.createContext(context);
vm.runInContext(source, context);

assert.equal(context.liveLutBlocksFullscreen(null), false);
assert.equal(context.liveLutBlocksFullscreen({}), false, "non-video ignores LUT gate");
assert.equal(
  context.liveLutBlocksFullscreen(videoClip),
  false,
  "video without live LUT stays allowed"
);
canHandle = true;
assert.equal(
  context.liveLutBlocksFullscreen(videoClip),
  true,
  "live WebGL LUT blocks fullscreen"
);
proxyActive = true;
assert.equal(
  context.liveLutBlocksFullscreen(videoClip),
  false,
  "baked LUT proxy may use fullscreen"
);
proxyActive = false;
canHandle = false;
hasLut = true;
assert.equal(
  context.liveLutBlocksFullscreen(videoClip),
  true,
  "LUT look with WebGL support blocks fullscreen even before canHandle"
);
console.log("Live LUT fullscreen gate passed");
