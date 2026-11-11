"use strict";
const $ = s => document.querySelector(s);
let AUTHED = false;
let loginPromise = null, loginResolve = null;

function showLogin() {
  if (!loginPromise) {
    $("#login").hidden = false;
    loginPromise = new Promise(res => { loginResolve = res; });
  }
  return loginPromise;
}
$("#login-form").onsubmit = async e => {
  e.preventDefault();
  $("#login-error").textContent = "";
  const r = await fetch("/api/auth/login", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: $("#login-token").value })
  });
  if (r.ok) {
    $("#login").hidden = true;
    $("#login-token").value = "";
    AUTHED = true;
    const res = loginResolve; loginPromise = null; loginResolve = null;
    if (res) res();
    loadVolumes().catch(() => {});
  } else {
    $("#login-error").textContent = "Неверный токен";
  }
};
$("#logout").onclick = async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  AUTHED = false;
  await showLogin();
};

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (opts.json) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  let r = await fetch(path, { ...opts, headers });
  if (r.status === 401) {
    AUTHED = false;
    await showLogin();
    r = await fetch(path, { ...opts, headers });
  }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).message || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}
const status = m => { $("#status-line").textContent = m; };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let activeTab = "volumes";
document.querySelectorAll("nav button[data-tab]").forEach(b => b.onclick = () => {
  activeTab = b.dataset.tab;
  document.querySelectorAll("nav button[data-tab]").forEach(x => x.classList.toggle("active", x === b));
  document.querySelectorAll("section").forEach(s => s.hidden = s.id !== "tab-" + activeTab);
  if (activeTab === "volumes") loadVolumes();
  if (activeTab === "gallery") loadImages();
  if (activeTab === "jobs") loadJobs();
});

async function loadVolumes() {
  const { items } = await api("/api/volumes");
  const sel = $("#f-volume");
  sel.innerHTML = '<option value="">все диски</option>' +
    items.map(v => `<option value="${v.id}">${esc(v.label || v.anchor)}</option>`).join("");
  const box = $("#volumes-list");
  box.innerHTML = "";
  for (const v of items) {
    const roots = (await api(`/api/volumes/${v.id}/roots`)).items;
    const card = document.createElement("div");
    card.className = "vol-card";
    card.innerHTML = `
      <b>${esc(v.label || "(без метки)")}</b>
      <span class="badge ${v.status}">${v.status}</span>
      <span class="muted">${esc(v.anchor || "")} · ${esc(v.fs_type || "?")} · ${esc(v.media_type || "?")}
        · serial ${esc(v.fs_serial || "?")} · marker ${v.marker_uuid ? "yes" : "no"}
        · last scan ${esc(v.last_scan_at || "никогда")}</span>
      ${v.identity_warning ? `<div class="warn">⚠ ${esc(v.identity_warning)}</div>` : ""}
      <div class="root-row">
        <input placeholder="подкаталог (пусто = весь диск)" data-vid="${v.id}" class="root-input">
        <button data-act="addroot" data-vid="${v.id}">+ root</button>
        <button data-act="rebind" data-vid="${v.id}">Rebind…</button>
      </div>
      ${roots.map(r => `<div class="root-row">
        <code>/${esc(r.relative_path)}</code>
        <span class="muted">scan: ${esc(r.last_scan_at || "никогда")}</span>
        <button data-act="scan" data-rid="${r.id}">Scan</button></div>`).join("")}`;
    box.appendChild(card);
  }
}
$("#vol-register").onclick = async () => {
  try {
    await api("/api/volumes", { method: "POST", json: {
      path: $("#vol-path").value.trim(), create_marker: $("#vol-marker").checked } });
    status("носитель зарегистрирован"); loadVolumes();
  } catch (e) { alert(e.message); }
};
$("#volumes-list").onclick = async e => {
  const b = e.target.closest("button"); if (!b) return;
  try {
    if (b.dataset.act === "addroot") {
      const inp = document.querySelector(`.root-input[data-vid="${b.dataset.vid}"]`);
      await api(`/api/volumes/${b.dataset.vid}/roots`, { method: "POST", json: { relative_path: inp.value.trim() } });
      loadVolumes();
    } else if (b.dataset.act === "scan") {
      const { job_id } = await api(`/api/roots/${b.dataset.rid}/scan`, { method: "POST" });
      status("scan job: " + job_id.slice(0, 8));
    } else if (b.dataset.act === "rebind") {
      const p = prompt("Новый путь к этому носителю:");
      if (p) { await api(`/api/volumes/${b.dataset.vid}/rebind`, { method: "POST", json: { path: p } }); loadVolumes(); }
    }
  } catch (err) { alert(err.message); }
};

