// Youtube Downloader Ultimate - Lógica Web (Download Direto Automático no Computador)

const STORAGE_KEY = "yt_downloader_ultimate_history_v2";

// Estado global
let currentMode = "video"; // "video" | "audio"
let historyItems = loadHistory();

// Elementos da UI
const tabBtns = document.querySelectorAll(".tab-btn");
const tabPanels = document.querySelectorAll(".tab-panel");
const urlInput = document.getElementById("urlInput");
const btnPaste = document.getElementById("btnPaste");
const modeBtns = document.querySelectorAll("#modeSwitch .seg-btn");
const qualitySelect = document.getElementById("qualitySelect");
const subsCheck = document.getElementById("subsCheck");
const trimCheck = document.getElementById("trimCheck");
const trimStart = document.getElementById("trimStart");
const trimEnd = document.getElementById("trimEnd");
const btnAddQueue = document.getElementById("btnAddQueue");
const downloadQueue = document.getElementById("downloadQueue");
const emptyQueueMsg = document.getElementById("emptyQueueMsg");
const btnClearQueue = document.getElementById("btnClearQueue");

const fileVideoInput = document.getElementById("fileVideoInput");
const fileAudioInput = document.getElementById("fileAudioInput");
const convTrimStart = document.getElementById("convTrimStart");
const convTrimEnd = document.getElementById("convTrimEnd");
const converterQueue = document.getElementById("converterQueue");
const emptyConvMsg = document.getElementById("emptyConvMsg");

const historyList = document.getElementById("historyList");
const historyCount = document.getElementById("historyCount");
const btnClearHistory = document.getElementById("btnClearHistory");

const playerModal = document.getElementById("playerModal");
const modalTitle = document.getElementById("modalTitle");
const modalBody = document.getElementById("modalBody");
const btnCloseModal = document.getElementById("btnCloseModal");
const toastContainer = document.getElementById("toastContainer");

// --- NAVEGAÇÃO POR ABAS ---
tabBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabBtns.forEach((b) => b.classList.remove("active"));
    tabPanels.forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    const target = document.getElementById(btn.dataset.tab);
    if (target) target.classList.add("active");
  });
});

// --- ALTERNÂNCIA VÍDEO / ÁUDIO ---
modeBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    modeBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentMode = btn.dataset.mode;
    const isAudio = currentMode === "audio";
    qualitySelect.disabled = isAudio;
    subsCheck.disabled = isAudio;
  });
});

// --- RECORTE DE TRECHO ---
trimCheck.addEventListener("change", () => {
  const enabled = trimCheck.checked;
  trimStart.disabled = !enabled;
  trimEnd.disabled = !enabled;
});

// --- BOTÃO COLAR ---
btnPaste.addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      urlInput.value = text.trim();
      urlInput.focus();
      showToast("📋 Link colado da área de transferência!");
    }
  } catch (_) {
    urlInput.focus();
  }
});

urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    handleAddDownload();
  }
});

btnAddQueue.addEventListener("click", handleAddDownload);

btnClearQueue.addEventListener("click", () => {
  const doneCards = downloadQueue.querySelectorAll(".download-item[data-done='true']");
  doneCards.forEach((c) => c.remove());
  updateEmptyQueueState();
});

btnCloseModal.addEventListener("click", closeModal);
playerModal.addEventListener("click", (e) => {
  if (e.target === playerModal) closeModal();
});

function closeModal() {
  playerModal.classList.add("hidden");
  modalBody.innerHTML = "";
}

function showToast(message) {
  if (!toastContainer) return;
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4200);
}

// --- DISPARO AUTOMÁTICO DE DOWNLOAD NO COMPUTADOR ---
function triggerAutoSaveToComputer(downloadUrl, filename = "video") {
  if (!downloadUrl) return;
  try {
    // O servidor envia Content-Disposition: attachment, então criar um link/iframe oculto
    // inicia imediatamente a transferência nativa do arquivo para a pasta Downloads do PC
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.setAttribute("download", filename);
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 2000);
  } catch (_) {
    window.location.assign(downloadUrl);
  }
}

// --- UTILITÁRIOS ---
function extractYouTubeId(url) {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtu.be")) return u.pathname.slice(1).split("/")[0];
    if (u.searchParams.get("v")) return u.searchParams.get("v");
    const m = u.pathname.match(/\/(shorts|embed|live)\/([^/?&]+)/);
    if (m) return m[2];
  } catch (_) {}
  return null;
}

