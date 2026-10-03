"use strict";

/* ================================================================ helpers */

const $ = (id) => document.getElementById(id);
const MAX_SECONDS = 30;
const MIN_SECONDS = 1.5;
const MAX_BYTES = 3 * 1024 * 1024;
const AUDIO_EXT = ["webm", "ogg", "opus", "m4a", "mp4", "mp3", "mpeg", "mpga", "wav", "flac"];
const state = { products: [], shops: [], draft: null, status: null, pending: null, lastOrder: null, freshNote: null };

const pkr = (n) => "Rs " + Math.round(n || 0).toLocaleString("en-PK");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hasUrdu = (s) => /[؀-ۿ]/.test(s || "");
const fmtSec = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const show = (id, on = true) => $(id).classList.toggle("hidden", !on);
const ICON = {
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v4"/></svg>',
  text: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="6" width="20" height="12" rx="2"/><path d="M7 14h10"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
};

function timeAgo(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

async function api(path, options = {}) {
  let res;
  try { res = await fetch(path, { credentials: "same-origin", ...options }); }
  catch { throw new Error("Can't reach the server. Check your connection and try again."); }
  if (res.status === 401) { location.href = "/login"; throw new Error("Please sign in."); }
  const type = res.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    const detail = body && body.detail;
    throw new Error(typeof detail === "string" ? detail : `Something went wrong (${res.status}). Please try again.`);
  }
  return body;
}
const postJson = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

/* ================================================================ boot + header */

async function boot() {
  const user = await api("/api/me");
  $("user-name").textContent = user.name;
  $("avatar").textContent = user.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const h = new Date().getHours();
  $("greeting").textContent = `${h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"}, ${user.name.split(" ")[0]}`;
  [state.products, state.shops] = await Promise.all([api("/api/catalogue"), api("/api/shops")]);
  renderShopSelect();
  renderSamples(await api("/api/samples"));
  renderExamples();
  buildMeter();
  await Promise.all([refreshStatus(), refreshStats(), loadNotes()]);
}

$("logout").onclick = async () => { await postJson("/api/logout", {}).catch(() => {}); location.href = "/"; };

async function refreshStatus() {
  const pill = $("ai-status");
  try {
    state.status = await api("/api/status");
    const recent = Object.values(state.status.last || {}).filter((x) => Date.now() / 1000 - x.at < 120);
    if (!state.status.providers.length) { pill.textContent = "Offline mode"; pill.className = "pill off"; pill.title = "No AI key configured: the rule-based parser handles typed orders."; }
    else if (recent.length && recent.every((x) => !x.ok)) { pill.textContent = "AI busy · fallback on"; pill.className = "pill warn"; pill.title = "The AI provider is rate-limited; the offline parser is handling orders."; }
    else { pill.textContent = "AI online"; pill.className = "pill ok"; pill.title = `Open models via ${state.status.providers.join(", ")}${state.status.tts ? " · Urdu voice by ElevenLabs" : ""}`; }
  } catch { pill.textContent = "AI status unknown"; pill.className = "pill warn"; }
}

async function refreshStats() {
  const d = await api("/api/dashboard");
  $("st-orders").textContent = d.orders_today;
  $("st-value").textContent = pkr(d.value_today);
  $("st-out").textContent = pkr(d.outstanding);
  $("st-notes").textContent = d.voice_notes;
}

document.querySelectorAll(".app-tabs button").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".app-tabs button").forEach((t) => t.classList.toggle("active", t === tab));
    ["new", "insights", "orders", "khata", "catalogue"].forEach((name) => show(`tab-${name}`, name === tab.dataset.tab));
    ({ insights: loadInsights, orders: loadOrders, khata: () => loadShops(), catalogue: renderCatalogue }[tab.dataset.tab] || (() => {}))();
  };
});

/* ================================================================ input mode switcher */

let mode = "record";
document.querySelectorAll(".segmented button").forEach((btn) => {
  btn.onclick = () => {
    if (recorder && recorder.state === "recording") { toast("Stop the recording first."); return; }
    mode = btn.dataset.mode;
    document.querySelectorAll(".segmented button").forEach((b) => b.classList.toggle("active", b === btn));
    ["record", "upload", "type"].forEach((m) => show(`mode-${m}`, m === mode));
    clearPending();
    setCaptureError("");
  };
});

function setCaptureError(message) { $("capture-error").textContent = message; }

/* ================================================================ recording with validation */

let recorder = null, stream = null, chunks = [], audioCtx = null, analyser = null, rafId = null;
let recStart = 0, peak = 0, voicedFrames = 0, totalFrames = 0, tickId = null;
const BARS = 28;

function buildMeter() { $("meter").innerHTML = "<i></i>".repeat(BARS); }

function pickMime() {
  const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  return types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
}

$("mic").onclick = () => (recorder && recorder.state === "recording" ? stopRecording() : startRecording());

async function startRecording() {
  setCaptureError("");
  clearPending();
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setCaptureError("This browser can't record audio. Upload a voice note or type the order instead.");
    return;
  }
  $("rec-hint").textContent = "Waiting for microphone permission…";
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch (err) {
    resetRecorderUi();
    setCaptureError(err.name === "NotAllowedError"
      ? "Microphone access is blocked. Click the lock icon in the address bar, allow the microphone, then try again."
      : err.name === "NotFoundError" ? "No microphone was found. Connect one, or upload / type the order instead."
      : "The microphone couldn't be started. Close other apps using it and try again.");
    return;
  }

  // Live level meter + silence detection.
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 512;
  audioCtx.createMediaStreamSource(stream).connect(analyser);
  peak = 0; voicedFrames = 0; totalFrames = 0;
  const data = new Uint8Array(analyser.fftSize);
  const bars = $("meter").children;
  const draw = () => {
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const v of data) { const x = (v - 128) / 128; sum += x * x; }
    const rms = Math.sqrt(sum / data.length);
    peak = Math.max(peak, rms);
    totalFrames++;
    if (rms > 0.03) voicedFrames++;
    for (let i = 0; i < BARS; i++) {
      const h = Math.min(44, 6 + rms * 260 * (0.55 + 0.45 * Math.sin((i + totalFrames / 3) / 2.2) ** 2));
      bars[i].style.height = `${h}px`;
    }
    rafId = requestAnimationFrame(draw);
  };
  draw();

  chunks = [];
  const mimeType = pickMime();
  recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = onRecordingStopped;
  recorder.start(250);
  recStart = Date.now();

  $("mic").classList.add("recording");
  $("mic").innerHTML = ICON.stop;
  $("mic").setAttribute("aria-label", "Stop recording");
  $("meter").classList.add("live");
  $("rec-hint").textContent = "Listening… tap the button again when you've finished the order.";
  tickId = setInterval(() => {
    const s = (Date.now() - recStart) / 1000;
    $("rec-time").innerHTML = `${fmtSec(s)} <small>/ 0:30</small>`;
    $("rec-bar").style.width = `${Math.min(100, (s / MAX_SECONDS) * 100)}%`;
    if (s >= MAX_SECONDS) { toast("Stopped at the 30-second limit."); stopRecording(); }
  }, 200);
}

