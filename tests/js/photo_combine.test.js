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
  assert.match(src, /detail-photo-combine-from-library/);
  assert.match(src, /detail-photo-combine-from-computer/);
  assert.match(src, /detail-photo-combine-library-dialog/);
  assert.match(src, /\/api\/search/);
  assert.match(src, /\/api\/desktop\/pick-open-file/);
  assert.match(src, /allow_multiple:\s*true/);
  assert.match(src, /source_path/);
  assert.match(src, /entry_id/);
  assert.match(src, /AbortController/);
  assert.match(src, /status === 409/);
  assert.match(src, /loadLibraryPhotos\(libraryFilter\.value\)/);
  assert.doesNotMatch(src, /detail-photo-combine-search/);
});