function parseTimeToSeconds(str) {
  if (!str) return null;
  const s = str.trim();
  if (!s) return null;
  if (/^\d+(\.\d+)?$/.test(s)) return parseFloat(s);
  const parts = s.split(":").map(Number);
  if (parts.some(isNaN)) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return null;
}

function updateEmptyQueueState() {
  const hasItems = downloadQueue.querySelectorAll(".download-item").length > 0;
  emptyQueueMsg.style.display = hasItems ? "none" : "block";
}

// --- ADICIONAR DOWNLOAD À FILA ---
async function handleAddDownload() {
  const rawUrl = urlInput.value.trim();
  if (!rawUrl) {
    urlInput.focus();
    return;
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(rawUrl).href;
  } catch (_) {
    showToast("⚠️ Insira um link válido começando com https://");
    return;
  }

  const mode = currentMode;
  const quality = qualitySelect.value;
  const qualityLabel =
    qualitySelect.options[qualitySelect.selectedIndex]?.text || `${quality}p`;
  const trimEnabled = trimCheck.checked;
  const tStart = trimEnabled ? trimStart.value.trim() : "";
  const tEnd = trimEnabled ? trimEnd.value.trim() : "";

  urlInput.value = "";
  createDownloadCard({
    url: parsedUrl,
    mode,
    quality,
    qualityLabel,
    trimStart: tStart,
    trimEnd: tEnd,
  });
}

async function fetchMetadata(url) {
  try {
    const res = await fetch(`/api/info?url=${encodeURIComponent(url)}`);
    if (res.ok) {
      const data = await res.json();
      if (data && data.title) return data;
    }
  } catch (_) {}

  const ytId = extractYouTubeId(url);
  try {
    const r = await fetch(`https://noembed.com/embed?url=${encodeURIComponent(url)}`);
    if (r.ok) {
      const oe = await r.json();
      if (oe && oe.title) {
        return {
          id: ytId,
          title: oe.title,
          author: oe.author_name || "Web",
          thumbnail:
            oe.thumbnail_url ||
            (ytId ? `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg` : null),
          platform: oe.provider_name || "Web",
          url,
        };
      }
    }
  } catch (_) {}

  return {
    id: ytId,
    title: ytId ? `Vídeo (${ytId})` : url,
    author: "Mídia Online",
    thumbnail: ytId ? `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg` : null,
    platform: "Web",
    url,
  };
}