function stopRecording() {
  if (recorder && recorder.state === "recording") recorder.stop();
}

function teardownAudio() {
  clearInterval(tickId);
  cancelAnimationFrame(rafId);
  stream?.getTracks().forEach((t) => t.stop());
  audioCtx?.close().catch(() => {});
  stream = null; audioCtx = null;
}

function resetRecorderUi() {
  $("mic").classList.remove("recording");
  $("mic").innerHTML = ICON.mic;
  $("mic").setAttribute("aria-label", "Start recording");
  $("meter").classList.remove("live");
  [...$("meter").children].forEach((b) => (b.style.height = "6px"));
  $("rec-time").innerHTML = "0:00 <small>/ 0:30</small>";
  $("rec-bar").style.width = "0";
  $("rec-hint").innerHTML = 'Tap the mic and say the order, e.g. <span lang="ur" class="urdu">“دو کارٹن شان بریانی، پانچ ٹین ڈالڈا، ادھار لکھ دیں”</span>';
}

function onRecordingStopped() {
  const duration = (Date.now() - recStart) / 1000;
  const voicedRatio = totalFrames ? voicedFrames / totalFrames : 0;
  teardownAudio();
  resetRecorderUi();
  const type = recorder.mimeType || "audio/webm";
  const blob = new Blob(chunks, { type });

  if (duration < MIN_SECONDS) { setCaptureError("That was too short. Hold on and say the full order (at least a couple of seconds)."); return; }
  if (peak < 0.02 || voicedRatio < 0.04) { setCaptureError("We couldn't hear anything. Check the right microphone is selected and speak a little closer."); return; }
  if (blob.size > MAX_BYTES) { setCaptureError("The recording is too large. Please keep it under 30 seconds."); return; }

  const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
  setPending({ blob, name: `voice-note.${ext}`, duration, label: `Recorded ${fmtSec(duration)}` });
}

/* ================================================================ upload with validation */

const dz = $("dropzone");
$("file").onchange = (e) => { const f = e.target.files[0]; if (f) acceptFile(f); e.target.value = ""; };
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) acceptFile(f); });

function audioDuration(blob) {
  return new Promise((resolve) => {
    const a = new Audio();
    const url = URL.createObjectURL(blob);
    a.preload = "metadata";
    a.onloadedmetadata = () => { URL.revokeObjectURL(url); resolve(Number.isFinite(a.duration) ? a.duration : null); };
    a.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
    a.src = url;
  });
}

async function acceptFile(file) {
  setCaptureError("");
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  if (!AUDIO_EXT.includes(ext) && !file.type.startsWith("audio/")) { setCaptureError("That isn't an audio file. Choose a voice note (.opus, .ogg, .m4a, .mp3, .wav or .webm)."); return; }
  if (file.size < 2048) { setCaptureError("That file is empty or too short."); return; }
  if (file.size > MAX_BYTES) { setCaptureError(`That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is 3 MB (about 30 seconds).`); return; }
  const duration = await audioDuration(file);
  if (duration !== null && duration > MAX_SECONDS + 1) { setCaptureError(`That voice note is ${fmtSec(duration)} long. Please use one under 30 seconds.`); return; }
  if (duration !== null && duration < 1) { setCaptureError("That voice note is too short to contain an order."); return; }
  setPending({ blob: file, name: file.name, duration, label: `${file.name}${duration ? ` · ${fmtSec(duration)}` : ""}` });
}

/* ================================================================ pending audio preview */

function setPending(p) {
  clearPending();
  state.pending = { ...p, url: URL.createObjectURL(p.blob) };
  $("preview-audio").src = state.pending.url;
  $("preview-meta").textContent = `${p.label} · listen back, then process it.`;
  show("preview", true);
  if (mode === "record") show("rec-idle", false);
  if (mode === "upload") show("mode-upload", false);
}

function clearPending() {
  if (state.pending?.url && state.pending.url !== state.draftAudioUrl) URL.revokeObjectURL(state.pending.url);
  state.pending = null;
  $("preview-audio").removeAttribute("src");
  show("preview", false);
  show("rec-idle", true);
  if (mode === "upload") show("mode-upload", true);
}

$("discard").onclick = () => { clearPending(); setCaptureError(""); };

$("process-audio").onclick = () => {
  const p = state.pending;
  if (!p) return;
  const form = new FormData();
  form.append("file", p.blob, p.name.replace(/\.opus$/i, ".ogg"));
  if (p.duration) form.append("duration", String(p.duration.toFixed(2)));
  state.draftAudioUrl = p.url;
  runParse(() => api("/api/parse/audio", { method: "POST", body: form }), "audio");
};

/* ================================================================ typed orders */

const EXAMPLES = [
  "3 carton Pepsi, 2 carton Sprite, cash",
  "dedh carton Dalda oil aur 2 bori cheeni, udhaar likh do",
  "پانچ پیکٹ ٹپال دانےدار اور دو کارٹن ملک پیک",
  "4 carton Surf Excel, 1 carton Lifebuoy, khata mein",
];

function renderExamples() {
  $("examples").innerHTML = EXAMPLES.map((e, i) => `<button class="chip" data-i="${i}" dir="auto">${esc(e)}</button>`).join("");
  document.querySelectorAll("#examples .chip").forEach((c) => (c.onclick = () => { $("order-text").value = EXAMPLES[c.dataset.i]; updateCount(); }));
}
const updateCount = () => ($("char-count").textContent = $("order-text").value.length);
$("order-text").addEventListener("input", updateCount);

$("parse-text").onclick = () => {
  const text = $("order-text").value.trim();
  if (text.length < 5) { setCaptureError("Type the order first, e.g. “2 carton Pepsi, 5 tin Dalda”."); return; }
  if (!/[\p{L}]/u.test(text)) { setCaptureError("The order needs product names, not just numbers."); return; }
  setCaptureError("");
  state.draftAudioUrl = null;
  runParse(() => postJson("/api/parse/text", { text }), "text");
};

/* ================================================================ processing */

const AGENT_ICON = { listener: "🎧", router: "🧭", extractor: "📦", catalogue: "🗂️", verifier: "✅", credit: "💳" };
const LIVE_AGENTS = [
  ["listener", "Listener agent", "Whisper turns the voice note into text"],
  ["router", "Router + Extraction agents", "Decide what the shopkeeper wants and pull out the items, in parallel"],
  ["catalogue", "Catalogue agent", "Match products and price them from your list"],
  ["verifier", "Verifier agent", "A second model double-checks the order"],
  ["credit", "Credit agent", "Check the shop's khata against its limit"],
];
const STEPS = {
  audio: LIVE_AGENTS,
  text: LIVE_AGENTS.slice(1),
  sample: [["catalogue", "Opening the sample order", "Pre-processed by the agents earlier"]],
  note: [["catalogue", "Opening your voice note", "From your history"]],
};

