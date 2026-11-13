/**
 * Preview-side managed grade cache policy for video WebGL bake.
 * Keeps legacy / failed clips from re-fetching every RAF frame and
 * rejects stale async results after a clip switch.
 */

export function createManagedGradePreviewCache({ fetchGrade }) {
  const inflightByStudioId = new Map();

  function readManagedGrade(clip) {
    if (!clip) return null;
    const raw = clip.dataset?.managedGradeJson;
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (parsed?.evaluator === "managed-sdr-v1") return parsed;
    } catch {
      /* corrupt cache */
    }
    return null;
  }

  function writeManagedGrade(clip, grade) {
    if (!clip?.dataset) return;
    if (grade?.evaluator === "managed-sdr-v1") {
      clip.dataset.managedGradeJson = JSON.stringify(grade);
      delete clip.dataset.managedGradeMiss;
      return;
    }
    if (clip.dataset.managedGradeJson) {
      delete clip.dataset.managedGradeJson;
    }
  }

  function markMiss(clip) {
    if (!clip?.dataset) return;
    clip.dataset.managedGradeMiss = "1";
    writeManagedGrade(clip, null);
  }

  function hasMiss(clip) {
    return clip?.dataset?.managedGradeMiss === "1";
  }

  function shouldStartFetch(clip) {
    if (!clip?.dataset?.studioId) return false;
    if (readManagedGrade(clip)) return false;
    if (hasMiss(clip)) return false;
    return true;
  }

  async function ensureCached(clip) {
    if (!clip?.dataset?.studioId) return null;
    const existing = readManagedGrade(clip);
    if (existing) return existing;
    if (hasMiss(clip)) return null;

    const studioId = String(clip.dataset.studioId);
    const pending = inflightByStudioId.get(studioId);
    if (pending) return pending;

    const promise = (async () => {
      try {
        const payload = await fetchGrade(studioId);
        if (String(clip.dataset.studioId) !== studioId) return null;
        if (payload?.evaluator === "managed-sdr-v1") {
          writeManagedGrade(clip, payload);
          return payload;
        }
        markMiss(clip);
        return null;
      } catch {
        if (String(clip.dataset.studioId) === studioId) {
          markMiss(clip);
        }
        return null;
      } finally {
        inflightByStudioId.delete(studioId);
      }
    })();

    inflightByStudioId.set(studioId, promise);
    return promise;
  }

  /**
   * Only cache inspector fill results when the async fill still matches
   * the clip that requested it and the editor's current studio id.
   */
  function cacheFillResult({ clip, requestedStudioId, editorStudioId, grade }) {
    if (!clip || requestedStudioId === null || requestedStudioId === undefined) return false;
    if (editorStudioId === null || editorStudioId === undefined) return false;
    if (String(clip.dataset?.studioId) !== String(requestedStudioId)) return false;
    if (String(editorStudioId) !== String(requestedStudioId)) return false;
    writeManagedGrade(clip, grade);
    return true;
  }

  return {
    readManagedGrade,
    writeManagedGrade,
    markMiss,
    hasMiss,
    shouldStartFetch,
    ensureCached,
    cacheFillResult,
    _inflightByStudioId: inflightByStudioId,
  };
}
