/**
 * Async preview tokens for Color Workspace (#363).
 * Bind project/clip/revision/context/generation so stale responses cannot paint.
 */

/**
 * @param {unknown[]} parts
 * @returns {string}
 */
export function contextDigestFromParts(parts) {
  return (Array.isArray(parts) ? parts : []).map((part) => String(part ?? "")).join("|");
}

/**
 * @returns {{
 *   begin: (identity: {
 *     projectId?: string|number|null,
 *     clipId?: string|number|null,
 *     revision?: string|number|null,
 *     contextDigest?: string|null,
 *   }) => {
 *     projectId: string,
 *     clipId: string,
 *     revision: string,
 *     contextDigest: string,
 *     generation: number,
 *   },
 *   isCurrent: (token: object|null|undefined) => boolean,
 *   invalidate: () => void,
 *   peek: () => object|null,
 * }}
 */
export function createPreviewTokenStore() {
  let generation = 0;
  /** @type {null | {
   *   projectId: string,
   *   clipId: string,
   *   revision: string,
   *   contextDigest: string,
   *   generation: number,
   * }} */
  let current = null;

  function begin(identity = {}) {
    generation += 1;
    current = {
      projectId: String(identity.projectId ?? ""),
      clipId: String(identity.clipId ?? ""),
      revision: String(identity.revision ?? ""),
      contextDigest: String(identity.contextDigest ?? ""),
      generation,
    };
    return { ...current };
  }

  function isCurrent(token) {
    if (!token || !current) return false;
    return (
      Number(token.generation) === Number(current.generation) &&
      String(token.projectId) === current.projectId &&
      String(token.clipId) === current.clipId &&
      String(token.revision) === current.revision &&
      String(token.contextDigest) === current.contextDigest
    );
  }

  function invalidate() {
    generation += 1;
    current = null;
  }

  function peek() {
    return current ? { ...current } : null;
  }

  return { begin, isCurrent, invalidate, peek };
}
