/**
 * Studio collage inspector + preview shell (ADR 0038 / #458).
 * Persistence goes through /api/studio/{id}/collage; media fill is WP3.
 */

import {
  PRESET_NAMES,
  aspectCss,
  collectDividers,
  iterLeaves,
  resolveRects,
} from "./collage-layout.js";

/**
 * @param {object} opts
 * @param {HTMLElement | null} opts.root
 * @param {() => HTMLElement | null} opts.getSelectedClip
 * @param {(id: string) => void} opts.showInspector
 * @param {(msg: string) => void} opts.showFlash
 * @param {(clip: HTMLElement, data: any) => void} [opts.onSpecApplied]
 * @param {typeof fetch} [opts.fetchImpl]
 */
export function createCollageEditor(opts) {
  const root = opts.root;
  const fetchImpl = opts.fetchImpl || fetch;
  const preview = document.getElementById("studio-preview-collage");
  const stage = document.getElementById("studio-preview-collage-stage");
  const durationEl = document.getElementById("inspector-collage-duration");
  const presetEl = document.getElementById("inspector-collage-preset");
  const aspectEl = document.getElementById("inspector-collage-aspect");
  const gapEl = document.getElementById("inspector-collage-gap");
  const bgEl = document.getElementById("inspector-collage-background");
  const cellActions = document.getElementById("inspector-collage-cell-actions");
  const removeForm = document.getElementById("inspector-collage-remove-form");

  let selectedLeafId = null;
  let drag = null;
  let saveChain = Promise.resolve();

  function msg(key, fallback) {
    const value = root?.dataset?.[key];
    return value && String(value).trim() ? String(value) : fallback;
  }

  function gestureGroup(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function isStillSelected(clip) {
    const selected = opts.getSelectedClip?.();
    return !!(
      selected &&
      clip &&
      String(selected.dataset?.studioId || "") === String(clip.dataset?.studioId || "")
    );
  }

  function aspectBox(spec, hostW, hostH) {
    const css = aspectCss(spec);
    const parts = String(css)
      .split("/")
      .map((part) => Number(String(part).trim()));
    const aw = parts[0] > 0 ? parts[0] : 16;
    const ah = parts[1] > 0 ? parts[1] : 9;
    const fit = Math.min(hostW / aw, hostH / ah);
    const width = Math.max(1, Math.floor(aw * fit));
    const height = Math.max(1, Math.floor(ah * fit));
    return { width, height, css };
  }

  function parseSpec(clip) {
    if (!clip) return null;
    const raw = clip.dataset.collageSpec;
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function isCollage(clip) {
    return clip?.dataset?.kind === "collage";
  }

  async function patchCollage(clip, body, group) {
    const id = clip?.dataset?.studioId;
    if (!id) return null;
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    if (group) headers["X-Studio-History-Group"] = group;
    const res = await fetchImpl(`/api/studio/${id}/collage`, {
      method: "PATCH",
      headers,
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error(data.detail || msg("collageFailed", "Could not save collage."));
    }
    if (data.collage_spec) {
      clip.dataset.collageSpec = JSON.stringify(data.collage_spec);
    }
    if (data.duration_s !== null && data.duration_s !== undefined) {
      clip.dataset.collageDuration = String(data.duration_s);
      clip.dataset.effectiveDuration = String(data.duration_s);
      const durLabel = clip.querySelector("[data-clip-duration]");
      if (durLabel) durLabel.textContent = `${Number(data.duration_s).toFixed(1)}s`;
    }
    opts.onSpecApplied?.(clip, data);
    return data;
  }

  function queueSave(clip, body, group) {
    saveChain = saveChain
      .catch(() => {})
      .then(() => patchCollage(clip, body, group))
      .catch((err) => {
        opts.showFlash(err?.message || msg("collageFailed", "Could not save collage."));
      });
    return saveChain;
  }

  function renderPreview(clip) {
    if (!preview || !stage) return;
    const spec = parseSpec(clip);
    if (!isCollage(clip) || !spec) {
      preview.hidden = true;
      stage.replaceChildren();
      return;
    }
    preview.hidden = false;
    const bg = spec.background === "transparent" ? "#0a0c0e" : spec.background || "#0a0c0e";
    stage.style.background = bg;
    const host = preview.getBoundingClientRect();
    const hostW = Math.max(1, Math.round(host.width || preview.clientWidth || 640));
    const hostH = Math.max(1, Math.round(host.height || preview.clientHeight || (hostW * 9) / 16));
    const box = aspectBox(spec, hostW, hostH);
    stage.style.aspectRatio = box.css;
    stage.style.width = `${box.width}px`;
    stage.style.height = `${box.height}px`;
    const width = box.width;
    const height = box.height;
    const rects = resolveRects(spec, width, height);
    const leaves = iterLeaves(spec.root);
    const emptyLabel = msg("collageEmptyCell", "Empty cell");
    stage.replaceChildren();
    for (const leaf of leaves) {
      const rect = rects[String(leaf.id)];
      if (!rect) continue;
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "studio-collage-cell";
      if (selectedLeafId && String(selectedLeafId) === String(leaf.id)) {
        cell.classList.add("is-selected");
      }
      cell.dataset.leafId = String(leaf.id);
      cell.style.left = `${(rect.x / width) * 100}%`;
      cell.style.top = `${(rect.y / height) * 100}%`;
      cell.style.width = `${(rect.w / width) * 100}%`;
      cell.style.height = `${(rect.h / height) * 100}%`;
      const label = document.createElement("span");
      label.textContent = leaf.media
        ? leaf.media.display_name || leaf.media.kind || "Media"
        : emptyLabel;
      cell.appendChild(label);
      cell.addEventListener("click", () => {
        selectedLeafId = String(leaf.id);
        if (cellActions) cellActions.hidden = false;
        renderPreview(clip);
      });
      stage.appendChild(cell);
    }
    const dividers = collectDividers(spec.root, 0, 0, width, height, Number(spec.gap_px) || 0);
    for (const div of dividers) {
      const handle = document.createElement("div");
      handle.className = `studio-collage-divider is-${div.dir}`;
      handle.dataset.splitId = div.id;
      handle.style.left = `${(div.x / width) * 100}%`;
      handle.style.top = `${(div.y / height) * 100}%`;
      handle.style.width = `${(div.w / width) * 100}%`;
      handle.style.height = `${(div.h / height) * 100}%`;
      handle.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        handle.setPointerCapture(event.pointerId);
        drag = {
          clip,
          splitId: div.id,
          dir: div.dir,
          origin: div.origin,
          span: div.span,
          startRatio: div.ratio,
        };
      });
      stage.appendChild(handle);
    }
  }

  function fillInspector(clip) {
    if (!isCollage(clip)) return;
    opts.showInspector("inspector-collage");
    const spec = parseSpec(clip) || {};
    if (durationEl) {
      durationEl.value = String(clip.dataset.collageDuration || spec.duration_s || "5");
    }
    if (presetEl) {
      const names = Array.isArray(spec.presets) ? spec.presets : PRESET_NAMES;
      // Keep selected blank; presets replace the tree.
      presetEl.value = names.includes(presetEl.value) ? presetEl.value : "1+1";
    }
    if (aspectEl) {
      const aspect = typeof spec.aspect === "string" ? spec.aspect : "16:9";
      aspectEl.value = aspect;
    }
    if (gapEl) gapEl.value = String(spec.gap_px ?? 8);
    if (bgEl && typeof spec.background === "string" && spec.background.startsWith("#")) {
      bgEl.value = spec.background.slice(0, 7);
    }
    if (removeForm) {
      const id = clip.dataset.studioId;
      removeForm.action = `/studio/${id}/remove`;
      const btn = removeForm.querySelector("button[type='submit']");
      if (btn) btn.setAttribute("formaction", `/studio/${id}/remove`);
    }
    if (cellActions) cellActions.hidden = !selectedLeafId;
    renderPreview(clip);
  }

  function hidePreview() {
    if (preview) preview.hidden = true;
    if (stage) stage.replaceChildren();
    selectedLeafId = null;
  }

  document.getElementById("inspector-collage-duration")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !durationEl) return;
    queueSave(clip, { duration_s: Number(durationEl.value) }, gestureGroup("collage-duration"));
  });
  document.getElementById("inspector-collage-preset")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !presetEl) return;
    selectedLeafId = null;
    queueSave(clip, { preset: presetEl.value }, gestureGroup("collage-preset")).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
  });
  document.getElementById("inspector-collage-aspect")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !aspectEl) return;
    queueSave(clip, { aspect: aspectEl.value }, gestureGroup("collage-aspect")).then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  });
  document.getElementById("inspector-collage-gap")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !gapEl) return;
    queueSave(clip, { gap_px: Number(gapEl.value) }, gestureGroup("collage-gap")).then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  });
  document.getElementById("inspector-collage-background")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !bgEl) return;
    queueSave(clip, { background: bgEl.value }, gestureGroup("collage-bg")).then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  });
  document.getElementById("inspector-collage-split-h")?.addEventListener("click", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !selectedLeafId) return;
    queueSave(
      clip,
      { op: "split", leaf_id: selectedLeafId, dir: "h" },
      gestureGroup("collage-split")
    ).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
  });
  document.getElementById("inspector-collage-split-v")?.addEventListener("click", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !selectedLeafId) return;
    queueSave(
      clip,
      { op: "split", leaf_id: selectedLeafId, dir: "v" },
      gestureGroup("collage-split")
    ).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
  });
  document.getElementById("inspector-collage-remove-cell")?.addEventListener("click", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !selectedLeafId) return;
    const leafId = selectedLeafId;
    selectedLeafId = null;
    queueSave(
      clip,
      { op: "remove_leaf", leaf_id: leafId },
      gestureGroup("collage-remove-cell")
    ).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
  });

  window.addEventListener("pointermove", (event) => {
    if (!drag || !stage) return;
    const rect = stage.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const pos =
      drag.dir === "h"
        ? ((event.clientX - rect.left) / rect.width) * (stage.clientWidth || rect.width)
        : ((event.clientY - rect.top) / rect.height) * (stage.clientHeight || rect.height);
    const ratio = Math.max(0.05, Math.min(0.95, (pos - drag.origin) / Math.max(1, drag.span)));
    drag.pendingRatio = ratio;
    // Live visual only via re-render with local mutation would need a draft;
    // keep pointer feedback light until pointerup persists.
  });
  window.addEventListener("pointerup", () => {
    if (!drag) return;
    const { clip, splitId, pendingRatio, startRatio } = drag;
    drag = null;
    if (
      pendingRatio === null ||
      pendingRatio === undefined ||
      Math.abs(pendingRatio - startRatio) < 0.001
    )
      return;
    queueSave(
      clip,
      { op: "set_ratio", split_id: splitId, ratio: pendingRatio },
      gestureGroup("collage-divider")
    ).then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  });

  async function addCollage() {
    try {
      const res = await fetchImpl("/api/studio/collages", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ preset: "1+1" }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        throw new Error(data.detail || msg("collageFailed", "Could not save collage."));
      }
      const id = data.id;
      window.location.href = `/studio?select=${encodeURIComponent(String(id))}`;
    } catch (err) {
      opts.showFlash(err?.message || msg("collageFailed", "Could not save collage."));
    }
  }

  document.getElementById("studio-add-collage")?.addEventListener("click", addCollage);
  document.getElementById("studio-add-collage-empty")?.addEventListener("click", addCollage);

  return {
    isCollage,
    fillInspector,
    hidePreview,
    renderPreview,
    parseSpec,
  };
}
