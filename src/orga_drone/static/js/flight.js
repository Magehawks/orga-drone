/**
 * Sequential flight playback across session/flow clips.
 * Exposes OrgaFlight for map/overlay global time sync.
 */
(function (global) {
  const dataEl = document.getElementById("flight-playlist-data");
  const player = document.getElementById("media-player");
  const listRoot = document.getElementById("flight-playlist-ui");
  if (!dataEl || !player || !listRoot) return;

  let playlist = [];
  try {
    playlist = JSON.parse(dataEl.textContent || "[]");
  } catch (_) {
    playlist = [];
  }
  if (!playlist.length) return;

  let index = parseInt(listRoot.dataset.startIndex || "0", 10);
  if (!Number.isFinite(index) || index < 0 || index >= playlist.length) index = 0;

  function durationOf(entry) {
    const d = entry && entry.duration_s;
    return typeof d === "number" && Number.isFinite(d) && d > 0 ? d : 0;
  }

  function offsetBefore(i) {
    let t = 0;
    for (let j = 0; j < i; j++) t += durationOf(playlist[j]);
    return t;
  }

  function totalDuration() {
    let t = 0;
    for (let j = 0; j < playlist.length; j++) t += durationOf(playlist[j]);
    return t;
  }

  function preferredSrc(entry) {
    const proxyRadio = document.querySelector('input[name="quality"][value="proxy"]');
    const useProxy = proxyRadio && proxyRadio.checked && entry.has_proxy;
    if (useProxy) return entry.proxy_url;
    return entry.stream_url;
  }

  function updateQualityRadios(entry) {
    const proxyInput = document.querySelector('input[name="quality"][value="proxy"]');
    const fullInput = document.querySelector('input[name="quality"][value="full"]');
    if (proxyInput) {
      proxyInput.setAttribute("data-src", entry.proxy_url);
      const label = proxyInput.closest("label");
      if (label) label.hidden = !entry.has_proxy;
      if (!entry.has_proxy && proxyInput.checked && fullInput) {
        fullInput.checked = true;
      }
    }
    if (fullInput) {
      fullInput.setAttribute("data-src", entry.stream_url);
    }
  }

  function markCurrent() {
    const entry = playlist[index];
    if (!entry) return;
    listRoot.querySelectorAll(".flight-clip").forEach((li) => {
      const id = parseInt(li.dataset.mediaId || "", 10);
      li.classList.toggle("current", id === entry.id);
    });
  }

  function loadIndex(nextIndex, { autoplay = true, seekLocal = 0 } = {}) {
    if (nextIndex < 0 || nextIndex >= playlist.length) return;
    const entry = playlist[nextIndex];
    if (!entry || !entry.can_play) {
      if (nextIndex + 1 < playlist.length) {
        loadIndex(nextIndex + 1, { autoplay, seekLocal: 0 });
      }
      return;
    }
    index = nextIndex;
    updateQualityRadios(entry);
    const src = preferredSrc(entry);
    const wasPlaying = autoplay;
    player.src = src;
    player.load();
    markCurrent();
    player.addEventListener(
      "loadedmetadata",
      () => {
        try {
          if (seekLocal > 0) {
            player.currentTime = Math.min(seekLocal, player.duration || seekLocal);
          }
        } catch (_) {}
        if (wasPlaying) player.play().catch(() => {});
        player.dispatchEvent(new Event("orgaflightchange"));
      },
      { once: true }
    );
  }

  function globalTime() {
    return offsetBefore(index) + (player.currentTime || 0);
  }

  function seekGlobal(t) {
    const target = Math.max(0, Number(t) || 0);
    let remaining = target;
    for (let i = 0; i < playlist.length; i++) {
      const dur = durationOf(playlist[i]);
      const span = dur > 0 ? dur : 0;
      if (i === playlist.length - 1 || remaining <= span || span <= 0) {
        const local = span > 0 ? Math.min(remaining, span) : remaining;
        if (i === index) {
          try {
            player.currentTime = local;
          } catch (_) {}
          player.dispatchEvent(new Event("orgaflightchange"));
        } else {
          loadIndex(i, { autoplay: !player.paused, seekLocal: local });
        }
        return;
      }
      remaining -= span;
    }
  }

  player.addEventListener("ended", () => {
    if (index + 1 < playlist.length) {
      loadIndex(index + 1, { autoplay: true, seekLocal: 0 });
    }
  });

  listRoot.querySelectorAll(".flight-play-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const i = parseInt(btn.getAttribute("data-play-index") || "", 10);
      if (!Number.isFinite(i)) return;
      loadIndex(i, { autoplay: true, seekLocal: 0 });
    });
  });

  // Keep quality radios in sync when user toggles while in flight mode
  document.querySelectorAll('input[name="quality"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (!input.checked) return;
      const entry = playlist[index];
      if (!entry) return;
      updateQualityRadios(entry);
      const src = preferredSrc(entry);
      const wasPlaying = !player.paused;
      const t = player.currentTime || 0;
      player.src = src;
      player.load();
      player.addEventListener(
        "loadedmetadata",
        () => {
          try {
            player.currentTime = Math.min(t, player.duration || t);
          } catch (_) {}
          if (wasPlaying) player.play().catch(() => {});
        },
        { once: true }
      );
    });
  });

  markCurrent();

  global.OrgaFlight = {
    active: true,
    globalTime,
    totalDuration,
    seekGlobal,
    clipIndex: () => index,
    playlist,
  };
})(window);
