/* WebGL2 LUT preview for Studio (PR #231). Renders one video frame with the
   existing grade factors and up to two local .cube LUTs to an offscreen canvas. */
(function () {
  "use strict";

  const lutTextCache = new Map();
  const lutDataCache = new Map();

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
    const data = new Uint8Array(triples.length * 4);
    for (let i = 0; i < triples.length; i += 1) {
      data[i * 4] = Math.max(0, Math.min(255, Math.round(triples[i][0] * 255)));
      data[i * 4 + 1] = Math.max(0, Math.min(255, Math.round(triples[i][1] * 255)));
      data[i * 4 + 2] = Math.max(0, Math.min(255, Math.round(triples[i][2] * 255)));
      data[i * 4 + 3] = 255;
    }
    return { size, data };
  }

  async function lutData(assetName) {
    if (lutDataCache.has(assetName)) return lutDataCache.get(assetName);
    if (!lutTextCache.has(assetName)) {
      const response = await fetch(`/api/luts/${encodeURIComponent(assetName)}`, {
        cache: "force-cache",
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
      vec3 applyLut(sampler3D lut, vec3 c) { return texture(lut, clamp(c, 0.0, 1.0)).rgb; }
      void main() {
        vec3 c = texture(uVideo, uv).rgb * uWarmth * uBrightness;
        c = (c - 0.5) * uContrast + 0.5;
        c = mix(vec3(luma(c)), c, uSaturation);
        if (uHasConv) c = applyLut(uConv, c);
        if (uHasCreative) c = mix(c, applyLut(uCreative, c), uCreativeStrength);
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
        this.identity = this._identityTexture();
      } catch (_) {
        this.available = false;
      }
    }

    _identityTexture() {
      const gl = this.gl;
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_3D, texture);
      const data = new Uint8Array([
        0, 0, 0, 255, 0, 0, 255, 255, 0, 0, 0, 255, 0, 0, 255, 255,
        0, 255, 0, 255, 0, 255, 255, 255, 0, 255, 0, 255, 0, 255, 255, 255,
      ]);
      gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGBA8, 2, 2, 2, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
      for (const key of ["TEXTURE_MIN_FILTER", "TEXTURE_MAG_FILTER"]) {
        gl.texParameteri(gl.TEXTURE_3D, gl[key], gl.LINEAR);
      }
      for (const key of ["TEXTURE_WRAP_S", "TEXTURE_WRAP_T", "TEXTURE_WRAP_R"]) {
        gl.texParameteri(gl.TEXTURE_3D, gl[key], gl.CLAMP_TO_EDGE);
      }
      return texture;
    }

    _textureFor(assetName) {
      const gl = this.gl;
      if (!assetName) return this.identity;
      if (this.assets.has(assetName)) return this.assets.get(assetName);
      const parsed = lutDataCache.get(assetName);
      if (!parsed) return null;
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_3D, texture);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      gl.texImage3D(
        gl.TEXTURE_3D, 0, gl.RGBA8, parsed.size, parsed.size, parsed.size,
        0, gl.RGBA, gl.UNSIGNED_BYTE, parsed.data
      );
      for (const key of ["TEXTURE_MIN_FILTER", "TEXTURE_MAG_FILTER"]) {
        gl.texParameteri(gl.TEXTURE_3D, gl[key], gl.LINEAR);
      }
      for (const key of ["TEXTURE_WRAP_S", "TEXTURE_WRAP_T", "TEXTURE_WRAP_R"]) {
        gl.texParameteri(gl.TEXTURE_3D, gl[key], gl.CLAMP_TO_EDGE);
      }
      this.assets.set(assetName, texture);
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
          this.convTex = look.conversion_lut && look.conversion_confirmed
            ? this._textureFor(look.conversion_lut) : this.identity;
          this.creativeTex = look.creative_lut && Number(look.creative_strength) > 0
            ? this._textureFor(look.creative_lut) : this.identity;
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

    render(video, { grade, look }) {
      if (!this.available || !this.scratchCtx || !look) return null;
      this.ensureLook(look);
      if (!this.isReady(look)) return null;
      const srcW = video.videoWidth || 0;
      const srcH = video.videoHeight || 0;
      if (!srcW || !srcH) return null;
      const scale = Math.min(1280 / srcW, 720 / srcH);
      let width = Math.max(2, Math.round(srcW * scale));
      let height = Math.max(2, Math.round(srcH * scale));
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
  };
})();
