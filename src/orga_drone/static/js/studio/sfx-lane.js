/**
 * Freely placed SFX lane (#184 / ADR 0036).
 * Pure DOM helpers for clip bars; persistence stays in the entry via injectables.
 */

export const SFX_MAX_CLIPS = 16;

export function audibleSfxDurationS(clip) {
  const duration = Number(clip?.duration_s);
  const sourceIn = Number(clip?.source_in_s);
  const sourceOut = Number(clip?.source_out_s);
  if (Number.isFinite(sourceIn) && Number.isFinite(sourceOut) && sourceOut > sourceIn) {
    return sourceOut - sourceIn;
  }
  if (Number.isFinite(duration) && duration > 0) return duration;
  return 0;
}

function roundSfxTime(value) {
  return Number(Number(value).toFixed(2));
}

export function sfxAfterDrag(clip, { mode, deltaStory, minSpan = 0.05 } = {}) {
  if (!clip || (mode !== "move" && mode !== "start" && mode !== "end")) return null;
  const delta = Number(deltaStory);
  if (!Number.isFinite(delta)) return null;
  const catalog = Number(clip.duration_s);
  const media = Number.isFinite(catalog) && catalog > 0 ? catalog : null;
  let sourceIn = Number(clip.source_in_s);
  if (!Number.isFinite(sourceIn) || sourceIn < 0) sourceIn = 0;
  let sourceOut = Number(clip.source_out_s);
  if (!Number.isFinite(sourceOut))
    sourceOut = media !== null ? media : sourceIn + audibleSfxDurationS(clip);
  if (!(sourceOut > sourceIn)) return null;
  let start = Number(clip.start_s);
  if (!Number.isFinite(start) || start < 0) start = 0;
  if (mode === "move") {
    start += delta;
  } else if (mode === "start") {
    const nextIn = Math.max(0, Math.min(sourceOut - minSpan, sourceIn + delta));
    start += nextIn - sourceIn;
    sourceIn = nextIn;
  } else {
    const ceiling = media !== null ? media : Math.max(sourceOut, sourceOut + delta);
    sourceOut = Math.max(sourceIn + minSpan, Math.min(ceiling, sourceOut + delta));
  }
  if (media !== null) sourceIn = Math.min(sourceIn, Math.max(0, media - minSpan));
  if (media !== null) sourceOut = Math.min(Math.max(sourceOut, sourceIn + minSpan), media);
  if (sourceOut - sourceIn < minSpan) return null;
  start = Math.max(0, Math.min(86400, start));
  return {
    start_s: roundSfxTime(start),
    source_in_s: roundSfxTime(sourceIn),
    source_out_s: roundSfxTime(sourceOut),
  };
}

export function sfxClipStyle(clip, pxPerSecond) {
  const start = Math.max(0, Number(clip?.start_s) || 0);
  const width = Math.max(audibleSfxDurationS(clip), 0.05);
  const left = start * pxPerSecond;
  const w = width * pxPerSecond;
  return {
    left: `${left}px`,
    width: `${Math.max(w, 8)}px`,
  };
}

export function renderSfxClips({
  container,
  clips,
  pxPerSecond,
  selectedId,
  onSelect,
  onPointerDown,
  onKeyDown,
  emptyLabel,
  keyHint,
}) {
  if (!container) return;
  const list = Array.isArray(clips) ? clips : [];
  container.replaceChildren();
  if (!list.length) {
    const empty = document.createElement("div");
    empty.className = "studio-sfx-empty";
    empty.textContent = emptyLabel || "";
    container.appendChild(empty);
    return;
  }
  for (const clip of list) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "studio-sfx-clip";
    button.dataset.sfxId = String(clip.id);
    if (String(selectedId) === String(clip.id)) {
      button.classList.add("is-selected");
    }
    const style = sfxClipStyle(clip, pxPerSecond);
    button.style.left = style.left;
    button.style.width = style.width;
    const name = clip.display_name || "SFX";
    button.title = keyHint ? `${name}. ${keyHint}` : name;
    button.setAttribute("aria-label", keyHint ? `${name}. ${keyHint}` : name);
    if (keyHint) {
      button.setAttribute(
        "aria-keyshortcuts",
        "ArrowLeft ArrowRight Shift+ArrowLeft Shift+ArrowRight Alt+ArrowLeft Alt+ArrowRight"
      );
    }
    const label = document.createElement("span");
    label.className = "studio-sfx-clip-label";
    label.textContent = name;
    const edgeIn = document.createElement("span");
    edgeIn.className = "studio-sfx-edge studio-sfx-edge-in";
    const edgeOut = document.createElement("span");
    edgeOut.className = "studio-sfx-edge studio-sfx-edge-out";
    button.append(edgeIn, label, edgeOut);
    button.addEventListener("click", (event) => {
      event.preventDefault();
      onSelect?.(clip.id);
    });
    button.addEventListener("pointerdown", (event) => onPointerDown?.(event, clip));
    button.addEventListener("keydown", (event) => onKeyDown?.(event, clip));
    container.appendChild(button);
  }
}

export function applySfxPayload(stateBox, payload) {
  const clips = Array.isArray(payload?.clips) ? payload.clips.slice() : [];
  if (stateBox && typeof stateBox === "object") {
    stateBox.clips = clips;
  }
  return clips;
}
