import {
  MAX_TIMELAPSE_SPEED,
  MIN_TIMELAPSE_SPEED,
  allowedTargetRange,
  captureValidatedDraft,
  draftFromSpeed,
  draftFromTarget,
  flatTimelapseRamp,
  timelapseConflict,
  validatedDraftMatches,
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
  let validated = null;

  function clipKey(clip) {
    return clip ? String(clip.dataset.studioId || "") : "";
  }

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

  function clearValidated() {
    validated = null;
    applyBtn.disabled = true;
  }

  function updateCalc(draft, span) {
    if (!calc) return;
    if (!draft) {
      calc.textContent = "";
      return;
    }
    const template =
      messages.calc ||
      "About {frames} frames (~{duration} s) at 30 fps (Story grid may differ by one frame).";
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

  function syncFrom(field) {
    const clip = getSelection();
    if (!clip || syncing || pending) return;
    syncing = true;
    lastField = field;
    try {
      const { start, end, span } = currentBounds(clip);
      const conflict = conflictFor(clip);
      if (conflict) {
        clearValidated();
        setStatus(localizeConflict(conflict), { error: true });
        updateCalc(null, span);
        return;
      }
      let draft = null;
      if (field === "speed") {
        draft = draftFromSpeed(span, Number(speedInput.value));
        // Keep the secondary field empty when the primary is invalid so Apply
        // cannot revive a stale rounded value after switching fields.
        targetInput.value = draft ? String(Number(draft.targetDurationS.toFixed(3))) : "";
      } else {
        draft = draftFromTarget(span, Number(targetInput.value));
        speedInput.value = draft ? String(Number(draft.speed.toFixed(4))) : "";
      }
      updateCalc(draft, span);
      if (!draft) {
        clearValidated();
        setStatus(messages.invalid || "Enter a valid target duration or speed.", {
          error: true,
        });
        return;
      }
      validated = captureValidatedDraft({
        clipId: clipKey(clip),
        start,
        end,
        field,
        draft,
      });
      if (draft.speed > 16) {
        setStatus(messages.previewApprox || "", { error: false });
      } else {
        setStatus("");
      }
      applyBtn.disabled = !validated;
    } finally {
      syncing = false;
    }
  }

  function fill() {
    const clip = getSelection();
    panel.hidden = !clip;
    if (!clip) {
      clearValidated();
      return;
    }
    const { start, end, span } = currentBounds(clip);
    const sameClip = selectedClip === clip;
    if (!sameClip) {
      selectedClip = clip;
      lastField = "target";
      validated = null;
      const range = allowedTargetRange(span);
      targetInput.value = range ? String(Number(range.max.toFixed(3))) : "";
      speedInput.value = String(MIN_TIMELAPSE_SPEED);
    } else if (
      validated &&
      !validatedDraftMatches(validated, { clipId: clipKey(clip), start, end })
    ) {
      // Trim, history restore, or source-range change while the same DOM node
      // stays selected — drop the stale Apply candidate.
      clearValidated();
      setStatus(messages.stale || "Source range changed. Re-enter Timelapse values.", {
        error: true,
      });
      updateCalc(null, span);
      const available = clip.dataset.available === "1";
      targetInput.disabled = !available || pending;
      speedInput.disabled = !available || pending;
      return;
    }
    const available = clip.dataset.available === "1";
    targetInput.disabled = !available || pending;
    speedInput.disabled = !available || pending;
    applyBtn.disabled = !available || pending || !validated;
    const conflict = conflictFor(clip);
    if (conflict) {
      clearValidated();
      setStatus(localizeConflict(conflict), { error: true });
      updateCalc(null, span);
      return;
    }
    if (!validated) syncFrom(lastField);
    else {
      updateCalc(validated, span);
      applyBtn.disabled = !available || pending;
      if (validated.speed > 16) setStatus(messages.previewApprox || "", { error: false });
    }
  }

  async function apply() {
    const clip = getSelection();
    if (!clip || pending) return;
    const conflict = conflictFor(clip);
    if (conflict) {
      clearValidated();
      setStatus(localizeConflict(conflict), { error: true });
      return;
    }
    const { start, end } = currentBounds(clip);
    if (!validatedDraftMatches(validated, { clipId: clipKey(clip), start, end })) {
      clearValidated();
      setStatus(messages.stale || "Source range changed. Re-enter Timelapse values.", {
        error: true,
      });
      return;
    }
    const draft = validated;
    const payload =
      Math.abs(draft.speed - 1) <= 1e-9
        ? null
        : flatTimelapseRamp(draft.start, draft.end, draft.speed);
    if (draft.speed > 1 && !payload) {
      onError();
      return;
    }
    pending = true;
    pause();
    panel.querySelectorAll("button,input").forEach((el) => {
      el.disabled = true;
    });
    const appliedKey = draft.key;
    try {
      // Re-check immediately before save so a concurrent trim cannot mutate.
      const live = currentBounds(clip);
      if (
        !validatedDraftMatches(validated, {
          clipId: clipKey(clip),
          start: live.start,
          end: live.end,
        }) ||
        validated.key !== appliedKey
      ) {
        clearValidated();
        setStatus(messages.stale || "Source range changed. Re-enter Timelapse values.", {
          error: true,
        });
        return;
      }
      await save(clip, payload);
      clearValidated();
      setStatus(messages.applied || "");
    } catch (error) {
      // Keep the last validated draft so a failed save does not look applied.
      onError(error);
      setStatus(messages.invalid || "Could not apply Timelapse.", { error: true });
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
