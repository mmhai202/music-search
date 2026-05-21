const listenButton = document.querySelector("#listenButton");
const buttonText = document.querySelector("#buttonText");
const deviceSelect = document.querySelector("#deviceSelect");
const selectedDeviceText = document.querySelector("#selectedDeviceText");
const microphoneButton = document.querySelector("#microphoneButton");
const microphoneButtonText = document.querySelector("#microphoneButtonText");
const microphoneSelect = document.querySelector("#microphoneSelect");
const selectedMicrophoneText = document.querySelector("#selectedMicrophoneText");
const audioFile = document.querySelector("#audioFile");
const fileName = document.querySelector("#fileName");
const uploadButton = document.querySelector("#uploadButton");
const uploadButtonText = document.querySelector("#uploadButtonText");
const filePreview = document.querySelector("#filePreview");
const previewAudio = document.querySelector("#previewAudio");
const previewPlay = document.querySelector("#previewPlay");
const previewPlayIcon = document.querySelector("#previewPlayIcon");
const previewPlayText = document.querySelector("#previewPlayText");
const previewReset = document.querySelector("#previewReset");
const previewRangeText = document.querySelector("#previewRangeText");
const waveformBox = document.querySelector("#waveformBox");
const waveformCanvas = document.querySelector("#waveformCanvas");
const resultEl = document.querySelector("#result");
const historyEl = document.querySelector("#history");
const clearButton = document.querySelector("#clearButton");

const PREVIEW_SECONDS = 10;
const MIN_AUDIO_SECONDS = 3;
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const ALLOWED_UPLOAD_EXTENSIONS = new Set(["mp3", "wav", "m4a", "mp4", "flac", "ogg", "webm"]);
const ALLOWED_UPLOAD_TYPES = new Set([
  "audio/mpeg",
  "audio/mp3",
  "audio/wav",
  "audio/x-wav",
  "audio/wave",
  "audio/mp4",
  "audio/m4a",
  "audio/x-m4a",
  "audio/flac",
  "audio/x-flac",
  "audio/ogg",
  "video/mp4",
  "video/webm",
  "application/ogg",
]);
const ERROR_MESSAGES = {
  no_audio_playing: "Không có audio đang phát. Mở nhạc hoặc video rồi thử lại.",
  recognition_busy: "Đang có lượt nhận diện khác chạy. Chờ lượt hiện tại kết thúc rồi thử lại.",
  file_too_large: "File audio quá lớn, tối đa 50MB.",
  unsupported_upload_type: "Chỉ hỗ trợ file MP3, WAV, M4A, MP4, FLAC, OGG hoặc WEBM.",
  unsupported_audio_file: "Định dạng file không đọc được. Thử file MP3, WAV, M4A, MP4, FLAC, OGG hoặc WEBM.",
  audio_too_short: "File audio quá ngắn. Cần tối thiểu 3 giây để nhận diện.",
  no_audio_stream: "Không tìm thấy audio trong file.",
  missing_dependency: "Thiếu ffmpeg hoặc vibra. Kiểm tra thư mục bin cạnh ứng dụng.",
  audio_device_not_found: "Không tìm thấy thiết bị audio để thu âm.",
  microphone_not_found: "Không tìm thấy microphone để thu âm.",
  no_microphone_signal: "Không nghe thấy âm thanh từ micro. Kiểm tra quyền micro hoặc thử nói gần micro hơn.",
};
const INITIAL_RESULT_HTML = `<p class="muted">Bấm nút để nghe audio hệ thống, hoặc chọn file audio để nhận diện.</p>`;
const DEVICE_REFRESH_MS = 2000;
const CLIENT_HEARTBEAT_MS = 2000;
const PLAY_ICON_PATH = "M8 5.8c0-.8.9-1.3 1.6-.9l8.2 5.2c.7.4.7 1.4 0 1.8l-8.2 5.2c-.7.4-1.6-.1-1.6-.9V5.8Z";
const STOP_ICON_PATH = "M7.2 6.2c0-.7.5-1.2 1.2-1.2h1.8c.7 0 1.2.5 1.2 1.2v11.6c0 .7-.5 1.2-1.2 1.2H8.4c-.7 0-1.2-.5-1.2-1.2V6.2Zm5.4 0c0-.7.5-1.2 1.2-1.2h1.8c.7 0 1.2.5 1.2 1.2v11.6c0 .7-.5 1.2-1.2 1.2h-1.8c-.7 0-1.2-.5-1.2-1.2V6.2Z";

