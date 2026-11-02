import assert from "node:assert/strict";
import test from "node:test";

import { createSaver } from "../../src/orga_drone/static/js/studio/settings.js";

function jsonResponse(body, { ok = true } = {}) {
  return {
    ok,
    json: async () => body,
  };
}

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function createTimers() {
  let nextId = 1;
  const pending = new Map();
  return {
    setTimeout(fn, ms) {
      const id = nextId;
      nextId += 1;
      pending.set(id, { fn, ms });
      return id;
    },
    clearTimeout(id) {
      pending.delete(id);
    },
    runAll() {
      const timers = [...pending.values()];
      pending.clear();
      timers.forEach((timer) => timer.fn());
    },
    get size() {
      return pending.size;
    },
  };
}

test("serializes queued saves and applies responses in order", async () => {
  const calls = [];
  const applied = [];
  const refreshed = [];
  const first = deferred();
  const saver = createSaver({
    url: (key) => `/api/${key}`,
    payload: (key) => ({ id: key }),
    fetchImpl: async (url, init) => {
      calls.push({
        url,
        body: JSON.parse(init.body),
        method: init.method,
        contentType: init.headers["Content-Type"],
        accept: init.headers.Accept,
      });
      if (calls.length === 1) await first.promise;
      return jsonResponse({ ok: true, saved: url });
    },
    apply: (key, body, requestBody) => {
      applied.push([key, body.saved, requestBody.id]);
    },
    refresh: (key) => {
      refreshed.push(key);
    },
  });

  saver.queue("1");
  saver.queue("2");
  await tick();
  assert.deepEqual(
    calls.map((call) => call.url),
    ["/api/1"]
  );

  first.resolve();
  await saver.whenIdle();
  assert.deepEqual(
    calls.map((call) => call.url),
    ["/api/1", "/api/2"]
  );
  assert.deepEqual(applied, [
    ["1", "/api/1", "1"],
    ["2", "/api/2", "2"],
  ]);
  assert.deepEqual(refreshed, ["1", "2"]);
  assert.deepEqual(
    calls.map((call) => [call.method, call.contentType, call.accept]),
    [
      ["PATCH", "application/json", "application/json"],
      ["PATCH", "application/json", "application/json"],
    ]
  );
});

test("continues after a failed save and reports the error", async () => {
  const applied = [];
  const errors = [];
  const saver = createSaver({
    url: (key) => `/api/${key}`,
    payload: (key) => ({ id: key }),
    fetchImpl: async (url) => {
      if (url === "/api/1") {
        return jsonResponse({ ok: false, detail: "bad detail" }, { ok: false });
      }
      return jsonResponse({ ok: true, saved: url });
    },
    apply: (key, body) => {
      applied.push([key, body.saved]);
    },
    errorMessage: "fallback",
    onError: (err) => errors.push(err),
  });

  saver.queue("1");
  saver.queue("2");
  await saver.whenIdle();

  assert.equal(errors.length, 1);
  assert.equal(errors[0].message, "bad detail");
  assert.deepEqual(applied, [["2", "/api/2"]]);
});

test("coalesces rapid saves per key when debounce is enabled", async () => {
  const timers = createTimers();
  const bodies = [];
  let value = "first";
  const saver = createSaver({
    url: () => "/api/1",
    payload: () => ({ value }),
    fetchImpl: async (_url, init) => {
      bodies.push(JSON.parse(init.body));
      return jsonResponse({ ok: true });
    },
    debounceMs: 50,
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
  });

  saver.queue("1");
  value = "second";
  saver.queue("1");
  value = "final";
  saver.queue("1");

  assert.equal(timers.size, 1);
  assert.deepEqual(bodies, []);

  await saver.flush();
  assert.deepEqual(bodies, [{ value: "final" }]);
});

test("flushes pending keys in insertion order", async () => {
  const timers = createTimers();
  const calls = [];
  const saver = createSaver({
    url: (key) => `/api/${key}`,
    payload: (key) => ({ id: key }),
    fetchImpl: async (url) => {
      calls.push(url);
      return jsonResponse({ ok: true });
    },
    debounceMs: 25,
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
  });

  saver.queue("a");
  saver.queue("b");
  await saver.flush();

  assert.deepEqual(calls, ["/api/a", "/api/b"]);
});

test("skips the request when the payload is unavailable", async () => {
  let fetchCount = 0;
  let applyCount = 0;
  const saver = createSaver({
    url: () => "/api/1",
    payload: () => null,
    fetchImpl: async () => {
      fetchCount += 1;
      return jsonResponse({ ok: true });
    },
    apply: () => {
      applyCount += 1;
    },
  });

  saver.queue("1");
  await saver.whenIdle();

  assert.equal(fetchCount, 0);
  assert.equal(applyCount, 0);
});

test("skips refresh when apply reports the clip is gone", async () => {
  let refreshCount = 0;
  const saver = createSaver({
    url: () => "/api/1",
    payload: () => ({ value: 1 }),
    fetchImpl: async () => jsonResponse({ ok: true }),
    apply: () => false,
    refresh: () => {
      refreshCount += 1;
    },
  });

  saver.queue("1");
  await saver.whenIdle();

  assert.equal(refreshCount, 0);
});

test("can use an injected shared chain for serialization", async () => {
  const calls = [];
  const first = deferred();
  let shared = Promise.resolve();
  const saver = createSaver({
    url: (key) => `/api/${key}`,
    payload: (key) => ({ id: key }),
    fetchImpl: async (url) => {
      calls.push(url);
      if (calls.length === 1) await first.promise;
      return jsonResponse({ ok: true, saved: url });
    },
    serialize: (run) => {
      const next = shared.then(run);
      shared = next.catch(() => {});
      return next;
    },
    getChain: () => shared,
  });

  saver.queue("1");
  await tick();
  assert.deepEqual(calls, ["/api/1"]);

  saver.queue("2");
  await tick();
  assert.deepEqual(calls, ["/api/1"]);

  first.resolve();
  await saver.whenIdle();
  assert.deepEqual(calls, ["/api/1", "/api/2"]);
});

test("keeps an injected shared chain alive after a failed save", async () => {
  const calls = [];
  const errors = [];
  let shared = Promise.resolve();
  const saver = createSaver({
    url: (key) => `/api/${key}`,
    payload: (key) => ({ id: key }),
    fetchImpl: async (url) => {
      calls.push(url);
      if (url === "/api/1") {
        return jsonResponse({ ok: false, detail: "bad shared save" }, { ok: false });
      }
      return jsonResponse({ ok: true, saved: url });
    },
    serialize: (run) => {
      const next = shared.then(run);
      shared = next.catch(() => {});
      return next;
    },
    getChain: () => shared,
    onError: (err) => errors.push(err.message),
  });

  saver.queue("1");
  saver.queue("2");
  await saver.whenIdle();

  assert.deepEqual(calls, ["/api/1", "/api/2"]);
  assert.deepEqual(errors, ["bad shared save"]);
});
