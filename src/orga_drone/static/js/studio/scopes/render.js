/** Canvas drawing for ScopeFrameV1 measurements. Display-only. */

import { normalizeDensityLog1p } from "./accumulate.js";

function clear(ctx, width, height, fill = "#141414") {
  ctx.fillStyle = fill;
  ctx.fillRect(0, 0, width, height);
}

function drawGrid(ctx, width, height, { xLines = 4, yLines = 4, offsetX = 0 } = {}) {
  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;
  for (let i = 1; i < xLines; i += 1) {
    const x = offsetX + (width * i) / xLines;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let i = 1; i < yLines; i += 1) {
    const y = (height * i) / yLines;
    ctx.beginPath();
    ctx.moveTo(offsetX, y);
    ctx.lineTo(offsetX + width, y);
    ctx.stroke();
  }
}

function maxBin(bins) {
  let peak = 0;
  for (let i = 0; i < bins.length; i += 1) if (bins[i] > peak) peak = bins[i];
  return peak;
}

function paintDensityRegion(ctx, density, columns, rows, x0, y0, width, height, color) {
  const norm = normalizeDensityLog1p(density);
  const image = ctx.createImageData(width, height);
  const data = image.data;
  const [cr, cg, cb] = color;
  for (let y = 0; y < height; y += 1) {
    const srcRow = Math.min(rows - 1, Math.floor((y / height) * rows));
    const flipped = rows - 1 - srcRow;
    for (let x = 0; x < width; x += 1) {
      const srcCol = Math.min(columns - 1, Math.floor((x / width) * columns));
      const amp = norm[flipped * columns + srcCol];
      const i = (y * width + x) * 4;
      data[i] = Math.round(cr * amp);
      data[i + 1] = Math.round(cg * amp);
      data[i + 2] = Math.round(cb * amp);
      data[i + 3] = Math.round(255 * Math.min(1, amp * 1.2));
    }
  }
  ctx.putImageData(image, x0, y0);
}

export function paintHistogram(canvas, histogram, { show = ["r", "g", "b", "luma"] } = {}) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  clear(ctx, width, height);
  drawGrid(ctx, width, height);
  const colors = {
    r: "rgba(255,80,80,0.85)",
    g: "rgba(80,220,120,0.85)",
    b: "rgba(90,140,255,0.85)",
    luma: "rgba(240,240,240,0.9)",
  };
  for (const channel of show) {
    const bins = histogram.absolute[channel];
    if (!bins) continue;
    const peak = maxBin(bins) || 1;
    ctx.strokeStyle = colors[channel] || "#fff";
    ctx.beginPath();
    for (let i = 0; i < 256; i += 1) {
      const x = (i / 255) * (width - 1);
      const y = height - 1 - (bins[i] / peak) * (height - 2);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
}

export function paintWaveform(canvas, waveform) {
  const ctx = canvas.getContext("2d");
  clear(ctx, canvas.width, canvas.height);
  paintDensityRegion(
    ctx,
    waveform.density,
    waveform.columns,
    waveform.rows,
    0,
    0,
    canvas.width,
    canvas.height,
    [230, 230, 230]
  );
  drawGrid(ctx, canvas.width, canvas.height);
}

export function paintRgbParade(canvas, parade) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  clear(ctx, width, height);
  const panelW = Math.floor(width / 3);
  const colors = {
    r: [255, 70, 70],
    g: [70, 220, 110],
    b: [80, 130, 255],
  };
  ["r", "g", "b"].forEach((channel, index) => {
    paintDensityRegion(
      ctx,
      parade.panels[channel],
      parade.columns,
      parade.rows,
      index * panelW,
      0,
      panelW,
      height,
      colors[channel]
    );
  });
  drawGrid(ctx, width, height, { xLines: 3, yLines: 4 });
}

export function paintVectorscope(canvas, vectorscope) {
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  clear(ctx, width, height);
  const size = Math.min(width, height);
  const ox = Math.floor((width - size) / 2);
  const oy = Math.floor((height - size) / 2);
  paintDensityRegion(
    ctx,
    vectorscope.density,
    vectorscope.size,
    vectorscope.size,
    ox,
    oy,
    size,
    size,
    [120, 220, 180]
  );
  ctx.strokeStyle = "rgba(255,255,255,0.35)";
  ctx.beginPath();
  ctx.moveTo(ox + size / 2, oy);
  ctx.lineTo(ox + size / 2, oy + size);
  ctx.moveTo(ox, oy + size / 2);
  ctx.lineTo(ox + size, oy + size / 2);
  ctx.stroke();
  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.font = "11px sans-serif";
  ctx.fillText("Cb →", ox + size - 36, oy + size / 2 - 6);
  ctx.fillText("Cr ↑", ox + size / 2 + 6, oy + 14);
}

export function paintScope(canvas, kind, measurements) {
  if (!canvas || !measurements) return;
  if (kind === "histogram") paintHistogram(canvas, measurements.histogram);
  else if (kind === "waveform") paintWaveform(canvas, measurements.waveform);
  else if (kind === "parade") paintRgbParade(canvas, measurements.parade);
  else if (kind === "vectorscope") paintVectorscope(canvas, measurements.vectorscope);
}
