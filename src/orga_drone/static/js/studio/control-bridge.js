/** One sequential command handshake. Editing/preview functions are injected. */
export function hasActiveControlGesture({
  dragCard,
  musicDragCard,
  dragOriginalMediaId,
  edgeDrag,
  maskDragging,
  playheadDragging,
}) {
  return Boolean(
    dragCard || musicDragCard || dragOriginalMediaId || edgeDrag || maskDragging || playheadDragging
  );
}

export function createControlBridge({
  sessionId,
  snapshot,
  whenIdle,
  applyCanonical,
  lockInput,
  status = () => {},
  request,
}) {
  let enabled = false;
  let running = false;
  let revision = 0;
  let dirty = false;
  let settling = null;
  let stopped = false;

  function noteLocalChange() {
    revision += 1;
    dirty = true;
  }

  function readState() {
    const state = snapshot();
    return { ...state, selection_revision: revision, busy: state.busy || dirty };
  }

  async function settle() {
    if (settling || !dirty) return;
    const before = revision;
    settling = Promise.resolve().then(whenIdle);
    try {
      await settling;
      if (revision === before && !snapshot().busy) dirty = false;
    } finally {
      settling = null;
    }
  }

  async function enable(pairingKey) {
    const result = await request("enable", { session_id: sessionId, pairing_key: pairingKey });
    enabled = result.enabled;
    status(enabled ? "ready" : "off");
    return result;
  }

  async function disable() {
    enabled = false;
    const result = await request("disable", {});
    status("off");
    return result;
  }

  async function tick() {
    if (running || stopped) return;
    running = true;
    try {
      if (enabled) void settle().catch(() => status("busy"));
      const polled = await request("poll", { session_id: sessionId, state: readState() });
      enabled = polled.enabled;
      if (!enabled) {
        status("off");
        return;
      }
      const current = readState();
      status(
        current.playing
          ? "playing"
          : current.busy
            ? "busy"
            : current.ready
              ? "ready"
              : "unsupported"
      );
      for (const command of polled.commands || []) {
        // Input exclusion begins before the final synchronous local state read.
        lockInput(true);
        try {
          let result = command;
          if (!result.persisted) {
            result = await request("execute", {
              session_id: sessionId,
              command_id: command.command_id,
              state: readState(),
            });
          }
          if (result.persisted && !result.ui_applied) {
            const fresh = readState();
            if (fresh.busy || fresh.playing) continue;
            const previewStatus = applyCanonical(result);
            await request("ack", {
              session_id: sessionId,
              command_id: result.command_id,
              preview_status: previewStatus,
            });
            status("applied");
          }
        } finally {
          lockInput(false);
        }
      }
    } catch (error) {
      status(error.code === "EDITOR_SESSION_CONFLICT" ? "conflict" : "disconnected");
    } finally {
      running = false;
    }
  }

  return {
    enable,
    disable,
    tick,
    noteLocalChange,
    readState,
    stop: () => {
      stopped = true;
    },
  };
}

export function createBridgeRequest(fetchImpl) {
  return async (action, body) => {
    const response = await fetchImpl(`/api/studio/control/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const value = await response.json();
    if (!response.ok) {
      const error = new Error("External control request failed");
      error.code = value.error?.code;
      throw error;
    }
    return value;
  };
}

/** Apply canonical settings only to the explicitly identified active clip. */
export function createCanonicalApplier({
  snapshot,
  getClip,
  writeImage,
  writeColor,
  writeHsl,
  writeWheels,
  writeDetail,
  fillInspector,
  syncHistory,
  refreshPreview,
  setSaved,
}) {
  return (result) => {
    const state = snapshot();
    if (result.project_id !== state.project_id || result.clip_id !== state.clip_id) {
      throw new Error("Canonical control target no longer selected");
    }
    const clip = getClip(result.clip_id);
    if (!clip) throw new Error("Control clip no longer present");
    const canonical = result.canonical || {};
    writeImage(clip, canonical.image, true);
    writeColor(clip, canonical.color_look);
    if (canonical.hsl && writeHsl) writeHsl(clip, canonical.hsl, true);
    if (canonical.color_wheels && writeWheels) writeWheels(clip, canonical.color_wheels, true);
    if (canonical.detail && writeDetail) writeDetail(clip, canonical.detail);
    fillInspector(clip);
    syncHistory(result.can_undo, result.can_redo);
    refreshPreview();
    setSaved(true);
    return "refresh_requested";
  };
}

export function mountControlUi({
  panel,
  snapshot,
  whenIdle,
  applyCanonical,
  fetchImpl,
  hasWriteFailure = () => false,
}) {
  const statusEl = panel.querySelector("[data-control-status]");
  const keyInput = panel.querySelector("input");
  const texts = JSON.parse(panel.dataset.messages);
  let locked = false;
  let pointerActive = false;
  let keyActive = false;
  let lastChange = -1000;
  const events = [
    "pointerdown",
    "pointerup",
    "click",
    "dblclick",
    "keydown",
    "keyup",
    "input",
    "change",
    "dragstart",
    "drop",
    "wheel",
  ];
  events.forEach((name) =>
    window.addEventListener(
      name,
      (event) => {
        if (panel.contains(event.target)) return;
        if (locked) {
          event.preventDefault();
          event.stopImmediatePropagation();
          return;
        }
        if (name === "pointerdown") pointerActive = true;
        if (name === "pointerup") pointerActive = false;
        if (name === "keydown") keyActive = true;
        if (name === "keyup") keyActive = false;
        if (["pointerdown", "keydown", "input", "change", "drop"].includes(name)) {
          lastChange = performance.now();
          bridge.noteLocalChange();
        }
      },
      { capture: true, passive: false }
    )
  );
  document.addEventListener(
    "pointercancel",
    () => {
      pointerActive = false;
    },
    true
  );
  window.addEventListener("blur", () => {
    pointerActive = false;
    keyActive = false;
  });
  const bridge = createControlBridge({
    sessionId: crypto.randomUUID(),
    request: createBridgeRequest(fetchImpl),
    snapshot: () => {
      const state = snapshot();
      return {
        ...state,
        busy: state.busy || pointerActive || keyActive || performance.now() - lastChange < 500,
      };
    },
    whenIdle,
    applyCanonical,
    lockInput: (value) => {
      locked = value;
    },
    status: (code) => {
      if (code === "busy" && hasWriteFailure()) code = "save_failed";
      const next = texts[code] || texts.disconnected;
      if (statusEl.textContent !== next) statusEl.textContent = next;
    },
  });
  async function enable() {
    const key = keyInput.value;
    keyInput.value = "";
    try {
      await bridge.enable(key);
    } catch {
      statusEl.textContent = texts.enable_failed;
    }
  }
  panel.querySelector("[data-control-enable]").addEventListener("click", enable);
  keyInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void enable();
    }
  });
  panel.querySelector("[data-control-disable]").addEventListener("click", () => {
    void bridge.disable().catch(() => {
      statusEl.textContent = texts.disconnected;
    });
  });
  let timer;
  let stopped = false;
  async function poll() {
    await bridge.tick();
    if (!stopped) timer = window.setTimeout(poll, 250);
  }
  void poll();
  window.addEventListener("pagehide", () => {
    stopped = true;
    bridge.stop();
    window.clearTimeout(timer);
  });
  return bridge;
}
