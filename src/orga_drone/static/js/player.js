(function () {
  const player = document.getElementById("media-player");
  if (!player) return;
  document.querySelectorAll('input[name="quality"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (!input.checked) return;
      const src = input.getAttribute("data-src");
      if (!src) return;
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
})();