async function runParse(call, kind, sampleShop = null) {
  setCaptureError("");
  show("review", false); show("done", false); show("intent-card", false);
  const steps = STEPS[kind];
  $("steps").className = "agent-live";
  $("steps").innerHTML = steps.map(([key, name, job]) => `<li><span class="trace-icon">${AGENT_ICON[key] || "•"}</span><span>${esc(name)}<small>${esc(job)}</small></span></li>`).join("");
  const items = [...$("steps").children];
  let i = 0;
  const advance = () => { items.forEach((li, j) => { li.classList.toggle("done", j < i); li.classList.toggle("active", j === i); }); };
  advance();
  const timer = setInterval(() => { if (i < steps.length - 1) { i++; advance(); } }, kind === "audio" ? 1100 : 1000);
  show("processing", true);
  $("processing").scrollIntoView({ behavior: "smooth", block: "center" });
  try {
    const draft = await call();
    clearInterval(timer);
    i = steps.length; advance();
    await new Promise((r) => setTimeout(r, 250));
    show("processing", false);
    if (kind === "audio" || kind === "text") {
      clearPending();
      if (kind === "text") { $("order-text").value = ""; updateCount(); }
      state.freshNote = draft.note_id;
      loadNotes();
      refreshStats();
    }
    renderDraft(draft, kind, sampleShop);
  } catch (err) {
    clearInterval(timer);
    show("processing", false);
    setCaptureError(err.message);
    $("capture").scrollIntoView({ behavior: "smooth", block: "start" });
  } finally {
    refreshStatus();
  }
}

/* ================================================================ review */

function modeBadge(d) {
  if (d.reopened) return ["Reopened from history", "pill plain"];
  if (d.mode === "cached") return ["Sample · AI-processed", "pill"];
  if (d.mode === "ai") {
    const model = (d.provider || "").split(":").pop();
    return [`AI · ${d.asr_provider ? "Whisper + " : ""}${model}`, "pill ok"];
  }
  return [d.ai_error ? "AI busy · offline parser used" : "Offline parser", "pill warn"];
}

/* ================================================================ agent trace */

