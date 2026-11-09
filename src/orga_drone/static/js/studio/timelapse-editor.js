import {
  MAX_TIMELAPSE_SPEED,
  MIN_TIMELAPSE_SPEED,
  allowedTargetRange,
  draftFromSpeed,
  draftFromTarget,
  flatTimelapseRamp,
  timelapseConflict,
} from "./timelapse.js";

export function createTimelapseEditor({
  panel,
  getSelection,
  readRamp,
  bounds,
  sectionRepeats,
  forwardLoop,
  save,
  pause,
  onError,
  messages,
}) {
  if (!panel) return { fill() {} };
  const targetInput = panel.querySelector("[data-timelapse-target]");
  const speedInput = panel.querySelector("[data-timelapse-speed]");
  const applyBtn = panel.querySelector("[data-timelapse-apply]");
  const status = panel.querySelector("[data-timelapse-status]");
  const calc = panel.querySelector("[data-timelapse-calc]");
  const hint = panel.querySelector("[data-timelapse-hint]");
  let selectedClip = null;
  let syncing = false;
  let pending = false;
  let lastField = "target";

  function setStatus(text, { error = false } = {}) {
    if (!status) return;
    status.textContent = text || "";
    status.hidden = !text;
    status.classList.toggle("is-error", !!error);
    if (text) status.setAttribute("role", "status");
  }

  function currentBounds(clip) {
    const range = bounds(clip);
    return { start: range.start, end: range.end, span: range.end - range.start };
  }

  function conflictFor(clip) {
    return timelapseConflict({
      hasRamp: !!readRamp(clip),
      sectionRepeats: sectionRepeats(clip),
      forwardLoop: forwardLoop(clip),
    });
  }

  function localizeConflict(code) {
    if (!code) return "";
    if (code.includes("speed ramp")) return messages.removeRamp || code;
    if (code.includes("section repeat")) return messages.removeRepeat || code;
    if (code.includes("soundtrack")) return messages.removeLoop || code;
    return code;
  }

  function formatSeconds(value) {
    if (!Number.isFinite(value)) return "—";
    return value >= 10 ? value.toFixed(1) : value.toFixed(2);
  }

  function updateCalc(draft, span) {
    if (!calc) return;
    if (!draft) {
      calc.textContent = "";
      return;
    }
    const template = messages.calc || "About {frames} frames ({duration} s) at 30 fps.";
    calc.textContent = template
      .replace("{frames}", String(draft.outputFrames))
      .replace("{duration}", formatSeconds(draft.outputDurationS));
    if (hint) {
      const range = allowedTargetRange(span);
      if (range) {
        hint.textContent = (messages.rangeHint || "")
          .replace("{min}", formatSeconds(range.min))
          .replace("{max}", formatSeconds(range.max))
          .replace("{maxSpeed}", String(MAX_TIMELAPSE_SPEED));
      }
    }
  }

  function readDraft(clip) {
    const { span } = currentBounds(clip);
    if (lastField === "speed") {
      const speed = Number(speedInput.value);
      return draftFromSpeed(span, speed);
    }
    const target = Number(targetInput.value);
    return draftFromTarget(span, target);
  }

  function syncFrom(field) {
    const clip = getSelection();
    if (!clip || syncing || pending) return;
    syncing = true;
    lastField = field;
    try {
      const { span } = currentBounds(clip);
      const conflict = conflictFor(clip);
      if (conflict) {
        setStatus(localizeConflict(conflict), { error: true });
        applyBtn.disabled = true;
        updateCalc(null, span);
        return;
      }
      let draft = null;
      if (field === "speed") {
        draft = draftFromSpeed(span, Number(speedInput.value));
        if (draft) targetInput.value = String(Number(draft.targetDurationS.toFixed(3)));
      } else {
        draft = draftFromTarget(span, Number(targetInput.value));
        if (draft) speedInput.value = String(Number(draft.speed.toFixed(4)));
      }
      updateCalc(draft, span);
      if (!draft) {
        setStatus(messages.invalid || "Enter a valid target duration or speed.", {
          error: true,
        });
        applyBtn.disabled = true;
        return;
      }
      if (draft.speed > 16) {
        setStatus(messages.previewApprox || "", { error: false });
      } else {
        setStatus("");
      }
      applyBtn.disabled = false;
    } finally {
      syncing = false;
    }
  }

  function fill() {
    const clip = getSelection();
    panel.hidden = !clip;
    if (!clip) return;
    if (selectedClip !== clip) {
      selectedClip = clip;
      lastField = "target";
      const { span } = currentBounds(clip);
      const range = allowedTargetRange(span);
      targetInput.value = range ? String(Number(range.max.toFixed(3))) : "";
      speedInput.value = String(MIN_TIMELAPSE_SPEED);
    }
    const available = clip.dataset.available === "1";
    targetInput.disabled = !available || pending;
    speedInput.disabled = !available || pending;
    applyBtn.disabled = !available || pending;
    const conflict = conflictFor(clip);
    if (conflict) {
      setStatus(localizeConflict(conflict), { error: true });
      applyBtn.disabled = true;
      updateCalc(null, currentBounds(clip).span);
      return;
    }
    syncFrom(lastField);
  }

  async function apply() {
    const clip = getSelection();
    if (!clip || pending) return;
    const conflict = conflictFor(clip);
    if (conflict) {
      setStatus(localizeConflict(conflict), { error: true });
      return;
    }
    const draft = readDraft(clip);
    if (!draft) {
      setStatus(messages.invalid || "Enter a valid target duration or speed.", {
        error: true,
      });
      return;
    }
    const { start, end } = currentBounds(clip);
    const payload =
      Math.abs(draft.speed - 1) <= 1e-9 ? null : flatTimelapseRamp(start, end, draft.speed);
    if (draft.speed > 1 && !payload) {
      onError();
      return;
    }
    pending = true;
    pause();
    panel.querySelectorAll("button,input").forEach((el) => {
      el.disabled = true;
    });
    try {
      await save(clip, payload);
      setStatus(messages.applied || "");
    } catch (error) {
      onError(error);
    } finally {
      pending = false;
      panel.querySelectorAll("button,input").forEach((el) => {
        el.disabled = false;
      });
      fill();
    }
  }

  targetInput?.addEventListener("input", () => syncFrom("target"));
  speedInput?.addEventListener("input", () => syncFrom("speed"));
  applyBtn?.addEventListener("click", () => apply());

  return { fill };
}
