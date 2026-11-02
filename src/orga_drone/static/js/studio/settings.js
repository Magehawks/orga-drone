const DEFAULT_HEADERS = {
  "Content-Type": "application/json",
  Accept: "application/json",
};

async function defaultReadJson(res) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

function defaultFetch(input, init) {
  return globalThis.fetch(input, init);
}

export function createSaver({
  url,
  method = "PATCH",
  payload,
  apply,
  refresh,
  errorMessage = "Could not save.",
  onError,
  headers = DEFAULT_HEADERS,
  fetchImpl = defaultFetch,
  readJson = defaultReadJson,
  debounceMs = 0,
  setTimeoutImpl = globalThis.setTimeout,
  clearTimeoutImpl = globalThis.clearTimeout,
  serialize,
  getChain,
}) {
  const waitMs = Math.max(0, Number(debounceMs) || 0);
  let chain = Promise.resolve();
  let timer = 0;
  const pendingKeys = new Set();

  function targetUrl(key) {
    return typeof url === "function" ? url(key) : url;
  }

  async function targetPayload(key) {
    const body = typeof payload === "function" ? await payload(key) : payload;
    return body;
  }

  async function save(key) {
    const requestBody = await targetPayload(key);
    if (requestBody === null || requestBody === undefined) return null;
    const res = await fetchImpl(targetUrl(key), {
      method,
      headers,
      body: JSON.stringify(requestBody),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || errorMessage);
    }
    const applied = apply ? await apply(key, body, requestBody) : true;
    if (applied !== false && refresh) await refresh(key, body);
    return body;
  }

  function enqueue(key) {
    const run = () => save(key);
    if (serialize) {
      const queued = Promise.resolve(serialize(run));
      return queued.catch((err) => {
        if (onError) onError(err, key);
      });
    }
    const next = chain.then(run);
    chain = next.catch((err) => {
      if (onError) onError(err, key);
    });
    return chain;
  }

  function drainPending() {
    const keys = [...pendingKeys];
    pendingKeys.clear();
    keys.forEach((key) => enqueue(key));
  }

  function flush() {
    if (timer) {
      clearTimeoutImpl(timer);
      timer = 0;
    }
    if (pendingKeys.size) drainPending();
    if (serialize && getChain) return getChain();
    return chain;
  }

  function queue(key) {
    if (!waitMs) return enqueue(key);
    pendingKeys.add(key);
    if (timer) clearTimeoutImpl(timer);
    timer = setTimeoutImpl(() => {
      timer = 0;
      drainPending();
    }, waitMs);
    return chain;
  }

  return {
    queue,
    save,
    flush,
    whenIdle: flush,
  };
}