const fmtMs = (ms) => (!ms ? "<1 ms" : ms < 100 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

function renderTrace(listId, totalId, steps, wallMs) {
  const label = { ok: "", warn: "check", fallback: "fallback", skipped: "skipped" };
  $(listId).innerHTML = (steps || []).map((s) => `
    <li class="trace-step ${esc(s.status)}">
      <span class="trace-icon">${AGENT_ICON[s.key] || "•"}</span>
      <div>
        <span class="t-name">${esc(s.name)} agent</span>${s.engine ? `<span class="t-engine">${esc(s.engine)}</span>` : ""}${label[s.status] ? `<span class="t-status">${label[s.status]}</span>` : ""}
        <div class="t-summary">${esc(s.summary)}</div>
        ${s.notes && s.notes.length ? `<ul class="t-notes">${s.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      </div>
      <span class="t-ms">${s.status === "skipped" ? "—" : fmtMs(s.ms)}</span>
    </li>`).join("");
  const ran = (steps || []).filter((s) => s.status !== "skipped").length;
  // Wall-clock time, not a sum: the Router and Extraction agents run in parallel.
  $(totalId).textContent = steps && steps.length ? `· ${ran} agent${ran === 1 ? "" : "s"} ran${wallMs ? ` · finished in ${(wallMs / 1000).toFixed(1)} s` : ""}` : "";
}

/* ================================================================ credit check (Credit agent, re-run when the shop changes) */

function creditCheck(shop, amount, kind = "order") {
  const after = kind === "order" ? shop.balance + amount : shop.balance - amount;
  const pct = shop.credit_limit ? Math.round((after / shop.credit_limit) * 100) : 0;
  return { after, pct, status: pct > 100 ? "over" : pct > 80 ? "warn" : "ok", limit: shop.credit_limit, balance: shop.balance };
}

function updateCreditAlert() {
  const el = $("credit-alert");
  const shop = state.shops.find((s) => s.id === Number($("shop").value));
  const by = Object.fromEntries(state.products.map((p) => [p.sku, p]));
  const total = (state.draft?.lines || []).reduce((t, l) => t + by[l.sku].price * l.quantity, 0);
  if (!shop || $("payment").value === "cash" || !total) { show("credit-alert", false); return; }
  const c = creditCheck(shop, total);
  if (c.status === "ok") { show("credit-alert", false); return; }
  el.className = `alert ${c.status === "over" ? "error" : "warn"}`;
  el.textContent = c.status === "over"
    ? `💳 Credit agent: this order takes ${shop.name} to ${pkr(c.after)}, over its ${pkr(c.limit)} khata limit (${c.pct}%). Ask for a payment first, or take this order as cash.`
    : `💳 Credit agent: ${shop.name} will owe ${pkr(c.after)}, ${c.pct}% of its ${pkr(c.limit)} khata limit.`;
  show("credit-alert", true);
}
["shop", "payment"].forEach((id) => $(id).addEventListener("change", updateCreditAlert));

function renderDraft(d, kind, sampleShop) {
  if (d.intent && d.intent !== "order") { renderIntent(d, kind); return; }
  state.draft = {
    transcript: d.transcript,
    note_id: d.note_id || null,
    source: kind === "sample" ? "sample" : (d.asr_provider || kind === "audio" || (kind === "note" && d.asr_provider)) ? "voice" : "text",
    lines: (d.lines || []).map((l) => ({ ...l })),
  };
  const t = d.timing;
  const tb = $("timing-badge");
  if (t && t.total_ms && !d.reopened) {
    tb.textContent = `Processed in ${(t.total_ms / 1000).toFixed(1)} s`;
    tb.title = t.asr_ms != null
      ? `Speech-to-text ${(t.asr_ms / 1000).toFixed(1)} s · extraction ${(t.extract_ms / 1000).toFixed(1)} s`
      : `Extraction ${(t.extract_ms / 1000).toFixed(1)} s`;
    show("timing-badge", true);
  } else {
    show("timing-badge", false);
  }
  const [label, cls] = modeBadge(d);
  $("mode-badge").textContent = label;
  $("mode-badge").className = cls;
  $("transcript").textContent = d.transcript;
  $("transcript").className = hasUrdu(d.transcript) ? "urdu" : "";

  const audio = $("review-audio");
  const audioUrl = kind === "audio" ? state.draftAudioUrl : kind === "note" && d.has_audio ? `/api/notes/${d.note_id}/audio` : null;
  if (audioUrl) { audio.src = audioUrl; show("review-audio", true); } else { audio.removeAttribute("src"); show("review-audio", false); }

  const um = d.unmatched || [];
  show("unmatched", um.length > 0);
  $("unmatched").textContent = um.length ? `Not in your catalogue: ${um.join(", ")}. Add the right product below if needed.` : "";
  $("payment").value = ["credit", "cash"].includes(d.payment) ? d.payment : "unknown";

  let shopId = d.shop_id;
  if (!shopId && sampleShop) shopId = state.shops.find((s) => s.name === sampleShop)?.id;
  $("shop").value = shopId || "";
  $("review-error").textContent = "";

  renderLines();
  renderTrace("review-trace", "review-trace-total", d.agents, d.timing && d.timing.total_ms);
  show("review-trace-wrap", Boolean(d.agents && d.agents.length));
  show("review", true);
  $("review").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ================================================================ payment reports, balance questions, other */

function shopOptions(selected) {
  return `<option value="">Choose shop…</option>` + state.shops.map((s) => `<option value="${s.id}"${s.id === selected ? " selected" : ""}>${esc(s.name)}</option>`).join("");
}

function meter(check) {
  const pct = Math.min(100, Math.max(0, check.pct));
  return `<div class="meter-bar ${check.status === "ok" ? "" : check.status}" role="img" aria-label="${check.pct}% of credit limit used"><div style="width:${pct}%"></div></div>
    <span class="muted" style="font-size:13px">${check.pct}% of the ${pkr(check.limit)} khata limit</span>`;
}

function renderIntent(d, kind) {
  state.draft = { transcript: d.transcript, note_id: d.note_id || null };
  const titles = { payment: "Payment reported", balance: "Balance question", other: "This doesn't look like an order" };
  const subs = {
    payment: "The Router agent heard the shopkeeper say they've paid. Check the amount and record it in their khata.",
    balance: "The Router agent heard the shopkeeper asking how much they owe. Prepare an Urdu reply with their balance.",
    other: "The Router agent couldn't find an order, payment or balance question in this message.",
  };
  $("intent-title").textContent = titles[d.intent] || "Message";
  $("intent-sub").textContent = subs[d.intent] || "";
  const [label, cls] = modeBadge(d);
  $("intent-badge").textContent = label;
  $("intent-badge").className = cls;
  const t = d.timing;
  $("intent-timing").textContent = t && t.total_ms ? `Processed in ${(t.total_ms / 1000).toFixed(1)} s` : "";
  show("intent-timing", Boolean(t && t.total_ms && !d.reopened));
  $("intent-transcript").textContent = d.transcript;
  $("intent-transcript").className = hasUrdu(d.transcript) ? "urdu" : "";
  const audioUrl = kind === "audio" ? state.draftAudioUrl : kind === "note" && d.has_audio ? `/api/notes/${d.note_id}/audio` : null;
  if (audioUrl) { $("intent-audio").src = audioUrl; show("intent-audio", true); } else { $("intent-audio").removeAttribute("src"); show("intent-audio", false); }
  $("intent-error").textContent = "";
  renderTrace("intent-trace", "intent-trace-total", d.agents, d.timing && d.timing.total_ms);

  const body = $("intent-body");
  const asOrder = `<button class="btn" id="as-order">Treat it as an order instead</button>`;
  if (d.intent === "payment") {
    body.innerHTML = `
      <div class="intent-grid">
        <label class="field"><span>Shop</span><select id="pi-shop">${shopOptions(d.shop_id)}</select></label>
        <label class="field"><span>Amount received (Rs)</span><input id="pi-amount" type="number" min="1" step="1" value="${d.amount || ""}" /></label>
      </div>
      <div id="pi-info"></div>
      <div class="intent-actions"><button class="btn primary" id="pi-record">Record payment in khata</button>${asOrder}</div>`;
    const info = () => {
      const shop = state.shops.find((s) => s.id === Number($("pi-shop").value));
      const amount = Number($("pi-amount").value) || 0;
      if (!shop) { $("pi-info").innerHTML = `<span class="muted">Choose the shop to see its khata.</span>`; return; }
      const c = creditCheck(shop, amount, "payment");
      $("pi-info").innerHTML = `<div class="muted" style="font-size:14px">💳 ${esc(shop.name)} owes <strong>${pkr(shop.balance)}</strong>${amount ? ` → <strong>${pkr(c.after)}</strong> after this payment` : ""}</div>${meter(c)}`;
    };
    $("pi-shop").onchange = info; $("pi-amount").oninput = info; info();
    $("pi-record").onclick = async () => {
      const shopId = Number($("pi-shop").value), amount = Math.round(Number($("pi-amount").value));
      if (!shopId) { $("intent-error").textContent = "Choose which shop paid."; return; }
      if (!amount || amount < 1) { $("intent-error").textContent = "Enter the amount received."; return; }
      $("pi-record").disabled = true;
      try {
        const res = await postJson(`/api/shops/${shopId}/payments`, { amount, note: "Payment reported by voice note" });
        state.shops = await api("/api/shops");
        showReplyCard({ title: `${pkr(amount)} received from ${res.shop}`, sub: `Recorded in khata · balance now ${pkr(res.balance)}`, ...res });
        refreshStats();
      } catch (e) { $("intent-error").textContent = e.message; $("pi-record").disabled = false; }
    };
  } else if (d.intent === "balance") {
    body.innerHTML = `
      <label class="field" style="max-width:360px"><span>Shop</span><select id="bi-shop">${shopOptions(d.shop_id)}</select></label>
      <div id="bi-info"></div>
      <div class="intent-actions"><button class="btn primary" id="bi-reply">Prepare Urdu reply</button>${asOrder}</div>`;
    const info = () => {
      const shop = state.shops.find((s) => s.id === Number($("bi-shop").value));
      if (!shop) { $("bi-info").innerHTML = `<span class="muted">Choose the shop to see what it owes.</span>`; return; }
      const c = creditCheck(shop, 0, "balance");
      $("bi-info").innerHTML = `<div class="balance-figure">${pkr(shop.balance)}</div><span class="muted">owed by ${esc(shop.name)}</span>${meter(c)}`;
    };
    $("bi-shop").onchange = info; info();
    $("bi-reply").onclick = async () => {
      const shopId = Number($("bi-shop").value);
      if (!shopId) { $("intent-error").textContent = "Choose the shop first."; return; }
      try {
        const res = await postJson("/api/replies/balance", { shop_id: shopId });
        showReplyCard({ title: `Balance reply for ${res.shop}`, sub: `Owes ${pkr(res.balance)} of a ${pkr(res.limit)} limit`, ...res });
      } catch (e) { $("intent-error").textContent = e.message; }
    };
  } else {
    body.innerHTML = `<div class="intent-actions">${asOrder}</div>`;
  }
  $("as-order").onclick = () => runParse(() => postJson("/api/parse/text", { text: d.transcript, intent: "order" }), "text");
  show("intent-card", true);
  $("intent-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

/** The confirmation card, reused for payment receipts and balance replies. */
function showReplyCard(res) {
  show("intent-card", false);
  state.lastOrder = { speech_token: res.speech_token };
  $("done-title").textContent = res.title;
  $("done-sub").textContent = res.sub;
  $("reply").textContent = res.reply;
  const phone = (res.phone || "").replace(/\D/g, "").replace(/^0/, "92");
  $("wa-link").href = `https://wa.me/${phone}?text=${encodeURIComponent(res.reply)}`;
  show("pay-pending", false);
  show("receipt-wrap", false);
  $("tts-audio").removeAttribute("src");
  show("tts-audio", false);
  $("tts-hint").textContent = state.status?.tts ? "" : "Add ELEVENLABS_API_KEY to hear this reply in an Urdu voice.";
  show("done", true);
  $("done").scrollIntoView({ behavior: "smooth", block: "start" });
}

const productOptions = (selected) => state.products.map((p) => `<option value="${esc(p.sku)}"${p.sku === selected ? " selected" : ""}>${esc(p.name)}</option>`).join("");

function renderLines() {
  const by = Object.fromEntries(state.products.map((p) => [p.sku, p]));
  const lines = state.draft.lines;
  show("no-items", lines.length === 0);
  $("lines").innerHTML = lines.map((l, i) => {
    const p = by[l.sku];
    const conf = l.confidence != null ? Math.round(l.confidence * 100) : null;
    const alts = (l.alternatives || []).map((a) => `<button class="alt" data-i="${i}" data-sku="${esc(a.sku)}">${esc(a.name)}</button>`).join("");
    return `<tr class="${l.needs_review ? "review-row" : ""}">
      <td><select class="sku" data-i="${i}" aria-label="Product">${productOptions(l.sku)}</select>
        ${l.spoken ? `<div class="heard">Heard: <span dir="auto">“${esc(l.spoken)}”</span>${conf !== null ? `<span class="conf ${conf < 75 ? "low" : ""}">${conf}%</span>` : ""}</div>` : ""}
        ${alts ? `<div class="alts">Did you mean ${alts}</div>` : ""}
        ${l.review_reason ? `<div class="review-reason">✅ ${esc(l.review_reason)}</div>` : ""}</td>
      <td><input type="number" class="qty" data-i="${i}" min="0.5" max="10000" step="0.5" value="${l.quantity}" aria-label="Quantity" /></td>
      <td>${esc(p.unit)}</td>
      <td>${pkr(p.price)}</td>
      <td><strong>${pkr(p.price * l.quantity)}</strong></td>
      <td><button class="icon-btn rm" data-i="${i}" aria-label="Remove ${esc(p.name)}">${ICON.trash}</button></td>
    </tr>`;
  }).join("");
  $("draft-total").textContent = pkr(lines.reduce((s, l) => s + by[l.sku].price * l.quantity, 0));
  updateCreditAlert();

  const resolve = (l) => { l.needs_review = false; l.alternatives = []; l.review_reason = null; };
  document.querySelectorAll("#lines .sku").forEach((el) => (el.onchange = () => { const l = lines[el.dataset.i]; l.sku = el.value; resolve(l); renderLines(); }));
  document.querySelectorAll("#lines .qty").forEach((el) => (el.onchange = () => {
    const v = Number(el.value);
    lines[el.dataset.i].quantity = Number.isFinite(v) && v > 0 ? Math.min(v, 10000) : 1;
    renderLines();
  }));
  document.querySelectorAll("#lines .rm").forEach((el) => (el.onclick = () => { lines.splice(el.dataset.i, 1); renderLines(); }));
  document.querySelectorAll("#lines .alt").forEach((el) => (el.onclick = () => { const l = lines[el.dataset.i]; l.sku = el.dataset.sku; resolve(l); renderLines(); }));
}

$("add-line").onclick = () => {
  state.draft.lines.push({ sku: state.products[0].sku, quantity: 1, spoken: "", alternatives: [] });
  renderLines();
  const selects = document.querySelectorAll("#lines .sku");
  selects[selects.length - 1]?.focus();
};

function renderShopSelect() {
  $("shop").innerHTML = `<option value="">Choose shop…</option>` + state.shops.map((s) => `<option value="${s.id}">${esc(s.name)} — ${esc(s.area)}</option>`).join("");
}

$("confirm").onclick = async () => {
  const err = $("review-error");
  err.textContent = "";
  const shopId = Number($("shop").value);
  if (!shopId) { err.textContent = "Choose which shop this order is for."; $("shop").focus(); return; }
  if (!state.draft.lines.length) { err.textContent = "Add at least one item before confirming."; return; }
  const uncertain = state.draft.lines.filter((l) => l.needs_review).length;
  if (uncertain && !confirm(`${uncertain} item${uncertain > 1 ? "s are" : " is"} still highlighted as uncertain. Confirm the order anyway?`)) return;

  const btn = $("confirm");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Confirming…';
  try {
    const res = await postJson("/api/orders", {
      shop_id: shopId,
      payment: $("payment").value,
      transcript: state.draft.transcript,
      source: state.draft.source,
      note_id: state.draft.note_id,
      lines: state.draft.lines.map((l) => ({ sku: l.sku, quantity: l.quantity, spoken: l.spoken || "" })),
    });
    state.lastOrder = res;
    showDone(res);
    state.shops = await api("/api/shops");
    refreshStats();
    loadNotes();
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Confirm order";
  }
};

/* ================================================================ done + Urdu voice */

const PAY_LABEL = { credit: "on khata", cash: "cash on delivery", unknown: "payment method pending" };
const RECEIPT_PAY = { credit: "Khata (credit)", cash: "Cash on delivery", unknown: "Pending: ask the shop" };

function pktTime(iso) {
  const d = new Date(new Date(iso).getTime() + 5 * 3600 * 1000);
  const h = d.getUTCHours() % 12 || 12;
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${h}:${String(d.getUTCMinutes()).padStart(2, "0")} ${d.getUTCHours() < 12 ? "AM" : "PM"} PKT`;
}

function renderReceipt(o) {
  if (!o || !o.lines) { show("receipt-wrap", false); return; }
  const qty = (q) => (Number.isInteger(Number(q)) ? Number(q) : Number(q).toString());
  const units = o.lines.reduce((t, l) => t + Number(l.quantity), 0);
  const due = o.payment === "credit"
    ? `<div><span>Added to khata</span><span>${pkr(o.total)}</span></div><div class="due"><span>Khata balance after this order</span><span>${pkr(o.balance)}</span></div>`
    : o.payment === "cash"
      ? `<div class="due"><span>To collect on delivery</span><span>${pkr(o.total)}</span></div>`
      : `<div class="due"><span>Payment method</span><span>Pending</span></div>`;
  $("receipt").innerHTML = `
    <div class="rc-band">
      <div><strong>${esc($("user-name").textContent)}</strong><small>Order desk powered by Awaz Order</small></div>
      <div class="rc-no"><strong>ORDER RECEIPT</strong><small>${esc(o.receipt_no || "")}</small></div>
    </div>
    <div class="rc-meta">
      <div><span class="lbl">Bill to</span><b>${esc(o.shop)}</b><br><span class="muted">${esc(o.area || "")}<br>${esc(o.phone || "")}</span></div>
      <div class="right"><span class="lbl">Details</span>${o.created_at ? `Date: ${esc(pktTime(o.created_at))}<br>` : ""}<span class="muted">Payment: ${esc(RECEIPT_PAY[o.payment] || o.payment)}</span></div>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Item</th><th class="num">Qty</th><th>Unit</th><th class="num">Rate</th><th class="num">Amount</th></tr></thead>
      <tbody>${o.lines.map((l, i) => `<tr><td>${i + 1}</td><td>${esc(l.name)}</td><td class="num">${qty(l.quantity)}</td><td>${esc(l.unit)}</td><td class="num">${Math.round(l.price).toLocaleString("en-PK")}</td><td class="num"><strong>${Math.round(l.line_total).toLocaleString("en-PK")}</strong></td></tr>`).join("")}</tbody>
    </table></div>
    <div class="rc-totals">
      <div class="muted"><span>${o.lines.length} line(s), ${qty(units)} unit(s)</span><span></span></div>
      <div class="rc-grand"><span>TOTAL</span><span>${pkr(o.total)}</span></div>
      ${due}
    </div>
    <div class="rc-foot">Thank you for your order. Prices are demo values.</div>`;
  show("receipt-wrap", true);
}

async function downloadReceipt(format) {
  const o = state.lastOrder;
  if (!o || !o.order_token) return;
  const btn = $(format === "pdf" ? "rc-pdf" : "rc-csv");
  btn.disabled = true;
  try {
    const res = await fetch("/api/receipt", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: o.order_token, format }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || "Couldn't create the receipt. Please try again.");
    }
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `receipt-${o.receipt_no}.${format}` });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    toast(`Receipt ${o.receipt_no} downloaded`, "success");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
  }
}
$("rc-pdf").onclick = () => downloadReceipt("pdf");
$("rc-csv").onclick = () => downloadReceipt("csv");
$("rc-print").onclick = () => window.print();

function renderDoneReply(res) {
  $("done-title").textContent = `Order #${res.id} confirmed`;
  $("done-sub").textContent = `${res.shop} · ${pkr(res.total)} · ${PAY_LABEL[res.payment] || ""}${res.payment === "credit" ? ` · khata balance ${pkr(res.balance)}` : ""}`;
  $("reply").textContent = res.reply;
  const phone = (res.phone || "").replace(/\D/g, "").replace(/^0/, "92");
  $("wa-link").href = `https://wa.me/${phone}?text=${encodeURIComponent(res.reply)}`;
  show("pay-pending", res.payment === "unknown");
  renderReceipt(res);
}

document.querySelectorAll("#pay-pending [data-pay]").forEach((btn) => (btn.onclick = async () => {
  const order = state.lastOrder;
  if (!order) return;
  const buttons = document.querySelectorAll("#pay-pending [data-pay]");
  buttons.forEach((b) => (b.disabled = true));
  try {
    const res = await postJson("/api/orders/payment", { payment: btn.dataset.pay, token: order.order_token });
    state.lastOrder = { ...order, ...res };
    renderDoneReply(state.lastOrder);
    $("tts-audio").removeAttribute("src");
    show("tts-audio", false);
    toast(btn.dataset.pay === "credit" ? "Recorded on khata. Send the updated reply." : "Recorded as cash on delivery. Send the updated reply.", "success");
    refreshStats();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}));

function showDone(res) {
  show("review", false);
  renderDoneReply(res);
  $("tts-audio").removeAttribute("src");
  show("tts-audio", false);
  $("tts-hint").textContent = state.status?.tts ? "" : urduBrowserVoice()
    ? "Using your browser's Urdu voice. Add an ElevenLabs key for a natural voice."
    : "Add ELEVENLABS_API_KEY to the server's .env to hear this reply in a natural Urdu voice.";
  show("done", true);
  $("done").scrollIntoView({ behavior: "smooth", block: "start" });
}

function urduBrowserVoice() {
  return (window.speechSynthesis?.getVoices() || []).find((v) => v.lang.toLowerCase().startsWith("ur"));
}

async function playOrderVoice(order, button, audioEl) {
  if (state.status?.tts) {
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> Generating Urdu voice…';
    try {
      // The signed token carries the exact text, so any server instance can voice it.
      const res = await fetch("/api/speech", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: order.speech_token }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "The voice service is unavailable right now.");
      }
      const url = URL.createObjectURL(await res.blob());
      audioEl.src = audioEl.dataset.url = url;
      audioEl.classList.remove("hidden");
      await audioEl.play().catch(() => {});
    } catch (e) {
      toast(e.message, "error");
    } finally {
      button.disabled = false;
      button.innerHTML = original;
    }
    return;
  }
  const voice = urduBrowserVoice();
  if (voice) {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance($("reply").textContent);
    u.voice = voice; u.lang = voice.lang;
    speechSynthesis.speak(u);
    return;
  }
  toast("Urdu voice isn't set up yet: add ELEVENLABS_API_KEY to the server's .env.", "error");
}

$("listen").onclick = () => state.lastOrder && playOrderVoice(state.lastOrder, $("listen"), $("tts-audio"));

$("copy-reply").onclick = async () => {
  try { await navigator.clipboard.writeText($("reply").textContent); toast("Reply copied to clipboard", "success"); }
  catch { toast("Couldn't copy automatically. Select the text and copy it.", "error"); }
};

$("new-order").onclick = () => {
  show("done", false);
  clearPending();
  window.scrollTo({ top: 0, behavior: "smooth" });
};

/* ================================================================ notes history */

async function loadNotes() {
  const notes = await api("/api/notes");
  if (!notes.length) {
    $("notes").innerHTML = `<div class="empty">No voice notes yet.<br>Record one on the left — it will appear here.</div>`;
    return;
  }
  $("notes").innerHTML = notes.map((n) => `
    <article class="note ${n.id === state.freshNote ? "fresh" : ""}" data-id="${n.id}">
      <div class="note-top">
        <span class="note-kind">${n.kind === "voice" ? ICON.mic : ICON.text}${n.kind === "voice" ? `Voice${n.duration ? ` · ${fmtSec(n.duration)}` : ""}` : "Typed"}</span>
        <span>${timeAgo(n.created_at)}</span>
      </div>
      <p class="note-text ${hasUrdu(n.transcript) ? "urdu" : ""}" dir="auto">${esc(n.transcript)}</p>
      <div class="note-top">
        <span>${n.items} item${n.items === 1 ? "" : "s"} · ${pkr(n.total)}</span>
        ${n.order_id ? `<span class="pill ok">Order #${n.order_id}</span>` : `<span class="pill plain">Draft</span>`}
      </div>
      <div class="note-actions">
        ${n.has_audio ? `<button class="btn sm play" data-id="${n.id}">▶ Play</button>` : ""}
        <button class="btn sm open" data-id="${n.id}">${n.order_id ? "Reorder" : "Open"}</button>
        <button class="icon-btn del" data-id="${n.id}" aria-label="Delete note">${ICON.trash}</button>
      </div>
    </article>`).join("");

  document.querySelectorAll("#notes .play").forEach((b) => (b.onclick = () => {
    const actions = b.parentElement;
    let audio = actions.querySelector("audio");
    if (!audio) {
      audio = document.createElement("audio");
      audio.controls = true;
      audio.src = `/api/notes/${b.dataset.id}/audio`;
      audio.onerror = () => toast("This recording is no longer stored on the demo server.", "error");
      actions.prepend(audio);
      b.remove();
      audio.play().catch(() => {});
    }
  }));
  document.querySelectorAll("#notes .open").forEach((b) => (b.onclick = async () => {
    const meta = notes.find((n) => n.id === Number(b.dataset.id));
    runParse(async () => ({ ...(await api(`/api/notes/${b.dataset.id}`)), has_audio: meta?.has_audio }), "note");
  }));
  document.querySelectorAll("#notes .del").forEach((b) => (b.onclick = async () => {
    if (!confirm("Delete this voice note from your history?")) return;
    await api(`/api/notes/${b.dataset.id}`, { method: "DELETE" });
    toast("Voice note deleted");
    loadNotes(); refreshStats();
  }));
}

/* ================================================================ samples */

function renderSamples(samples) {
  $("samples").innerHTML = samples.map((s) => `
    <button class="sample" data-id="${esc(s.id)}" data-shop="${esc(s.shop)}">
      <strong>${esc(s.title)}</strong><span dir="auto">${esc(s.transcript)}</span>
    </button>`).join("");
  document.querySelectorAll(".sample").forEach((el) => (el.onclick = () => {
    state.draftAudioUrl = null;
    runParse(() => postJson(`/api/samples/${el.dataset.id}/parse`, {}), "sample", el.dataset.shop);
  }));
}

/* ================================================================ orders, khata, catalogue */

async function loadOrders() {
  const orders = await api("/api/orders");
  if (!orders.length) { $("orders").innerHTML = `<div class="empty">No orders yet. Confirm one from the New order tab.</div>`; return; }
  $("orders").innerHTML = `<table><thead><tr><th>#</th><th>Shop</th><th>Items</th><th>Payment</th><th>Total</th><th>Source</th><th>Date</th><th>Receipt</th></tr></thead><tbody>${
    orders.map((o) => `<tr>
      <td><strong>${o.id}</strong></td><td>${esc(o.shop)}</td>
      <td>${o.lines.map((l) => `${l.quantity} × ${esc(l.name)}`).join("<br>")}</td>
      <td>${o.payment === "credit" ? '<span class="pill">Khata</span>' : o.payment === "cash" ? '<span class="pill ok">Cash</span>'
        : `<div class="pay-cell"><span class="pill warn">Pending</span><button class="btn sm set-pay" data-id="${o.id}" data-pay="credit">Khata</button><button class="btn sm set-pay" data-id="${o.id}" data-pay="cash">Cash</button></div>`}</td>
      <td><strong>${pkr(o.total)}</strong></td><td>${esc(o.source)}</td><td class="muted">${timeAgo(o.created_at)}</td>
      <td><div class="pay-cell"><a class="btn sm" href="/api/orders/${o.id}/receipt?format=pdf" download>PDF</a><a class="btn sm" href="/api/orders/${o.id}/receipt?format=csv" download>CSV</a></div></td>
    </tr>`).join("")}</tbody></table>`;
  document.querySelectorAll("#orders .set-pay").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try {
      await postJson(`/api/orders/${b.dataset.id}/payment`, { payment: b.dataset.pay });
      toast(`Order #${b.dataset.id} recorded as ${b.dataset.pay === "credit" ? "khata (credit)" : "cash"}`, "success");
      loadOrders();
      refreshStats();
    } catch (e) {
      toast(e.message, "error");
      b.disabled = false;
    }
  }));
}

