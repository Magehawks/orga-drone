/**
 * Collage multi-leaf playback helpers (ADR 0038 / #461).
 * Leaf videos follow the Story wall clock; they never drive it.
 */

export const MAX_CONCURRENT_COLLAGE_VIDEOS = 4;

/**
 * @param {number} localS story-local time inside the collage item
 * @param {number} startOffsetS leaf media start offset
 * @param {number|null|undefined} mediaDurationS source duration when known
 * @returns {{ t: number, hold: boolean }}
 */
export function leafSourceTime(localS, startOffsetS, mediaDurationS) {
  const local = Math.max(0, Number(localS) || 0);
  const offset = Math.max(0, Number(startOffsetS) || 0);
  const raw = offset + local;
  const duration =
    mediaDurationS == null || !(Number(mediaDurationS) > 0)
      ? null
      : Math.max(0, Number(mediaDurationS));
  if (duration == null) {
    return { t: raw, hold: false };
  }
  if (raw >= duration) {
    return { t: duration, hold: true };
  }
  return { t: raw, hold: false };
}

/**
 * @param {any} spec
 * @returns {number}
 */
export function countVideoLeaves(spec) {
  if (!spec || !spec.root) return 0;
  let count = 0;
  const walk = (node) => {
    if (!node) return;
    if (node.type === "leaf") {
      const media = node.media;
      if (media && String(media.kind || "").toLowerCase() === "video") count += 1;
      return;
    }
    walk(node.a);
    walk(node.b);
  };
  walk(spec.root);
  return count;
}

/**
 * @param {number} videoLeafCount
 * @param {number} [cap]
 */
export function shouldUseStillFallback(videoLeafCount, cap = MAX_CONCURRENT_COLLAGE_VIDEOS) {
  return Number(videoLeafCount) > Number(cap);
}

/**
 * Stream URL for a collage leaf. External leaves use the Studio leaf stream route.
 * @param {string|number} studioId
 * @param {any} leaf
 */
export function leafMediaUrl(studioId, leaf) {
  const media = leaf && leaf.media;
  if (!media) return null;
  if (media.source === "library" && media.media_id) {
    if (String(media.kind || "").toLowerCase() === "video") {
      return `/media/${media.media_id}/stream`;
    }
    return `/media/${media.media_id}/stream`;
  }
  if (media.source === "external" && media.has_path) {
    return `/api/studio/${encodeURIComponent(String(studioId))}/collage/leaves/${encodeURIComponent(String(leaf.id))}/stream`;
  }
  return null;
}

/**
 * @param {object} opts
 * @param {HTMLElement | null} opts.stage
 * @param {typeof fetch} [opts.fetchImpl]
 */
