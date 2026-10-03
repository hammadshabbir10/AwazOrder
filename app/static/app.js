"use strict";

const $ = (id) => document.getElementById(id);
const state = { products: [], shops: [], draft: null, sampleShop: null };
const MAX_SECONDS = 30;

const pkr = (n) => "Rs " + Math.round(n).toLocaleString("en-PK");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.add("hidden"), 3000);
}

async function api(path, options = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...options });
  let body = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (res.status === 401 && path !== "/api/login") { showLogin(); throw new Error("Please log in."); }
  if (!res.ok) throw new Error((body && body.detail && (typeof body.detail === "string" ? body.detail : "Please check the form.")) || `Request failed (${res.status})`);
  return body;
}
const postJson = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

/* ---------------------------------------------------------------- auth */

function showLogin() {
  $("app-view").classList.add("hidden");
  $("login-view").classList.remove("hidden");
}

async function showApp(user) {
  $("login-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("user-name").textContent = user.name;
  [state.products, state.shops] = await Promise.all([api("/api/catalogue"), api("/api/shops")]);
  renderSamples(await api("/api/samples"));
  renderShopSelect();
  refreshStats();
  refreshStatus();
}

$("fill-demo").onclick = () => { $("email").value = "demo@awazorder.pk"; $("password").value = "Demo@1234"; };

$("login-form").onsubmit = async (e) => {
  e.preventDefault();
  $("login-error").textContent = "";
  try {
    const user = await postJson("/api/login", { email: $("email").value, password: $("password").value });
    await showApp(user);
  } catch (err) { $("login-error").textContent = err.message; }
};

$("logout").onclick = async () => { await postJson("/api/logout", {}); showLogin(); };

/* ---------------------------------------------------------------- status + stats */

async function refreshStatus() {
  const b = $("ai-status");
  try {
    const s = await api("/api/status");
    const lastFailed = Object.values(s.last || {}).some((x) => !x.ok);
    if (!s.providers.length) { b.textContent = "Offline mode"; b.className = "badge off"; b.title = "No AI provider configured: rule-based parser in use."; }
    else if (lastFailed) { b.textContent = "AI: fallback active"; b.className = "badge warn"; b.title = JSON.stringify(s.last); }
    else { b.textContent = "AI: " + s.providers.join(" → ") + " ✓"; b.className = "badge"; b.title = "Open models via " + s.providers.join(", ") + ", offline parser as last resort"; }
  } catch { b.textContent = "AI: unknown"; b.className = "badge warn"; }
}

async function refreshStats() {
  const d = await api("/api/dashboard");
  $("st-orders").textContent = d.orders_today;
  $("st-value").textContent = pkr(d.value_today);
  $("st-out").textContent = pkr(d.outstanding);
}

/* ---------------------------------------------------------------- tabs */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
    $("tab-" + tab.dataset.tab).classList.remove("hidden");
    ({ orders: loadOrders, khata: loadShops, catalogue: renderCatalogue }[tab.dataset.tab] || (() => {}))();
  };
});

/* ---------------------------------------------------------------- samples */

function renderSamples(samples) {
  $("samples").innerHTML = samples.map((s) => `
    <button class="sample" data-id="${esc(s.id)}" data-shop="${esc(s.shop)}">
      <strong>${esc(s.title)}</strong>
      <p dir="auto">${esc(s.transcript)}</p>
    </button>`).join("");
  document.querySelectorAll(".sample").forEach((el) => {
    el.onclick = () => runParse(() => postJson(`/api/samples/${el.dataset.id}/parse`, {}), "Processing sample…", el.dataset.shop);
  });
}

/* ---------------------------------------------------------------- input: record / upload / type */

let recorder = null, chunks = [], recTimer = null, recStart = 0;

$("rec-btn").onclick = async () => {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { toast("Recording isn't supported in this browser. Upload a file or type the order."); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { toast("Microphone permission denied. Upload a file or type the order instead."); return; }
  chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    clearInterval(recTimer);
    $("rec-btn").classList.remove("recording");
    $("rec-label").textContent = "Tap to record";
    const type = recorder.mimeType || "audio/webm";
    const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
    sendAudio(new Blob(chunks, { type }), `voice-note.${ext}`);
  };
  recorder.start();
  recStart = Date.now();
  $("rec-btn").classList.add("recording");
  $("rec-label").textContent = "Recording… tap to stop";
  recTimer = setInterval(() => {
    const s = Math.floor((Date.now() - recStart) / 1000);
    $("rec-timer").textContent = `0:${String(s).padStart(2, "0")} / 0:30`;
    if (s >= MAX_SECONDS) recorder.stop();
  }, 250);
};

$("audio-file").onchange = (e) => {
  const file = e.target.files[0];
  if (file) sendAudio(file, file.name);
  e.target.value = "";
};

function sendAudio(blob, name) {
  const form = new FormData();
  form.append("file", blob, name);
  runParse(() => api("/api/parse/audio", { method: "POST", body: form }), "Listening to the voice note…");
}