async function loadShops(selectId) {
  state.shops = await api("/api/shops");
  renderShopSelect();
  $("shops").innerHTML = state.shops.map((s) => `
    <button class="shop-row" data-id="${s.id}">
      <span><strong>${esc(s.name)}</strong><small>${esc(s.area)} · ${esc(s.phone)}</small></span>
      <span class="owed ${s.balance <= 0 ? "zero" : ""}">${pkr(s.balance)}</span>
    </button>`).join("");
  document.querySelectorAll(".shop-row").forEach((el) => (el.onclick = () => openLedger(Number(el.dataset.id))));
  if (selectId) openLedger(selectId);
}

async function openLedger(shopId) {
  document.querySelectorAll(".shop-row").forEach((el) => el.classList.toggle("active", Number(el.dataset.id) === shopId));
  const shop = state.shops.find((s) => s.id === shopId);
  const entries = await api(`/api/shops/${shopId}/ledger`);
  $("ledger-title").textContent = shop.name;
  $("ledger-sub").textContent = `${pkr(shop.balance)} currently owed`;
  const kind = { opening: "Opening balance", credit_order: "Order on khata", payment: "Payment received" };
  $("ledger").innerHTML = `${entries.length ? `<div class="table-wrap"><table><thead><tr><th>Date</th><th>Entry</th><th style="text-align:right">Amount</th></tr></thead><tbody>${
    entries.map((e) => `<tr><td class="muted">${esc(e.created_at.slice(0, 10))}</td><td>${esc(kind[e.kind] || e.kind)}<br><small class="muted">${esc(e.note)}</small></td>
      <td style="text-align:right" class="${e.amount < 0 ? "amount-neg" : "amount-pos"}">${e.amount < 0 ? "−" : "+"}${pkr(Math.abs(e.amount))}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">No entries yet.</div>`}
    <form class="pay-form" id="pay-form" novalidate>
      <input type="number" id="pay-amount" min="1" step="1" placeholder="Payment received (Rs)" aria-label="Payment amount" />
      <button class="btn primary">Record payment</button>
    </form>`;
  $("pay-form").onsubmit = async (e) => {
    e.preventDefault();
    const amount = Math.round(Number($("pay-amount").value));
    if (!amount || amount < 1) { toast("Enter the amount received.", "error"); return; }
    if (amount > shop.balance && shop.balance > 0 && !confirm(`That's more than the ${pkr(shop.balance)} owed. Record it anyway?`)) return;
    try {
      await postJson(`/api/shops/${shopId}/payments`, { amount });
      toast(`Payment of ${pkr(amount)} recorded`, "success");
      await loadShops(shopId);
      refreshStats();
    } catch (err) { toast(err.message, "error"); }
  };
}