async function createDownloadCard(opts) {
  const { url, mode, quality, qualityLabel, trimStart: tStart, trimEnd: tEnd } = opts;
  const isAudio = mode === "audio";
  const iconMode = isAudio ? "🎵" : "🎬";
  const trimBadge =
    tStart || tEnd ? ` ✂️[${tStart || "00:00"}-${tEnd || "fim"}]` : "";
  const prefix = isAudio
    ? `[${iconMode} MP3${trimBadge}]`
    : `[${iconMode} ${qualityLabel}${trimBadge}]`;

  const card = document.createElement("div");
  card.className = "download-item";
  card.innerHTML = `
    <div class="item-thumb">⏳</div>
    <div class="item-body">
      <div class="item-info">${prefix} Obtendo informações do vídeo...</div>
      <div class="item-title">${url}</div>
      <div class="progress-track">
        <div class="progress-bar ${isAudio ? "audio" : "video"}" style="width: 6%"></div>
      </div>
    </div>
    <div class="item-actions">
      <button class="btn-action cancel" title="Cancelar">✕</button>
    </div>
  `;

  downloadQueue.prepend(card);
  updateEmptyQueueState();

  const thumbEl = card.querySelector(".item-thumb");
  const infoEl = card.querySelector(".item-info");
  const titleEl = card.querySelector(".item-title");
  const barEl = card.querySelector(".progress-bar");
  const actionsEl = card.querySelector(".item-actions");
  let cancelled = false;

  card.querySelector(".cancel").addEventListener("click", () => {
    cancelled = true;
    card.remove();
    updateEmptyQueueState();
  });

  // Passo 1: Metadados rápidos
  const meta = await fetchMetadata(url);
  if (cancelled) return;

  titleEl.textContent = meta.title || url;
  if (meta.thumbnail) {
    thumbEl.innerHTML = `<img src="${meta.thumbnail}" alt="Thumbnail" loading="lazy" />`;
  } else {
    thumbEl.textContent = iconMode;
  }

  infoEl.textContent = `${prefix} Iniciando download: 10%`;
  barEl.style.width = "10%";

  // Passo 2: Inicia o job limpo via /api/download
  let initData = null;
  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "init",
        url,
        mode,
        quality,
        trimStart: tStart,
        trimEnd: tEnd,
      }),
    });
    if (res.ok) {
      initData = await res.json();
    }
  } catch (_) {}

  if (cancelled) return;

  if (!initData || initData.error) {
    barEl.style.width = "0%";
    infoEl.textContent = `${prefix} Erro: ${
      initData?.error || "Não foi possível processar este link."
    }`;
    infoEl.classList.add("error");
    return;
  }

  // Atualiza título/capa caso o servidor tenha retornado mais detalhes
  if (initData.title && (!meta.title || meta.title.startsWith("Vídeo ("))) {
    meta.title = initData.title;
    titleEl.textContent = initData.title;
  }
  if (initData.thumbnail && !meta.thumbnail) {
    meta.thumbnail = initData.thumbnail;
    thumbEl.innerHTML = `<img src="${initData.thumbnail}" alt="Thumbnail" loading="lazy" />`;
  }

  let finalDownloadUrl = initData.downloadUrl || null;

  // Passo 3: Se estiver em processamento ("polling"), acompanha o progresso real até 100%
  if (initData.status === "polling" && initData.jobId) {
    const jobId = initData.jobId;
    const progressUrl = initData.progressUrl || "";

    for (let attempt = 0; attempt < 60; attempt++) {
      if (cancelled) return;
      await new Promise((r) => setTimeout(r, 1400));
      if (cancelled) return;

      try {
        const progRes = await fetch(
          `/api/download?action=progress&jobId=${encodeURIComponent(
            jobId
          )}&progressUrl=${encodeURIComponent(progressUrl)}`
        );
        if (!progRes.ok) continue;
        const progData = await progRes.json();

        if (progData.error) {
          throw new Error(progData.error);
        }

        const pct = progData.progress || Math.min(95, 15 + attempt * 5);
        barEl.style.width = `${pct}%`;
        infoEl.textContent = `${prefix} Baixando e preparando arquivo: ${pct}%`;

        if (progData.status === "completed" && progData.downloadUrl) {
          finalDownloadUrl = progData.downloadUrl;
          break;
        }
      } catch (err) {
        barEl.style.width = "0%";
        infoEl.textContent = `${prefix} Erro: ${err.message}`;
        infoEl.classList.add("error");
        return;
      }
    }
  }

  if (cancelled) return;

  if (!finalDownloadUrl) {
    barEl.style.width = "0%";
    infoEl.textContent = `${prefix} Tempo limite excedido ao preparar vídeo. Tente novamente.`;
    infoEl.classList.add("error");
    return;
  }

  // Passo 4: Concluído! Baixa automaticamente para o computador do usuário
  barEl.style.width = "100%";
  card.dataset.done = "true";
  infoEl.textContent = `${prefix} Concluído! Transferindo para o seu computador...`;
  infoEl.classList.add(isAudio ? "audio-done" : "video-done");

  const ext = isAudio ? "mp3" : "mp4";
  const safeName = `${(meta.title || "video").replace(/[<>:"/\\|?*]+/g, "").slice(0, 80)}.${ext}`;

  // Dispara o download automático no navegador sem abrir abas externas!
  triggerAutoSaveToComputer(finalDownloadUrl, safeName);
  showToast(`✅ Download concluído: "${(meta.title || "").slice(0, 40)}..."`);

  actionsEl.innerHTML = "";

  // Botão Visualizar (▶)
  const btnPreview = document.createElement("button");
  btnPreview.className = "btn-action preview";
  btnPreview.innerHTML = "▶ Visualizar";
  btnPreview.addEventListener("click", () => {
    openPreviewModal(meta, finalDownloadUrl, { tStart, tEnd });
  });
  actionsEl.appendChild(btnPreview);

  // Botão Baixar Novamente (⬇) direto do CDN limpo
  const aSave = document.createElement("a");
  aSave.className = `btn-action ${isAudio ? "save-audio" : "save-video"}`;
  aSave.href = finalDownloadUrl;
  aSave.download = safeName;
  aSave.innerHTML = isAudio ? "⬇ Salvar MP3" : "⬇ Salvar MP4";
  actionsEl.appendChild(aSave);

  // Botão Remover da lista (✕)
  const btnRemove = document.createElement("button");
  btnRemove.className = "btn-action cancel";
  btnRemove.textContent = "✕";
  btnRemove.addEventListener("click", () => {
    card.remove();
    updateEmptyQueueState();
  });
  actionsEl.appendChild(btnRemove);

  // Salva no Histórico
  saveToHistory({
    title: meta.title || url,
    url,
    thumbnail: meta.thumbnail,
    mode,
    quality: isAudio ? "MP3 Áudio" : qualityLabel,
    date: new Date().toLocaleString("pt-BR"),
  });
}