export function createCollagePlayback(opts) {
  const stage = opts.stage;
  /** @type {Map<string, HTMLVideoElement|HTMLImageElement>} */
  const mediaEls = new Map();
  let activeStudioId = null;
  let fallback = false;
  /** @type {HTMLImageElement | null} */
  let composedEl = null;
  let composedObjectUrl = null;
  let composedSeq = 0;

  function teardown() {
    composedSeq += 1;
    for (const el of mediaEls.values()) {
      if (el instanceof HTMLVideoElement) {
        try {
          el.pause();
        } catch {
          /* ignore */
        }
        el.removeAttribute("src");
        try {
          el.load();
        } catch {
          /* ignore */
        }
      }
      el.remove();
    }
    mediaEls.clear();
    if (composedObjectUrl) {
      URL.revokeObjectURL(composedObjectUrl);
      composedObjectUrl = null;
    }
    if (composedEl) {
      composedEl.remove();
      composedEl = null;
    }
    activeStudioId = null;
    fallback = false;
  }

  function pause() {
    for (const el of mediaEls.values()) {
      if (el instanceof HTMLVideoElement) {
        try {
          el.pause();
        } catch {
          /* ignore */
        }
      }
    }
  }

  /**
   * @param {object} args
   * @param {any} args.spec
   * @param {string|number} args.studioId
   * @param {Record<string, {x:number,y:number,w:number,h:number}>} args.rects
   * @param {number} args.width
   * @param {number} args.height
   * @param {boolean} [args.forceStill]
   */
  function mount({ spec, studioId, rects, width, height, forceStill = false }) {
    if (!stage || !spec) return;
    const videoCount = countVideoLeaves(spec);
    fallback = Boolean(forceStill) || shouldUseStillFallback(videoCount);
    activeStudioId = String(studioId || "");
    const keep = new Set();
    const leaves = [];
    const walk = (node) => {
      if (!node) return;
      if (node.type === "leaf") {
        leaves.push(node);
        return;
      }
      walk(node.a);
      walk(node.b);
    };
    walk(spec.root);

    if (fallback) {
      for (const [id, el] of [...mediaEls.entries()]) {
        if (el instanceof HTMLVideoElement) {
          try {
            el.pause();
          } catch {
            /* ignore */
          }
        }
        el.remove();
        mediaEls.delete(id);
      }
      return;
    }

    let videoSlots = 0;
    for (const leaf of leaves) {
      const id = String(leaf.id);
      const rect = rects[id];
      if (!rect) continue;
      keep.add(id);
      const media = leaf.media;
      if (!media) {
        const stale = mediaEls.get(id);
        if (stale) {
          if (stale instanceof HTMLVideoElement) {
            try {
              stale.pause();
            } catch {
              /* ignore */
            }
          }
          stale.remove();
          mediaEls.delete(id);
        }
        continue;
      }
      const url = leafMediaUrl(activeStudioId, leaf);
      const isVideo = String(media.kind || "").toLowerCase() === "video" && !fallback;
      let el = mediaEls.get(id);
      if (isVideo && videoSlots < MAX_CONCURRENT_COLLAGE_VIDEOS) {
        videoSlots += 1;
        if (!(el instanceof HTMLVideoElement)) {
          if (el) el.remove();
          el = document.createElement("video");
          el.muted = true;
          el.playsInline = true;
          el.preload = "auto";
          el.setAttribute("playsinline", "");
          el.setAttribute("muted", "");
          mediaEls.set(id, el);
          stage.appendChild(el);
        }
      } else {
        if (!(el instanceof HTMLImageElement) || el instanceof HTMLVideoElement) {
          if (el) {
            if (el instanceof HTMLVideoElement) {
              try {
                el.pause();
              } catch {
                /* ignore */
              }
            }
            el.remove();
          }
          el = document.createElement("img");
          el.alt = "";
          mediaEls.set(id, el);
          stage.appendChild(el);
        }
        if (media && media.source === "library" && media.media_id) {
          el.src = `/media/${media.media_id}/thumb`;
        } else if (url && !(el instanceof HTMLVideoElement)) {
          /* photos via stream; videos in fallback stay on thumb when available */
          if (media && String(media.kind || "").toLowerCase() === "photo") {
            el.src = url;
          }
        }
      }
      el.className = "studio-collage-play-media";
      el.dataset.leafId = id;
      el.style.left = `${(rect.x / width) * 100}%`;
      el.style.top = `${(rect.y / height) * 100}%`;
      el.style.width = `${(rect.w / width) * 100}%`;
      el.style.height = `${(rect.h / height) * 100}%`;
      const fit =
        media && String(media.fit || "fill").toLowerCase() === "fit" ? "contain" : "cover";
      el.style.objectFit = fit;
      if (el instanceof HTMLVideoElement && url) {
        const sourceKey = media && media.source_key ? String(media.source_key) : "";
        const token = `${url}#${sourceKey}`;
        if (el.dataset.sourceToken !== token) {
          el.dataset.sourceToken = token;
          el.src = url;
          try {
            el.load();
          } catch {
            /* ignore */
          }
        }
      }
      if (stage && !el.isConnected) {
        stage.appendChild(el);
      }
    }
    for (const [id, el] of [...mediaEls.entries()]) {
      if (!keep.has(id)) {
        if (el instanceof HTMLVideoElement) {
          try {
            el.pause();
          } catch {
            /* ignore */
          }
        }
        el.remove();
        mediaEls.delete(id);
      }
    }
  }

  /**
   * @param {object} args
   * @param {number} args.localS
   * @param {boolean} args.playing
   * @param {boolean} [args.seek]
   * @param {any} [args.spec]
   */
  async function updateComposedStill(localS) {
    if (!fallback || !stage || !activeStudioId) return;
    const seq = ++composedSeq;
    try {
      const res = await fetch(`/api/studio/${encodeURIComponent(activeStudioId)}/collage/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ t_s: Number(localS) || 0 }),
      });
      if (seq !== composedSeq) return;
      if (!res.ok) return;
      const blob = await res.blob();
      if (seq !== composedSeq) return;
      if (!composedEl) {
        composedEl = document.createElement("img");
        composedEl.alt = "";
        composedEl.className = "studio-collage-play-media studio-collage-play-composed";
      }
      if (composedObjectUrl) URL.revokeObjectURL(composedObjectUrl);
      composedObjectUrl = URL.createObjectURL(blob);
      composedEl.src = composedObjectUrl;
      composedEl.style.left = "0";
      composedEl.style.top = "0";
      composedEl.style.width = "100%";
      composedEl.style.height = "100%";
      composedEl.style.objectFit = "fill";
      composedEl.style.zIndex = "0";
      if (!composedEl.isConnected) stage.appendChild(composedEl);
    } catch {
      /* preview endpoint may be unavailable until WP4 */
    }
  }

  function sync({ localS, playing, seek = false, spec = null }) {
    if (fallback) {
      void updateComposedStill(localS);
    }
    for (const [id, el] of mediaEls.entries()) {
      if (!(el instanceof HTMLVideoElement)) continue;
      let startOffset = 0;
      let duration = Number.isFinite(el.duration) ? el.duration : null;
      if (spec && spec.root) {
        const find = (node) => {
          if (!node) return null;
          if (node.type === "leaf" && String(node.id) === id) return node;
          return find(node.a) || find(node.b);
        };
        const leaf = find(spec.root);
        if (leaf && leaf.media) {
          startOffset = Number(leaf.media.start_offset_s) || 0;
        }
      }
      const { t, hold } = leafSourceTime(localS, startOffset, duration);
      const drift = Math.abs((el.currentTime || 0) - t);
      if (seek || hold || drift > 0.3) {
        try {
          if (Number.isFinite(t)) el.currentTime = t;
        } catch {
          /* ignore seek errors before metadata */
        }
      }
      if (playing && !hold) {
        const p = el.play();
        if (p && typeof p.catch === "function") p.catch(() => {});
      } else {
        try {
          el.pause();
        } catch {
          /* ignore */
        }
      }
    }
  }

  return {
    mount,
    sync,
    pause,
    teardown,
    isFallback: () => fallback,
    MAX_CONCURRENT_COLLAGE_VIDEOS,
  };
}
