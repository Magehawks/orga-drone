/**
 * Async preview tokens for Color Workspace (#363).
 * Bind project/clip/revision/context/generation so stale responses cannot paint.
 * Tokens are keyed (default: clipId) so parallel A/B preview fetches do not
 * invalidate each other.
 */

/**
 * @param {unknown[]} parts
 * @returns {string}
 */
export function contextDigestFromParts(parts) {
  return (Array.isArray(parts) ? parts : []).map((part) => String(part ?? "")).join("|");
}

/**
 * @param {{
 *   projectId?: string|number|null,
 *   clipId?: string|number|null,
 *   revision?: string|number|null,
 *   contextDigest?: string|null,
 *   key?: string|null,
 * }} identity
 * @returns {string}
 */
export function previewTokenKey(identity = {}) {
  if (identity.key !== null && identity.key !== undefined && identity.key !== "") {
    return String(identity.key);
  }
  return String(identity.clipId ?? "");
}

/**
 * @returns {{
 *   begin: (identity: object) => object,
 *   isCurrent: (token: object|null|undefined) => boolean,
 *   invalidate: (key?: string|null) => void,
 *   peek: (key?: string|null) => object|null,
 * }}
 */
export function createPreviewTokenStore() {
  /** @type {Map<string, {
   *   projectId: string,
   *   clipId: string,
   *   revision: string,
   *   contextDigest: string,
   *   generation: number,
   *   key: string,
   * }>} */
  const currentByKey = new Map();
  /** @type {Map<string, number>} */
  const generationByKey = new Map();

  function begin(identity = {}) {
    const key = previewTokenKey(identity);
    const generation = (Number(generationByKey.get(key)) || 0) + 1;
    generationByKey.set(key, generation);
    const token = {
      projectId: String(identity.projectId ?? ""),
      clipId: String(identity.clipId ?? ""),
      revision: String(identity.revision ?? ""),
      contextDigest: String(identity.contextDigest ?? ""),
      generation,
      key,
    };
    currentByKey.set(key, token);
    return { ...token };
  }

  function isCurrent(token) {
    if (!token) return false;
    const key = String(token.key ?? previewTokenKey(token));
    const current = currentByKey.get(key);
    if (!current) return false;
    return (
      Number(token.generation) === Number(current.generation) &&
      String(token.projectId) === current.projectId &&
      String(token.clipId) === current.clipId &&
      String(token.revision) === current.revision &&
      String(token.contextDigest) === current.contextDigest
    );
  }

  function invalidate(key) {
    if (key === null || key === undefined || key === "") {
      for (const existing of [...generationByKey.keys()]) {
        generationByKey.set(existing, (Number(generationByKey.get(existing)) || 0) + 1);
      }
      currentByKey.clear();
      return;
    }
    const id = String(key);
    generationByKey.set(id, (Number(generationByKey.get(id)) || 0) + 1);
    currentByKey.delete(id);
  }

  function peek(key) {
    if (key === null || key === undefined || key === "") {
      const first = currentByKey.values().next();
      return first.done ? null : { ...first.value };
    }
    const current = currentByKey.get(String(key));
    return current ? { ...current } : null;
  }

  return { begin, isCurrent, invalidate, peek };
}