let historyItems = [];
let previewUrl = "";
let previewDuration = 0;
let selectionStart = 0;
let selectionEnd = PREVIEW_SECONDS;
let waveformPeaks = [];
let activeWaveformDrag = "";
let playbackFrame = 0;
let busyState = false;
let busyMode = "";
let heartbeatTimer = 0;
const clientId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function userErrorMessage(error) {
  const message = String(error?.error || error?.message || error || "");
  const code = String(error?.code || "");
  const lowered = message.toLowerCase();

  if (ERROR_MESSAGES[code]) {
    return message || ERROR_MESSAGES[code];
  }
  if (lowered.includes("does not contain any stream")) {
    return "Không tìm thấy audio trong file.";
  }
  if (lowered.includes("invalid data found when processing input")) {
    return "Định dạng file không đọc được. Thử file MP3, WAV, M4A, MP4, FLAC, OGG hoặc WEBM.";
  }
  return message;
}

async function readApiJson(response) {
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }

  if (!response.ok) {
    return {
      ok: false,
      error: data.error || `Lỗi ${response.status}`,
      code: data.code || "http_error",
    };
  }

  return data;
}

function sendClientClose() {
  const url = `/api/client-close?id=${encodeURIComponent(clientId)}`;
  if (navigator.sendBeacon) {
    navigator.sendBeacon(url, new Blob([], { type: "text/plain" }));
    return;
  }
  fetch(url, { method: "POST", keepalive: true }).catch(() => {});
}

function sendClientHeartbeat() {
  fetch(`/api/client-heartbeat?id=${encodeURIComponent(clientId)}`, {
    method: "POST",
    cache: "no-store",
    keepalive: true,
  }).catch(() => {});
}

function startClientHeartbeat() {
  sendClientHeartbeat();
  heartbeatTimer = window.setInterval(sendClientHeartbeat, CLIENT_HEARTBEAT_MS);
  window.addEventListener("pagehide", () => {
    window.clearInterval(heartbeatTimer);
    sendClientClose();
  });
}