const G = { page: 1, pageSize: 60, total: 0, items: [], selection: new Set() };
async function loadImages() {
  const p = new URLSearchParams({ page: G.page, page_size: G.pageSize, order: $("#f-order").value });
  if ($("#f-volume").value) p.set("volume_id", $("#f-volume").value);
  if ($("#f-status").value) p.set("status", $("#f-status").value);
  if ($("#f-q").value.trim()) p.set("q", $("#f-q").value.trim());
  const data = await api("/api/images?" + p);
  G.items = data.items; G.total = data.total;
  const grid = $("#grid"); grid.innerHTML = "";
  for (let i = 0; i < G.items.length; i++) {
    const it = G.items[i];
    const cell = document.createElement("div");
    cell.className = "cell";
    const thumb = it.scan_status === "ok"
      ? `/api/images/${it.id}/thumbnail?v=${it.mtime_ns}` : "";
    cell.innerHTML = `
      ${thumb ? `<img loading="lazy" src="${thumb}" alt="">` : `<div style="aspect-ratio:1"></div>`}
      <input type="checkbox" class="sel" ${G.selection.has(it.id) ? "checked" : ""}>
      <span class="st badge ${it.scan_status}">${it.scan_status}${it.volume_status === "offline" ? " · offline" : ""}</span>
      <div class="cap" title="${esc(it.relative_path)}">${esc(it.filename)}</div>`;
    cell.querySelector(".sel").onclick = ev => {
      ev.stopPropagation();
      ev.target.checked ? G.selection.add(it.id) : G.selection.delete(it.id);
      $("#sel-count").textContent = G.selection.size ? `выбрано: ${G.selection.size}` : "";
    };
    cell.onclick = () => openViewer(i);
    grid.appendChild(cell);
  }
  const pages = Math.max(1, Math.ceil(G.total / G.pageSize));
  $("#pg-info").textContent = `${G.page} / ${pages} · всего ${G.total}`;
}
$("#f-apply").onclick = () => { G.page = 1; loadImages().catch(e => alert(e.message)); };
$("#pg-prev").onclick = () => { if (G.page > 1) { G.page--; loadImages(); } };
$("#pg-next").onclick = () => { if (G.page * G.pageSize < G.total) { G.page++; loadImages(); } };

const V = { idx: 0, scale: 1, tx: 0, ty: 0, drag: null };
function vTransform() {
  $("#viewer-img").style.transform = `translate(${V.tx}px,${V.ty}px) scale(${V.scale})`;
}
async function openViewer(i) {
  V.idx = i; V.scale = 1; V.tx = V.ty = 0;
  const it = G.items[i];
  $("#viewer").hidden = false;
  const img = $("#viewer-img");
  img.src = it.scan_status === "ok" && it.volume_status === "online"
    ? `/api/images/${it.id}/original` : "";
  vTransform();
  const meta = await api(`/api/images/${it.id}`);
  let exif = {};
  try { exif = JSON.parse(meta.exif_json || "{}"); } catch {}
  $("#viewer-meta").innerHTML = `
    <h3>${esc(meta.filename)}</h3>
    <p class="muted">${esc(meta.volume_label || "")} (${meta.volume_status})<br>/${esc(meta.relative_path)}</p>
    <p>${meta.width}×${meta.height} · ${esc(meta.format)} · ${esc(meta.mode)}<br>
    ${(meta.file_size / 1024).toFixed(1)} KB · orientation ${meta.orientation}<br>
    created: ${esc(meta.created_at_fs || "?")}</p>
    <h4>EXIF</h4><pre>${esc(JSON.stringify(exif, null, 2))}</pre>`;
}
function vStep(d) {
  const n = V.idx + d;
  if (n >= 0 && n < G.items.length) openViewer(n);
}
$("#viewer-close").onclick = () => { $("#viewer").hidden = true; };
$("#viewer-prev").onclick = () => vStep(-1);
$("#viewer-next").onclick = () => vStep(1);
document.addEventListener("keydown", e => {
  if ($("#viewer").hidden) return;
  if (e.key === "Escape") $("#viewer").hidden = true;
  if (e.key === "ArrowLeft") vStep(-1);
  if (e.key === "ArrowRight") vStep(1);
});
$("#viewer-img-wrap").addEventListener("wheel", e => {
  e.preventDefault();
  V.scale = Math.min(12, Math.max(0.2, V.scale * Math.pow(1.15, -e.deltaY / 100)));
  vTransform();
}, { passive: false });
$("#viewer-img-wrap").addEventListener("mousedown", e => { V.drag = { x: e.clientX - V.tx, y: e.clientY - V.ty }; });
window.addEventListener("mousemove", e => { if (V.drag) { V.tx = e.clientX - V.drag.x; V.ty = e.clientY - V.drag.y; vTransform(); } });
window.addEventListener("mouseup", () => { V.drag = null; });

async function loadJobs() {
  const { items, paused } = await api("/api/jobs?limit=100");
  $("#queue-state").textContent = paused ? "очередь на паузе" : "очередь работает";
  const tb = $("#jobs-table tbody");
  tb.innerHTML = items.map(j => `<tr>
    <td>${esc(j.kind)}</td><td><span class="badge ${esc(j.status)}">${j.status}</span></td>
    <td><progress max="1" value="${j.progress ?? 0}"></progress></td>
    <td class="muted">${esc(j.error || j.progress_msg || "")}</td>
    <td class="muted">${esc(j.created_at)}</td>
    <td>${["pending", "running"].includes(j.status) ? `<button data-jid="${j.id}">Cancel</button>` : ""}</td>
  </tr>`).join("");
  const active = items.filter(j => ["pending", "running"].includes(j.status)).length;
  $("#jobs-badge").textContent = active ? `(${active})` : "";
}
$("#jobs-table").onclick = async e => {
  const b = e.target.closest("button"); if (!b) return;
  await api(`/api/jobs/${b.dataset.jid}/cancel`, { method: "POST" }); loadJobs();
};
$("#jobs-pause").onclick = async () => { await api("/api/jobs/pause", { method: "POST" }); loadJobs(); };
$("#jobs-resume").onclick = async () => { await api("/api/jobs/resume", { method: "POST" }); loadJobs(); };
setInterval(() => { if (AUTHED && activeTab === "jobs") loadJobs().catch(() => {}); }, 2000);
setInterval(async () => {
  if (!AUTHED) return;
  try {
    const { items } = await api("/api/jobs?status=running&limit=50");
    $("#jobs-badge").textContent = items.length ? `(${items.length})` : "";
  } catch {}
}, 5000);

(async () => {
  try {
    const s = await (await fetch("/api/auth/status")).json();
    $("#logout").hidden = !s.auth_required;
    AUTHED = s.authenticated;
    if (!AUTHED) await showLogin();
    await loadVolumes();
  } catch (e) { status(e.message); }
})();