"use strict";

// Playback presentation only: no analytics, remote APIs, accounts, or application data.
const videos = Array.from(document.querySelectorAll("video"));
const formatTime = (seconds) => {
  if (!Number.isFinite(seconds)) return "";
  const value = Math.round(seconds);
  return `${Math.floor(value / 60).toString().padStart(2, "0")}:${(value % 60).toString().padStart(2, "0")}`;
};

for (const video of videos) {
  const status = document.querySelector(`.player-status[data-for="${video.id}"]`);
  const error = document.querySelector(`.media-error[data-for="${video.id}"]`);
  const setStatus = (text) => { if (status) status.textContent = text; };
  const ready = () => setStatus(`可在线播放 · ${formatTime(video.duration)}`);
  video.addEventListener("loadedmetadata", ready);
  video.addEventListener("play", () => {
    for (const other of videos) if (other !== video && !other.paused) other.pause();
  });
  video.addEventListener("playing", () => setStatus("播放中"));
  video.addEventListener("pause", () => {
    if (!video.ended && !video.error) setStatus(`已暂停 · ${formatTime(video.currentTime)} / ${formatTime(video.duration)}`);
  });
  video.addEventListener("waiting", () => { if (!video.paused) setStatus("缓冲中…"); });
  video.addEventListener("ended", () => setStatus("播放结束 · 可重新播放"));
  video.addEventListener("error", () => {
    setStatus("暂时无法播放");
    if (error) error.hidden = false;
  });
  const source = video.querySelector("source");
  if (source) source.addEventListener("error", () => {
    setStatus("视频未能加载");
    if (error) error.hidden = false;
  });
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) ready();
}

for (const button of document.querySelectorAll("[data-retry]")) {
  button.addEventListener("click", () => {
    const video = document.getElementById(button.dataset.retry);
    if (!(video instanceof HTMLVideoElement)) return;
    const error = document.querySelector(`.media-error[data-for="${video.id}"]`);
    const status = document.querySelector(`.player-status[data-for="${video.id}"]`);
    if (error) error.hidden = true;
    if (status) status.textContent = "正在重新加载…";
    video.load();
    video.focus();
  });
}