$("parse-text").onclick = () => {
  const text = $("order-text").value.trim();
  if (text.length < 3) { toast("Type an order first."); return; }
  runParse(() => postJson("/api/parse/text", { text }), "Reading the order…");
};

async function runParse(call, busyText, sampleShop = null) {
  $("parse-error").classList.add("hidden");
  $("draft").classList.add("hidden");
  $("done").classList.add("hidden");
  $("busy-text").textContent = busyText;
  $("busy").classList.remove("hidden");
  try {
    const draft = await call();
    state.sampleShop = sampleShop;
    renderDraft(draft);
  } catch (err) {
    $("parse-error").textContent = err.message;
    $("parse-error").classList.remove("hidden");
  } finally {
    $("busy").classList.add("hidden");
    refreshStatus();
  }
}

/* ---------------------------------------------------------------- draft review */

function modeLabel(d) {
  if (d.mode === "cached") return ["Cached sample · AI-processed", "badge"];
  if (d.mode === "ai") return [`AI · ${d.asr_provider ? "Whisper + " : ""}${(d.provider || "").split(":").pop()}`, "badge"];
  return [d.ai_error ? "Offline fallback (AI unavailable)" : "Offline rule-based parser", "badge warn"];
}

function renderDraft(d) {
  state.draft = {
    transcript: d.transcript,
    source: d.asr_provider ? "voice" : d.mode === "cached" || d.mode === "offline" && state.sampleShop ? "sample" : "text",
    lines: d.lines.map((l) => ({ ...l })),
  };
  const [label, cls] = modeLabel(d);
  $("mode-badge").textContent = label;
  $("mode-badge").className = cls;
  $("transcript").textContent = d.transcript;
  const um = d.unmatched || [];
  $("unmatched").classList.toggle("hidden", !um.length);
  $("unmatched").textContent = um.length ? "Not in catalogue: " + um.join(", ") : "";
  $("payment").value = d.payment === "unknown" ? "unknown" : d.payment;

  let shopId = d.shop_id;
  if (!shopId && state.sampleShop) shopId = state.shops.find((s) => s.name === state.sampleShop)?.id;
  $("shop").value = shopId || "";

  renderLines();
  $("draft").classList.remove("hidden");
  $("draft").scrollIntoView({ behavior: "smooth", block: "start" });
}

function productOptions(selected) {
  return state.products.map((p) => `<option value="${esc(p.sku)}" ${p.sku === selected ? "selected" : ""}>${esc(p.name)}</option>`).join("");
}

function renderLines() {
  const by = Object.fromEntries(state.products.map((p) => [p.sku, p]));
  const rows = state.draft.lines.map((l, i) => {
    const p = by[l.sku];
    const total = p.price * l.quantity;
    const alts = (l.alternatives || []).map((a) => `<button class="chip" data-i="${i}" data-sku="${esc(a.sku)}">${esc(a.name)}?</button>`).join("");
    return `<tr class="${l.needs_review ? "review" : ""}">
      <td><select data-i="${i}" class="sku">${productOptions(l.sku)}</select>
        ${l.spoken ? `<div class="conf" dir="auto">heard: “${esc(l.spoken)}”${l.confidence != null ? ` · ${Math.round(l.confidence * 100)}% sure` : ""}</div>` : ""}
        ${alts ? `<div class="chips">Did you mean ${alts}</div>` : ""}</td>
      <td><input type="number" min="0.5" step="0.5" value="${l.quantity}" data-i="${i}" class="qty" /></td>
      <td>${esc(p.unit)}</td><td>${pkr(p.price)}</td><td><strong>${pkr(total)}</strong></td>
      <td><button class="x" data-i="${i}" aria-label="Remove item">×</button></td></tr>`;
  });
  $("lines").innerHTML = rows.join("") || `<tr><td colspan="6" class="muted">No items recognised. Add them manually.</td></tr>`;
  $("draft-total").textContent = pkr(state.draft.lines.reduce((s, l) => s + by[l.sku].price * l.quantity, 0));

  document.querySelectorAll("#lines .sku").forEach((el) => el.onchange = () => { const l = state.draft.lines[el.dataset.i]; l.sku = el.value; l.needs_review = false; l.alternatives = []; renderLines(); });
  document.querySelectorAll("#lines .qty").forEach((el) => el.onchange = () => { state.draft.lines[el.dataset.i].quantity = Math.max(0.5, Number(el.value) || 1); renderLines(); });
  document.querySelectorAll("#lines .x").forEach((el) => el.onclick = () => { state.draft.lines.splice(el.dataset.i, 1); renderLines(); });
  document.querySelectorAll("#lines .chip").forEach((el) => el.onclick = () => { const l = state.draft.lines[el.dataset.i]; l.sku = el.dataset.sku; l.needs_review = false; l.alternatives = []; renderLines(); });
}

$("add-line").onclick = () => {
  state.draft.lines.push({ sku: state.products[0].sku, quantity: 1, spoken: "", alternatives: [] });
  renderLines();
};

function renderShopSelect() {
  $("shop").innerHTML = `<option value="">Select shop…</option>` + state.shops.map((s) => `<option value="${s.id}">${esc(s.name)} — ${esc(s.area)}</option>`).join("");
}