function formatBytes(bytes) {
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(mb >= 10 ? 0 : 1)}MB`;
}

function renderWarning(message) {
  resultEl.innerHTML = `<p class="notice warning">${escapeHtml(message)}</p>`;
}

function fileExtension(filename) {
  const parts = String(filename || "").toLowerCase().split(".");
  return parts.length > 1 ? parts.pop() : "";
}

function validateSelectedFile(file) {
  if (!file) {
    return null;
  }

  const extension = fileExtension(file.name);
  const type = String(file.type || "").toLowerCase();
  const allowedByExtension = ALLOWED_UPLOAD_EXTENSIONS.has(extension);
  const allowedByType = ALLOWED_UPLOAD_TYPES.has(type);
  if (!allowedByExtension && !allowedByType) {
    return {
      code: "unsupported_upload_type",
      error: "Chỉ hỗ trợ file MP3, WAV, M4A, MP4, FLAC, OGG hoặc WEBM.",
    };
  }

  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      code: "file_too_large",
      error: `File audio quá lớn (${formatBytes(file.size)}), tối đa 50MB.`,
    };
  }

  return null;
}

function setBusy(isBusy, mode = "") {
  busyState = isBusy;
  busyMode = isBusy ? mode : "";
  listenButton.disabled = busyState;
  deviceSelect.disabled = busyState;
  microphoneButton.disabled = busyState;
  microphoneSelect.disabled = busyState;
  uploadButton.disabled = busyState;
  audioFile.disabled = busyState;
  previewPlay.disabled = busyState || !audioFile.files?.[0];
  previewReset.disabled = busyState;
  waveformBox.classList.toggle("is-disabled", busyState || !audioFile.files?.[0]);
  listenButton.classList.toggle("is-listening", busyState && busyMode === "system");
  microphoneButton.classList.toggle("is-listening", busyState && busyMode === "microphone");
  buttonText.textContent = busyState && busyMode === "system" ? "Đang nghe..." : "Tìm bài đang phát";
  microphoneButtonText.textContent = busyState && busyMode === "microphone" ? "Đang ghi..." : "Ghi âm và tìm bài";
  uploadButtonText.textContent = busyState && busyMode === "upload" ? "Đang tìm..." : "Tìm kiếm";
}

function deviceLabel(device, activeText = "đang phát") {
  const label = device.label || device.id || "Audio device";
  return device.active ? `${label} (${activeText})` : label;
}

function updateSelectedDeviceText() {
  const selectedOption = deviceSelect.options[deviceSelect.selectedIndex];
  selectedDeviceText.textContent = selectedOption?.textContent || "Auto";
}

function updateSelectedMicrophoneText() {
  const selectedOption = microphoneSelect.options[microphoneSelect.selectedIndex];
  selectedMicrophoneText.textContent = selectedOption?.textContent || "Auto";
}

function renderDeviceOptions(selectEl, devices, updateLabel, activeText = "đang phát") {
  const selected = selectEl.value;
  selectEl.innerHTML = `<option value="">Auto</option>`;
  for (const device of devices) {
    const option = document.createElement("option");
    option.value = device.id || "";
    option.textContent = deviceLabel(device, activeText);
    selectEl.appendChild(option);
  }

  if (selected && devices.some((device) => device.id === selected)) {
    selectEl.value = selected;
  }
  updateLabel();
}

function renderDevices(devices) {
  renderDeviceOptions(deviceSelect, devices, updateSelectedDeviceText);
}

function renderMicrophones(devices) {
  renderDeviceOptions(microphoneSelect, devices, updateSelectedMicrophoneText, "đang thu");
}

async function loadDevices() {
  if (busyState) {
    return;
  }

  try {
    const response = await fetch(`/api/devices?t=${Date.now()}`, { cache: "no-store" });
    const data = await readApiJson(response);
    if (!data.ok && data.error) {
      throw new Error(userErrorMessage(data));
    }
    renderDevices(data.devices || []);
  } catch (error) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Auto";
    deviceSelect.innerHTML = "";
    deviceSelect.appendChild(option);
    updateSelectedDeviceText();
  }
}

async function loadMicrophones() {
  if (busyState) {
    return;
  }

  try {
    const response = await fetch(`/api/microphones?t=${Date.now()}`, { cache: "no-store" });
    const data = await readApiJson(response);
    if (!data.ok && data.error) {
      throw new Error(userErrorMessage(data));
    }
    renderMicrophones(data.devices || []);
  } catch (error) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Auto";
    microphoneSelect.innerHTML = "";
    microphoneSelect.appendChild(option);
    updateSelectedMicrophoneText();
  }
}

function startDeviceRefresh() {
  loadDevices();
  loadMicrophones();
  setInterval(() => {
    loadDevices();
    loadMicrophones();
  }, DEVICE_REFRESH_MS);
  window.addEventListener("focus", () => {
    loadDevices();
    loadMicrophones();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      loadDevices();
      loadMicrophones();
    }
  });
}

function formatTime(value) {
  const total = Math.max(0, Math.floor(Number(value) || 0));
  const minutes = String(Math.floor(total / 60)).padStart(2, "0");
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function selectedStartSeconds() {
  return Math.max(0, selectionStart);
}

function selectedEndSeconds() {
  return Math.max(selectedStartSeconds() + MIN_AUDIO_SECONDS, selectionEnd);
}

function updatePreviewRangeText() {
  previewRangeText.textContent = `${formatTime(selectedStartSeconds())} - ${formatTime(selectedEndSeconds())}`;
}

function stopPreview() {
  previewAudio.pause();
  if (playbackFrame) {
    cancelAnimationFrame(playbackFrame);
    playbackFrame = 0;
  }
  previewPlayText.textContent = "Nghe thử";
  previewPlayIcon.setAttribute("d", PLAY_ICON_PATH);
  drawWaveform();
}

function animatePlayback() {
  if (!previewAudio.paused && previewAudio.currentTime >= selectedEndSeconds()) {
    previewAudio.currentTime = selectedEndSeconds();
    stopPreview();
    return;
  }
  drawWaveform();
  if (!previewAudio.paused) {
    playbackFrame = requestAnimationFrame(animatePlayback);
  }
}

function resetPreview() {
  stopPreview();
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = "";
  }
  previewAudio.removeAttribute("src");
  previewAudio.load();
  previewPlay.disabled = true;
  previewDuration = 0;
  selectionStart = 0;
  selectionEnd = PREVIEW_SECONDS;
  waveformPeaks = [];
  updatePreviewRangeText();
  drawWaveform();
  filePreview.classList.add("is-hidden");
}

function resetSelectedFile() {
  audioFile.value = "";
  fileName.textContent = "Chọn file để tìm";
  resultEl.innerHTML = INITIAL_RESULT_HTML;
  previewReset.classList.add("is-hidden");
  resetPreview();
}

function rejectSelectedFile(error) {
  audioFile.value = "";
  resetPreview();
  fileName.textContent = "Chọn file để tìm";
  previewReset.classList.add("is-hidden");
  renderResult({ ok: false, ...error });
}

function loadFilePreview(file) {
  resetPreview();
  if (!file) {
    return;
  }

  const fileError = validateSelectedFile(file);
  if (fileError) {
    rejectSelectedFile(fileError);
    return;
  }

  resultEl.innerHTML = INITIAL_RESULT_HTML;
  previewUrl = URL.createObjectURL(file);
  previewAudio.src = previewUrl;
  filePreview.classList.remove("is-hidden");
  previewReset.classList.remove("is-hidden");
  previewPlay.disabled = false;
  updatePreviewRangeText();
  drawWaveform();
  analyzeWaveform(file);
}

function clampSelection() {
  const duration = Math.max(MIN_AUDIO_SECONDS, previewDuration || PREVIEW_SECONDS);
  selectionStart = Math.max(0, Math.min(selectionStart, duration - MIN_AUDIO_SECONDS));
  selectionEnd = Math.max(selectionStart + MIN_AUDIO_SECONDS, Math.min(selectionEnd, duration));
}

function clampPlayhead() {
  if (previewAudio.currentTime < selectionStart) {
    previewAudio.currentTime = selectionStart;
  } else if (previewAudio.currentTime > selectionEnd) {
    previewAudio.currentTime = selectionEnd;
  }
}

function clampedPlayheadTime() {
  return Math.max(selectionStart, Math.min(previewAudio.currentTime, selectionEnd));
}

function canvasPointToSeconds(event) {
  const rect = waveformCanvas.getBoundingClientRect();
  if (!rect.width) {
    return 0;
  }
  const x = Math.max(0, Math.min(event.clientX - rect.left, rect.width));
  const duration = previewDuration || PREVIEW_SECONDS;
  return (x / rect.width) * duration;
}

function setSelectionFromPointer(event) {
  const seconds = canvasPointToSeconds(event);
  if (activeWaveformDrag === "start") {
    selectionStart = Math.min(seconds, selectionEnd - MIN_AUDIO_SECONDS);
  } else if (activeWaveformDrag === "end") {
    selectionEnd = Math.max(seconds, selectionStart + MIN_AUDIO_SECONDS);
  } else if (activeWaveformDrag === "move") {
    const width = selectionEnd - selectionStart;
    selectionStart = seconds - width / 2;
    selectionEnd = selectionStart + width;
  } else if (activeWaveformDrag === "playhead") {
    previewAudio.currentTime = Math.max(selectionStart, Math.min(seconds, selectionEnd));
  }
  clampSelection();
  stopPreview();
  clampPlayhead();
  updatePreviewRangeText();
  drawWaveform();
}

function drawWaveform() {
  const rect = waveformBox.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width || 1));
  const height = 92;
  const ratio = window.devicePixelRatio || 1;
  waveformCanvas.width = Math.floor(width * ratio);
  waveformCanvas.height = Math.floor(height * ratio);
  waveformCanvas.style.width = `${width}px`;
  waveformCanvas.style.height = `${height}px`;

  const ctx = waveformCanvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fffafd";
  ctx.fillRect(0, 0, width, height);

  const center = height / 2;
  const barGap = 2;
  const barWidth = 2;
  const barCount = Math.max(1, Math.floor(width / (barWidth + barGap)));
  const peaks = waveformPeaks.length ? waveformPeaks : Array.from({ length: barCount }, (_, index) => {
    return 0.28 + Math.abs(Math.sin(index * 0.37)) * 0.45;
  });

  ctx.strokeStyle = "rgba(234, 219, 230, 0.95)";
  ctx.beginPath();
  ctx.moveTo(0, center);
  ctx.lineTo(width, center);
  ctx.stroke();

  ctx.fillStyle = "rgba(89, 79, 86, 0.58)";
  for (let index = 0; index < barCount; index += 1) {
    const peakIndex = Math.floor((index / barCount) * peaks.length);
    const peak = Math.max(0.08, peaks[peakIndex] || 0.08);
    const barHeight = Math.max(6, peak * (height - 16));
    const x = index * (barWidth + barGap) + 4;
    ctx.fillRect(x, center - barHeight / 2, barWidth, barHeight);
  }

  const duration = previewDuration || PREVIEW_SECONDS;
  const startX = (selectionStart / duration) * width;
  const endX = (selectionEnd / duration) * width;

  ctx.fillStyle = "rgba(255, 95, 158, 0.16)";
  ctx.fillRect(startX, 0, Math.max(2, endX - startX), height);

  ctx.fillStyle = "#ff5f9e";
  ctx.fillRect(startX - 2, 0, 4, height);
  ctx.fillRect(endX - 2, 0, 4, height);

  if (previewAudio.src) {
    const displayTime = clampedPlayheadTime();
    const currentX = (displayTime / duration) * width;
    ctx.fillStyle = "#ffd166";
    ctx.shadowColor = "rgba(255, 209, 102, 0.48)";
    ctx.shadowBlur = 4;
    ctx.fillRect(currentX - 2, 0, 4, height);
    ctx.shadowBlur = 0;

    const labelWidth = 38;
    const labelX = Math.max(0, Math.min(width - labelWidth, currentX - labelWidth / 2));
    ctx.fillStyle = "rgba(39, 33, 43, 0.86)";
    ctx.fillRect(labelX, height - 22, labelWidth, 18);
    ctx.fillStyle = "#ffffff";
    ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
    ctx.fillText(formatTime(displayTime), labelX + 4, height - 9);
  }
}

async function analyzeWaveform(file) {
  try {
    const buffer = await file.arrayBuffer();
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      drawWaveform();
      return;
    }
    const context = new AudioContextClass();
    const audioBuffer = await context.decodeAudioData(buffer);
    previewDuration = audioBuffer.duration || previewDuration;
    selectionStart = 0;
    selectionEnd = Math.min(PREVIEW_SECONDS, Math.max(MIN_AUDIO_SECONDS, previewDuration));

    const data = audioBuffer.getChannelData(0);
    const peakCount = 180;
    const blockSize = Math.max(1, Math.floor(data.length / peakCount));
    waveformPeaks = Array.from({ length: peakCount }, (_, index) => {
      const start = index * blockSize;
      const end = Math.min(data.length, start + blockSize);
      let max = 0;
      for (let sampleIndex = start; sampleIndex < end; sampleIndex += 1) {
        max = Math.max(max, Math.abs(data[sampleIndex]));
      }
      return max;
    });
    await context.close?.();
    clampSelection();
    updatePreviewRangeText();
    drawWaveform();
  } catch (error) {
    drawWaveform();
  }
}

function trackText(item) {
  return [item.title, item.artist].filter(Boolean).join(" - ");
}

function coverMarkup(item, sizeClass = "") {
  const coverUrl = item.cover_url || "";
  if (coverUrl) {
    return `
      <img
        class="cover ${sizeClass}"
        src="${escapeHtml(coverUrl)}"
        alt=""
        loading="lazy"
        referrerpolicy="no-referrer"
      >
    `;
  }
  return `
    <span class="cover cover-fallback ${sizeClass}" aria-hidden="true">
      <svg class="note-icon" viewBox="0 0 48 48" focusable="false">
        <path d="M30.5 8.5c0-.9.6-1.7 1.5-1.9l6.8-1.5c1.2-.3 2.2.6 2.2 1.8v5.8c0 .9-.6 1.7-1.5 1.9l-4.8 1.1v19c0 4.7-4 8.3-9 8.3-4.2 0-7.5-2.5-7.5-6 0-3.7 3.6-6.4 8.3-6.4 1.5 0 2.8.3 4 .8V8.5Z"/>
      </svg>
    </span>
  `;
}

async function copyTrack(item, button) {
  const value = trackText(item);
  if (!value) {
    return;
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }

    const oldText = button.textContent;
    button.textContent = "Đã copy";
    button.disabled = true;
    setTimeout(() => {
      button.textContent = oldText;
      button.disabled = false;
    }, 1100);
  } catch (error) {
    button.textContent = "Lỗi copy";
    setTimeout(() => {
      button.textContent = "Copy";
    }, 1100);
  }
}

function renderResult(data) {
  if (!data.ok) {
    renderWarning(userErrorMessage(data) || "Có lỗi rồi.");
    return;
  }

  if (!data.found) {
    renderWarning("Chưa tìm thấy bài nào. Thử tăng âm lượng hoặc chạy lại lần nữa.");
    return;
  }

  const title = escapeHtml(data.title);
  const artist = escapeHtml(data.artist || "Unknown artist");
  const shazamLink = data.href
    ? `<a href="${escapeHtml(data.href)}" target="_blank" rel="noreferrer">Shazam</a>`
    : "";
  const youtubeLink = data.youtube_url
    ? `<a href="${escapeHtml(data.youtube_url)}" target="_blank" rel="noreferrer">YouTube</a>`
    : "";
  const links = [shazamLink, youtubeLink].filter(Boolean).join(" · ");

  resultEl.innerHTML = `
    <div class="track-card">
      ${coverMarkup(data, "cover-large")}
      <div class="track-info">
        <span class="track-title">${title}</span>
        <p class="track-artist">${artist}</p>
        <p class="track-meta">${escapeHtml(data.elapsed)}s ${links}</p>
      </div>
      <button class="icon-button js-copy-result" type="button">Copy</button>
    </div>
  `;

  resultEl.querySelector(".js-copy-result")?.addEventListener("click", (event) => {
    copyTrack(data, event.currentTarget);
  });
}

function renderHistory(items) {
  historyItems = items;
  if (!items.length) {
    historyEl.innerHTML = `<p class="muted">Chưa có bài nào.</p>`;
    return;
  }

  historyEl.innerHTML = items.map((item) => {
    const title = escapeHtml(item.title);
    const artist = escapeHtml(item.artist || "Unknown artist");
    const time = escapeHtml(item.created_at || "");
    const id = escapeHtml(item.id || "");
    const titleHtml = item.href
      ? `<a class="history-title" href="${escapeHtml(item.href)}" target="_blank" rel="noreferrer">${title}</a>`
      : `<span class="history-title">${title}</span>`;

    return `
      <article class="history-item" data-id="${id}">
        ${coverMarkup(item)}
        <div class="history-main">
          <div class="history-line">
            ${titleHtml}
            <span class="history-time">${time}</span>
          </div>
          <div class="history-artist">${artist}</div>
          <div class="history-actions">
            <button class="text-button js-copy" type="button">Copy</button>
            <button class="text-button danger js-delete" type="button">Xóa</button>
          </div>
        </div>
      </article>
    `;
  }).join("");
}

async function loadHistory() {
  const response = await fetch(`/api/history?t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`History lỗi ${response.status}`);
  }
  const data = await response.json();
  renderHistory(data.items || []);
}

