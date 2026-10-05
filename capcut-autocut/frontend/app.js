// AutoCut for CapCut - フロントエンド
// バックエンドと同じオリジンで配信される前提。別ホストで動かす場合は API_BASE を変更する。
const API_BASE = window.AUTOCUT_API || "";

const CATEGORY_LABELS = {
  silence: "無音",
  filler: "フィラー",
  retake: "言い直し",
  stumble: "噛み・言い淀み",
  redundant: "重複",
  long_pause: "長い間",
  off_topic: "撮影中の独り言",
  manual: "手動",
};

const $ = (sel) => document.querySelector(sel);
const video = $("#video");
const canvas = $("#timeline");
const ctx = canvas.getContext("2d");

const state = {
  project: null,
  waveform: [],
  markIn: null,
  markOut: null,
  pollTimer: null,
  saveTimer: null,
};

// ------------------------------------------------------------ API

async function api(path, options = {}) {
  const res = await fetch(API_BASE + path, options);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* JSON でない */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res;
}
const getJSON = async (path) => (await api(path)).json();
const sendJSON = async (path, method, body) =>
  (await api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();

// ------------------------------------------------------------ ユーティリティ

function fmt(t) {
  if (t == null || isNaN(t)) return "--:--";
  const m = Math.floor(t / 60);
  const s = (t % 60).toFixed(1).padStart(4, "0");
  return `${m}:${s}`;
}
const cuts = () => state.project?.cuts || [];
const duration = () => state.project?.info?.duration || 0;
const enabledCuts = () => cuts().filter((c) => c.enabled).sort((a, b) => a.start - b.start);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function keepSegments() {
  // バックエンドと同じロジック（プレビュー用に即時計算）
  const ranges = enabledCuts().map((c) => [c.start, c.end]);
  const merged = [];
  for (const [s, e] of ranges) {
    if (merged.length && s <= merged.at(-1)[1]) merged.at(-1)[1] = Math.max(merged.at(-1)[1], e);
    else merged.push([s, e]);
  }
  const keeps = [];
  let cursor = 0;
  for (const [s, e] of merged) {
    if (s - cursor >= 0.1) keeps.push([cursor, s]);
    cursor = e;
  }
  if (duration() - cursor >= 0.1) keeps.push([cursor, duration()]);
  return keeps;
}

// ------------------------------------------------------------ ヘルスチェック

async function loadHealth() {
  try {
    const h = await getJSON("/api/health");
    $("#health").innerHTML = [
      `<span class="badge ${h.whisper ? "ok" : "ng"}">文字起こし (Whisper)</span>`,
      `<span class="badge ${h.claude_key ? "ok" : "ng"}">Claude API</span>`,
      `<span class="badge ${h.capcut_draft_dir ? "ok" : "ng"}">CapCut 直接追加</span>`,
    ].join("");
    if (h.capcut_draft_dir) $("#installDraft").classList.remove("hidden");
    if (!h.whisper || !h.claude_key) {
      $("#use_ai").checked = false;
      $("#use_ai").dispatchEvent(new Event("change"));
    }
  } catch {
    $("#health").innerHTML = `<span class="badge ng">バックエンドに接続できません</span>`;
  }
}

// ------------------------------------------------------------ プロジェクト

async function loadProjects() {
  const items = await getJSON("/api/projects");
  const list = $("#projectList");
  list.innerHTML = "";
  for (const p of items) {
    const li = document.createElement("li");
    li.className = p.id === state.project?.id ? "active" : "";
    li.innerHTML = `<span class="name"></span><span class="meta">${fmt(p.info?.duration)}</span>`;
    li.querySelector(".name").textContent = p.name;
    li.onclick = () => openProject(p.id);
    list.appendChild(li);
  }
}

async function upload(file) {
  const fd = new FormData();
  fd.append("file", file);
  $("#uploadStatus").textContent = `アップロード中: ${file.name}`;
  try {
    const p = await (await api("/api/projects", { method: "POST", body: fd })).json();
    $("#uploadStatus").textContent = "";
    await openProject(p.id);
    await loadProjects();
  } catch (e) {
    $("#uploadStatus").textContent = `エラー: ${e.message}`;
  }
}

async function openProject(id) {
  clearInterval(state.pollTimer);
  const [project, waveform] = await Promise.all([
    getJSON(`/api/projects/${id}`),
    getJSON(`/api/projects/${id}/waveform`),
  ]);
  state.project = project;
  state.waveform = waveform;
  state.markIn = state.markOut = null;
  video.src = `${API_BASE}/api/projects/${id}/media`;
  $("#emptyState").classList.add("hidden");
  $("#analyzeBtn").disabled = false;
  if (project.settings) applySettings(project.settings);
  renderAll();
  loadProjects();
  if (project.status === "analyzing") startPolling();
}

// ------------------------------------------------------------ 解析

function readSettings() {
  return {
    noise_db: +$("#noise_db").value,
    min_silence: +$("#min_silence").value,
    padding: +$("#padding").value,
    use_ai: $("#use_ai").checked,
    ai_min_confidence: +$("#ai_min_confidence").value,
    instructions: $("#instructions").value,
    language: "ja",
  };
}

function applySettings(s) {
  for (const key of ["noise_db", "min_silence", "padding", "ai_min_confidence"]) {
    if (s[key] != null) $("#" + key).value = s[key];
  }
  $("#use_ai").checked = !!s.use_ai;
  $("#instructions").value = s.instructions || "";
  updateOutputs();
}

async function analyze() {
  if (!state.project) return;
  try {
    state.project = await sendJSON(`/api/projects/${state.project.id}/analyze`, "POST", readSettings());
    renderStatus();
    startPolling();
  } catch (e) {
    alert(e.message);
  }
}

function startPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    const p = await getJSON(`/api/projects/${state.project.id}`);
    state.project = p;
    renderStatus();
    if (p.status !== "analyzing") {
      clearInterval(state.pollTimer);
      renderAll();
    }
  }, 1500);
}

