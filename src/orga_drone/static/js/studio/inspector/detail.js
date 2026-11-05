import { createSaver } from "../settings.js";

const NEUTRAL_DETAIL = { sharpen: 0, denoise: 0 };

export function neutralDetail() {
  return { ...NEUTRAL_DETAIL };
}

export function clampDetailSlider(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, Math.round(number)));
}

export function readDetail(clip) {
  const neutral = neutralDetail();
  if (!clip) return neutral;
  try {
    const parsed = JSON.parse(clip.dataset.detail || "");
    if (!parsed || typeof parsed !== "object") return neutral;
    return {
      sharpen: clampDetailSlider(parsed.sharpen),
      denoise: clampDetailSlider(parsed.denoise),
    };
  } catch {
    return neutral;
  }
}

export function writeDetail(clip, detail) {
  if (!clip) return;
  clip.dataset.detail = JSON.stringify(detail || neutralDetail());
}

function getElement(documentImpl, id) {
  return documentImpl && typeof documentImpl.getElementById === "function"
    ? documentImpl.getElementById(id)
    : null;
}

export function createDetailControls({
  documentImpl = globalThis.document,
  getSelectedClip = () => null,
  getClipById = () => null,
  setSaved = () => {},
  showError = () => {},
  refresh = () => {},
  errorMessage = "Could not save sharpen or denoise.",
  fetchImpl,
  readJson,
  setTimeoutImpl,
  clearTimeoutImpl,
} = {}) {
  const elements = {
    sharpen: getElement(documentImpl, "inspector-detail-sharpen"),
    denoise: getElement(documentImpl, "inspector-detail-denoise"),
    sharpenValue: getElement(documentImpl, "inspector-detail-sharpen-value"),
    denoiseValue: getElement(documentImpl, "inspector-detail-denoise-value"),
    reset: getElement(documentImpl, "inspector-detail-reset"),
  };
  const listeners = [];
  let bound = false;

  const saver = createSaver({
    url: (studioId) => `/api/studio/${studioId}/detail`,
    method: "PATCH",
    payload: (studioId) => {
      const clip = getClipById(studioId);
      return clip ? readDetail(clip) : null;
    },
    apply: (studioId, body, requestBody) => {
      const clip = getClipById(studioId);
      if (!clip) return false;
      writeDetail(clip, body.detail || requestBody);
      return true;
    },
    refresh: (studioId) => {
      const clip = getClipById(studioId);
      if (!clip) return;
      const selected = getSelectedClip();
      if (selected && String(selected.dataset.studioId) === String(studioId)) {
        fill(clip);
      }
      setSaved(true);
    },
    errorMessage,
    onError: (err) => {
      showError((err && err.message) || errorMessage);
    },
    fetchImpl,
    readJson,
    setTimeoutImpl,
    clearTimeoutImpl,
  });

  function fill(clip) {
    const detail = readDetail(clip);
    if (elements.sharpen) elements.sharpen.value = String(detail.sharpen);
    if (elements.denoise) elements.denoise.value = String(detail.denoise);
    if (elements.sharpenValue) elements.sharpenValue.textContent = String(detail.sharpen);
    if (elements.denoiseValue) elements.denoiseValue.textContent = String(detail.denoise);
  }

  function readInputs() {
    return {
      sharpen: clampDetailSlider(elements.sharpen && elements.sharpen.value),
      denoise: clampDetailSlider(elements.denoise && elements.denoise.value),
    };
  }

  function queueSave(clip) {
    const studioId = clip && clip.dataset.studioId;
    if (!studioId) return;
    saver.queue(studioId);
  }

  function on(target, event, handler) {
    if (!target || typeof target.addEventListener !== "function") return;
    target.addEventListener(event, handler);
    listeners.push({ target, event, handler });
  }

  function handleInput() {
    const clip = getSelectedClip();
    if (!clip) return;
    writeDetail(clip, readInputs());
    fill(clip);
    setSaved(false);
    refresh(clip);
  }

  function handleChange() {
    const clip = getSelectedClip();
    if (!clip) return;
    queueSave(clip);
  }

  function handleReset() {
    const clip = getSelectedClip();
    if (!clip) return;
    writeDetail(clip, neutralDetail());
    fill(clip);
    setSaved(false);
    queueSave(clip);
  }

  function bind() {
    if (bound) return;
    bound = true;
    [elements.sharpen, elements.denoise].forEach((input) => {
      on(input, "input", handleInput);
      on(input, "change", handleChange);
    });
    on(elements.reset, "click", handleReset);
  }

  function destroy() {
    listeners.forEach(({ target, event, handler }) => {
      target.removeEventListener(event, handler);
    });
    listeners.length = 0;
    bound = false;
  }

  return {
    bind,
    destroy,
    fill,
    queueSave,
    whenIdle: saver.whenIdle,
    read: readDetail,
    write: writeDetail,
    neutral: neutralDetail,
    clamp: clampDetailSlider,
  };
}
