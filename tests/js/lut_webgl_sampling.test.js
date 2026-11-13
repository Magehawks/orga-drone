import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(
  path.resolve(here, "../../src/orga_drone/static/js/studio-lut-webgl.js"),
  "utf8"
);
const shader = /const fs = `([\s\S]*?)`;/.exec(source)?.[1] || "";

test("WebGL LUT sampling uses tetrahedral texelFetch (#360)", () => {
  assert.match(shader, /float uConvSize/);
  assert.match(shader, /float uCreativeSize/);
  assert.match(shader, /bool tetBefore\(/);
  assert.match(shader, /texelFetch\(lut,/);
  assert.doesNotMatch(shader, /vec3 lutCoord\(/);
  assert.match(shader, /applyLut\(uConv, c, uConvSize\)/);
  assert.match(shader, /applyLut\(uCreative, c, uCreativeSize\)/);
});

test("WebGL renderer supplies each LUT texture size", () => {
  assert.match(source, /uniform1f\(this\.uConvSize/);
  assert.match(source, /uniform1f\(this\.uCreativeSize/);
  assert.match(source, /getUniformLocation\(program, "uConvSize"\)/);
  assert.match(source, /getUniformLocation\(program, "uCreativeSize"\)/);
});