// ------------------------------------------------------------ カット編集

function saveCutsSoon() {
  clearTimeout(state.saveTimer);
  renderAll();
  state.saveTimer = setTimeout(async () => {
    const p = await sendJSON(`/api/projects/${state.project.id}/cuts`, "PUT", { cuts: cuts() });
    state.project = { ...state.project, keeps: p.keeps, kept_duration: p.kept_duration };
  }, 400);
}

function toggleCut(id) {
  const c = cuts().find((x) => x.id === id);
  if (c) { c.enabled = !c.enabled; saveCutsSoon(); }
}

function removeCut(id) {
  state.project.cuts = cuts().filter((c) => c.id !== id);
  saveCutsSoon();
}

function addManualCut() {
  let { markIn: s, markOut: e } = state;
  if (s == null || e == null) return alert("I キーで開始位置、O キーで終了位置を指定してください");
  if (e < s) [s, e] = [e, s];
  if (e - s < 0.05) return;
  state.project.cuts.push({
    id: Math.random().toString(16).slice(2, 12),
    start: +s.toFixed(3), end: +e.toFixed(3),
    source: "manual", category: "manual", reason: "手動で追加", confidence: 1, enabled: true,
  });
  state.project.cuts.sort((a, b) => a.start - b.start);
  state.markIn = state.markOut = null;
  saveCutsSoon();
}

function bulk(action) {
  for (const c of cuts()) {
    if (action === "all-on") c.enabled = true;
    if (action === "ai-off" && c.source === "ai") c.enabled = false;
    if (action === "ai-on" && c.source === "ai") c.enabled = true;
  }
  saveCutsSoon();
}

// ------------------------------------------------------------ 描画

function renderAll() {
  renderStatus();
  renderStats();
  renderTable();
  drawTimeline();
}

function renderStatus() {
  const p = state.project;
  const analyzing = p?.status === "analyzing";
  $("#progress").classList.toggle("hidden", !analyzing);
  $("#progressText").textContent = p?.progress || "";
  $("#analyzeBtn").disabled = !p || analyzing;
  $("#analyzeBtn").textContent = p?.cuts?.length ? "設定を変えて再解析" : "自動カットを実行";
  const warnings = [...(p?.warnings || []), ...(p?.error ? [`エラー: ${p.error}`] : [])];
  $("#warnings").innerHTML = "";
  for (const w of warnings) {
    const li = document.createElement("li");
    li.textContent = w;
    $("#warnings").appendChild(li);
  }
}

function renderStats() {
  if (!state.project) return ($("#stats").textContent = "");
  const kept = keepSegments().reduce((sum, [s, e]) => sum + (e - s), 0);
  const total = duration();
  const pct = total ? Math.round((1 - kept / total) * 100) : 0;
  $("#stats").innerHTML = `${fmt(total)} → <b>${fmt(kept)}</b>（${pct}% 短縮）`;
}