function renderCatalogue() {
  const q = $("cat-search").value.trim().toLowerCase();
  const items = state.products.filter((p) => !q || p.name.toLowerCase().includes(q) || p.aliases.some((a) => a.toLowerCase().includes(q)));
  $("catalogue").innerHTML = items.length ? items.map((p) => `
    <div class="cat-item"><strong>${esc(p.name)}</strong>
      <span class="price">${pkr(p.price)} <small>/ ${esc(p.unit)}</small></span>
      <small dir="auto">${esc(p.aliases.join(" · "))}</small></div>`).join("") : `<div class="empty">No products match “${esc(q)}”.</div>`;
}
$("cat-search").addEventListener("input", renderCatalogue);

/* ================================================================ go */

if (window.speechSynthesis) speechSynthesis.onvoiceschanged = () => {};
/* ================================================================ insights */

const insights = { days: 30, data: null, view: {} };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const seriesColor = (n) => getComputedStyle(document.documentElement).getPropertyValue(`--series-${n}`).trim();

function dayLabel(iso, long) {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return long ? `${DAYS[date.getUTCDay()]}, ${d} ${MONTHS[m - 1]}` : `${d} ${MONTHS[m - 1]}`;
}

/** Pakistani compact amounts: 43.3K, 4.36 lakh, 1.34 crore. */
function compactRs(n, withRs = true) {
  const a = Math.abs(n);
  const s = a >= 1e7 ? `${+(n / 1e7).toFixed(2)} Cr` : a >= 1e5 ? `${+(n / 1e5).toFixed(2)} L` : a >= 1e3 ? `${+(n / 1e3).toFixed(1)}K` : `${Math.round(n)}`;
  return withRs ? `Rs ${s}` : s;
}
const hourLabel = (h) => `${h % 12 || 12} ${h < 12 ? "am" : "pm"}`;
const RS = { axis: (v) => compactRs(v, false), short: (v) => compactRs(v), full: (v) => pkr(v), unit: "order value" };
const COUNT = (noun) => ({ axis: (v) => `${v}`, short: (v) => `${v}`, full: (v) => `${v} ${noun}${v === 1 ? "" : "s"}`, unit: "" });