function openPreviewModal(meta, directUrl, trim) {
  modalTitle.textContent = meta.title || "Pré-visualização";
  modalBody.innerHTML = "";

  const ytId = meta.id || extractYouTubeId(meta.url);
  if (ytId) {
    const startSec = parseTimeToSeconds(trim?.tStart) || 0;
    const endSec = parseTimeToSeconds(trim?.tEnd);
    let embedUrl = `https://www.youtube.com/embed/${ytId}?autoplay=1&start=${Math.floor(
      startSec
    )}`;
    if (endSec && endSec > startSec) {
      embedUrl += `&end=${Math.floor(endSec)}`;
    }
    const iframe = document.createElement("iframe");
    iframe.src = embedUrl;
    iframe.width = "100%";
    iframe.height = "380";
    iframe.style.border = "none";
    iframe.style.borderRadius = "10px";
    iframe.allow = "autoplay; encrypted-media; picture-in-picture";
    iframe.allowFullscreen = true;
    modalBody.appendChild(iframe);
  } else if (directUrl) {
    const video = document.createElement("video");
    video.src = directUrl;
    video.controls = true;
    video.autoplay = true;
    video.style.maxWidth = "100%";
    video.style.maxHeight = "380px";
    video.style.borderRadius = "10px";
    modalBody.appendChild(video);
  }

  playerModal.classList.remove("hidden");
}

// --- CONVERSOR & RECORTADOR LOCAL (WEB AUDIO API) ---
fileAudioInput.addEventListener("change", (e) => {
  const files = Array.from(e.target.files || []);
  files.forEach((f) => processLocalConversion(f, "wav"));
  fileAudioInput.value = "";
});

fileVideoInput.addEventListener("change", (e) => {
  const files = Array.from(e.target.files || []);
  files.forEach((f) => processLocalConversion(f, "mp4"));
  fileVideoInput.value = "";
});