function renderTable() {
  const filter = $("#categoryFilter").value;
  const cats = [...new Set(cuts().map((c) => c.category))];
  const select = $("#categoryFilter");
  const current = select.value;
  select.innerHTML = `<option value="">すべてのカテゴリ</option>` +
    cats.map((c) => `<option value="${c}">${CATEGORY_LABELS[c] || c}</option>`).join("");
  select.value = cats.includes(current) ? current : "";

  const rows = cuts().filter((c) => !filter || c.category === filter);
  $("#cutCount").textContent = `${enabledCuts().length} / ${cuts().length} 件 ON`;
  const tbody = $("#cutRows");
  tbody.innerHTML = "";
  for (const c of rows) {
    const tr = document.createElement("tr");
    tr.className = c.enabled ? "" : "off";
    tr.dataset.id = c.id;
    tr.innerHTML = `
      <td><input type="checkbox" ${c.enabled ? "checked" : ""}></td>
      <td>${fmt(c.start)}</td>
      <td>${(c.end - c.start).toFixed(1)}s</td>
      <td><span class="tag ${c.source}">${CATEGORY_LABELS[c.category] || c.category}</span></td>
      <td class="reason"></td>
      <td>${c.source === "ai" ? Math.round(c.confidence * 100) + "%" : ""}</td>
      <td><button class="del" title="削除">✕</button></td>`;
    tr.querySelector(".reason").textContent = c.reason;
    tr.querySelector("input").onclick = (ev) => { ev.stopPropagation(); toggleCut(c.id); };
    tr.querySelector(".del").onclick = (ev) => { ev.stopPropagation(); removeCut(c.id); };
    tr.onclick = () => {
      // カットの少し前から再生して、カットの効果を確認できるようにする
      video.currentTime = Math.max(0, c.start - 1.5);
      video.play();
    };
    tbody.appendChild(tr);
  }
}

function drawTimeline() {
  const wrap = $("#timelineWrap");
  const zoom = +$("#zoom").value;
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(wrap.clientWidth - 2, 100) * zoom;
  const height = 140;
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const total = duration();
  if (!total) return;
  const x = (t) => (t / total) * width;
  const rulerH = 18;
  const mid = rulerH + (height - rulerH) / 2;

  // 目盛り
  ctx.fillStyle = cssVar("--muted");
  ctx.font = "10px system-ui";
  const pxPerSec = width / total;
  const step = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600].find((s) => s * pxPerSec > 70) || 600;
  for (let t = 0; t <= total; t += step) {
    ctx.fillRect(x(t), 0, 1, 6);
    ctx.fillText(fmt(t).replace(/\.\d$/, ""), x(t) + 3, 12);
  }

  // 波形
  const peaks = state.waveform;
  ctx.fillStyle = cssVar("--wave");
  if (peaks.length) {
    const amp = (height - rulerH) / 2 - 4;
    for (let px = 0; px < width; px++) {
      const i0 = Math.floor((px / width) * peaks.length);
      const i1 = Math.max(i0 + 1, Math.floor(((px + 1) / width) * peaks.length));
      let peak = 0;
      for (let i = i0; i < i1 && i < peaks.length; i++) peak = Math.max(peak, peaks[i]);
      const h = Math.max(1, peak * amp);
      ctx.fillRect(px, mid - h, 1, h * 2);
    }
  }

  // カット範囲
  const colors = { silence: cssVar("--silence"), ai: cssVar("--ai"), manual: cssVar("--manual") };
  for (const c of cuts()) {
    const x0 = x(c.start), w = Math.max(1, x(c.end) - x0);
    if (c.enabled) {
      ctx.globalAlpha = 0.55;
      ctx.fillStyle = colors[c.source];
      ctx.fillRect(x0, rulerH, w, height - rulerH);
      ctx.globalAlpha = 1;
    } else {
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = colors[c.source];
      ctx.strokeRect(x0 + 0.5, rulerH + 0.5, w - 1, height - rulerH - 1);
      ctx.setLineDash([]);
    }
  }

  // IN / OUT マーカー
  if (state.markIn != null || state.markOut != null) {
    ctx.fillStyle = "rgba(239, 68, 68, .25)";
    const a = state.markIn ?? state.markOut, b = state.markOut ?? state.markIn;
    ctx.fillRect(x(Math.min(a, b)), rulerH, Math.max(2, Math.abs(x(b) - x(a))), height - rulerH);
  }

  // 再生ヘッド
  ctx.fillStyle = cssVar("--accent");
  ctx.fillRect(x(video.currentTime) - 1, 0, 2, height);
}

function cutAtTime(t) {
  return cuts().find((c) => t >= c.start && t <= c.end);
}

function timeFromEvent(ev) {
  const rect = canvas.getBoundingClientRect();
  return ((ev.clientX - rect.left) / rect.width) * duration();
}

// ------------------------------------------------------------ 再生（カット箇所スキップ）

function playbackLoop() {
  if (state.project && $("#skipCuts").checked && !video.paused) {
    const t = video.currentTime;
    const c = enabledCuts().find((x) => t >= x.start && t < x.end - 0.02);
    if (c) video.currentTime = c.end;
  }
  if (state.project) {
    drawTimeline();
    highlightPlayingRow();
  }
  requestAnimationFrame(playbackLoop);
}

