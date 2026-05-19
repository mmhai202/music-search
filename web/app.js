const listenButton = document.querySelector("#listenButton");
const buttonText = document.querySelector("#buttonText");
const audioFile = document.querySelector("#audioFile");
const fileName = document.querySelector("#fileName");
const uploadButton = document.querySelector("#uploadButton");
const uploadButtonText = document.querySelector("#uploadButtonText");
const resultEl = document.querySelector("#result");
const historyEl = document.querySelector("#history");
const clearButton = document.querySelector("#clearButton");

let historyItems = [];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function userErrorMessage(error) {
  const message = String(error || "");
  if (message.toLowerCase().includes("does not contain any stream")) {
    return "Không tìm thấy audio trong file.";
  }
  return message;
}

function setBusy(isBusy) {
  listenButton.disabled = isBusy;
  uploadButton.disabled = isBusy;
  audioFile.disabled = isBusy;
  listenButton.classList.toggle("is-listening", isBusy);
  buttonText.textContent = isBusy ? "Đang nghe..." : "Tìm bài đang phát";
  uploadButtonText.textContent = isBusy ? "Đang tìm..." : "Tìm kiếm";
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
    resultEl.innerHTML = `<p class="muted">${escapeHtml(userErrorMessage(data.error) || "Co loi roi")}</p>`;
    return;
  }

  if (!data.found) {
    resultEl.innerHTML = `<p class="muted">Chưa tìm thấy bài nào. Thử tăng âm lượng hoặc chạy lại lần nữa.</p>`;
    return;
  }

  const title = escapeHtml(data.title);
  const artist = escapeHtml(data.artist || "Unknown artist");
  const link = data.href
    ? `<a href="${escapeHtml(data.href)}" target="_blank" rel="noreferrer">Mở Shazam</a>`
    : "";

  resultEl.innerHTML = `
    <div class="track-card">
      ${coverMarkup(data, "cover-large")}
      <div class="track-info">
        <span class="track-title">${title}</span>
        <p class="track-artist">${artist}</p>
        <p class="track-meta">${escapeHtml(data.elapsed)}s ${link}</p>
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
  setBusy(true);
  resultEl.innerHTML = `<p class="muted">Đang nghe audio từ máy...</p>`;

  try {
    const response = await fetch("/api/recognize", { method: "POST" });
    const data = await response.json();
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
    resultEl.innerHTML = `<p class="muted">Chọn một file audio trước khi nhận diện.</p>`;
    return;
  }

  setBusy(true);
  resultEl.innerHTML = `<p class="muted">Đang tải và nhận diện ${escapeHtml(file.name)}...</p>`;

  try {
    const response = await fetch("/api/recognize-file", {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: file,
    });
    const data = await response.json();
    renderResult(data);
    await loadHistory();
  } catch (error) {
    renderResult({ ok: false, error: error.message });
  } finally {
    setBusy(false);
  }
}

listenButton.addEventListener("click", recognize);
uploadButton.addEventListener("click", recognizeFile);
audioFile.addEventListener("change", () => {
  const file = audioFile.files?.[0];
  fileName.textContent = file ? file.name : "Chọn file để tìm";
});
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
