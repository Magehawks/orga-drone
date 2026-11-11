/** Public Color Scopes UI surface for Studio entry wiring. */

export {
  SCOPE_FRAME_VERSION,
  SCOPE_PROFILES,
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
  SCOPE_TRANSFERS,
  createScopeFrameV1,
  describeScopeSource,
  isScopeFrameCurrent,
  requireSafeInt,
  scopeFrameIdentity,
  scopeViewKey,
} from "./scope-frame.js";

export {
  LUMA_COEFF,
  VECTORSCOPE_CB_SCALE,
  VECTORSCOPE_CR_SCALE,
  accumulateAllScopes,
  accumulateHistogram,
  accumulateRgbParade,
  accumulateVectorscope,
  accumulateWaveform,
  expandLegalRange,
  histogramBin,
  lumaY,
  normalizeDensityLog1p,
  vectorscopeCbCr,
} from "./accumulate.js";

export {
  COLOR_BAR_RGB,
  FIXTURE_IDS,
  colorBarVectorscopeTargets,
  createScopeFixture,
  listScopeFixtures,
} from "./fixtures.js";

export {
  paintHistogram,
  paintRgbParade,
  paintScope,
  paintVectorscope,
  paintWaveform,
} from "./render.js";

export { SCOPE_KINDS, createColorScopesPanel } from "./panel.js";
