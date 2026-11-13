/* WebGL2 LUT preview for Studio (PR #231). Renders one video frame with the
   existing grade factors and up to two local .cube LUTs to an offscreen canvas. */
(function () {
  "use strict";

  const lutTextCache = new Map();
  const lutDataCache = new Map();

  function clamp01(value) {
    return Math.min(1, Math.max(0, Number(value) || 0));
  }

  function parseCube(text) {
    const sizeMatch = /LUT_3D_SIZE\s+(\d+)/i.exec(text);
    const size = sizeMatch ? Number(sizeMatch[1]) : 0;
    if (!size || size < 2 || size > 65) throw new Error("invalid LUT size");
    const triples = [];
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith("#") || /^(TITLE|LUT_3D_SIZE|DOMAIN_)/i.test(line)) continue;
      const parts = line.split(/\s+/).map(Number);
      if (parts.length === 3 && parts.every(Number.isFinite)) triples.push(parts);
    }
    if (triples.length !== size * size * size) throw new Error("invalid LUT rows");
    // Keep float tables for capability-gated RGBA16F/32F upload (#360).
    // RGBA8 remains the fallback path and is labeled exact:false.
    const dataF32 = new Float32Array(triples.length * 4);
    const dataU8 = new Uint8Array(triples.length * 4);
    for (let i = 0; i < triples.length; i += 1) {
      const r = clamp01(triples[i][0]);
      const g = clamp01(triples[i][1]);
      const b = clamp01(triples[i][2]);
      dataF32[i * 4] = r;
      dataF32[i * 4 + 1] = g;
      dataF32[i * 4 + 2] = b;
      dataF32[i * 4 + 3] = 1;
      dataU8[i * 4] = Math.max(0, Math.min(255, Math.round(r * 255)));
      dataU8[i * 4 + 1] = Math.max(0, Math.min(255, Math.round(g * 255)));
      dataU8[i * 4 + 2] = Math.max(0, Math.min(255, Math.round(b * 255)));
      dataU8[i * 4 + 3] = 255;
    }
    return { size, dataF32, dataU8, data: dataU8 };
  }

  function canUpload3d(gl, internalFormat, type, pixels) {
    const texture = gl.createTexture();
    if (!texture) return false;
    gl.bindTexture(gl.TEXTURE_3D, texture);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.getError();
    try {
      gl.texImage3D(
        gl.TEXTURE_3D, 0, internalFormat, 2, 2, 2, 0, gl.RGBA, type, pixels
      );
    } catch (_) {
      gl.bindTexture(gl.TEXTURE_3D, null);
      gl.deleteTexture(texture);
      return false;
    }
    const err = gl.getError();
    gl.bindTexture(gl.TEXTURE_3D, null);
    gl.deleteTexture(texture);
    return err === gl.NO_ERROR;
  }

  function probeLutPrecision(gl) {
    if (!gl) {
      return { precision: "rgba8", canSampleFloatLut: false, extensions: [] };
    }
    const extensions = [];
    if (gl.getExtension("EXT_color_buffer_float")) {
      extensions.push("EXT_color_buffer_float");
    }
    if (gl.getExtension("OES_texture_float_linear")) {
      extensions.push("OES_texture_float_linear");
    }
    if (canUpload3d(gl, gl.RGBA32F, gl.FLOAT, new Float32Array(8 * 4))) {
      return { precision: "rgba32f", canSampleFloatLut: true, extensions };
    }
    if (canUpload3d(gl, gl.RGBA16F, gl.HALF_FLOAT, new Uint16Array(8 * 4))) {
      return { precision: "rgba16f", canSampleFloatLut: true, extensions };
    }
    return { precision: "rgba8", canSampleFloatLut: false, extensions };
  }

  function lutFetchUrl(assetName) {
    if (!assetName) return "";
    // Managed bake URLs are absolute API paths (#360).
    if (assetName.startsWith("/api/")) return assetName;
    return `/api/luts/${encodeURIComponent(assetName)}`;
  }

  async function lutData(assetName) {
    if (lutDataCache.has(assetName)) return lutDataCache.get(assetName);
    if (!lutTextCache.has(assetName)) {
      const response = await fetch(lutFetchUrl(assetName), {
        cache: assetName.startsWith("/api/studio/") ? "no-store" : "force-cache",
        headers: { Accept: "text/plain" },
      });
      if (!response.ok) throw new Error("LUT fetch failed");
      lutTextCache.set(assetName, await response.text());
    }
    const parsed = parseCube(lutTextCache.get(assetName));
    lutDataCache.set(assetName, parsed);
    return parsed;
  }

  function supported() {
    try {
      const canvas = document.createElement("canvas");
      return !!canvas.getContext("webgl2");
    } catch (_) {
      return false;
    }
  }

  class Renderer {
    constructor() {
      this.canvas = document.createElement("canvas");
      this.canvas.className = "studio-lut-webgl";
      this.gl = this.canvas.getContext("webgl2", {
        antialias: false,
        alpha: false,
        depth: false,
        stencil: false,
        powerPreference: "high-performance",
      });
      this.available = !!this.gl;
      this.onReady = null;
      this.lookKey = "";
      this.loadingKey = "";
      this.failedKey = "";
      this.assets = new Map();
      this.convTex = null;
      this.creativeTex = null;
      this.videoTex = null;
      this.scratch = document.createElement("canvas");
      this.scratchCtx = this.scratch.getContext("2d");
      this.lutPrecision = "rgba8";
      this.lutPrecisionInfo = {
        precision: "rgba8",
        canSampleFloatLut: false,
        extensions: [],
      };
      if (this.available) this._setup();
    }

    _setup() {
      const gl = this.gl;
      const vs = `#version 300 es
      in vec2 a; out vec2 uv;
      void main() { uv = vec2(a.x * 0.5 + 0.5, 0.5 - a.y * 0.5); gl_Position = vec4(a, 0.0, 1.0); }`;
      const fs = `#version 300 es
      precision highp float;
      precision highp sampler2D;
      precision highp sampler3D;
      uniform sampler2D uVideo;
      uniform sampler3D uConv;
      uniform sampler3D uCreative;
      uniform float uConvSize;
      uniform float uCreativeSize;
      uniform bool uHasConv;
      uniform bool uHasCreative;
      uniform float uCreativeStrength;
      uniform vec3 uWarmth;
      uniform float uBrightness;
      uniform float uContrast;
      uniform float uSaturation;
      uniform float uRamp;
      in vec2 uv;
      out vec4 outColor;
      float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
      bool tetBefore(vec3 frac, int left, int right) {
        float fl = left == 0 ? frac.r : (left == 1 ? frac.g : frac.b);
        float fr = right == 0 ? frac.r : (right == 1 ? frac.g : frac.b);
        return fl > fr || (fl == fr && left < right);
      }
      // Tetrahedral sampling matches FFmpeg/CPU (#360). Table storage is
      // capability-gated (RGBA32F/16F when upload works; else RGBA8).
      vec3 applyLut(sampler3D lut, vec3 c, float size) {
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
        vec3 axis0 = o0 == 0 ? vec3(1.0, 0.0, 0.0) : (o0 == 1 ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, 1.0));
        vec3 axis1 = o1 == 0 ? vec3(1.0, 0.0, 0.0) : (o1 == 1 ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, 1.0));
        vec3 alongFirst = texelFetch(lut, ivec3(min(baseF + axis0, vec3(size - 1.0))), 0).rgb;
        vec3 alongTwo = texelFetch(lut, ivec3(min(baseF + axis0 + axis1, vec3(size - 1.0))), 0).rgb;
        vec3 far = texelFetch(lut, i1, 0).rgb;
        float w1 = o0 == 0 ? frac.r : (o0 == 1 ? frac.g : frac.b);
        float w2 = o1 == 0 ? frac.r : (o1 == 1 ? frac.g : frac.b);
        float w3 = o2 == 0 ? frac.r : (o2 == 1 ? frac.g : frac.b);
        return v000 + w1 * (alongFirst - v000) + w2 * (alongTwo - alongFirst) + w3 * (far - alongTwo);
      }
      void main() {
        vec3 c = texture(uVideo, uv).rgb * uWarmth * uBrightness;
        c = (c - 0.5) * uContrast + 0.5;
        c = mix(vec3(luma(c)), c, uSaturation);
        if (uHasConv) c = applyLut(uConv, c, uConvSize);
        if (uHasCreative) c = mix(c, applyLut(uCreative, c, uCreativeSize), uCreativeStrength);
        c = mix(vec3(luma(c)), c, uRamp);
        outColor = vec4(clamp(c, 0.0, 1.0), 1.0);
      }`;
      const shader = (type, src) => {
        const value = gl.createShader(type);
        gl.shaderSource(value, src);
        gl.compileShader(value);
        if (!gl.getShaderParameter(value, gl.COMPILE_STATUS)) {
          throw new Error(gl.getShaderInfoLog(value) || "shader compile failed");
        }
        return value;
      };
      try {
        const program = gl.createProgram();
        gl.attachShader(program, shader(gl.VERTEX_SHADER, vs));
        gl.attachShader(program, shader(gl.FRAGMENT_SHADER, fs));
        gl.linkProgram(program);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("program link failed");
        this.program = program;
        gl.useProgram(program);
        const buffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        const loc = gl.getAttribLocation(program, "a");
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
        this.uVideo = gl.getUniformLocation(program, "uVideo");
        this.uConv = gl.getUniformLocation(program, "uConv");
        this.uCreative = gl.getUniformLocation(program, "uCreative");
        this.uConvSize = gl.getUniformLocation(program, "uConvSize");
        this.uCreativeSize = gl.getUniformLocation(program, "uCreativeSize");
        this.uHasConv = gl.getUniformLocation(program, "uHasConv");
        this.uHasCreative = gl.getUniformLocation(program, "uHasCreative");
        this.uCreativeStrength = gl.getUniformLocation(program, "uCreativeStrength");
        this.uWarmth = gl.getUniformLocation(program, "uWarmth");
        this.uBrightness = gl.getUniformLocation(program, "uBrightness");
        this.uContrast = gl.getUniformLocation(program, "uContrast");
        this.uSaturation = gl.getUniformLocation(program, "uSaturation");
        this.uRamp = gl.getUniformLocation(program, "uRamp");
        gl.uniform1i(this.uVideo, 0);
        gl.uniform1i(this.uConv, 1);
        gl.uniform1i(this.uCreative, 2);
        this.videoTex = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, this.videoTex);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        this.lutPrecisionInfo = probeLutPrecision(gl);
        this.lutPrecision = this.lutPrecisionInfo.precision;
        this.identity = this._identityTexture();
      } catch (_) {
        this.available = false;
      }
    }

    _texImage3dLut(texture, size, parsed) {
      const gl = this.gl;
      gl.bindTexture(gl.TEXTURE_3D, texture);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      const precision = this.lutPrecision || "rgba8";
      if (precision === "rgba32f" && parsed.dataF32) {
        gl.texImage3D(
          gl.TEXTURE_3D, 0, gl.RGBA32F, size, size, size,
          0, gl.RGBA, gl.FLOAT, parsed.dataF32
        );
      } else if (precision === "rgba16f" && parsed.dataF32) {
        // Upload float source; driver converts to half float storage.
        gl.texImage3D(
          gl.TEXTURE_3D, 0, gl.RGBA16F, size, size, size,
          0, gl.RGBA, gl.FLOAT, parsed.dataF32
        );
      } else {
        gl.texImage3D(
          gl.TEXTURE_3D, 0, gl.RGBA8, size, size, size,
          0, gl.RGBA, gl.UNSIGNED_BYTE, parsed.dataU8 || parsed.data
        );
      }
      // texelFetch ignores filters; NEAREST avoids float-linear extension needs.
      for (const key of ["TEXTURE_MIN_FILTER", "TEXTURE_MAG_FILTER"]) {
        gl.texParameteri(gl.TEXTURE_3D, gl[key], gl.NEAREST);
      }
      for (const key of ["TEXTURE_WRAP_S", "TEXTURE_WRAP_T", "TEXTURE_WRAP_R"]) {
        gl.texParameteri(gl.TEXTURE_3D, gl[key], gl.CLAMP_TO_EDGE);
      }
    }

    _identityTexture() {
      const gl = this.gl;
      const texture = gl.createTexture();
      const dataF32 = new Float32Array([
        0, 0, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1,
        0, 0, 1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1,
      ]);
      const dataU8 = new Uint8Array([
        0, 0, 0, 255, 255, 0, 0, 255, 0, 255, 0, 255, 255, 255, 0, 255,
        0, 0, 255, 255, 255, 0, 255, 255, 0, 255, 255, 255, 255, 255, 255, 255,
      ]);
      this._texImage3dLut(texture, 2, { dataF32, dataU8 });
      return texture;
    }

    _textureFor(assetName) {
      const gl = this.gl;
      if (!assetName) return this.identity;
      const cacheKey = `${this.lutPrecision || "rgba8"}::${assetName}`;
      if (this.assets.has(cacheKey)) return this.assets.get(cacheKey);
      const parsed = lutDataCache.get(assetName);
      if (!parsed) return null;
      const texture = gl.createTexture();
      this._texImage3dLut(texture, parsed.size, parsed);
      this.assets.set(cacheKey, texture);
      return texture;
    }

    _lookKey(look) {
      if (!look) return "";
      return JSON.stringify([
        look.conversion_lut || "", Boolean(look.conversion_confirmed),
        look.creative_lut || "", Number(look.creative_strength) > 0,
      ]);
    }

    isReady(look) {
      return this.available && !!this._lookKey(look) && this.lookKey === this._lookKey(look);
    }

    ensureLook(look) {
      if (!this.available || !look) return;
      const key = this._lookKey(look);
      if (!key || key === this.lookKey || key === this.loadingKey || key === this.failedKey) return;
      this.loadingKey = key;
      const assets = [];
      if (look.conversion_lut && look.conversion_confirmed) assets.push(look.conversion_lut);
      if (look.creative_lut && Number(look.creative_strength) > 0) assets.push(look.creative_lut);
      Promise.all([...new Set(assets)].map(lutData))
        .then(() => {
          if (this.loadingKey !== key) return;
          const convData = look.conversion_lut && look.conversion_confirmed
            ? lutDataCache.get(look.conversion_lut) : null;
          const creativeData = look.creative_lut && Number(look.creative_strength) > 0
            ? lutDataCache.get(look.creative_lut) : null;
          this.convTex = convData ? this._textureFor(look.conversion_lut) : this.identity;
          this.creativeTex = creativeData ? this._textureFor(look.creative_lut) : this.identity;
          this.convSize = convData ? convData.size : 2;
          this.creativeSize = creativeData ? creativeData.size : 2;
          this.lookKey = key;
          this.loadingKey = "";
          if (this.onReady) this.onReady();
        })
        .catch(() => {
          if (this.loadingKey === key) {
            this.failedKey = key;
            this.loadingKey = "";
          }
        });
    }

    render(video, { grade, look, frameW, frameH, dpr, maxEdge }) {
      if (!this.available || !this.scratchCtx || !look) return null;
      this.ensureLook(look);
      if (!this.isReady(look)) return null;
      const srcW = video.videoWidth || 0;
      const srcH = video.videoHeight || 0;
      if (!srcW || !srcH) return null;
      const cssW = Math.max(2, Number(frameW) || 1280);
      const cssH = Math.max(2, Number(frameH) || 720);
      const ratio = Math.max(1, Math.min(3, Number(dpr) || 1));
      const scale = Math.min(cssW / srcW, cssH / srcH) * ratio;
      let width = Math.min(srcW, Math.max(2, Math.round(srcW * scale)));
      let height = Math.min(srcH, Math.max(2, Math.round(srcH * scale)));
      const edgeCap = Math.max(64, Number(maxEdge) || 4096);
      const longEdge = Math.max(width, height);
      if (longEdge > edgeCap) {
        const fit = edgeCap / longEdge;
        width = Math.max(2, Math.round(width * fit));
        height = Math.max(2, Math.round(height * fit));
      }
      width -= width % 2;
      height -= height % 2;
      if (this.canvas.width !== width || this.canvas.height !== height) {
        this.canvas.width = width;
        this.canvas.height = height;
      }
      if (this.scratch.width !== width || this.scratch.height !== height) {
        this.scratch.width = width;
        this.scratch.height = height;
      }
      const gl = this.gl;
      this.scratchCtx.imageSmoothingEnabled = true;
      this.scratchCtx.imageSmoothingQuality = "high";
      this.scratchCtx.drawImage(video, 0, 0, width, height);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.videoTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, this.scratch);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_3D, this.convTex || this.identity);
      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_3D, this.creativeTex || this.identity);
      gl.viewport(0, 0, width, height);
      gl.useProgram(this.program);
      gl.uniform1i(this.uHasConv, look.conversion_lut && look.conversion_confirmed ? 1 : 0);
      gl.uniform1i(this.uHasCreative,
        look.creative_lut && Number(look.creative_strength) > 0 ? 1 : 0);
      gl.uniform1f(this.uConvSize, this.convSize);
      gl.uniform1f(this.uCreativeSize, this.creativeSize);
      gl.uniform1f(this.uCreativeStrength, Math.max(0, Math.min(1, Number(look.creative_strength) / 100)));
      const warmth = grade && grade.warmthGains ? grade.warmthGains : [1, 1, 1];
      gl.uniform3f(this.uWarmth, warmth[0], warmth[1], warmth[2]);
      gl.uniform1f(this.uBrightness, grade ? grade.brightness : 1);
      gl.uniform1f(this.uContrast, grade ? grade.contrast : 1);
      gl.uniform1f(this.uSaturation, grade ? grade.saturation : 1);
      gl.uniform1f(this.uRamp, grade ? grade.ramp : 1);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      return this.canvas;
    }
  }

  window.OrgaLutPreview = {
    supported: supported(),
    createRenderer: () => (supported() ? new Renderer() : null),
    /** Best-effort static probe without retaining a renderer. */
    probePrecision: () => {
      try {
        const canvas = document.createElement("canvas");
        const gl = canvas.getContext("webgl2", {
          antialias: false,
          alpha: false,
          depth: false,
          stencil: false,
        });
        return probeLutPrecision(gl);
      } catch (_) {
        return { precision: "rgba8", canSampleFloatLut: false, extensions: [] };
      }
    },
  };
})();
