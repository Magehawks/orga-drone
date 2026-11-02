export function evaluateLutProxyEligibility({
  kind,
  hasClipAudio = false,
  playbackSpeed = 1,
  hasSlowBar = false,
  sectionRepeats = 1,
  forwardLoopActive = false,
  colorAnimationKeys = 0,
  saturationRampEnabled = false,
  hasLut = false,
  hslActive = false,
  colorWheelsActive = false,
} = {}) {
  if (kind !== "video") return false;
  if (hasClipAudio) return false;
  if (Number(playbackSpeed) < 0.999 || hasSlowBar) return false;
  if (Number(sectionRepeats) > 1 || forwardLoopActive) return false;
  if (Number(colorAnimationKeys) >= 2) return false;
  if (saturationRampEnabled) return false;
  if (hasLut) return true;
  return Boolean(hslActive) || Boolean(colorWheelsActive);
}

export function evaluateLutWebglHandling({
  kind,
  webglSupported = false,
  colorAnimationKeys = 0,
  hslActive = false,
  colorWheelsActive = false,
  hasLut = false,
} = {}) {
  if (kind !== "video") return false;
  if (!webglSupported) return false;
  if (Number(colorAnimationKeys) >= 2) return false;
  if (hslActive) return false;
  if (colorWheelsActive) return false;
  return Boolean(hasLut);
}

export function lutProxyPrepareKey(dataset = {}) {
  return JSON.stringify([
    dataset.colorLook,
    dataset.imageAdjust,
    dataset.hsl,
    dataset.colorWheels,
    dataset.sourceIn,
    dataset.sourceOut,
    dataset.saturationRamp,
    dataset.playbackSpeed,
  ]);
}
