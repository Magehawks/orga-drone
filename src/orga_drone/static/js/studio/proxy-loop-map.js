/**
 * Map one graded playback-proxy cycle onto forward-loop / section-repeat seeks.
 *
 * The proxy file is always a single play of the trimmed source (t=0 at cut-in).
 * Story wraps and overlaps must therefore seek in proxy-local time, not absolute
 * source time. Shared by Studio orchestration and focused unit tests (#294 B).
 */

/**
 * @param {boolean} proxyActive
 * @param {number} sourceInS Absolute source cut-in seconds.
 * @param {number} offsetS Clip-local offset within one play (after speed map).
 * @returns {number} currentTime to apply on the HTML media element.
 */
export function proxyRelativeMediaTime(proxyActive, sourceInS, offsetS) {
  const offset = Math.max(0, Number(offsetS) || 0);
  const inS = Math.max(0, Number(sourceInS) || 0);
  return proxyActive ? offset : inS + offset;
}

/**
 * End of the current play on the loaded media timeline.
 * Non-proxy keeps the historical ``sourceIn + mappedEnd`` absolute clock.
 * Proxy uses mappedEnd alone (proxy files start at t=0).
 *
 * @param {boolean} proxyActive
 * @param {number} sourceInS Absolute source cut-in.
 * @param {number} mappedEndS Clip-local mapped end of one play.
 * @returns {number}
 */
export function playEndMediaTime(proxyActive, sourceInS, mappedEndS) {
  const mapped = Math.max(0, Number(mappedEndS) || 0);
  const inS = Math.max(0, Number(sourceInS) || 0);
  return proxyActive ? mapped : inS + mapped;
}

/**
 * Whether a media clock has reached the end of the current play (with epsilon).
 *
 * @param {number} mediaTimeS
 * @param {number} endMediaS
 * @param {number} [epsilonS=0.01]
 */
export function mediaReachedPlayEnd(mediaTimeS, endMediaS, epsilonS = 0.01) {
  const media = Number(mediaTimeS);
  const end = Number(endMediaS);
  const eps = Number(epsilonS);
  if (!Number.isFinite(media) || !Number.isFinite(end)) return false;
  return media >= end - (Number.isFinite(eps) ? eps : 0.01);
}
