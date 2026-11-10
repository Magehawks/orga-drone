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
const context = {
  lutWebglCanHandle: () => canHandle,
  lutProxyActiveFor: () => proxyActive,
};
vm.createContext(context);
vm.runInContext(source, context);

assert.equal(context.liveLutBlocksFullscreen(null), false);
assert.equal(context.liveLutBlocksFullscreen({}), false, "no live LUT");
canHandle = true;
assert.equal(context.liveLutBlocksFullscreen({}), true, "live WebGL LUT blocks fullscreen");
proxyActive = true;
assert.equal(
  context.liveLutBlocksFullscreen({}),
  false,
  "baked LUT proxy may use fullscreen"
);
console.log("Live LUT fullscreen gate passed");
