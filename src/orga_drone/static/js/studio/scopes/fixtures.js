/** Deterministic synthetic ScopeFrameV1 fixtures for UI and math tests. */

import { SCOPE_SOURCE_KINDS, SCOPE_TAP_IDS, createScopeFrameV1 } from "./scope-frame.js";
import { vectorscopeCbCr } from "./accumulate.js";

function fillSolid(width, height, rgba) {
  const channels = 4;
  const stride = width * channels;
  const rgb = new Float32Array(height * stride);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = y * stride + x * channels;
      rgb[i] = rgba[0];
      rgb[i + 1] = rgba[1];
      rgb[i + 2] = rgba[2];
      rgb[i + 3] = rgba[3];
    }
  }
  return { rgb, stride, channels };
}

function baseMeta(fixtureId, width, height) {
  return {
    version: 1,
    width,
    height,
    profile: "bt709",
    transfer: "bt709",
    straightAlpha: true,
    legalRange: false,
    ptsNum: 0,
    ptsDen: 1,
    frameIndex: 0,
    projectId: "fixture-project",
    clipId: "fixture-clip",
    gradeRevision: "0",
    contextDigest: `fixture:${fixtureId}`,
    tapId: SCOPE_TAP_IDS.FIXTURE,
    roi: { x: 0, y: 0, width, height },
    sampleFactor: 1,
    sourceKind: SCOPE_SOURCE_KINDS.FIXTURE,
    fixtureId,
  };
}

function solidFrame(fixtureId, rgba, size = 8) {
  const { rgb, stride, channels } = fillSolid(size, size, rgba);
  return createScopeFrameV1({
    ...baseMeta(fixtureId, size, size),
    rgb,
    stride,
    channels,
  });
}

/** Seven vertical BT.709-ish bars for vectorscope targets. */
export const COLOR_BAR_RGB = Object.freeze([
  Object.freeze([0.75, 0.75, 0.75]),
  Object.freeze([0.75, 0.75, 0]),
  Object.freeze([0, 0.75, 0.75]),
  Object.freeze([0, 0.75, 0]),
  Object.freeze([0.75, 0, 0.75]),
  Object.freeze([0.75, 0, 0]),
  Object.freeze([0, 0, 0.75]),
]);

function colorBarsFrame(width = 70, height = 40) {
  const channels = 4;
  const stride = width * channels;
  const rgb = new Float32Array(height * stride);
  const barW = Math.floor(width / COLOR_BAR_RGB.length);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const bar = Math.min(COLOR_BAR_RGB.length - 1, Math.floor(x / barW));
      const color = COLOR_BAR_RGB[bar];
      const i = y * stride + x * channels;
      rgb[i] = color[0];
      rgb[i + 1] = color[1];
      rgb[i + 2] = color[2];
      rgb[i + 3] = 1;
    }
  }
  return createScopeFrameV1({
    ...baseMeta("color-bars", width, height),
    rgb,
    stride,
    channels,
  });
}

export const FIXTURE_IDS = Object.freeze(["black", "gray", "red", "green", "blue", "color-bars"]);

export function listScopeFixtures() {
  return FIXTURE_IDS.slice();
}

export function createScopeFixture(fixtureId, overrides = {}) {
  switch (fixtureId) {
    case "black":
      return solidFrame("black", [0, 0, 0, 1], overrides.size || 8);
    case "gray":
      return solidFrame("gray", [0.5, 0.5, 0.5, 1], overrides.size || 8);
    case "red":
      return solidFrame("red", [1, 0, 0, 1], overrides.size || 8);
    case "green":
      return solidFrame("green", [0, 1, 0, 1], overrides.size || 8);
    case "blue":
      return solidFrame("blue", [0, 0, 1, 1], overrides.size || 8);
    case "color-bars":
      return colorBarsFrame(overrides.width || 70, overrides.height || 40);
    default:
      throw new Error(`Unknown scope fixture: ${fixtureId}`);
  }
}

export function colorBarVectorscopeTargets() {
  return COLOR_BAR_RGB.map((rgb) => {
    const { cb, cr } = vectorscopeCbCr(rgb[0], rgb[1], rgb[2]);
    return Object.freeze({ rgb, cb, cr });
  });
}
