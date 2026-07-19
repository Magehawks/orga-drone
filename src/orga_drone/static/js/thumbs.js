(function () {
  // Nudge LRF thumbnails to show a frame (some browsers need play/pause)
  document.querySelectorAll("video.list-thumb, .thumb video").forEach((video) => {
    const reveal = () => {
      try {
        video.currentTime = 0.1;
      } catch (_) {}
    };
    video.addEventListener("loadeddata", reveal, { once: true });
    if (video.readyState >= 2) reveal();
  });
})();