async function processLocalConversion(file, targetFormat) {
  emptyConvMsg.style.display = "none";
  const isAudio = targetFormat === "wav";
  const icon = isAudio ? "🎵" : "🎬";

  const tStartSec = parseTimeToSeconds(convTrimStart.value) || 0;
  const tEndSec = parseTimeToSeconds(convTrimEnd.value);

  const card = document.createElement("div");
  card.className = "download-item";
  card.innerHTML = `
    <div class="item-thumb">${icon}</div>
    <div class="item-body">
      <div class="item-info">Convertendo para ${targetFormat.toUpperCase()}...</div>
      <div class="item-title">${file.name}</div>
      <div class="progress-track">
        <div class="progress-bar ${isAudio ? "audio" : "video"}" style="width: 20%"></div>
      </div>
    </div>
    <div class="item-actions"></div>
  `;
  converterQueue.prepend(card);

  const infoEl = card.querySelector(".item-info");
  const barEl = card.querySelector(".progress-bar");
  const actionsEl = card.querySelector(".item-actions");

  try {
    if (isAudio) {
      const arrayBuf = await file.arrayBuffer();
      barEl.style.width = "50%";
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const decoded = await audioCtx.decodeAudioData(arrayBuf);
      barEl.style.width = "85%";

      const sampleRate = decoded.sampleRate;
      const startSample = Math.max(0, Math.floor(tStartSec * sampleRate));
      const endSample = tEndSec
        ? Math.min(decoded.length, Math.floor(tEndSec * sampleRate))
        : decoded.length;

      if (endSample <= startSample) {
        throw new Error("Tempo final deve ser maior que o tempo inicial.");
      }

      const wavBlob = audioBufferToWavBlob(decoded, startSample, endSample);
      const blobUrl = URL.createObjectURL(wavBlob);
      const baseName = file.name.replace(/\.[^/.]+$/, "");
      const outName = `${baseName}${tStartSec || tEndSec ? "_recorte" : ""}.wav`;

      barEl.style.width = "100%";
      card.dataset.done = "true";
      infoEl.textContent = "Conversão Concluída! Salvando no computador...";
      infoEl.classList.add("audio-done");

      triggerAutoSaveToComputer(blobUrl, outName);

      const a = document.createElement("a");
      a.className = "btn-action save-audio";
      a.href = blobUrl;
      a.download = outName;
      a.textContent = "⬇ Baixar WAV";
      actionsEl.appendChild(a);
      audioCtx.close();
    } else {
      barEl.style.width = "100%";
      card.dataset.done = "true";
      const blobUrl = URL.createObjectURL(file);
      const baseName = file.name.replace(/\.[^/.]+$/, "");
      const outName = `${baseName}.mp4`;
      infoEl.textContent = "Vídeo Pronto! Salvando no computador...";
      infoEl.classList.add("video-done");

      triggerAutoSaveToComputer(blobUrl, outName);

      const a = document.createElement("a");
      a.className = "btn-action save-video";
      a.href = blobUrl;
      a.download = outName;
      a.textContent = "⬇ Salvar MP4";
      actionsEl.appendChild(a);
    }
  } catch (err) {
    barEl.style.width = "0%";
    infoEl.textContent = `Erro: ${err.message || "Formato não suportado pelo navegador"}`;
    infoEl.classList.add("error");
  }
}

function audioBufferToWavBlob(buffer, startSample, endSample) {
  const numChannels = buffer.numberOfChannels;
  const sampleRate = buffer.sampleRate;
  const frameCount = endSample - startSample;
  const bytesPerSample = 2;
  const blockAlign = numChannels * bytesPerSample;
  const dataSize = frameCount * blockAlign;
  const arrayBuffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(arrayBuffer);

  function writeStr(offset, str) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);

  const channels = [];
  for (let c = 0; c < numChannels; c++) {
    channels.push(buffer.getChannelData(c));
  }

  let offset = 44;
  for (let i = startSample; i < endSample; i++) {
    for (let c = 0; c < numChannels; c++) {
      const sample = Math.max(-1, Math.min(1, channels[c][i]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
  }

  return new Blob([arrayBuffer], { type: "audio/wav" });
}

// --- HISTÓRICO (LOCALSTORAGE) ---
function loadHistory() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (_) {
    return [];
  }
}

function saveToHistory(item) {
  historyItems.unshift(item);
  historyItems = historyItems.slice(0, 100);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(historyItems));
  } catch (_) {}
  renderHistory();
}

function renderHistory() {
  historyCount.textContent = String(historyItems.length);
  historyList.innerHTML = "";

  if (historyItems.length === 0) {
    historyList.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📜</div>
        <h3>Histórico vazio</h3>
        <p>Seus downloads concluídos aparecerão aqui para acesso rápido.</p>
      </div>
    `;
    return;
  }

  historyItems.forEach((item) => {
    const row = document.createElement("div");
    row.className = "download-item";
    const isAudio = item.mode === "audio";
    row.innerHTML = `
      <div class="item-thumb">
        ${
          item.thumbnail
            ? `<img src="${item.thumbnail}" alt="Thumb" loading="lazy" />`
            : isAudio
            ? "🎵"
            : "🎬"
        }
      </div>
      <div class="item-body">
        <div class="item-info">${item.date} • ${item.quality}</div>
        <div class="item-title">${item.title}</div>
      </div>
      <div class="item-actions">
        <button class="btn-action preview">🔄 Baixar Novamente</button>
      </div>
    `;
    row.querySelector("button").addEventListener("click", () => {
      document.querySelector('[data-tab="tab-downloader"]').click();
      urlInput.value = item.url;
      handleAddDownload();
    });
    historyList.appendChild(row);
  });
}

btnClearHistory.addEventListener("click", () => {
  historyItems = [];
  localStorage.removeItem(STORAGE_KEY);
  renderHistory();
});

// Inicializa histórico
renderHistory();