$("confirm").onclick = async () => {
  const shopId = Number($("shop").value);
  if (!shopId) { toast("Select the shop first."); return; }
  if (!state.draft.lines.length) { toast("Add at least one item."); return; }
  if (state.draft.lines.some((l) => l.needs_review) && !confirm("Some items are marked uncertain (highlighted). Confirm anyway?")) return;
  $("confirm").disabled = true;
  try {
    const res = await postJson("/api/orders", {
      shop_id: shopId,
      payment: $("payment").value,
      transcript: state.draft.transcript,
      source: state.draft.source,
      lines: state.draft.lines.map((l) => ({ sku: l.sku, quantity: l.quantity, spoken: l.spoken || "" })),
    });
    $("draft").classList.add("hidden");
    $("done-id").textContent = `#${res.id} · ${res.shop}`;
    $("reply").textContent = res.reply;
    const phone = (res.phone || "").replace(/\D/g, "").replace(/^0/, "92");
    $("wa-link").href = `https://wa.me/${phone}?text=${encodeURIComponent(res.reply)}`;
    $("done").classList.remove("hidden");
    $("done").scrollIntoView({ behavior: "smooth" });
    state.shops = await api("/api/shops");
    refreshStats();
  } catch (err) { toast(err.message); }
  finally { $("confirm").disabled = false; }
};

$("copy-reply").onclick = async () => {
  try { await navigator.clipboard.writeText($("reply").textContent); toast("Reply copied"); }
  catch { toast("Select the text and copy it manually."); }
};

$("new-order").onclick = () => {
  $("done").classList.add("hidden");
  $("order-text").value = "";
  window.scrollTo({ top: 0, behavior: "smooth" });
};

/* ---------------------------------------------------------------- orders, khata, catalogue */

async function loadOrders() {
  const orders = await api("/api/orders");
  $("orders").innerHTML = orders.length ? `<table><thead><tr><th>#</th><th>Shop</th><th>Items</th><th>Payment</th><th>Total</th><th>Source</th></tr></thead><tbody>${
    orders.map((o) => `<tr><td>${o.id}</td><td>${esc(o.shop)}</td><td>${o.lines.map((l) => `${l.quantity} × ${esc(l.name)}`).join("<br>")}</td>
      <td>${o.payment === "credit" ? "Khata" : o.payment === "cash" ? "Cash" : "—"}</td><td><strong>${pkr(o.total)}</strong></td><td>${esc(o.source)}</td></tr>`).join("")
  }</tbody></table>` : `<p class="muted">No orders yet. Confirm one from the New order tab.</p>`;
}

async function loadShops(selectId) {
  state.shops = await api("/api/shops");
  $("shops").innerHTML = state.shops.map((s) => `<div class="shop" data-id="${s.id}">
    <div><strong>${esc(s.name)}</strong><small>${esc(s.area)} · ${esc(s.phone)}</small></div>
    <div class="owed ${s.balance <= 0 ? "zero" : ""}">${pkr(s.balance)}</div></div>`).join("");
  document.querySelectorAll(".shop").forEach((el) => el.onclick = () => openLedger(Number(el.dataset.id)));
  if (selectId) openLedger(selectId);
}

async function openLedger(shopId) {
  document.querySelectorAll(".shop").forEach((el) => el.classList.toggle("active", Number(el.dataset.id) === shopId));
  const shop = state.shops.find((s) => s.id === shopId);
  const entries = await api(`/api/shops/${shopId}/ledger`);
  $("ledger-title").textContent = `${shop.name}: ${pkr(shop.balance)} owed`;
  const kind = { opening: "Opening balance", credit_order: "Order on khata", payment: "Payment" };
  $("ledger").innerHTML = `${entries.length ? `<table><thead><tr><th>Date</th><th>Entry</th><th>Amount</th></tr></thead><tbody>${
    entries.map((e) => `<tr><td>${esc(e.created_at.slice(0, 10))}</td><td>${esc(kind[e.kind] || e.kind)}<br><small class="muted">${esc(e.note)}</small></td>
      <td class="${e.amount < 0 ? "neg" : ""}">${e.amount < 0 ? "−" : "+"}${pkr(Math.abs(e.amount))}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">No entries.</p>`}
    <form class="pay-form" id="pay-form"><input type="number" min="1" placeholder="Payment received (Rs)" id="pay-amount" required /><button class="btn primary">Record payment</button></form>`;
  $("pay-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await postJson(`/api/shops/${shopId}/payments`, { amount: Number($("pay-amount").value) });
      toast("Payment recorded");
      await loadShops(shopId);
      refreshStats();
    } catch (err) { toast(err.message); }
  };
}

function renderCatalogue() {
  $("catalogue").innerHTML = state.products.map((p) => `<div class="cat"><strong>${esc(p.name)}</strong>
    <span>${pkr(p.price)} / ${esc(p.unit)}</span><small dir="auto">${esc(p.aliases.join(" · "))}</small></div>`).join("");
}

/* ---------------------------------------------------------------- boot */

api("/api/me").then(showApp).catch(showLogin);
