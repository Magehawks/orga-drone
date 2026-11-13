/**
 * Pure tetrahedral 3D LUT sampling matching Python studio_managed_lut.sample_lut (#360).
 * Float table values; no 8-bit quantization in this reference path.
 */

/**
 * Descending fractional axes. Equal fractions resolve red, then green, then blue.
 * @param {[number, number, number]} fractions
 * @returns {[number, number, number]}
 */
export function interpolationOrder(fractions) {
  const axes = [0, 1, 2];
  axes.sort((a, b) => {
    const diff = fractions[b] - fractions[a];
    if (diff !== 0) return diff;
    return a - b;
  });
  return /** @type {[number, number, number]} */ ([axes[0], axes[1], axes[2]]);
}

/**
 * @param {{
 *   size: number,
 *   data: ArrayLike<number>|Float32Array|number[],
 *   domainMin?: [number, number, number],
 *   domainMax?: [number, number, number],
 * }} lut  data is RGB triples packed as length size^3 * 3 (or nested triples)
 * @param {[number, number, number]} rgb
 * @returns {[number, number, number]}
 */
export function sampleLutTetrahedral(lut, rgb) {
  const size = Number(lut.size);
  if (!Number.isFinite(size) || size < 2) {
    throw new Error("invalid LUT size");
  }
  const domainMin = lut.domainMin || [0, 0, 0];
  const domainMax = lut.domainMax || [1, 1, 1];
  const coords = [0, 0, 0];
  for (let index = 0; index < 3; index += 1) {
    const span = domainMax[index] - domainMin[index];
    const scaled = (rgb[index] - domainMin[index]) / span;
    coords[index] = Math.min(1, Math.max(0, scaled)) * (size - 1);
  }

  const flat = lut.data;
  const triples = flat.length === size * size * size * 3;

  function vertex(red, green, blue) {
    const idx = red + green * size + blue * size * size;
    if (triples) {
      const base = idx * 3;
      return [flat[base], flat[base + 1], flat[base + 2]];
    }
    const triple = flat[idx];
    return [triple[0], triple[1], triple[2]];
  }

  const fractions = /** @type {[number, number, number]} */ ([
    coords[0] % 1,
    coords[1] % 1,
    coords[2] % 1,
  ]);
  const base = coords.map((coord) => Math.floor(coord));
  const [first, second, third] = interpolationOrder(fractions);

  function at(offsets) {
    return vertex(
      Math.min(base[0] + offsets[0], size - 1),
      Math.min(base[1] + offsets[1], size - 1),
      Math.min(base[2] + offsets[2], size - 1)
    );
  }

  function axisOffset(axis) {
    return [Number(axis === 0), Number(axis === 1), Number(axis === 2)];
  }

  function both(left, right) {
    return [
      Number(left === 0 || right === 0),
      Number(left === 1 || right === 1),
      Number(left === 2 || right === 2),
    ];
  }

  const origin = at([0, 0, 0]);
  const alongFirst = at(axisOffset(first));
  const alongTwo = at(both(first, second));
  const far = at([1, 1, 1]);
  const weightFirst = fractions[first];
  const weightSecond = fractions[second];
  const weightThird = fractions[third];
  return [
    origin[0] +
      weightFirst * (alongFirst[0] - origin[0]) +
      weightSecond * (alongTwo[0] - alongFirst[0]) +
      weightThird * (far[0] - alongTwo[0]),
    origin[1] +
      weightFirst * (alongFirst[1] - origin[1]) +
      weightSecond * (alongTwo[1] - alongFirst[1]) +
      weightThird * (far[1] - alongTwo[1]),
    origin[2] +
      weightFirst * (alongFirst[2] - origin[2]) +
      weightSecond * (alongTwo[2] - alongFirst[2]) +
      weightThird * (far[2] - alongTwo[2]),
  ];
}

/**
 * GLSL fragment helper matching sampleLutTetrahedral (texelFetch path).
 * Tie-break matches Python: descending fraction, then ascending axis index.
 */
export const TETRAHEDRAL_GLSL = `
bool tetBefore(vec3 frac, int left, int right) {
  float fl = left == 0 ? frac.r : (left == 1 ? frac.g : frac.b);
  float fr = right == 0 ? frac.r : (right == 1 ? frac.g : frac.b);
  return fl > fr || (fl == fr && left < right);
}
vec3 tetrahedralSample(sampler3D lut, vec3 c, float size) {
  vec3 clamped = clamp(c, 0.0, 1.0);
  vec3 coords = clamped * (size - 1.0);
  vec3 baseF = floor(coords);
  vec3 frac = coords - baseF;
  int o0 = 0;
  int o1 = 1;
  int o2 = 2;
  if (!tetBefore(frac, o0, o1)) { int t = o0; o0 = o1; o1 = t; }
  if (!tetBefore(frac, o1, o2)) { int t = o1; o1 = o2; o2 = t; }
  if (!tetBefore(frac, o0, o1)) { int t = o0; o0 = o1; o1 = t; }
  ivec3 i0 = ivec3(baseF);
  ivec3 i1 = ivec3(min(baseF + 1.0, vec3(size - 1.0)));
  vec3 v000 = texelFetch(lut, i0, 0).rgb;
  vec3 axis0 = o0 == 0 ? vec3(1,0,0) : (o0 == 1 ? vec3(0,1,0) : vec3(0,0,1));
  vec3 axis1 = o1 == 0 ? vec3(1,0,0) : (o1 == 1 ? vec3(0,1,0) : vec3(0,0,1));
  ivec3 iFirst = ivec3(min(baseF + axis0, vec3(size - 1.0)));
  ivec3 iTwo = ivec3(min(baseF + axis0 + axis1, vec3(size - 1.0)));
  vec3 alongFirst = texelFetch(lut, iFirst, 0).rgb;
  vec3 alongTwo = texelFetch(lut, iTwo, 0).rgb;
  vec3 far = texelFetch(lut, i1, 0).rgb;
  float w1 = o0 == 0 ? frac.r : (o0 == 1 ? frac.g : frac.b);
  float w2 = o1 == 0 ? frac.r : (o1 == 1 ? frac.g : frac.b);
  float w3 = o2 == 0 ? frac.r : (o2 == 1 ? frac.g : frac.b);
  return v000 + w1 * (alongFirst - v000) + w2 * (alongTwo - alongFirst) + w3 * (far - alongTwo);
}
`;
