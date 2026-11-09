import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const studioJs = path.resolve(here, "../../src/orga_drone/static/js/studio.js");

test("studio.js keeps a single selectedVideoClip binding", () => {
  const script = fs.readFileSync(studioJs, "utf8");
  const decls = script.match(/\b(?:function|const)\s+selectedVideoClip\b/g) || [];
  assert.equal(
    decls.length,
    1,
    `expected one selectedVideoClip binding, found ${decls.length}: ${decls.join(", ")}`
  );
});

test("studio.js parses as an ES module", () => {
  const checked = spawnSync(process.execPath, ["--check", studioJs], {
    encoding: "utf8",
  });
  assert.equal(checked.status, 0, checked.stderr || checked.stdout || "node --check failed");
});
