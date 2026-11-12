import assert from "node:assert/strict";
import test from "node:test";
import {
  SFX_MAX_CLIPS,
  audibleSfxDurationS,
  applySfxPayload,
  sfxAfterDrag,
  sfxClipStyle,
} from "../../src/orga_drone/static/js/studio/sfx-lane.js";

test("SFX helpers map placement and payload clips", () => {
  assert.equal(SFX_MAX_CLIPS, 16);
  assert.equal(audibleSfxDurationS({ source_in_s: 0.5, source_out_s: 2.5, duration_s: 9 }), 2);
  assert.equal(audibleSfxDurationS({ duration_s: 3 }), 3);
  const style = sfxClipStyle({ start_s: 2, source_in_s: 0, source_out_s: 1 }, 10);
  assert.equal(style.left, "20px");
  assert.equal(style.width, "10px");
  const box = {};
  applySfxPayload(box, {
    clips: [{ id: 1, display_name: "wind", start_s: 1.5 }],
  });
  assert.equal(box.clips.length, 1);
  assert.equal(box.clips[0].id, 1);
});

test("SFX drag moves the story start and edge resize trims the source", () => {
  const clip = { start_s: 2, source_in_s: 0.5, source_out_s: 2.5, duration_s: 4 };
  const moved = sfxAfterDrag(clip, { mode: "move", deltaStory: 1.25 });
  assert.equal(moved.start_s, 3.25);
  assert.equal(moved.source_in_s, 0.5);
  assert.equal(moved.source_out_s, 2.5);
  const head = sfxAfterDrag(clip, { mode: "start", deltaStory: 0.2 });
  assert.equal(head.source_in_s, 0.7);
  assert.equal(head.start_s, 2.2);
  assert.equal(head.source_out_s, 2.5);
  const tail = sfxAfterDrag(clip, { mode: "end", deltaStory: 2 });
  assert.equal(tail.start_s, 2);
  assert.equal(tail.source_out_s, 4);
  assert.equal(tail.source_in_s, 0.5);
  assert.equal(sfxAfterDrag(clip, { mode: "move", deltaStory: -9 }).start_s, 0);
  assert.equal(sfxAfterDrag(clip, { mode: "start", deltaStory: -2 }).source_in_s, 0);
});
