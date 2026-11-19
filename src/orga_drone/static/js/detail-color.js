/** Photo Detail advanced color (HSL / wheels / LUT / managed gate) (#492). */

import { bindSliderNumberPair } from "./studio/slider-number-sync.js";

const HSL_RANGES = ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"];
const WHEEL_IDS = ["shadows", "midtones", "highlights"];

function clampHsl(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(-100, Math.min(100, Math.round(number)));
}

function neutralHsl() {
  const ranges = {};
  HSL_RANGES.forEach((id) => {
    ranges[id] = { hue: 0, saturation: 0, luminance: 0 };
  });
  return { ranges };
}

function neutralWheels() {
  const wheels = {};
  WHEEL_IDS.forEach((id) => {
    wheels[id] = { x: 0, y: 0 };
  });
  return { wheels };
}

function readJson(el, attr, fallback) {
  try {
    const parsed = JSON.parse(el?.dataset?.[attr] || "");
    return parsed && typeof parsed === "object" ? parsed : fallback;
  } catch (_) {
    return fallback;
  }
}

function createDetailColor() {
  const panel = document.getElementById("detail-image-adjust");
  const exportRoot = document.getElementById("detail-export");
  if (!panel) return null;
  const mediaId = panel.dataset.mediaId || exportRoot?.dataset?.mediaId;
  if (!mediaId) return null;

  const gradePreview = document.getElementById("detail-export-grade-preview");
  const pagePreview = document.querySelector(".photo-preview");
  const originalSrc = gradePreview?.getAttribute("src") || pagePreview?.getAttribute("src") || "";
  let state = readJson(panel, "photoColor", {
    hsl: neutralHsl(),
    color_wheels: neutralWheels(),
    color: {},
    managed: false,
    needs_server_preview: false,
  });
  if (!state.hsl?.ranges) state.hsl = neutralHsl();
  if (!state.color_wheels?.wheels) state.color_wheels = neutralWheels();

  let selectedRange = "red";
  let previewTimer = 0;
  let saveTimer = 0;
  const hslPairs = {};
  const undoBtn = document.getElementById("detail-color-undo");
  const redoBtn = document.getElementById("detail-color-redo");
  const managedStatus = panel.querySelector("[data-detail-managed-status]");
  const wrapBtn = panel.querySelector("[data-detail-managed-wrap]");
  const convertBtn = panel.querySelector("[data-detail-managed-convert]");

  function applyHistoryFlags(payload) {
    if (undoBtn) undoBtn.disabled = !payload?.can_undo;
    if (redoBtn) redoBtn.disabled = !payload?.can_redo;
  }

  function hslIsNeutral(hsl) {
    return HSL_RANGES.every((id) => {
      const row = hsl?.ranges?.[id] || {};
      return !row.hue && !row.saturation && !row.luminance;
    });
  }

  function wheelsIsNeutral(wheels) {
    return WHEEL_IDS.every((id) => {
      const point = wheels?.wheels?.[id] || {};
      return !point.x && !point.y;
    });
  }

  function needsServerPreview() {
    if (state.managed) return true;
    if (!hslIsNeutral(state.hsl)) return true;
    if (!wheelsIsNeutral(state.color_wheels)) return true;
    return Boolean(state.color?.creative_lut || state.color?.conversion_lut);
  }

  function fillHsl() {
    const row = state.hsl.ranges[selectedRange] || { hue: 0, saturation: 0, luminance: 0 };
    Object.entries(hslPairs).forEach(([key, pair]) => {
      pair.setValue(clampHsl(row[key] || 0));
    });
    panel.querySelectorAll("[data-detail-hsl-range]").forEach((button) => {
      const active = button.dataset.detailHslRange === selectedRange;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  function readHslFromControls() {
    const next = {
      ranges: { ...(state.hsl.ranges || neutralHsl().ranges) },
    };
    const row = { ...(next.ranges[selectedRange] || { hue: 0, saturation: 0, luminance: 0 }) };
    Object.entries(hslPairs).forEach(([key, pair]) => {
      row[key] = pair.getValue();
    });
    next.ranges[selectedRange] = row;
    return next;
  }

  function paintWheel(wheelId) {
    const point = state.color_wheels.wheels[wheelId] || { x: 0, y: 0 };
    const marker = document.getElementById(`detail-color-wheel-point-${wheelId}`);
    const wheel = document.querySelector(`[data-detail-color-wheel="${wheelId}"]`);
    if (marker) {
      marker.style.left = `${50 + point.x * 50}%`;
      marker.style.top = `${50 + point.y * 50}%`;
    }
    if (wheel) {
      const dist = Math.min(1, Math.hypot(point.x, point.y));
      wheel.setAttribute("aria-valuenow", String(dist.toFixed(3)));
    }
  }

  function fillWheels() {
    WHEEL_IDS.forEach(paintWheel);
  }

  async function refreshServerPreview() {
    const targets = [gradePreview, pagePreview].filter(Boolean);
    if (!needsServerPreview()) {
      targets.forEach((el) => {
        if (originalSrc) el.setAttribute("src", originalSrc);
        el.style.filter = "";
      });
      window.dispatchEvent(
        new CustomEvent("orga-detail-color-preview", { detail: { mode: "css" } })
      );
      return;
    }
    const url = `/api/media/${encodeURIComponent(mediaId)}/color-preview?max_edge=1080&t=${Date.now()}`;
    targets.forEach((el) => {
      el.style.filter = "";
      el.setAttribute("src", url);
    });
    window.dispatchEvent(
      new CustomEvent("orga-detail-color-preview", { detail: { mode: "server", url } })
    );
  }

  function schedulePreview() {
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(() => {
      void refreshServerPreview();
    }, 80);
  }

  async function patchJson(path, body) {
    const res = await fetch(path, {
      method: "PATCH",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "save failed");
    return data;
  }

  async function saveHsl(commit = true) {
    state.hsl = readHslFromControls();
    schedulePreview();
    if (!commit) return;
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(async () => {
      try {
        const data = await patchJson(`/api/media/${mediaId}/hsl`, state.hsl);
        state.hsl = data.hsl || state.hsl;
        applyHistoryFlags(data);
      } catch (_) {
        /* keep local state; next commit retries */
      }
    }, 160);
  }

  async function saveWheels(wheels) {
    state.color_wheels = wheels;
    fillWheels();
    schedulePreview();
    try {
      const data = await patchJson(`/api/media/${mediaId}/color-wheels`, wheels);
      state.color_wheels = data.color_wheels || wheels;
      applyHistoryFlags(data);
    } catch (_) {
      /* ignore transient */
    }
  }

  function pointFromEvent(wheelEl, event) {
    const rect = wheelEl.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const radius = Math.min(rect.width, rect.height) / 2 || 1;
    let x = (event.clientX - cx) / radius;
    let y = (event.clientY - cy) / radius;
    const dist = Math.hypot(x, y);
    if (dist > 1) {
      x /= dist;
      y /= dist;
    }
    return { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 };
  }

  // Bind HSL pairs
  [
    ["hue", "detail-hsl-hue", "detail-hsl-hue-number"],
    ["saturation", "detail-hsl-saturation", "detail-hsl-saturation-number"],
    ["luminance", "detail-hsl-luminance", "detail-hsl-luminance-number"],
  ].forEach(([key, rangeId, numberId]) => {
    const slider = document.getElementById(rangeId);
    const numberInput = document.getElementById(numberId);
    if (!slider || !numberInput) return;
    hslPairs[key] = bindSliderNumberPair({
      slider,
      numberInput,
      min: -100,
      max: 100,
      step: 1,
      onInput: () => {
        void saveHsl(false);
      },
      onCommit: () => {
        void saveHsl(true);
      },
    });
  });

  panel.querySelectorAll("[data-detail-hsl-range]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedRange = button.dataset.detailHslRange || "red";
      fillHsl();
    });
  });

  document.getElementById("detail-hsl-reset")?.addEventListener("click", () => {
    state.hsl.ranges[selectedRange] = { hue: 0, saturation: 0, luminance: 0 };
    fillHsl();
    void saveHsl(true);
  });
  document.getElementById("detail-hsl-reset-all")?.addEventListener("click", () => {
    state.hsl = neutralHsl();
    fillHsl();
    void saveHsl(true);
  });

  panel.querySelectorAll("[data-detail-color-wheel]").forEach((wheelEl) => {
    const wheelId = wheelEl.dataset.detailColorWheel;
    let dragging = false;
    const apply = (event) => {
      const point = pointFromEvent(wheelEl, event);
      const next = {
        wheels: {
          ...(state.color_wheels.wheels || {}),
          [wheelId]: point,
        },
      };
      void saveWheels(next);
    };
    wheelEl.addEventListener("pointerdown", (event) => {
      if (event.button !== undefined && event.button !== 0) return;
      dragging = true;
      wheelEl.setPointerCapture?.(event.pointerId);
      apply(event);
    });
    wheelEl.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      apply(event);
    });
    wheelEl.addEventListener("pointerup", () => {
      dragging = false;
    });
  });

  WHEEL_IDS.forEach((wheelId) => {
    document
      .getElementById(`detail-color-wheel-reset-${wheelId}`)
      ?.addEventListener("click", () => {
        const next = {
          wheels: {
            ...(state.color_wheels.wheels || {}),
            [wheelId]: { x: 0, y: 0 },
          },
        };
        void saveWheels(next);
      });
  });

  async function loadLuts() {
    const select = document.getElementById("detail-color-lut");
    if (!select) return;
    try {
      const res = await fetch("/api/luts", { headers: { Accept: "application/json" } });
      const data = await res.json().catch(() => ({}));
      const items = Array.isArray(data.items)
        ? data.items
        : Array.isArray(data.luts)
          ? data.luts
          : [];
      const current = String(state.color?.creative_lut || "");
      select.innerHTML = "";
      const none = document.createElement("option");
      none.value = "";
      none.textContent = "None";
      select.appendChild(none);
      items.forEach((lut) => {
        const asset = String(lut.asset_name || lut.filename || "");
        if (!asset) return;
        const opt = document.createElement("option");
        opt.value = asset;
        opt.textContent = lut.display_name || lut.name || asset;
        select.appendChild(opt);
      });
      select.value = current;
    } catch (_) {
      /* LUT library optional */
    }
  }

  document.getElementById("detail-color-lut")?.addEventListener("change", async (event) => {
    const asset = event.target.value || "";
    const body = {
      input_profile: state.color?.input_profile || "rec709",
      conversion_lut: state.color?.conversion_lut || "",
      creative_lut: asset,
      creative_strength: state.color?.creative_strength ?? 100,
      conversion_confirmed: Boolean(state.color?.conversion_confirmed),
    };
    try {
      const data = await patchJson(`/api/media/${mediaId}/color-look`, body);
      state.color = data.color || body;
      applyHistoryFlags(data);
      schedulePreview();
    } catch (_) {
      /* ignore */
    }
  });

  async function postHistory(kind) {
    const res = await fetch(`/api/media/${mediaId}/color/${kind}`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return;
    state.hsl = data.hsl || state.hsl;
    state.color_wheels = data.color_wheels || state.color_wheels;
    state.color = data.color || state.color;
    state.managed = Boolean(data.managed);
    applyHistoryFlags(data);
    fillHsl();
    fillWheels();
    schedulePreview();
    updateManagedChrome();
  }

  undoBtn?.addEventListener("click", () => {
    void postHistory("undo");
  });
  redoBtn?.addEventListener("click", () => {
    void postHistory("redo");
  });

  function updateManagedChrome() {
    if (managedStatus) {
      managedStatus.textContent = state.managed
        ? panel.dataset.msgManaged || "Managed Color Workspace active on this photo."
        : "";
    }
    if (convertBtn) convertBtn.hidden = state.managed;
    if (wrapBtn) wrapBtn.hidden = state.managed;
  }

  wrapBtn?.addEventListener("click", async () => {
    try {
      const res = await fetch(`/api/media/${mediaId}/grade/wrap`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "wrap failed");
      state.managed = false;
      if (managedStatus) {
        managedStatus.textContent =
          panel.dataset.msgWrap || "Legacy grade wrapped. Convert to edit managed tools.";
      }
      if (convertBtn) convertBtn.hidden = false;
      applyHistoryFlags(data);
    } catch (error) {
      if (managedStatus) managedStatus.textContent = String(error.message || error);
    }
  });

  convertBtn?.addEventListener("click", async () => {
    const ok = window.confirm(
      panel.dataset.msgConvertConfirm ||
        "Convert to managed Color Workspace? Appearance can change."
    );
    if (!ok) return;
    try {
      const res = await fetch(`/api/media/${mediaId}/grade/convert-managed`, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ acknowledge_appearance_change: true }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "convert failed");
      state.managed = true;
      updateManagedChrome();
      applyHistoryFlags(data);
      schedulePreview();
    } catch (error) {
      if (managedStatus) managedStatus.textContent = String(error.message || error);
    }
  });

  // Intercept CSS-only preview when advanced color is active.
  const originalApply = window.orgaDetailApplyGradePreview;
  window.orgaDetailColor = {
    needsServerPreview,
    refreshServerPreview,
    getState: () => state,
  };
  window.addEventListener("orga-detail-basic-preview", () => {
    if (needsServerPreview()) {
      schedulePreview();
    }
  });

  fillHsl();
  fillWheels();
  void loadLuts();
  updateManagedChrome();
  if (needsServerPreview()) schedulePreview();
  applyHistoryFlags({ can_undo: false, can_redo: false });
  void fetch(`/api/media/${mediaId}/color`, { headers: { Accept: "application/json" } })
    .then((res) => res.json())
    .then((data) => {
      if (!data?.ok) return;
      state.hsl = data.hsl || state.hsl;
      state.color_wheels = data.color_wheels || state.color_wheels;
      state.color = data.color || state.color;
      state.managed = Boolean(data.managed);
      applyHistoryFlags(data);
      fillHsl();
      fillWheels();
      updateManagedChrome();
      if (needsServerPreview()) schedulePreview();
    })
    .catch(() => {});

  return { originalApply };
}

createDetailColor();