let lastPlayingId = null;
function highlightPlayingRow() {
  const c = cutAtTime(video.currentTime);
  const id = c?.id || null;
  if (id === lastPlayingId) return;
  lastPlayingId = id;
  document.querySelectorAll("#cutRows tr.playing").forEach((tr) => tr.classList.remove("playing"));
  if (id) document.querySelector(`#cutRows tr[data-id="${id}"]`)?.classList.add("playing");
}

// ------------------------------------------------------------ 書き出し

async function exportAs(fmtName) {
  if (!state.project) return;
  const status = $("#exportStatus");
  const params = new URLSearchParams();
  if (fmtName === "capcut") {
    params.set("media_path", $("#mediaPath").value.trim());
    params.set("captions", $("#draftCaptions").checked);
  }
  status.textContent = fmtName === "mp4" ? "MP4 を書き出し中…（数分かかることがあります）" : "書き出し中…";
  try {
    await flushSave();
    const res = await api(`/api/projects/${state.project.id}/export/${fmtName}?${params}`);
    const blob = await res.blob();
    const ext = { mp4: "mp4", srt: "srt", capcut: "zip", json: "json" }[fmtName];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${state.project.name}_autocut.${ext}`;
    a.click();
    URL.revokeObjectURL(a.href);
    status.textContent = "書き出しました";
  } catch (e) {
    status.textContent = `エラー: ${e.message}`;
  }
}

async function installDraft() {
  try {
    await flushSave();
    const params = new URLSearchParams({ captions: $("#draftCaptions").checked });
    const r = await (await api(`/api/projects/${state.project.id}/export/capcut-install?${params}`, { method: "POST" })).json();
    $("#exportStatus").textContent = `CapCut に追加しました: ${r.folder}（CapCut を再起動してください）`;
  } catch (e) {
    $("#exportStatus").textContent = `エラー: ${e.message}`;
  }
}

async function flushSave() {
  if (!state.saveTimer) return;
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  await sendJSON(`/api/projects/${state.project.id}/cuts`, "PUT", { cuts: cuts() });
}

// ------------------------------------------------------------ イベント

function updateOutputs() {
  $("#noiseOut").textContent = `${$("#noise_db").value} dB`;
  $("#minSilenceOut").textContent = `${(+$("#min_silence").value).toFixed(1)} 秒`;
  $("#paddingOut").textContent = `${(+$("#padding").value).toFixed(2)} 秒`;
  $("#confOut").textContent = `${Math.round($("#ai_min_confidence").value * 100)}%`;
}

function bindEvents() {
  const drop = $("#dropzone");
  $("#fileInput").onchange = (e) => e.target.files[0] && upload(e.target.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("drag"); };
  drop.ondragleave = () => drop.classList.remove("drag");
  drop.ondrop = (e) => {
    e.preventDefault();
    drop.classList.remove("drag");
    if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]);
  };

  document.querySelectorAll("#settingsPanel input[type=range]").forEach((el) => (el.oninput = updateOutputs));
  $("#use_ai").onchange = () => $("#aiOptions").classList.toggle("hidden", !$("#use_ai").checked);
  $("#analyzeBtn").onclick = analyze;

  canvas.onclick = (ev) => { video.currentTime = timeFromEvent(ev); };
  canvas.ondblclick = (ev) => {
    const c = cutAtTime(timeFromEvent(ev));
    if (c) toggleCut(c.id);
  };
  $("#zoom").oninput = drawTimeline;
  window.addEventListener("resize", drawTimeline);

  $("#markIn").onclick = () => { state.markIn = video.currentTime; drawTimeline(); };
  $("#markOut").onclick = () => { state.markOut = video.currentTime; drawTimeline(); };
  $("#addCut").onclick = addManualCut;

  document.querySelectorAll("[data-bulk]").forEach((b) => (b.onclick = () => bulk(b.dataset.bulk)));
  $("#categoryFilter").onchange = renderTable;
  document.querySelectorAll("[data-export]").forEach((b) => (b.onclick = () => exportAs(b.dataset.export)));
  $("#installDraft").onclick = installDraft;

  document.addEventListener("keydown", (e) => {
    if (!state.project || e.target.matches("input[type=text], textarea")) return;
    if (e.code === "Space") { e.preventDefault(); video.paused ? video.play() : video.pause(); }
    else if (e.key === "i") $("#markIn").click();
    else if (e.key === "o") $("#markOut").click();
    else if (e.key === "x") addManualCut();
    else if (e.key === "ArrowLeft") video.currentTime = Math.max(0, video.currentTime - (e.shiftKey ? 5 : 1));
    else if (e.key === "ArrowRight") video.currentTime = Math.min(duration(), video.currentTime + (e.shiftKey ? 5 : 1));
  });
}

bindEvents();
updateOutputs();
loadHealth();
loadProjects();
requestAnimationFrame(playbackLoop);
