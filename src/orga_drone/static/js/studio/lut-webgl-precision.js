/** WebGL2 LUT texture precision probe and upload helpers (#360). */

export const LUT_PRECISION_RGBA8 = "rgba8";
export const LUT_PRECISION_RGBA16F = "rgba16f";
export const LUT_PRECISION_RGBA32F = "rgba32f";

/**
 * Probe which 3D LUT storage formats this WebGL2 context can upload.
 * Prefer float tables so tetrahedral texelFetch matches the CPU float path.
 * EXT_color_buffer_float is recorded for harness FBO readback; it is not
 * required to sample a float 3D LUT with texelFetch.
 *
 * @param {WebGL2RenderingContext} gl
 * @returns {{
 *   precision: "rgba32f"|"rgba16f"|"rgba8",
 *   extensions: string[],
 *   canSampleFloatLut: boolean,
 *   canRenderFloat: boolean,
 * }}
 */
export function probeLutTexturePrecision(gl) {
  const extensions = [];
  if (!gl) {
    return {
      precision: LUT_PRECISION_RGBA8,
      extensions,
      canSampleFloatLut: false,
      canRenderFloat: false,
    };
  }
  const colorBufferFloat = gl.getExtension("EXT_color_buffer_float");
  if (colorBufferFloat) extensions.push("EXT_color_buffer_float");
  const floatLinear = gl.getExtension("OES_texture_float_linear");
  if (floatLinear) extensions.push("OES_texture_float_linear");

  const canRenderFloat = Boolean(colorBufferFloat);

  if (_canUpload3d(gl, gl.RGBA32F, gl.FLOAT)) {
    return {
      precision: LUT_PRECISION_RGBA32F,
      extensions,
      canSampleFloatLut: true,
      canRenderFloat,
    };
  }
  if (_canUpload3d(gl, gl.RGBA16F, gl.HALF_FLOAT)) {
    return {
      precision: LUT_PRECISION_RGBA16F,
      extensions,
      canSampleFloatLut: true,
      canRenderFloat,
    };
  }
  return {
    precision: LUT_PRECISION_RGBA8,
    extensions,
    canSampleFloatLut: false,
    canRenderFloat,
  };
}

function _canUpload3d(gl, internalFormat, type) {
  const texture = gl.createTexture();
  if (!texture) return false;
  gl.bindTexture(gl.TEXTURE_3D, texture);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.getError(); // clear
  const pixels =
    type === gl.FLOAT
      ? new Float32Array(8 * 4)
      : type === gl.HALF_FLOAT
        ? new Uint16Array(8 * 4)
        : new Uint8Array(8 * 4);
  try {
    gl.texImage3D(gl.TEXTURE_3D, 0, internalFormat, 2, 2, 2, 0, gl.RGBA, type, pixels);
  } catch {
    gl.bindTexture(gl.TEXTURE_3D, null);
    gl.deleteTexture(texture);
    return false;
  }
  const err = gl.getError();
  gl.bindTexture(gl.TEXTURE_3D, null);
  gl.deleteTexture(texture);
  return err === gl.NO_ERROR;
}

/**
 * Quantize float RGB triples to RGBA8 UNORM (legacy WebGL path).
 * @param {Float32Array|number[]} rgbFloat packed RGB or RGBA
 * @param {number} size cube edge
 * @param {boolean} hasAlpha whether source already has alpha
 */
export function quantizeLutToRgba8(rgbFloat, size, hasAlpha = false) {
  const count = size * size * size;
  const out = new Uint8Array(count * 4);
  const stride = hasAlpha ? 4 : 3;
  for (let i = 0; i < count; i += 1) {
    const base = i * stride;
    out[i * 4] = _u8(rgbFloat[base]);
    out[i * 4 + 1] = _u8(rgbFloat[base + 1]);
    out[i * 4 + 2] = _u8(rgbFloat[base + 2]);
    out[i * 4 + 3] = 255;
  }
  return out;
}

function _u8(value) {
  return Math.max(0, Math.min(255, Math.round(Number(value) * 255)));
}

/**
 * Expand packed RGB floats to RGBA float32 for texImage3D.
 * @param {Float32Array|number[]} rgbFloat
 * @param {number} size
 * @param {boolean} hasAlpha
 */
export function expandLutToRgba32f(rgbFloat, size, hasAlpha = false) {
  const count = size * size * size;
  const out = new Float32Array(count * 4);
  const stride = hasAlpha ? 4 : 3;
  for (let i = 0; i < count; i += 1) {
    const base = i * stride;
    out[i * 4] = _clamp01(rgbFloat[base]);
    out[i * 4 + 1] = _clamp01(rgbFloat[base + 1]);
    out[i * 4 + 2] = _clamp01(rgbFloat[base + 2]);
    out[i * 4 + 3] = 1;
  }
  return out;
}

function _clamp01(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

/**
 * Measure max/mean absolute RGB error between two sample functions over probes.
 * @param {Array<[number, number, number]>} probes
 * @param {(rgb: [number, number, number]) => [number, number, number]} reference
 * @param {(rgb: [number, number, number]) => [number, number, number]} candidate
 */
export function measureRgbParity(probes, reference, candidate) {
  let maxErr = 0;
  let sum = 0;
  let count = 0;
  for (const rgb of probes) {
    const a = reference(rgb);
    const b = candidate(rgb);
    for (let c = 0; c < 3; c += 1) {
      const err = Math.abs(a[c] - b[c]);
      if (err > maxErr) maxErr = err;
      sum += err;
      count += 1;
    }
  }
  return {
    maxError: maxErr,
    meanError: count ? sum / count : 0,
    samples: count,
  };
}

/** Representative probes: identity, neutrals, high-contrast, gradients. */
export const PARITY_PROBES = [
  [0, 0, 0],
  [1, 1, 1],
  [0.5, 0.5, 0.5],
  [0.25, 0.5, 0.75],
  [0.1, 0.2, 0.3],
  [0.9, 0.1, 0.5],
  [0.01, 0.01, 0.01],
  [0.99, 0.99, 0.5],
  [1 / 3, 2 / 3, 0.125],
  [0.42, 0.17, 0.83],
];
