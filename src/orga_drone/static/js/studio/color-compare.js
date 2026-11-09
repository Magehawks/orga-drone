/** Ephemeral paused-color comparison. Owns no clip settings or render caches. */
export function createColorCompare({
  button,
  status,
  getTarget,
  whenIdle,
  onChange,
  messages,
  windowImpl = window,
  documentImpl = document,
  fetchImpl = fetch,
  imageFactory = () => new Image(),
  urlImpl = URL,
}) {
  let held = false;
  let target = null;
  let picture = null;
  let objectUrl = "";
  let controller = null;
  let token = 0;
  let input = null;
  const bindings = [];
  const bind = (element, name, handler) => {
    element?.addEventListener(name, handler);
    bindings.push(() => element?.removeEventListener(name, handler));
  };
  const same = (a, b) => a && b && a.key === b.key;
  const show = (text = "") => {
    if (!status) return;
    status.textContent = text;
    status.hidden = !text;
  };
  function release() {
    const changed = held || picture;
    held = false;
    target = null;
    picture = null;
    input = null;
    token += 1;
    controller?.abort();
    controller = null;
    if (objectUrl) urlImpl.revokeObjectURL(objectUrl);
    objectUrl = "";
    button?.setAttribute("aria-pressed", "false");
    show();
    if (changed) onChange();
  }
  function refresh() {
    const current = getTarget();
    if (held && !same(target, current)) release();
    if (button) button.disabled = !current;
    return current;
  }
  async function hold(source) {
    if (held) return;
    const current = refresh();
    if (!current) return;
    held = true;
    input = source;
    target = current;
    const requestToken = ++token;
    button?.setAttribute("aria-pressed", "true");
    show(messages.loading);
    const valid = () => held && requestToken === token && same(target, getTarget());
    try {
      await whenIdle();
      if (!valid()) return;
      controller = new AbortController();
      const response = await fetchImpl(current.url, {
        cache: "no-store",
        headers: { Accept: "image/jpeg" },
        signal: controller.signal,
      });
      if (!valid()) return;
      if (!response.ok) throw new Error("Comparison unavailable");
      const blob = await response.blob();
      if (!valid()) return;
      const decodedUrl = urlImpl.createObjectURL(blob);
      const decoded = imageFactory();
      decoded.src = decodedUrl;
      try {
        await decoded.decode();
      } catch (error) {
        urlImpl.revokeObjectURL(decodedUrl);
        throw error;
      }
      if (!valid()) {
        urlImpl.revokeObjectURL(decodedUrl);
        return;
      }
      objectUrl = decodedUrl;
      picture = decoded;
      show(messages.before);
      onChange();
    } catch (error) {
      if (valid() && error?.name !== "AbortError") show(messages.failed);
    }
  }
  bind(button, "pointerdown", (event) => {
    if (event.button !== 0 || button.disabled) return;
    event.preventDefault();
    button.focus();
    button.setPointerCapture?.(event.pointerId);
    void hold("pointer");
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
    bind(button, name, () => {
      if (input === "pointer") release();
    });
  }
  bind(button, "keydown", (event) => {
    if (![" ", "Enter"].includes(event.key)) return;
    event.preventDefault();
    if (!event.repeat) void hold(event.key);
  });
  bind(button, "keyup", (event) => {
    if (![" ", "Enter"].includes(event.key)) return;
    event.preventDefault();
    if (input === event.key) release();
  });
  bind(button, "blur", release);
  bind(windowImpl, "blur", release);
  bind(windowImpl, "pagehide", release);
  bind(documentImpl, "visibilitychange", () => {
    if (documentImpl.hidden) release();
  });
  refresh();
  return {
    refresh,
    release,
    pictureFor(clip) {
      refresh();
      return held && picture && String(clip?.dataset?.studioId) === target?.id ? picture : null;
    },
    destroy() {
      release();
      bindings.forEach((unbind) => unbind());
    },
  };
}