async function clearHistory() {
  if (!historyItems.length) {
    return;
  }

  if (!confirm("Xóa toàn bộ lịch sử?")) {
    return;
  }

  const oldText = clearButton.textContent;
  clearButton.disabled = true;
  clearButton.textContent = "Đang xóa";

  try {
    const response = await fetch("/api/clear-history", { method: "POST" });
    if (!response.ok) {
      throw new Error(`Xóa lỗi ${response.status}`);
    }
    renderHistory([]);
  } catch (error) {
    historyEl.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
  } finally {
    clearButton.disabled = false;
    clearButton.textContent = oldText;
  }
}

async function deleteHistoryItem(id) {
  const response = await fetch(`/api/delete-history?id=${encodeURIComponent(id)}`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Xóa lỗi ${response.status}`);
  }
  const data = await response.json();
  renderHistory(data.items || []);
}

async function recognize() {
  setBusy(true, "system");
  previewReset.classList.remove("is-hidden");
  resultEl.innerHTML = `<p class="muted">Đang nghe audio từ máy, tối đa 5 giây...</p>`;

  try {
    const device = deviceSelect.value;
    const query = device ? `?device=${encodeURIComponent(device)}` : "";
    const response = await fetch(`/api/recognize${query}`, { method: "POST" });
    const data = await readApiJson(response);
    renderResult(data);
    await loadHistory();
  } catch (error) {
    renderResult({ ok: false, error: error.message });
  } finally {
    setBusy(false);
  }
}

async function recognizeMicrophone() {
  setBusy(true, "microphone");
  previewReset.classList.remove("is-hidden");
  resultEl.innerHTML = `<p class="muted">Đang ghi âm từ microphone, tối đa 5 giây...</p>`;

  try {
    const device = microphoneSelect.value;
    const query = device ? `?device=${encodeURIComponent(device)}` : "";
    const response = await fetch(`/api/recognize-mic${query}`, { method: "POST" });
    const data = await readApiJson(response);
    renderResult(data);
    await loadHistory();
  } catch (error) {
    renderResult({ ok: false, error: error.message });
  } finally {
    setBusy(false);
  }
}

async function recognizeFile() {
  const file = audioFile.files?.[0];
  if (!file) {
    renderWarning("Chọn một file audio trước khi nhận diện.");
    return;
  }

  const fileError = validateSelectedFile(file);
  if (fileError) {
    rejectSelectedFile(fileError);
    return;
  }

  setBusy(true, "upload");
  previewReset.classList.remove("is-hidden");
  const startSeconds = selectedStartSeconds();
  const endSeconds = selectedEndSeconds();
  resultEl.innerHTML = `<p class="muted">Đang tìm trong khoảng ${escapeHtml(formatTime(startSeconds))} - ${escapeHtml(formatTime(endSeconds))} của ${escapeHtml(file.name)}...</p>`;

  try {
    const response = await fetch("/api/recognize-file", {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
        "X-Start-Seconds": String(startSeconds),
        "X-End-Seconds": String(endSeconds),
      },
      body: file,
    });
    const data = await readApiJson(response);
    renderResult(data);
    await loadHistory();
  } catch (error) {
    renderResult({ ok: false, error: error.message });
  } finally {
    setBusy(false);
  }
}

listenButton.addEventListener("click", recognize);
deviceSelect.addEventListener("change", updateSelectedDeviceText);
microphoneButton.addEventListener("click", recognizeMicrophone);
microphoneSelect.addEventListener("change", updateSelectedMicrophoneText);
uploadButton.addEventListener("click", recognizeFile);
audioFile.addEventListener("change", () => {
  const file = audioFile.files?.[0];
  fileName.textContent = file ? file.name : "Chọn file để tìm";
  loadFilePreview(file);
});
previewAudio.addEventListener("loadedmetadata", () => {
  const duration = Number.isFinite(previewAudio.duration) ? previewAudio.duration : 0;
  previewDuration = duration || previewDuration;
  if (duration > 0 && duration < MIN_AUDIO_SECONDS) {
    rejectSelectedFile({
      code: "audio_too_short",
      error: "File audio quá ngắn. Cần tối thiểu 3 giây để nhận diện.",
    });
    return;
  }
  selectionStart = 0;
  selectionEnd = Math.min(PREVIEW_SECONDS, Math.max(MIN_AUDIO_SECONDS, previewDuration || PREVIEW_SECONDS));
  clampSelection();
  previewAudio.currentTime = selectionStart;
  updatePreviewRangeText();
  drawWaveform();
});
previewAudio.addEventListener("error", () => {
  if (!audioFile.files?.[0]) {
    return;
  }
  rejectSelectedFile({
    code: "unsupported_audio_file",
    error: "Định dạng file không đọc được. Thử file MP3, WAV, M4A, MP4, FLAC, OGG hoặc WEBM.",
  });
});
previewAudio.addEventListener("timeupdate", () => {
  if (!previewAudio.paused && previewAudio.currentTime >= selectedEndSeconds()) {
    previewAudio.currentTime = selectedEndSeconds();
    stopPreview();
    return;
  }
  drawWaveform();
});
previewAudio.addEventListener("ended", () => {
  stopPreview();
  drawWaveform();
});
waveformCanvas.addEventListener("pointerdown", (event) => {
  if (!audioFile.files?.[0]) {
    return;
  }
  const duration = previewDuration || PREVIEW_SECONDS;
  const clicked = canvasPointToSeconds(event);
  const threshold = Math.max(1, duration * 0.025);
  if (Math.abs(clicked - clampedPlayheadTime()) <= threshold) {
    activeWaveformDrag = "playhead";
  } else if (Math.abs(clicked - selectionStart) <= threshold) {
    activeWaveformDrag = "start";
  } else if (Math.abs(clicked - selectionEnd) <= threshold) {
    activeWaveformDrag = "end";
  } else if (clicked > selectionStart && clicked < selectionEnd) {
    activeWaveformDrag = "move";
  } else {
    const distanceToStart = Math.abs(clicked - selectionStart);
    const distanceToEnd = Math.abs(clicked - selectionEnd);
    activeWaveformDrag = distanceToStart < distanceToEnd ? "start" : "end";
  }
  waveformCanvas.setPointerCapture(event.pointerId);
  setSelectionFromPointer(event);
});
waveformCanvas.addEventListener("pointermove", (event) => {
  if (!activeWaveformDrag) {
    return;
  }
  setSelectionFromPointer(event);
});
waveformCanvas.addEventListener("pointerup", (event) => {
  activeWaveformDrag = "";
  waveformCanvas.releasePointerCapture(event.pointerId);
});
window.addEventListener("resize", drawWaveform);
previewPlay.addEventListener("click", async () => {
  if (!audioFile.files?.[0]) {
    return;
  }

  if (!previewAudio.paused) {
    stopPreview();
    return;
  }

  if (previewAudio.currentTime < selectedStartSeconds() || previewAudio.currentTime >= selectedEndSeconds()) {
    previewAudio.currentTime = selectedStartSeconds();
  }
  previewPlayText.textContent = "Dừng";
  previewPlayIcon.setAttribute("d", STOP_ICON_PATH);
  try {
    await previewAudio.play();
    animatePlayback();
  } catch (error) {
    previewPlayText.textContent = "Không phát được";
    setTimeout(() => {
      previewPlayText.textContent = "Nghe thử";
    }, 1200);
  }
});
previewReset.addEventListener("click", resetSelectedFile);
clearButton.addEventListener("click", clearHistory);
historyEl.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) {
    return;
  }

  const itemEl = button.closest(".history-item");
  const id = itemEl?.dataset.id || "";
  const item = historyItems.find((historyItem) => historyItem.id === id);

  if (button.classList.contains("js-copy") && item) {
    copyTrack(item, button);
    return;
  }

  if (button.classList.contains("js-delete") && id) {
    button.disabled = true;
    button.textContent = "Đang xóa";
    try {
      await deleteHistoryItem(id);
    } catch (error) {
      button.disabled = false;
      button.textContent = "Lỗi xóa";
    }
  }
});
loadHistory().catch((error) => {
  historyEl.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
});
startDeviceRefresh();
startClientHeartbeat();
