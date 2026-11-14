/**
 * Smoke: photo-combine.js ships as a page script with the expected API surface.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SCRIPT = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "src",
  "orga_drone",
  "static",
  "js",
  "photo-combine.js"
);

test("photo-combine.js targets combine endpoints and dialog entry", () => {
  const src = fs.readFileSync(SCRIPT, "utf8");
  assert.match(src, /\/api\/photo-combine\/inspect/);
  assert.match(src, /\/api\/photo-combine\/preview/);
  assert.match(src, /\/api\/photo-combine\/export/);
  assert.match(src, /detail-photo-combine-open/);
  assert.match(src, /\/api\/search/);
  assert.match(src, /entry_id/);
});
