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
 * Stream URL for a collage leaf. External and identity-key library leaves use
 * the Studio leaf stream route (server resolves paths / identity_key).
 * @param {string|number} studioId
 * @param {any} leaf
 */
export function leafMediaUrl(studioId, leaf) {
  const media = leaf && leaf.media;
  if (!media) return null;
  const leafStream = () =>
    `/api/studio/${encodeURIComponent(String(studioId))}/collage/leaves/${encodeURIComponent(String(leaf.id))}/stream`;
  if (media.source === "library") {
    if (media.media_id) {
      return `/media/${media.media_id}/stream`;
    }
    if (media.identity_key) {
      return leafStream();
    }
    return null;
  }
  if (media.source === "external" && media.has_path) {
    return leafStream();
  }
  return null;
}

/**
 * True when live object-fit alone cannot match the saved framing window.
 * @param {any} media
 */
export function leafNeedsFramedStill(media) {
  if (!media) return false;
  const zoom = Number(media.zoom);
  const panX = Number(media.pan_x);
  const panY = Number(media.pan_y);
  if (Number.isFinite(zoom) && Math.abs(zoom - 1) > 0.001) return true;
  if (Number.isFinite(panX) && Math.abs(panX - 0.5) > 0.001) return true;
  if (Number.isFinite(panY) && Math.abs(panY - 0.5) > 0.001) return true;
  return false;
}

const BROWSER_PHOTO_RE = /\.(jpe?g|png|webp|gif|bmp)$/i;
const NEEDS_DECODE_PHOTO_RE = /\.(heic|heif|dng|tif|tiff)$/i;

/**
 * Photos that WebView2 cannot show from the raw leaf stream (HEIC/HEIF/DNG/TIFF,
 * identity-only library refs, or external photos without a browser-safe name).
 * Prefer composed stills instead of assigning undecodable src.
 * @param {any} media
 */
export function leafNeedsDecodedStill(media) {
  if (!media) return false;
  if (String(media.kind || "").toLowerCase() === "video") return false;
  if (media.source === "library") {
    if (media.media_id) return false;
    return Boolean(media.identity_key);
  }
  if (media.source === "external") {
    const name = String(media.display_name || "");
    if (NEEDS_DECODE_PHOTO_RE.test(name)) return true;
    if (name && BROWSER_PHOTO_RE.test(name)) return false;
    /* Unknown or missing extension: do not risk an undecodable live <img>. */
    return true;
  }
  return false;
}

/**
 * @param {any} spec
 */
export function specNeedsFramedStill(spec) {
  if (!spec || !spec.root) return false;
  let needed = false;
  const walk = (node) => {
    if (!node || needed) return;
    if (node.type === "leaf") {
      if (leafNeedsFramedStill(node.media) || leafNeedsDecodedStill(node.media)) {
        needed = true;
      }
      return;
    }
    walk(node.a);
    walk(node.b);
  };
  walk(spec.root);
  return needed;
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
  let composedInFlight = false;
  /** @type {number | null} */
  let composedPendingLocalS = null;
  let playMediaVisible = true;

  function setPlayMediaVisible(visible) {
    playMediaVisible = Boolean(visible);
    for (const el of mediaEls.values()) {
      el.hidden = !playMediaVisible;
      el.style.visibility = playMediaVisible ? "visible" : "hidden";
    }
    if (composedEl) {
      composedEl.hidden = playMediaVisible && !fallback;
      composedEl.style.visibility = !playMediaVisible || fallback ? "visible" : "hidden";
      composedEl.style.zIndex = !playMediaVisible || fallback ? "2" : "0";
    }
  }

  function teardown() {
    composedSeq += 1;
    composedInFlight = false;
    composedPendingLocalS = null;
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
      } else {
        el.removeAttribute("src");
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
    playMediaVisible = true;
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
    fallback =
      Boolean(forceStill) || shouldUseStillFallback(videoCount) || specNeedsFramedStill(spec);
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
            stale.removeAttribute("src");
            try {
              stale.load();
            } catch {
              /* ignore */
            }
          } else {
            stale.removeAttribute("src");
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
          if (el) {
            el.removeAttribute("src");
            el.remove();
          }
          el = document.createElement("video");
          el.muted = true;
          el.playsInline = true;
          el.preload = "auto";
          el.setAttribute("playsinline", "");
          el.setAttribute("muted", "");
          mediaEls.set(id, el);
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
              el.removeAttribute("src");
              try {
                el.load();
              } catch {
                /* ignore */
              }
            } else {
              el.removeAttribute("src");
            }
            el.remove();
          }
          el = document.createElement("img");
          el.alt = "";
          mediaEls.set(id, el);
        }
        if (media && media.source === "library" && media.media_id) {
          el.src = `/media/${media.media_id}/thumb`;
        } else if (url && !(el instanceof HTMLVideoElement)) {
          /* photos via stream (incl. identity_key library); videos keep no thumb */
          if (media && String(media.kind || "").toLowerCase() === "photo") {
            const key = media.source_key ? String(media.source_key) : "";
            el.src = key ? url + "?v=" + encodeURIComponent(key) : url;
          } else {
            el.removeAttribute("src");
          }
        } else if (!(el instanceof HTMLVideoElement)) {
          el.removeAttribute("src");
        }
      }
      el.className = "studio-collage-play-media";
      el.dataset.leafId = id;
      el.hidden = !playMediaVisible;
      el.style.visibility = playMediaVisible ? "visible" : "hidden";
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
      /* Always reattach after stage.replaceChildren() in the editor. */
      stage.appendChild(el);
    }
    for (const [id, el] of [...mediaEls.entries()]) {
      if (!keep.has(id)) {
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
        } else {
          el.removeAttribute("src");
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
    if (!stage || !activeStudioId) return;
    if (!fallback && playMediaVisible) return;
    if (composedInFlight) {
      composedPendingLocalS = Number(localS) || 0;
      return;
    }
    composedInFlight = true;
    const seq = ++composedSeq;
    const requestLocalS = Number(localS) || 0;
    try {
      const res = await fetch(`/api/studio/${encodeURIComponent(activeStudioId)}/collage/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ t_s: requestLocalS }),
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
      composedEl.style.zIndex = "2";
      composedEl.hidden = false;
      composedEl.style.visibility = "visible";
      stage.appendChild(composedEl);
    } catch {
      /* preview endpoint may be unavailable until WP4 */
    } finally {
      composedInFlight = false;
      if (composedPendingLocalS !== null && seq === composedSeq) {
        const pending = composedPendingLocalS;
        composedPendingLocalS = null;
        void updateComposedStill(pending);
      }
    }
  }

  function sync({ localS, playing, seek = false, spec = null }) {
    const isPlaying = Boolean(playing);
    /* Paused: hide raw leaf media so the WP4 composed still (grades/framing) shows. */
    setPlayMediaVisible(isPlaying && !fallback);
    if (fallback || !isPlaying) {
      void updateComposedStill(localS);
    }
    for (const [id, el] of mediaEls.entries()) {
      if (!(el instanceof HTMLVideoElement)) continue;
      let startOffset = 0;
      const duration = Number.isFinite(el.duration) ? el.duration : null;
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
    setPlayMediaVisible,
    isFallback: () => fallback,
    MAX_CONCURRENT_COLLAGE_VIDEOS,
  };
}
