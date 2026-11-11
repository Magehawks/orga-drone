import assert from "node:assert/strict";
import test from "node:test";
import {
  beginRequestToken,
  buildColorGradeSummaryParts,
  formatColorGradeSummary,
  isCurrentRequestToken,
  shouldRefreshColorInspector,
} from "../../src/orga_drone/static/js/studio/color-workspace.js";

test("request tokens supersede older in-flight Quick Look responses per clip", () => {
  const store = new Map();
  const first = beginRequestToken(store, "11");
  const second = beginRequestToken(store, "11");
  assert.equal(first, 1);
  assert.equal(second, 2);
  assert.equal(isCurrentRequestToken(store, "11", first), false);
  assert.equal(isCurrentRequestToken(store, "11", second), true);
  beginRequestToken(store, "22");
  assert.equal(isCurrentRequestToken(store, "11", second), true);
});

test("color inspector refresh stays bound to the selected clip and current request", () => {
  assert.equal(
    shouldRefreshColorInspector({
      clipId: "11",
      selectedId: "22",
      requestCurrent: true,
    }),
    false
  );
  assert.equal(
    shouldRefreshColorInspector({
      clipId: "11",
      selectedId: "11",
      requestCurrent: false,
    }),
    false
  );
  assert.equal(
    shouldRefreshColorInspector({
      clipId: "11",
      selectedId: "11",
      requestCurrent: true,
    }),
    true
  );
});

test("grade summary lists HSL, wheels, LUT, detail and black-and-white activity", () => {
  const parts = buildColorGradeSummaryParts(
    {
      lookId: "",
      basicActive: false,
      conversionOn: true,
      creativeLutOn: true,
      hslActive: true,
      wheelsActive: true,
      tonalActive: true,
      detailActive: true,
      bwActive: true,
    },
    {
      conversion: "Camera conversion on",
      creativeLut: "Creative LUT on",
      hsl: "HSL active",
      wheels: "Color wheels active",
      tonal: "Fine-tune active",
      detail: "Sharpen or denoise on",
      bw: "Black-and-white ramp on",
    }
  );
  assert.deepEqual(parts, [
    "Camera conversion on",
    "Creative LUT on",
    "HSL active",
    "Color wheels active",
    "Fine-tune active",
    "Sharpen or denoise on",
    "Black-and-white ramp on",
  ]);
  assert.equal(formatColorGradeSummary(parts, "No color changes yet"), parts.join(" · "));
});

test("grade summary prefers Quick Look name over manual slider label", () => {
  const parts = buildColorGradeSummaryParts(
    {
      lookId: "cinematic",
      lookName: "Cinematic",
      basicActive: true,
    },
    { look: "Look: {name}", sliders: "Manual sliders" }
  );
  assert.deepEqual(parts, ["Look: Cinematic"]);
});

test("empty grade summary falls back to the neutral label", () => {
  assert.equal(formatColorGradeSummary([], "No color changes yet"), "No color changes yet");
});

test("delayed Quick Look completion must not refresh another clip's inspector", async () => {
  const tokens = new Map();
  const fills = [];
  const writes = [];
  let selectedId = "11";

  async function applyQuickLook(clipId, lookId, fetchImpl) {
    const token = beginRequestToken(tokens, clipId);
    const body = await fetchImpl(lookId);
    if (!isCurrentRequestToken(tokens, clipId, token)) return { superseded: true };
    if (!body.ok) throw new Error("failed");
    writes.push({ clipId, lookId: body.quick_look, image: body.image });
    if (
      shouldRefreshColorInspector({
        clipId,
        selectedId,
        requestCurrent: isCurrentRequestToken(tokens, clipId, token),
      })
    ) {
      fills.push(clipId);
    }
    return { superseded: false };
  }

  let resolveA;
  const pendingA = new Promise((resolve) => {
    resolveA = resolve;
  });
  const runA = applyQuickLook("11", "cinematic", async () => pendingA);
  selectedId = "22";
  await applyQuickLook("22", "vibrant", async () => ({
    ok: true,
    quick_look: "vibrant",
    image: { exposure: 5 },
  }));
  resolveA({ ok: true, quick_look: "cinematic", image: { exposure: 20 } });
  const resultA = await runA;

  assert.equal(resultA.superseded, false);
  assert.deepEqual(
    writes.map((item) => item.clipId),
    ["22", "11"]
  );
  assert.deepEqual(fills, ["22"]);
  assert.equal(writes.find((item) => item.clipId === "11").lookId, "cinematic");
});

test("reordered Quick Look responses keep only the latest look for one clip", async () => {
  const tokens = new Map();
  const applied = [];
  let resolveFirst;
  const firstBody = new Promise((resolve) => {
    resolveFirst = resolve;
  });

  async function apply(lookId, bodyPromise) {
    const token = beginRequestToken(tokens, "11");
    const body = await bodyPromise;
    if (!isCurrentRequestToken(tokens, "11", token)) return { superseded: true };
    applied.push(body.quick_look);
    return { superseded: false };
  }

  const first = apply("cinematic", firstBody);
  const second = apply("vibrant", Promise.resolve({ ok: true, quick_look: "vibrant" }));
  const secondResult = await second;
  resolveFirst({ ok: true, quick_look: "cinematic" });
  const firstResult = await first;

  assert.equal(secondResult.superseded, false);
  assert.equal(firstResult.superseded, true);
  assert.deepEqual(applied, ["vibrant"]);
});

test("failed Quick Look for a previous clip does not refill the inspector", async () => {
  const tokens = new Map();
  const fills = [];
  let selectedId = "11";
  let resolveFail;
  const failing = new Promise((resolve) => {
    resolveFail = resolve;
  });

  async function apply(clipId, bodyPromise) {
    const token = beginRequestToken(tokens, clipId);
    try {
      const body = await bodyPromise;
      if (!isCurrentRequestToken(tokens, clipId, token)) return { superseded: true };
      if (!body.ok) throw new Error("failed");
      return { superseded: false };
    } catch (err) {
      if (!isCurrentRequestToken(tokens, clipId, token)) return { superseded: true };
      throw err;
    }
  }

  const run = apply("11", failing).catch((err) => {
    if (
      shouldRefreshColorInspector({
        clipId: "11",
        selectedId,
        requestCurrent: true,
      })
    ) {
      fills.push("11");
    }
    return err;
  });
  selectedId = "22";
  resolveFail({ ok: false });
  await run;
  assert.deepEqual(fills, []);
});