document.querySelectorAll("#range button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll("#range button").forEach((x) => x.classList.toggle("active", x === b));
  insights.days = Number(b.dataset.days);
  loadInsights();
}));

document.querySelectorAll(".chart-card .view-toggle").forEach((btn) => (btn.onclick = () => {
  const key = btn.closest(".chart-card").dataset.chart;
  insights.view[key] = insights.view[key] === "table" ? "chart" : "table";
  btn.textContent = insights.view[key] === "table" ? "Chart" : "Table";
  renderCharts();
}));

async function loadInsights() {
  // Refetch keeps the frame: hold the previous render, dimmed, until new data lands.
  $("chart-grid").classList.add("loading");
  $("kpis").classList.add("loading");
  try {
    insights.data = await api(`/api/analytics?days=${insights.days}`);
    renderKpis();
    renderCharts();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    $("chart-grid").classList.remove("loading");
    $("kpis").classList.remove("loading");
  }
}

function delta(cur, prev, complete) {
  if (!complete || !prev) return "";
  const pct = Math.round(((cur - prev) / prev) * 100);
  const up = pct >= 0;
  return `<span class="delta ${up ? "up" : "down"}">${up ? "▲" : "▼"} ${Math.abs(pct)}%</span> <span>vs previous ${insights.days} days</span>`;
}

