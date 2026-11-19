/** Bidirectional slider ↔ number sync for Studio/Detail color controls (#490). */

/**
 * Clamp a numeric value to [min, max] with optional step quantization.
 * Non-finite input returns ``fallback``.
 */
export function clampSyncedNumber(value, { min, max, step = 1, fallback = 0 } = {}) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  let next = Math.min(max, Math.max(min, number));
  if (step > 0) {
    const decimals = String(step).includes(".")
      ? String(step).split(".")[1].length
      : 0;
    const scaled = Math.round(next / step) * step;
    next = Number(scaled.toFixed(decimals));
    next = Math.min(max, Math.max(min, next));
  }
  return next;
}

/**
 * Wire a range input and a number input so they stay synchronized.
 *
 * - ``input`` on either updates the other and calls ``onInput(value)``.
 * - ``change`` on either, or Enter on the number field, commits via ``onCommit(value)``.
 * - Invalid number text is restored to the last valid value on commit.
 */
export function bindSliderNumberPair({
  slider,
  numberInput,
  min,
  max,
  step = 1,
  fallback = 0,
  format = (value) => String(value),
  onInput = null,
  onCommit = null,
} = {}) {
  if (!slider || !numberInput) {
    return { setValue() {}, getValue: () => fallback };
  }

  const bounds = {
    min: Number(min ?? slider.min ?? numberInput.min),
    max: Number(max ?? slider.max ?? numberInput.max),
    step: Number(step ?? slider.step ?? numberInput.step ?? 1),
    fallback,
  };

  let lastValid = clampSyncedNumber(slider.value, bounds);

  function paint(value, { emitInput = false, emitCommit = false } = {}) {
    const next = clampSyncedNumber(value, bounds);
    lastValid = next;
    const text = format(next);
    if (slider.value !== text && slider.value !== String(next)) {
      slider.value = String(next);
    } else {
      slider.value = String(next);
    }
    if (numberInput.value !== text) {
      numberInput.value = text;
    }
    if (emitInput) onInput?.(next);
    if (emitCommit) onCommit?.(next);
    return next;
  }

  function readClampedFrom(el) {
    return clampSyncedNumber(el.value, bounds);
  }

  slider.addEventListener("input", () => {
    paint(readClampedFrom(slider), { emitInput: true });
  });
  slider.addEventListener("change", () => {
    paint(readClampedFrom(slider), { emitCommit: true });
  });

  numberInput.addEventListener("input", () => {
    const raw = numberInput.value;
    if (raw === "" || raw === "-" || raw === "+" || raw === "." || raw === "-.") {
      return;
    }
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return;
    const next = clampSyncedNumber(parsed, bounds);
    lastValid = next;
    slider.value = String(next);
    onInput?.(next);
  });

  function commitNumber() {
    const raw = String(numberInput.value ?? "").trim();
    if (raw === "" || !Number.isFinite(Number(raw))) {
      paint(lastValid, { emitCommit: true });
      return;
    }
    paint(raw, { emitCommit: true });
  }

  numberInput.addEventListener("change", commitNumber);
  numberInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitNumber();
      numberInput.blur?.();
    }
  });

  paint(lastValid);

  return {
    setValue(value, { emitInput = false, emitCommit = false } = {}) {
      return paint(value, { emitInput, emitCommit });
    },
    getValue() {
      return lastValid;
    },
    setDisabled(disabled) {
      slider.disabled = Boolean(disabled);
      numberInput.disabled = Boolean(disabled);
    },
  };
}
