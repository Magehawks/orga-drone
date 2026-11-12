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

export function sfxPreviewGain(localS, durationS, fadeInS, fadeOutS) {
  const t = Number(localS);
  const bed = Number(durationS);
  if (!Number.isFinite(t) || !Number.isFinite(bed) || t < 0 || t >= bed) return 0;
  let fadeIn = Math.max(0, Number(fadeInS) || 0);
  let fadeOut = Math.max(0, Number(fadeOutS) || 0);
  const total = fadeIn + fadeOut;
  if (!(bed > 0) || total <= 0) {
    fadeIn = 0;
    fadeOut = 0;
  } else if (total > bed) {
    const scale = bed / total;
    fadeIn *= scale;
    fadeOut *= scale;
  }
  let gain = 1;
  if (fadeIn > 0 && t < fadeIn) gain = t / fadeIn;
  const fadeOutStart = Math.max(0, bed - fadeOut);
  if (fadeOut > 0 && t > fadeOutStart) {
    gain = Math.min(gain, Math.max(0, (bed - t) / fadeOut));
  }
  return Math.max(0, Math.min(1, gain));
}

export function sfxWaveformColumns(peaks, durationS, sourceInS, sourceOutS, columnCount) {
  if (!Array.isArray(peaks) || peaks.length === 0) return [];
  const duration = Number(durationS);
  const sourceIn = Number(sourceInS);
  const sourceOut = Number(sourceOutS);
  const columns = Math.max(1, Math.floor(Number(columnCount) || 1));
  if (!(duration > 0) || !Number.isFinite(sourceIn) || !Number.isFinite(sourceOut)) return [];
  if (!(sourceOut > sourceIn)) return [];
  const span = sourceOut - sourceIn;
  const out = [];
  for (let index = 0; index < columns; index += 1) {
    const t0 = sourceIn + (span * index) / columns;
    const t1 = sourceIn + (span * (index + 1)) / columns;
    let start = Math.floor((t0 / duration) * peaks.length);
    let end = Math.ceil((t1 / duration) * peaks.length);
    start = Math.max(0, Math.min(peaks.length - 1, start));
    end = Math.max(start + 1, Math.min(peaks.length, end));
    let peak = 0;
    for (let cursor = start; cursor < end; cursor += 1) {
      const value = Number(peaks[cursor]);
      if (Number.isFinite(value) && value > peak) peak = value;
    }
    out.push(peak);
  }
  return out;
}

export function paintSfxWaveform(canvas, waveform, clip) {
  if (!canvas || typeof canvas.getContext !== "function") return;
  const context = canvas.getContext("2d");
  if (!context) return;
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight;
  if (!(cssWidth > 0) || !(cssHeight > 0)) return;
  const pixelRatio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(cssWidth * pixelRatio));
  const height = Math.max(1, Math.round(cssHeight * pixelRatio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  context.clearRect(0, 0, width, height);
  if (!waveform || waveform.status !== "ready" || !Array.isArray(waveform.peaks)) return;
  const duration = Number(waveform.duration_s) || Number(clip?.duration_s) || 0;
  const sourceIn = Math.max(0, Number(clip?.source_in_s) || 0);
  let sourceOut = Number(clip?.source_out_s);
  if (!Number.isFinite(sourceOut) || !(sourceOut > sourceIn)) {
    sourceOut = sourceIn + audibleSfxDurationS(clip);
  }
  const columns = sfxWaveformColumns(
    waveform.peaks,
    duration,
    sourceIn,
    sourceOut,
    Math.max(8, Math.floor(cssWidth / 2))
  );
  if (!columns.length) return;
  context.fillStyle = "rgba(47, 158, 143, 0.9)";
  const mid = height / 2;
  const gap = Math.max(1, Math.floor(pixelRatio));
  const barWidth = width / columns.length;
  columns.forEach((peak, index) => {
    const barHeight = Math.max(pixelRatio, peak * height * 0.82);
    context.fillRect(
      index * barWidth,
      mid - barHeight / 2,
      Math.max(pixelRatio, barWidth - gap),
      barHeight
    );
  });
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
    const wave = document.createElement("canvas");
    wave.className = "studio-sfx-wave";
    wave.setAttribute("aria-hidden", "true");
    button.dataset.waveform = clip.waveform_url ? "pending" : "none";
    const label = document.createElement("span");
    label.className = "studio-sfx-clip-label";
    label.textContent = name;
    const edgeIn = document.createElement("span");
    edgeIn.className = "studio-sfx-edge studio-sfx-edge-in";
    const edgeOut = document.createElement("span");
    edgeOut.className = "studio-sfx-edge studio-sfx-edge-out";
    button.append(wave, edgeIn, label, edgeOut);
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