function renderKpis() {
  const a = insights.data, k = a.kpis, p = a.previous;
  show("sim-note", a.simulated);
  const sec = (ms) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)} s`);
  const tiles = [
    ["Order value", compactRs(k.revenue), delta(k.revenue, p.revenue, p.complete) || `${insights.days} days · ${pkr(k.revenue)}`],
    ["Orders", k.orders.toLocaleString("en-PK"), delta(k.orders, p.orders, p.complete) || `${k.voice_share}% came in as voice notes`],
    ["Average order", compactRs(k.aov), `${k.credit_share}% on khata (credit)`],
    ["Voice note → draft", sec(k.median_ms), k.p90_ms ? `median · 90% under ${sec(k.p90_ms)} · typed ${sec(k.median_text_ms)}` : "no voice orders in this period"],
    ["Lines needing review", `${k.review_rate}%`, `AI unsure, flagged for a human · offline fallback ${k.fallback_rate}%`],
  ];
  $("kpis").innerHTML = tiles.map(([label, value, sub]) => `
    <div class="kpi"><span class="k-label">${esc(label)}</span><span class="k-value">${esc(value)}</span><span class="k-sub">${sub}</span></div>`).join("");
}

function renderCharts() {
  const a = insights.data;
  if (!a || $("tab-insights").classList.contains("hidden")) return;
  const c1 = seriesColor(1), c2 = seriesColor(2), c3 = seriesColor(3);
  const channels = [
    { key: "voice", label: "Voice notes", color: c1 },
    { key: "text", label: "Typed", color: c2 },
    { key: "sample", label: "Samples", color: c3 },
  ];
  $("channel-legend").innerHTML = channels.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`).join("");
  const khata = a.khata.filter((s) => s.balance > 0);

  const charts = {
    value: {
      chart: (h) => Charts.area(h, a.daily, { value: (d) => d.value, label: (d, long) => dayLabel(d.date, long), format: RS, color: c1, ariaLabel: `Daily order value over the last ${a.days} days` }),
      table: () => [["Day", "Orders", "Order value"], a.daily.map((d) => [dayLabel(d.date, true), d.orders, pkr(d.value)])],
    },
    channel: {
      chart: (h) => Charts.columns(h, a.daily, { series: channels, label: (d, long) => dayLabel(d.date, long), format: COUNT("order"), ariaLabel: "Orders per day by channel: voice notes, typed and samples" }),
      table: () => [["Day", "Voice notes", "Typed", "Samples", "Total"], a.daily.map((d) => [dayLabel(d.date, true), d.voice, d.text, d.sample, d.voice + d.text + d.sample])],
    },
    speed: {
      chart: (h) => a.processing.n
        ? Charts.columns(h, a.processing.bins, { series: [{ key: "count", label: "voice orders", color: c1 }], label: (d) => d.label, format: COUNT("voice order"), ariaLabel: "Distribution of voice note processing time" })
        : (h.innerHTML = `<div class="empty">No voice orders in this period yet.</div>`),
      table: () => [["Processing time", "Voice orders"], a.processing.bins.map((b) => [b.label, b.count])],
    },
    products: {
      chart: (h) => Charts.hbars(h, a.top_products, { value: (p) => p.value, label: (p) => p.name, format: RS, color: c1, ariaLabel: "Top products by order value" }),
      table: () => [["Product", "Quantity", "Order value"], a.top_products.map((p) => [p.name, `${p.qty} ${p.unit}`, pkr(p.value)])],
    },
    khata: {
      chart: (h) => khata.length
        ? Charts.hbars(h, khata, { value: (s) => s.balance, label: (s) => s.shop, format: { ...RS, unit: "owed" }, color: c1, ariaLabel: "Outstanding khata balance by shop" })
        : (h.innerHTML = `<div class="empty">Every shop is fully paid up.</div>`),
      table: () => [["Shop", "Balance owed"], a.khata.map((s) => [s.shop, pkr(s.balance)])],
    },
    hours: {
      chart: (h) => Charts.columns(h, a.hours, { series: [{ key: "orders", label: "orders", color: c1 }], label: (d) => hourLabel(d.hour), format: COUNT("order"), ariaLabel: "Orders by hour of day", height: 220 }),
      table: () => [["Hour", "Orders"], a.hours.map((d) => [hourLabel(d.hour), d.orders])],
    },
  };

  document.querySelectorAll(".chart-card").forEach((card) => {
    const key = card.dataset.chart;
    const host = card.querySelector(".chart-host");
    if (insights.view[key] === "table") {
      const [headers, rows] = charts[key].table();
      Charts.table(host, headers, rows);
    } else {
      host.replaceChildren();
      charts[key].chart(host);
    }
  });
}

// Re-render at the new width (charts draw at real pixel size for crisp text).
let resizeTimer;
new ResizeObserver(() => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderCharts, 150); }).observe($("chart-grid"));

boot().catch((e) => toast(e.message, "error"));
