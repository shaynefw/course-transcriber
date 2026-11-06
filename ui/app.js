"use strict";
/* Transcriber control panel UI. Talks only to this Mac (127.0.0.1). */

/* ============================== helpers ============================== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) { } } };
const sess = { get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { } } };

let TOKEN = "", ST = null, TREE = null, LES = {}, SEL = null, treeDirty = true, wasRunning = false;
const WEB = "Web videos";

async function get(p) {
  const r = await fetch(p);
  let j = {};
  try { j = await r.json(); } catch (e) { }
  if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}
async function post(p, b) {
  const r = await fetch(p, { method: "POST", headers: { "X-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify(b || {}) });
  let j = {};
  try { j = await r.json(); } catch (e) { }
  return j;
}
const bytes = n => { n = n || 0; if (n < 1024) return n + " B"; const u = ["KB", "MB", "GB", "TB"]; let i = -1; do { n /= 1024; i++; } while (n >= 1024 && i < 3); return n.toFixed(n < 10 ? 1 : 0) + " " + u[i]; };
const dur = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
const hms = t => { t = Math.round(t || 0); const p = n => String(n).padStart(2, "0"); return `${p(Math.floor(t / 3600))}:${p(Math.floor(t % 3600 / 60))}:${p(t % 60)}`; };
const etaLeft = s => s < 60 ? "LESS THAN A MINUTE LEFT" : "ABOUT " + etaTxt(s) + " LEFT";
const etaTxt = s => { if (s < 60) return "UNDER A MINUTE"; const m = Math.round(s / 60); if (m < 60) return m + " MIN"; const h = Math.floor(m / 60); return h + " H " + (m % 60) + " MIN"; };
const num = n => n == null ? "–" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? (n / 1e3).toFixed(1) + "K" : String(n);
let toastT;
function toast(msg, bad) { const t = $("#toast"); t.textContent = msg; t.classList.toggle("bad", !!bad); t.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), bad ? 6500 : 3800); }
const isTyping = e => /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "");

/* ============================== boot ============================== */
(function boot() {
  const b = $("#boot");
  if (sess.get("booted") || matchMedia("(prefers-reduced-motion: reduce)").matches) { b.classList.add("off"); return; }
  sess.set("booted", "1");
  const lines = ["TRANSCRIBER // LOCAL TERMINAL", "", "MEMORY CHECK ............ OK", "AUDIO DECODERS ........... OK", "SPEECH MODEL LINK ........ OK", "FILE SYSTEM .............. MOUNTED", "", "READY."];
  let i = 0; const pre = $("#bootText");
  const tick = () => { pre.textContent = lines.slice(0, ++i).join("\n"); if (i < lines.length) setTimeout(tick, 85); else setTimeout(() => b.classList.add("off"), 260); };
  tick();
})();

/* ============================== tabs ============================== */
const TABS = ["sources", "transcribe", "snapshots", "files", "ai", "system"];
function setTab(t, replace = true) {
  if (!TABS.includes(t)) t = "sources";
  document.body.dataset.tab = t;
  $$(".tab").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === t)));
  store.set("tab", t);
  if (replace) history.replaceState(null, "", "#" + t);
  if (t === "files" && treeDirty) loadTree();
  if (t === "sources") loadSingles();
  if (t === "sources" || t === "transcribe" || t === "snapshots") loadSources();
  if (t === "ai") aiOpen();
  window.scrollTo(0, 0);
}
$$(".tab").forEach(b => b.onclick = () => setTab(b.dataset.tab));
document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "Escape") { if (!$("#lightbox").hidden) closeLightbox(); else if (!$("#modal").hidden) closeModal(); return; }
  if (!$("#lightbox").hidden) { if (e.key === "ArrowRight") lbStep(1); if (e.key === "ArrowLeft") lbStep(-1); return; }
  if (isTyping(e) || !$("#modal").hidden) return;
  if (/^[1-6]$/.test(e.key)) setTab(TABS[+e.key - 1]);
  if (e.key === "/" && document.body.dataset.tab === "files") { e.preventDefault(); $("#fsearch").focus(); }
});

/* sources sub-tabs */
$$("#srcSeg button").forEach(b => b.onclick = () => {
  $$("#srcSeg button").forEach(x => x.classList.toggle("on", x === b));
  $$(".sub").forEach(s => s.classList.toggle("on", s.id === "sub-" + b.dataset.sub));
  store.set("sub", b.dataset.sub);
  if (b.dataset.sub === "singles") loadSingles();
});

/* ============================== waveform ============================== */
(function wave() {
  const c = $("#wave"), g = c.getContext("2d");
  let on = true, amp = 0, t0 = performance.now();
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function size() { const r = c.getBoundingClientRect(), d = devicePixelRatio || 1; c.width = Math.max(100, r.width * d); c.height = r.height * d; }
  addEventListener("resize", size); size();
  $("#fxWave").addEventListener("change", e => { on = e.target.checked; store.set("fxWave", on ? "1" : "0"); if (!on) clear(); });
  function clear() { g.clearRect(0, 0, c.width, c.height); }
  function frame(now) {
    if (document.hidden || !on) { setTimeout(() => requestAnimationFrame(frame), 250); return; }
    const w = c.width, h = c.height, running = !!(ST && ST.running);
    amp += ((running ? 1 : 0.06) - amp) * 0.06;
    clear(); g.lineWidth = Math.max(1.5, h / 22); g.strokeStyle = "#42ff94"; g.shadowColor = "#42ff94"; g.shadowBlur = 8; g.beginPath();
    const t = (now - t0) / 1000;
    for (let x = 0; x <= w; x += 3) {
      const u = x / w;
      const env = Math.pow(Math.sin(Math.PI * u), 0.8);
      const s = Math.sin(u * 38 - t * 7) * 0.5 + Math.sin(u * 17 + t * 3.1) * 0.35 + Math.sin(u * 83 - t * 11) * 0.25;
      const blip = Math.exp(-Math.pow((((u * 3 - t * 0.35) % 1 + 1) % 1 - 0.5) * 18, 2)) * (running ? 0.15 : 1) * 0.9;
      const y = h / 2 - (s * amp * env + blip * env * (1 - amp * 0.7)) * (h * 0.4);
      x === 0 ? g.moveTo(x, y) : g.lineTo(x, y);
    }
    g.stroke();
    setTimeout(() => requestAnimationFrame(frame), reduce ? 400 : 33);
  }
  requestAnimationFrame(frame);
  if (store.get("fxWave") === "0") { on = false; $("#fxWave").checked = false; clear(); }
})();
$("#fxCrt").addEventListener("change", e => { document.body.classList.toggle("no-fx", !e.target.checked); store.set("fxCrt", e.target.checked ? "1" : "0"); });
if (store.get("fxCrt") === "0") { document.body.classList.add("no-fx"); $("#fxCrt").checked = false; }

/* ============================== status + dock ============================== */
async function poll() {
  try { ST = await get("/api/status"); TOKEN = ST.token; render(); }
  catch (e) { $("#phasePill").textContent = "PANEL STOPPED"; $("#phasePill").className = "pill err"; $("#curName").textContent = "THE PANEL IS NOT RUNNING."; $("#reopen").hidden = false; $("#stop").hidden = true; }
}
let lastCourses = "";
function render() {
  const s = ST, run = s.running;
  $("#reopen").hidden = true;
  /* dock */
  const pill = $("#phasePill");
  let phase = s.phase || "idle", step = "";
  const m = /^step (\d+) of (\d+): (.*)$/.exec(phase);
  if (m) { step = `STEP ${m[1]} OF ${m[2]} · `; phase = m[3]; }
  pill.textContent = run ? phase.toUpperCase() : (s.last_exit && s.last_exit !== 0 ? "STOPPED" : "IDLE");
  pill.className = "pill" + (run ? " run" : (s.last_exit && s.last_exit !== 0 ? " err" : ""));
  $("#curName").textContent = run ? (s.current || "WORKING…") : (s.last_exit === null || s.last_exit === undefined ? "READY" : (s.last_exit === 0 ? "LAST RUN FINISHED" : "LAST RUN STOPPED"));
  $("#curBar").style.width = (run && s.current ? s.percent : 0) + "%";
  $("#curMeta").textContent = run && s.current ? `${step}${s.percent}% · ${dur(s.elapsed_file)} ON THIS LESSON · ${s.eta_file != null ? etaLeft(s.eta_file) : "ESTIMATING…"}` : (run ? step.replace(/ · $/, "") : "");
  $("#runMeta").textContent = run || (s.last_exit !== null && s.last_exit !== undefined)
    ? `THIS RUN: ${s.run_done}${run && s.plan_files ? " OF " + s.plan_files : ""} DONE${s.run_failed ? ", " + s.run_failed + " FAILED" : ""}${run ? " · RUNNING " + dur(s.elapsed_run) : ""}${s.speed ? " · LAST LESSON " + s.speed.toUpperCase() : ""}` : "";
  /* compact one-line summary for phone screens */
  const short = t => etaTxt(t).replace("UNDER A MINUTE", "<1 MIN"), clock = t => new Date(Date.now() + t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  $("#miniMeta").textContent = run
    ? (m ? `${m[1]}/${m[2]} · ` : "") + (s.current ? `${s.percent}% · ${s.eta_file != null ? short(s.eta_file) + " LEFT" : "ESTIMATING…"}` : "STARTING…") + (s.plan_files ? ` · BATCH ${s.eta_batch != null ? short(s.eta_batch) + " · ≈" + clock(s.eta_batch) : "…"} · ${s.run_done}/${s.plan_files}` : "")
    : $("#runMeta").textContent;
  const bm = $("#batchMeta");
  if (run && s.plan_files) bm.textContent = s.eta_batch != null ? `WHOLE BATCH: ${etaLeft(s.eta_batch)} · FINISHES ≈ ${new Date(Date.now() + s.eta_batch * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "WHOLE BATCH: ESTIMATING…";
  else bm.textContent = "";
  const stop = $("#stop"); stop.hidden = !run; stop.disabled = !!s.stopping; stop.textContent = s.stopping ? "STOPPING…" : "STOP";
  const lg = $("#log"), atEnd = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 8;
  if (!$("#drawer").hidden) { lg.textContent = s.log.join("\n"); if (atEnd) lg.scrollTop = lg.scrollHeight; }

  /* locks */
  $$("[data-idle]").forEach(b => b.disabled = run);
  ["model", "english", "watch", "interval", "change", "capture", "burst", "redo", "preset"].forEach(i => $("#" + i).disabled = run);
  $("#o-fail").hidden = !s.failed;

  /* courses + pending */
  const cj = JSON.stringify(s.courses) + run;
  if (cj !== lastCourses) { lastCourses = cj; renderCourses(); }
  renderPending();

  /* when a job finishes: refresh what depends on it */
  if (wasRunning && !run) { treeDirty = true; loadSingles(); loadTree(); loadSources(); }
  wasRunning = run;
}
$("#logToggle").onclick = () => {
  const d = $("#drawer"), open = d.hidden; d.hidden = !open;
  $("#logToggle").textContent = open ? "LOG ▼" : "LOG ▲"; $("#logToggle").setAttribute("aria-expanded", String(open));
  if (open) { $("#log").textContent = (ST ? ST.log : []).join("\n"); $("#log").scrollTop = 1e9; }
};
$("#copylog").onclick = async () => {
  let text = ""; try { text = await (await fetch("/api/log")).text(); } catch (e) { text = $("#log").textContent; }
  const ok = await copyText(text);
  $("#copied").textContent = ok ? `COPIED ✓ (${text.split("\n").length} LINES)` : "COULDN'T COPY: SELECT THE TEXT AND PRESS ⌘C";
  setTimeout(() => $("#copied").textContent = "", 4000);
};
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { }
  const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (e2) { } t.remove(); return ok;
}
$("#stop").onclick = async () => { await post("/api/stop"); poll(); };
$("#reopen").onclick = () => reopenFlow(m => { $("#curName").textContent = m; });

/* ============================== sources ============================== */
function renderCourses() {
  const el = $("#courses"), cs = ST.courses.filter(k => k.name !== "Single files" && k.name !== "Web videos"), run = ST.running;
  if (!cs.length) { el.className = "list empty"; el.textContent = "NO COURSES YET. CLICK “+ ADD COURSE FOLDER” BELOW."; return; }
  el.className = "list";
  el.innerHTML = cs.map(k => {
    const pct = k.total ? Math.round(k.done / k.total * 100) : 0;
    return `<div class="item"><div class="nm">${esc(k.name)}</div>
      <div class="acts"><button class="btn small" data-files="${esc(k.name)}">VIEW FILES</button>${k.link && !run ? `<button class="btn small ghost" data-rm="${esc(k.name)}" title="Unlinks the folder from this list. Your files are untouched.">REMOVE</button>` : ""}</div>
      <div class="meta">${k.done} OF ${k.total} TRANSCRIBED · SNAPSHOTS: ${k.snaps || 0} OVERVIEW, ${k.vis || 0} VISUAL, ${k.combo || 0} COMBINED${k.target ? " · " + esc(k.target) : ""}</div>
      <div class="bar thin"><i style="width:${pct}%"></i></div></div>`;
  }).join("");
}
$("#courses").addEventListener("click", async e => {
  const rm = e.target.closest("[data-rm]"), vf = e.target.closest("[data-files]");
  if (rm) { const r = await post("/api/remove-course", { name: rm.dataset.rm }); toast(r.ok ? "REMOVED FROM THE LIST. YOUR FILES ARE UNTOUCHED." : (r.msg || "COULDN'T REMOVE"), !r.ok); poll(); }
  if (vf) { SEL = { t: "course", course: vf.dataset.files }; OPEN.add("c:" + vf.dataset.files); V.tab = null; $("#files").dataset.pane = "view"; setTab("files"); if (!treeDirty) { renderTree(); renderView(); } }
});
$("#add").onclick = async () => {
  toast("CHOOSE A FOLDER IN THE DIALOG…");
  const r = await post("/api/add-course");
  if (r.msg === "added") toast(`ADDED “${r.name}”.`); else if (r.msg !== "cancelled") toast(String(r.msg || "COULDN'T ADD"), true);
  poll();
};
async function loadSingles() {
  let list = []; try { list = await get("/api/singles"); } catch (e) { return; }
  const el = $("#singlesList");
  if (!list.length) { el.className = "list empty"; el.textContent = "NOTHING PICKED YET"; return; }
  el.className = "list";
  const gone = list.filter(f => !f.exists).length;
  el.innerHTML = (gone ? `<div class="row" style="margin-bottom:10px"><button class="btn small danger" data-clearmissing>CLEAR ${gone} MISSING</button><span class="hint nm">Their original files are gone (moved or deleted).</span></div>` : "") + list.map(f => `<div class="item"><div class="nm">${esc(f.name)}</div>
    <div class="acts"><button class="btn small ghost" data-rms="${esc(f.name)}" title="Removes it from this list only. The original file and any transcript are untouched.">REMOVE</button></div>
    <div class="meta">${f.done ? '<span class="ok">✓ TRANSCRIBED</span>' : '<span class="no">NOT TRANSCRIBED YET</span>'} · ${f.exists ? esc(f.target) : "ORIGINAL NOT FOUND (MOVED OR DELETED?)"}</div></div>`).join("");
}
$("#singlesList").addEventListener("click", async e => {
  if (e.target.closest("[data-clearmissing]")) { clearMissingFlow(); return; }
  const b = e.target.closest("[data-rms]"); if (!b) return;
  const r = await post("/api/remove-single", { name: b.dataset.rms }); toast(r.ok ? "REMOVED FROM THE LIST." : "COULDN'T REMOVE", !r.ok); loadSingles(); poll();
});
$("#pickfiles").onclick = async () => {
  toast("CHOOSE FILES IN THE DIALOG…");
  const r = await post("/api/pick-files");
  if (r.msg === "cancelled") return;
  if (!r.added || !r.added.length) { toast(r.skipped && r.skipped.length ? "NOTHING ADDED: " + r.skipped.join(", ") : "NO FILES CHOSEN.", true); return; }
  const st = await post("/api/start", { mode: "files", english: $("#flang").value === "en", model: $("#model").value, do_snapshots: $("#fsn").checked, snap: snapSettings() });
  toast((st.ok ? `TRANSCRIBING ${r.added.length} FILE${r.added.length === 1 ? "" : "S"}…` : "ADDED, BUT A JOB IS ALREADY RUNNING. START TRANSCRIBING WHEN IT FINISHES.") + (r.skipped.length ? " SKIPPED: " + r.skipped.join(", ") : ""), !st.ok);
  loadSingles(); poll();
};
$("#webgo").onclick = async () => {
  const urls = $("#urls").value.split("\n").map(x => x.trim()).filter(Boolean);
  if (!urls.length) { toast("PASTE AT LEAST ONE LINK FIRST.", true); return; }
  const r = await post("/api/start", { mode: "web", urls, quality: $("#wq").value, playlist: $("#wpl").checked, do_transcribe: $("#wtr").checked, do_snapshots: $("#wsn").checked, model: $("#model").value, english: $("#english").checked, snap: snapSettings() });
  toast(r.ok ? "STARTED." : "COULDN'T START (ALREADY RUNNING, OR NO VALID HTTP/HTTPS LINKS).", !r.ok); poll();
};
$("#o-web").onclick = async () => { const r = await post("/api/open", { what: "webvideos" }); if (!r.ok) toast("NOTHING DOWNLOADED YET.", true); };
$("#upd").onclick = async () => { toast("UPDATING THE DOWNLOADER…"); const r = await post("/api/update-downloader"); toast(r.ok ? "DOWNLOADER IS UP TO DATE (" + r.msg + ")." : "UPDATE FAILED: " + r.msg, !r.ok); };

/* ============================== transcribe + snapshots ============================== */
function snapSettings() { return { capture: $("#capture").value, interval: +$("#interval").value, change: +$("#change").value, burst: +$("#burst").value, speech_only: true }; }
$("#go").onclick = async () => {
  const sel = scopeTr.selection();
  const r = await post("/api/start", { mode: "transcribe", model: $("#model").value, english: $("#english").checked, watch: $("#watch").checked, ...(sel ? { select: sel } : {}) });
  toast(r.ok ? (sel ? `TRANSCRIBING ${sel.length} SELECTED VIDEO${sel.length === 1 ? "" : "S"}…` : "TRANSCRIBING…") : "COULDN'T START (ALREADY RUNNING, OR NOTHING SELECTED).", !r.ok); poll();
};
$("#snap").onclick = async () => {
  const sel = scopeSn.selection();
  const r = await post("/api/start", { mode: "snapshots", capture: $("#capture").value, interval: +$("#interval").value, change: +$("#change").value, burst: +$("#burst").value, redo: $("#redo").checked, speech_only: true, select: sel });
  toast(r.ok ? `TAKING SNAPSHOTS OF ${sel.length} SELECTED VIDEO${sel.length === 1 ? "" : "S"}…` : "COULDN'T START (ALREADY RUNNING, OR NOTHING SELECTED).", !r.ok); poll();
};
const PRESETS = {
  frames: { capture: "visual", interval: "1", burst: "10", change: "0" },
  safety: { capture: "combined", interval: "5", burst: "10", change: "1" },
  overview: { capture: "all", interval: "5", burst: "5", change: "1" }
};
function capUI() {
  const c = $("#capture").value;
  $("#l-burst").hidden = c === "all"; $("#h-all").hidden = c !== "all"; $("#h-vis").hidden = c !== "visual"; $("#h-comb").hidden = c !== "combined";
  if (typeof scopeSn !== "undefined") scopeSn.sync();
}
function applyPreset() {
  const p = PRESETS[$("#preset").value]; if (!p) return;
  $("#capture").value = p.capture; $("#interval").value = p.interval; $("#burst").value = p.burst; $("#change").value = p.change; capUI();
}
$("#preset").onchange = applyPreset;
$("#capture").onchange = () => { const c = $("#capture").value; $("#interval").value = c === "visual" ? "1" : "5"; capUI(); markCustom(); };
["interval", "burst", "change"].forEach(i => $("#" + i).addEventListener("change", markCustom));
function markCustom() {
  const p = PRESETS[$("#preset").value]; if (!p) return;
  if (p.capture !== $("#capture").value || p.interval !== $("#interval").value || p.burst !== $("#burst").value || p.change !== $("#change").value) $("#preset").value = "custom";
}
function renderPending() { if (typeof scopeTr !== "undefined") { scopeTr.render(); scopeSn.render(); } }
$("#redo").addEventListener("change", () => scopeSn.sync());
$("#watch").addEventListener("change", () => scopeTr.render());

/* ============================== system ============================== */
$$("[data-open]").forEach(b => b.onclick = async () => { const r = await post("/api/open", { what: b.dataset.open }); if (!r.ok) toast("NOTHING THERE YET.", true); });
$("#retag").onclick = async () => { const r = await post("/api/retag"); toast(Array.isArray(r.msg) ? r.msg[0] : (r.msg || "DONE"), !r.ok); treeDirty = true; poll(); };
$("#o-fail").onclick = () => post("/api/open", { what: ST && ST.mode !== "snapshots" ? "failed" : ({ visual: "snapfailed-visual", combined: "snapfailed-combined" }[ST && ST.capture] || "snapfailed") });
$("#quit").onclick = async () => {
  if (ST && ST.running && !confirm("A job is running. Stop it and quit?")) return;
  await post("/api/quit");
  showClosed();
};
const sleep = ms => new Promise(r => setTimeout(r, ms));
function showClosed() {
  clearInterval(pollTimer);
  document.body.innerHTML = `<main class="closed"><h1>TRANSCRIBER CLOSED</h1>
    <p>The panel has shut down. Everything you finished is saved.</p>
    <div class="row mt"><button class="btn primary big" id="reopen">REOPEN TRANSCRIBER</button><button class="btn" id="closeTab">CLOSE THIS TAB</button></div>
    <p class="hint" id="closedMsg"></p></main>`;
  $("#reopen").onclick = () => reopenFlow(m => { $("#closedMsg").textContent = m; });
  $("#closeTab").onclick = () => {
    window.close(); window.open("", "_self").close();
    setTimeout(() => { $("#closedMsg").textContent = "YOUR BROWSER WON'T LET A PAGE CLOSE ITSELF HERE. CLOSE THIS TAB WITH ⌘W."; }, 500);
  };
}
/* Start the panel again from the browser: a transcriber:// link wakes Transcriber.app, then we wait for the panel and reload into it. */
async function reopenFlow(say) {
  say("STARTING TRANSCRIBER…");
  const a = document.createElement("a"); a.href = "transcriber://open"; document.body.appendChild(a); a.click(); a.remove();
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) {
    await sleep(1200);
    try { const r = await fetch("/api/ping", { cache: "no-store" }); if (r.ok) { say("CONNECTED. LOADING…"); location.reload(); return; } } catch (e) { }
    if (Date.now() - t0 > 12000) say("STILL WAITING… IF YOUR BROWSER ASKED “OPEN TRANSCRIBER?”, CHOOSE OPEN. OTHERWISE DOUBLE-CLICK TRANSCRIBER.APP IN THE TRANSCRIBER FOLDER (OR RUN ./GUI.COMMAND). THIS PAGE RECONNECTS BY ITSELF.");
  }
  say("COULDN'T START IT. DOUBLE-CLICK TRANSCRIBER.APP IN THE TRANSCRIBER FOLDER, THEN RELOAD THIS PAGE.");
}

/* ============================== FILES: tree ============================== */
const OPEN = new Set();
let FILTER = "";
async function loadTree(force) {
  if (!TREE) $("#tree").innerHTML = '<div class="placeholder">LOADING FILES…</div>';
  try { TREE = await get("/api/tree" + (force ? "?force=1" : "")); }
  catch (e) { toast("COULDN'T READ THE FILE LIST: " + e.message, true); return; }
  treeDirty = false; LES = {};
  TREE.courses.forEach(c => c.modules.forEach(m => m.lessons.forEach(l => LES[l.rel] = l)));
  if (SEL && SEL.t === "lesson" && !LES[SEL.rel]) SEL = null;
  renderTree(); renderView(); loadStorage(force); topStats();
}
async function loadStorage(force) {
  let s; try { s = await get("/api/storage" + (force ? "?force=1" : "")); } catch (e) { return; }
  const tr = s.transcripts.bytes, sn = s["snap-all"].bytes + s["snap-visual"].bytes + s["snap-combined"].bytes, dl = s.downloads.bytes, tot = Math.max(tr + sn + dl, 1);
  const seg = (b, c) => `<i style="width:${Math.max(b / tot * 100, b ? 1.5 : 0)}%;background:${c}"></i>`;
  $("#storage").innerHTML = `<span>STORAGE</span><span class="gauge">${seg(tr, "#42ff94")}${seg(sn, "#13803f")}${seg(dl, "#ffc24d")}</span>
    <span>TRANSCRIPTS <b>${bytes(tr)}</b></span><span>SNAPSHOTS <b>${bytes(sn)}</b></span><span>DOWNLOADS <b>${bytes(dl)}</b></span>`;
}
function topStats() {
  if (!TREE) return;
  let l = 0, w = 0, img = 0;
  Object.values(LES).forEach(x => { if (x.transcript) { l++; w += x.words || 0; } Object.values(x.snaps).forEach(s => img += s.count || 0); });
  $("#topstats").innerHTML = `LESSONS <b>${l}</b> · WORDS <b>${num(w)}</b><span class="nl"></span>SNAPSHOT IMAGES <b>${num(img)}</b>`;
}
const courseLabel = n => n || "(LOOSE FILES)";
function lessonMatches(l) { if (!FILTER) return true; return (l.title + " " + l.module + " " + l.course).toLowerCase().includes(FILTER); }
function badges(l) {
  const b = [];
  if (l.transcript) b.push("T"); if (l.cues) b.push("★" + l.cues);
  if (l.snaps.all) b.push("A"); if (l.snaps.visual) b.push("V"); if (l.snaps.combined) b.push("C"); if (l.download) b.push("D"); if (l.findings) b.push("F");
  return b.join(" ");
}
function renderTree() {
  const el = $("#tree");
  if (!TREE) { el.innerHTML = ""; return; }
  if (!TREE.courses.length) { el.innerHTML = '<div class="placeholder">NOTHING HERE YET.<br>TRANSCRIBE OR TAKE SNAPSHOTS FIRST.</div>'; return; }
  const out = [];
  TREE.courses.forEach(c => {
    const mods = c.modules.map(m => ({ m, ls: m.lessons.filter(lessonMatches) })).filter(x => x.ls.length);
    if (!mods.length) return;
    const ck = "c:" + c.name, copen = FILTER || OPEN.has(ck);
    const n = mods.reduce((a, x) => a + x.ls.length, 0);
    out.push(`<button class="tnode ${copen ? "open" : ""} ${SEL && SEL.t === "course" && SEL.course === c.name ? "sel" : ""}" data-k="${esc(ck)}" data-sel='${esc(JSON.stringify({ t: "course", course: c.name }))}'><span class="cv">▶</span><span class="tt">${esc(courseLabel(c.name))}</span><span class="bd">${n}</span></button>`);
    if (!copen) return;
    mods.forEach(({ m, ls }) => {
      const showMod = !(c.modules.length === 1 && m.path === "");
      const mk = "m:" + c.name + "|" + m.path, mopen = !showMod || FILTER || OPEN.has(mk);
      if (showMod) out.push(`<button class="tnode tmod ${mopen ? "open" : ""} ${SEL && SEL.t === "module" && SEL.course === c.name && SEL.path === m.path ? "sel" : ""}" data-k="${esc(mk)}" data-sel='${esc(JSON.stringify({ t: "module", course: c.name, path: m.path }))}'><span class="cv">▶</span><span class="tt">${esc(m.module)}</span><span class="bd">${ls.length}</span></button>`);
      if (!mopen) return;
      ls.forEach(l => out.push(`<button class="tnode ${showMod ? "tles" : "tmod"} ${SEL && SEL.t === "lesson" && SEL.rel === l.rel ? "sel" : ""}" data-sel='${esc(JSON.stringify({ t: "lesson", rel: l.rel }))}' title="${esc(l.title)}"><span class="tt">${esc(l.title)}</span><span class="bd">${badges(l)}</span></button>`));
    });
  });
  el.innerHTML = out.join("") || '<div class="placeholder">NO LESSONS MATCH.</div>';
  const sel = el.querySelector(".sel"); if (sel && !FILTER) sel.scrollIntoView({ block: "nearest" });
}
$("#tree").addEventListener("click", e => {
  const b = e.target.closest(".tnode"); if (!b) return;
  if (b.dataset.k) { OPEN.has(b.dataset.k) ? OPEN.delete(b.dataset.k) : OPEN.add(b.dataset.k); }
  select(JSON.parse(b.dataset.sel));
});
$("#fsearch").addEventListener("input", e => { FILTER = e.target.value.trim().toLowerCase(); renderTree(); });
$("#frefresh").onclick = () => { loadTree(true); toast("FILE LIST REFRESHED."); };
function select(s) { SEL = s; V.tab = null; $("#files").dataset.pane = "view"; renderTree(); renderView(); window.scrollTo(0, 0); }
$("#fview").addEventListener("click", e => { if (e.target.closest("[data-back]")) { $("#files").dataset.pane = "tree"; window.scrollTo(0, 0); } });

/* ============================== FILES: viewer ============================== */
const V = { tab: null, set: null, visOnly: false, q: "", hits: 0, cur: 0 };
const TXT = {};
function findFolder(sel) {
  const c = TREE.courses.find(x => x.name === sel.course); if (!c) return null;
  if (sel.t === "course") return { course: c, lessons: c.modules.flatMap(m => m.lessons), modules: c.modules, label: courseLabel(c.name), rel: c.name, crumbs: "LIBRARY" };
  const m = c.modules.find(x => x.path === sel.path); if (!m) return null;
  return { course: c, module: m, lessons: m.lessons, modules: [], label: m.module, rel: (c.name ? c.name + "/" : "") + m.path, crumbs: "LIBRARY / " + courseLabel(c.name) };
}
function renderView() {
  const v = $("#fview");
  if (!TREE || !SEL) { $("#files").dataset.pane = "tree"; v.innerHTML = '<div class="placeholder">SELECT A COURSE, MODULE OR LESSON TO VIEW ITS FILES.</div>'; return; }
  if (SEL.t === "lesson") return renderLesson(LES[SEL.rel]);
  const f = findFolder(SEL); if (!f) { SEL = null; return renderView(); }
  renderFolder(f);
}
function setCounts(ls) {
  const c = { t: 0, a: 0, v: 0, c: 0, d: 0, words: 0, cues: 0 };
  ls.forEach(l => { if (l.transcript) { c.t++; c.words += l.words || 0; c.cues += l.cues || 0; } if (l.snaps.all) c.a++; if (l.snaps.visual) c.v++; if (l.snaps.combined) c.c++; if (l.download) c.d++; });
  return c;
}
function renderFolder(f) {
  const c = setCounts(f.lessons), isModule = !!f.module;
  if (!V.tab || !["overview", "index", "bundle"].includes(V.tab)) V.tab = "overview";
  const hasIndex = f.course.index, hasBundle = isModule && f.module.bundle;
  $("#fview").innerHTML = `<button class="btn small back" data-back>← LIBRARY</button><div class="fhead"><div class="crumbs">${esc(f.crumbs)}</div><h2>${esc(f.label)}</h2></div>
    <div class="stat4"><div><small>LESSONS</small><b>${f.lessons.length}</b></div><div><small>TRANSCRIBED</small><b>${c.t}</b></div><div><small>WORDS</small><b>${num(c.words)}</b></div>
      <div><small>SNAPSHOT SETS</small><b>${c.a} / ${c.v} / ${c.c}</b></div>${c.d ? `<div><small>DOWNLOADED VIDEOS</small><b>${c.d}</b></div>` : ""}</div>
    <div class="ftabs"><button data-vt="overview" class="${V.tab === "overview" ? "on" : ""}">OVERVIEW</button>
      <button data-vt="index" class="${V.tab === "index" ? "on" : ""}" ${hasIndex ? "" : "disabled"}>INDEX</button>
      ${isModule ? `<button data-vt="bundle" class="${V.tab === "bundle" ? "on" : ""}" ${hasBundle ? "" : "disabled"}>UPLOAD BUNDLE</button>` : ""}</div>
    <div class="toolbar"><span class="grow"></span><button class="btn small" id="vCopy" ${V.tab === "overview" ? "hidden" : ""}>COPY</button>
      <button class="btn small" id="vAi" title="Copy a prompt that points your AI at this ${isModule ? "module" : "course"}">COPY AI PROMPT</button>
      <button class="btn small" id="vReveal">SHOW IN FINDER</button><button class="btn small danger" id="vDelete" ${ST && ST.running ? "disabled title='A job is running'" : ""}>DELETE…</button></div>
    <div id="vbody"></div>`;
  $$("#fview [data-vt]").forEach(b => b.onclick = () => { V.tab = b.dataset.vt; renderFolder(f); });
  $("#vAi").onclick = () => copyAiPrompt({ course: f.course.name, module: isModule ? f.module.path : "", lesson: "" });
  $("#vReveal").onclick = () => revealMenu(f);
  $("#vDelete").onclick = () => openDelete(f);
  const body = $("#vbody");
  if (V.tab === "overview") {
    const rows = isModule ? f.lessons.map(l => `<div class="rw" data-l="${esc(l.rel)}"><span class="t">${esc(l.title)}</span><span class="m">${badges(l)} ${l.dur ? "· " + dur(l.dur) : ""} ${l.words ? "· " + num(l.words) + " W" : ""}</span></div>`)
      : f.modules.map(m => `<div class="rw" data-m="${esc(m.path)}"><span class="t">${esc(m.module)}</span><span class="m">${m.lessons.length} LESSONS · ${m.lessons.filter(l => l.transcript).length} TRANSCRIBED</span></div>`);
    body.innerHTML = `<div class="rows">${rows.join("")}</div>`;
    body.onclick = e => { const r = e.target.closest(".rw"); if (!r) return; if (r.dataset.l) { select({ t: "lesson", rel: r.dataset.l }); } else { OPEN.add("c:" + f.course.name); OPEN.add("m:" + f.course.name + "|" + r.dataset.m); select({ t: "module", course: f.course.name, path: r.dataset.m }); } };
  } else {
    body.onclick = null;
    const kind = V.tab, rel = f.course.name, mod = isModule ? f.module.module : "";
    body.innerHTML = '<div class="viewer md">LOADING…</div>';
    getText(kind, rel, mod).then(t => {
      const vb = $("#vbody .viewer"); if (!vb) return; vb.textContent = t.missing ? "(NOT FOUND)" : t.text + (t.truncated ? "\n\n… (TRUNCATED: FILE IS LARGE)" : "");
      $("#vCopy").onclick = async () => toast(await copyText(t.text) ? "COPIED." : "COULDN'T COPY.", false);
    }).catch(e => { $("#vbody").textContent = e.message; });
  }
}
async function getText(kind, rel, module) {
  const key = kind + "|" + rel + "|" + (module || "");
  if (TXT[key] && TXT[key].v === TREEVER) return TXT[key].t;
  const t = await get(`/api/text?kind=${encodeURIComponent(kind)}&rel=${encodeURIComponent(rel)}&module=${encodeURIComponent(module || "")}`);
  TXT[key] = { v: TREEVER, t }; return t;
}
let TREEVER = 0;

function renderLesson(l) {
  if (!l) { SEL = null; return renderView(); }
  const sets = Object.keys(l.snaps), hasSnaps = sets.length > 0;
  if (!V.tab || !["txt", "ts", "cues", "snaps", "findings"].includes(V.tab)) V.tab = l.transcript ? "txt" : "snaps";
  if (!hasSnaps && V.tab === "snaps") V.tab = "txt";
  if (!V.set || !l.snaps[V.set]) V.set = ["combined", "visual", "all"].find(s => l.snaps[s]) || null;
  const SETN = { all: "OVERVIEW", visual: "VISUAL-ONLY", combined: "COMBINED" };
  const crumbs = ["LIBRARY", courseLabel(l.course), l.module_path ? l.module : ""].filter(Boolean).join(" / ");
  $("#fview").innerHTML = `<button class="btn small back" data-back>← LIBRARY</button><div class="fhead"><div class="crumbs">${esc(crumbs)}</div><h2>${esc(l.title)}</h2></div>
    <div class="chips">${l.transcript ? `<span class="chip hot">TRANSCRIPT · ${num(l.words)} WORDS${l.dur ? " · " + dur(l.dur) : ""}</span>` : '<span class="chip">NO TRANSCRIPT</span>'}
      ${l.cues ? `<span class="chip hot">★ ${l.cues} VISUAL CUES</span>` : ""}
      ${sets.map(s => `<span class="chip hot">${SETN[s]} · ${l.snaps[s].count} IMAGES</span>`).join("")}
      ${l.download ? `<span class="chip">DOWNLOADED VIDEO · ${bytes(l.download.size)}</span>` : ""}</div>
    <div class="ftabs">
      <button data-vt="txt" class="${V.tab === "txt" ? "on" : ""}" ${l.transcript ? "" : "disabled"}>TRANSCRIPT</button>
      <button data-vt="ts" class="${V.tab === "ts" ? "on" : ""}" ${l.transcript ? "" : "disabled"}>TIMESTAMPS</button>
      <button data-vt="cues" class="${V.tab === "cues" ? "on" : ""}" ${l.transcript ? "" : "disabled"}>VISUAL CUES</button>
      <button data-vt="snaps" class="${V.tab === "snaps" ? "on" : ""}" ${hasSnaps ? "" : "disabled"}>SNAPSHOTS</button>
      <button data-vt="findings" class="${V.tab === "findings" ? "on" : ""}" title="Notes an AI keeps about this lesson">AI NOTES${l.findings ? " · " + esc(l.findings.status.toUpperCase()) : ""}</button></div>
    <div class="toolbar">
      <span class="srch" id="srch" ${V.tab === "snaps" ? "hidden" : ""}><input type="search" id="vq" placeholder="SEARCH THIS TEXT…" value="${esc(V.q)}" autocomplete="off" spellcheck="false"><button class="btn small" id="vPrev" title="Previous match">↑</button><button class="btn small" id="vNext" title="Next match">↓</button><span class="cnt" id="vCnt"></span></span>
      <span class="grow"></span><button class="btn small" id="vCopy" ${V.tab === "snaps" ? "hidden" : ""}>COPY</button>
      <button class="btn small" id="vAi" title="Copy a prompt that points your AI at this lesson">COPY AI PROMPT</button>
      <button class="btn small" id="vReveal">SHOW IN FINDER</button><button class="btn small danger" id="vDelete" ${ST && ST.running ? "disabled title='A job is running'" : ""}>DELETE…</button></div>
    <div id="vbody"></div>`;
  $("#vAi").onclick = () => copyAiPrompt({ course: l.course, module: l.module_path, lesson: l.rel });
  $$("#fview [data-vt]").forEach(b => b.onclick = () => { V.tab = b.dataset.vt; V.q = ""; renderLesson(l); });
  $("#vReveal").onclick = () => revealMenu(l);
  $("#vDelete").onclick = () => openDelete(l);
  if (V.tab === "snaps") return renderGallery(l);
  const rawKind = V.tab;
  $("#vbody").innerHTML = '<div class="viewer">LOADING…</div>';
  getText(rawKind, l.rel, "").then(t => {
    const vb = $("#vbody .viewer"); if (!vb) return;
    if (rawKind === "findings" && t.missing) {
      $("#vbody").innerHTML = `<div class="placeholder">NO AI NOTES FOR THIS LESSON YET.<br>An AI creates them as it studies the lesson, or you can start an empty notes file now.<br><br><button class="btn primary" id="mkFind">CREATE NOTES FILE</button></div>`;
      $("#mkFind").onclick = async () => { const r = await post("/api/findings/new", { rel: l.rel }); if (r.error) { toast(r.error, true); return; } toast(r.created ? "NOTES FILE CREATED: " + r.path : "ALREADY EXISTS."); TREEVER++; await loadTree(true); };
      return;
    }
    if (t.missing) { vb.textContent = "(NOT FOUND)"; return; }
    const text = t.text + (t.truncated ? "\n\n… (TRUNCATED: FILE IS LARGE)" : "");
    const draw = () => drawText(vb, text, rawKind === "findings" ? "txt" : rawKind, l);
    draw();
    $("#vCopy").onclick = async () => toast(await copyText(t.text) ? "COPIED." : "COULDN'T COPY.", false);
    const q = $("#vq");
    q.oninput = () => { V.q = q.value; V.cur = 0; draw(); };
    q.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); stepHit(e.shiftKey ? -1 : 1); } };
    $("#vNext").onclick = () => stepHit(1); $("#vPrev").onclick = () => stepHit(-1);
  }).catch(e => { $("#vbody").textContent = e.message; });
}
function drawText(vb, text, kind, l) {
  const q = V.q.trim(), re = q ? new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi") : null;
  let hits = 0;
  const hl = line => { if (!re) return esc(line); return line.split(re).map((p, i) => i % 2 ? (hits++, `<mark>${esc(p)}</mark>`) : esc(p)).join(""); };
  const lines = text.split("\n");
  if (kind === "txt") vb.innerHTML = lines.map(x => hl(x)).join("\n");
  else vb.innerHTML = lines.map(x => {
    const m = /^(\[VISUAL\] )?\[(\d\d):(\d\d):(\d\d)\]/.exec(x);
    if (!m) return `<span class="ln">${hl(x)}</span>`;
    const t = (+m[2]) * 3600 + (+m[3]) * 60 + (+m[4]);
    return `<span class="ln ${m[1] ? "vis" : "ts"}" data-t="${t}" title="Click to see the nearest snapshot">${hl(x)}</span>`;
  }).join("");
  vb.onclick = e => { const s = e.target.closest("[data-t]"); if (s) openNearest(l, +s.dataset.t); };
  V.hits = hits; $("#vCnt").textContent = q ? (hits ? `${Math.min(V.cur + 1, hits)}/${hits}` : "0") : "";
  if (q && hits) markCur(vb);
}
function markCur(vb) { const ms = vb.querySelectorAll("mark"); ms.forEach(m => m.classList.remove("cur")); const m = ms[Math.min(V.cur, ms.length - 1)]; if (m) { m.classList.add("cur"); m.scrollIntoView({ block: "center" }); } }
function stepHit(d) { if (!V.hits) return; V.cur = (V.cur + d + V.hits) % V.hits; const vb = $("#vbody .viewer"); markCur(vb); $("#vCnt").textContent = `${V.cur + 1}/${V.hits}`; }

/* ============================== FILES: gallery + lightbox ============================== */
let LB = { imgs: [], i: 0, mode: "", rel: "" };
async function renderGallery(l) {
  const SETN = { all: "OVERVIEW", visual: "VISUAL-ONLY", combined: "COMBINED" }, sets = ["combined", "visual", "all"].filter(s => l.snaps[s]);
  $("#vbody").innerHTML = `<div class="sets">${sets.map(s => `<button class="btn small ${V.set === s ? "on" : ""}" data-set="${s}">${SETN[s]} (${l.snaps[s].count})</button>`).join("")}
    <label class="chk"><input type="checkbox" id="visOnly" ${V.visOnly ? "checked" : ""}><span>★ VISUAL ONLY</span></label><span class="hint nm" id="gCount"></span></div>
    <div class="grid" id="grid"><div class="placeholder">LOADING…</div></div>`;
  $$("#vbody [data-set]").forEach(b => b.onclick = () => { V.set = b.dataset.set; renderGallery(l); });
  $("#visOnly").onchange = e => { V.visOnly = e.target.checked; renderGallery(l); };
  let list; try { list = (await get(`/api/snaps?mode=${V.set}&rel=${encodeURIComponent(l.rel)}`)).images; } catch (e) { $("#grid").textContent = e.message; return; }
  const shown = V.visOnly ? list.filter(x => x.visual) : list;
  $("#gCount").textContent = `${shown.length} IMAGES · CLICK ONE TO ENLARGE`;
  $("#grid").innerHTML = shown.length ? shown.map((x, i) => `<figure class="${x.visual ? "v" : ""}" data-i="${i}"><img loading="lazy" alt="" src="${imgUrl(V.set, l.rel, x.name)}"><figcaption><span>${hms(x.t)}</span><span></span></figcaption></figure>`).join("") : '<div class="placeholder">NO IMAGES IN THIS VIEW.</div>';
  $("#grid").onclick = e => { const f = e.target.closest("figure"); if (f) openLightbox(shown, +f.dataset.i, V.set, l.rel); };
}
const imgUrl = (mode, rel, name) => `/api/img?mode=${mode}&rel=${encodeURIComponent(rel)}&name=${encodeURIComponent(name)}`;
function openLightbox(imgs, i, mode, rel) { LB = { imgs, i, mode, rel }; $("#lightbox").hidden = false; drawLB(); }
function drawLB() {
  const x = LB.imgs[LB.i]; if (!x) return;
  $("#lightbox").innerHTML = `<div class="lb"><img alt="" src="${imgUrl(LB.mode, LB.rel, x.name)}">
    <div class="cap"><b>${hms(x.t)}</b>${x.visual ? " · ★ VISUAL" : ""} · ${LB.i + 1} OF ${LB.imgs.length}${x.said ? "<br>" + esc(x.said) : ""}</div>
    <div class="bar2"><button class="btn small" id="lbPrev">← PREV</button><button class="btn small" id="lbNext">NEXT →</button><button class="btn small" id="lbReveal">SHOW FILE IN FINDER</button><button class="btn small" id="lbClose">CLOSE</button></div></div>`;
  $("#lbPrev").onclick = () => lbStep(-1); $("#lbNext").onclick = () => lbStep(1); $("#lbClose").onclick = closeLightbox;
  $("#lbReveal").onclick = () => post("/api/reveal", { root: "snap-" + LB.mode, rel: LB.rel + "/" + x.name });
  const nx = LB.imgs[LB.i + 1]; if (nx) new Image().src = imgUrl(LB.mode, LB.rel, nx.name);
}
function lbStep(d) { if (!LB.imgs.length) return; LB.i = (LB.i + d + LB.imgs.length) % LB.imgs.length; drawLB(); }
function closeLightbox() { $("#lightbox").hidden = true; $("#lightbox").innerHTML = ""; }
$("#lightbox").addEventListener("click", e => { if (e.target.id === "lightbox") closeLightbox(); });
let swipeX = null;                                   /* swipe left/right to step through pictures on a touch screen */
$("#lightbox").addEventListener("touchstart", e => { swipeX = e.touches.length === 1 ? e.touches[0].clientX : null; }, { passive: true });
$("#lightbox").addEventListener("touchend", e => { if (swipeX === null) return; const dx = e.changedTouches[0].clientX - swipeX; swipeX = null; if (Math.abs(dx) > 50) lbStep(dx < 0 ? 1 : -1); }, { passive: true });
async function openNearest(l, t) {
  const mode = ["combined", "visual", "all"].find(s => l.snaps[s]);
  if (!mode) { toast("NO SNAPSHOTS FOR THIS LESSON YET.", true); return; }
  let list; try { list = (await get(`/api/snaps?mode=${mode}&rel=${encodeURIComponent(l.rel)}`)).images; } catch (e) { toast(e.message, true); return; }
  if (!list.length) { toast("NO IMAGES IN THAT SET.", true); return; }
  let best = 0; list.forEach((x, i) => { if (Math.abs(x.t - t) < Math.abs(list[best].t - t)) best = i; });
  openLightbox(list, best, mode, l.rel);
}

/* ============================== FILES: modal, reveal, delete ============================== */
function modal(html, cls) { const m = $("#modal"); m.innerHTML = `<div class="dlg ${cls || ""}" role="dialog" aria-modal="true">${html}</div>`; m.hidden = false; const f = m.querySelector("button,input"); if (f) f.focus(); return m.firstElementChild; }
function closeModal() { const m = $("#modal"); m.hidden = true; m.innerHTML = ""; }
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });

function locations(x) {                      /* x: lesson or folder descriptor -> places that exist on disk */
  const out = [];
  if (x.rel !== undefined && x.title !== undefined) {            /* lesson */
    if (x.transcript) out.push({ label: "TRANSCRIPT FILES", root: "transcripts", rel: x.rel + ".txt" });
    ["all", "visual", "combined"].forEach(s => { if (x.snaps[s]) out.push({ label: "SNAPSHOTS: " + { all: "OVERVIEW", visual: "VISUAL-ONLY", combined: "COMBINED" }[s], root: "snap-" + s, rel: x.rel }); });
    if (x.download) { const sub = x.rel.slice(WEB.length + 1), dir = sub.includes("/") ? sub.slice(0, sub.lastIndexOf("/") + 1) : ""; out.push({ label: "DOWNLOADED VIDEO", root: "downloads", rel: dir + x.download.file }); }
  } else {                                                      /* folder */
    const ls = x.lessons;
    if (ls.some(l => l.transcript)) out.push({ label: "TRANSCRIPTS FOLDER", root: "transcripts", rel: x.rel });
    ["all", "visual", "combined"].forEach(s => { if (ls.some(l => l.snaps[s])) out.push({ label: "SNAPSHOTS: " + { all: "OVERVIEW", visual: "VISUAL-ONLY", combined: "COMBINED" }[s], root: "snap-" + s, rel: x.rel }); });
    if (ls.some(l => l.download)) out.push({ label: "DOWNLOADS FOLDER", root: "downloads", rel: x.rel.startsWith(WEB + "/") ? x.rel.slice(WEB.length + 1) : "" });
  }
  return out;
}
function revealMenu(x) {
  const locs = locations(x);
  if (!locs.length) { toast("NOTHING TO SHOW YET.", true); return; }
  const d = modal(`<h2>SHOW IN FINDER</h2><p class="hint top0">Opens the location in a Finder window. Optional: everything is also viewable here.</p>
    ${locs.map((l, i) => `<div class="opt" data-i="${i}" style="grid-template-columns:1fr auto"><span>${esc(l.label)}</span><button class="btn small">OPEN</button></div>`).join("")}
    <div class="row mt"><button class="btn" id="mClose">CLOSE</button></div>`);
  d.querySelectorAll("[data-i]").forEach(r => r.onclick = async () => { const l = locs[+r.dataset.i]; const res = await post("/api/reveal", { root: l.root, rel: l.rel }); if (res.ok === false) toast(res.error || "COULDN'T OPEN", true); });
  $("#mClose").onclick = closeModal;
}

function deleteOptions(x) {
  const opts = [], isLesson = x.title !== undefined;
  const SETN = { all: "OVERVIEW", visual: "VISUAL-ONLY", combined: "COMBINED" };
  const it = (parts, rel) => ({ kind: isLesson ? "lesson" : "folder", rel: rel === undefined ? x.rel : rel, parts });
  const ls = isLesson ? [x] : x.lessons;
  if (ls.some(l => l.transcript)) opts.push({ key: "transcript", label: isLesson ? "TRANSCRIPT FILES (.txt, timestamps, visual cues)" : "TRANSCRIPTS, INDEX AND BUNDLES", items: [it(["transcript"])] });
  ["all", "visual", "combined"].forEach(s => { if (ls.some(l => l.snaps[s])) opts.push({ key: "snap-" + s, label: "SNAPSHOTS: " + SETN[s], items: [it(["snap-" + s])] }); });
  if (ls.some(l => l.download)) {
    let items;
    if (isLesson) items = [it(["download"])];
    else if (x.module) items = [it(["download"])];
    else items = x.modules.filter(m => m.lessons.some(l => l.download)).map(m => ({ kind: "folder", rel: WEB + "/" + m.path, parts: ["download"] }));
    opts.push({ key: "download", label: "DOWNLOADED VIDEO FILE" + (ls.filter(l => l.download).length > 1 ? "S" : ""), items });
  }
  return opts;
}
async function openDelete(x) {
  if (ST && ST.running) { toast("A JOB IS RUNNING. STOP IT OR WAIT FOR IT TO FINISH FIRST.", true); return; }
  const isLesson = x.title !== undefined, title = isLesson ? x.title : x.label, opts = deleteOptions(x);
  if (!opts.length) { toast("NOTHING TO DELETE HERE.", true); return; }
  const d = modal(`<h2>DELETE FILES</h2><p class="hint top0"><b>${esc(title)}</b><br>Choose what to delete. Your original videos are never touched.</p>
    <div id="opts">${opts.map((o, i) => `<label class="opt"><input type="checkbox" data-i="${i}"><span>${esc(o.label)}</span><span class="sz" id="sz${i}">…</span></label>`).join("")}</div>
    <p class="hint" id="dNote"></p><div class="row mt"><button class="btn danger" id="dNext" disabled>DELETE SELECTED…</button><button class="btn" id="dCancel">CANCEL</button></div>`, "bad");
  $("#dCancel").onclick = closeModal;
  const sizes = await Promise.all(opts.map(o => post("/api/delete-preview", { items: o.items })));
  sizes.forEach((r, i) => { const el = $("#sz" + i); if (el) el.textContent = r.error ? "?" : `${r.files} FILES · ${bytes(r.bytes)}`; });
  const sync = () => { const sel = $$("#opts input:checked"); $("#dNext").disabled = !sel.length; $("#dNote").textContent = sel.length ? "SELECTED: " + bytes(sel.reduce((a, c) => a + (sizes[+c.dataset.i].bytes || 0), 0)) : ""; };
  $$("#opts input").forEach(c => c.onchange = sync);
  $("#dNext").onclick = () => confirmDelete(x, opts.filter((o, i) => $$("#opts input")[i].checked), isLesson);
}
function confirmDelete(x, chosen, isLesson) {
  const items = chosen.flatMap(o => o.items), needType = !isLesson || chosen.some(o => o.key === "download");
  const redo = chosen.some(o => o.key === "transcript" || o.key.startsWith("snap-")), dl = chosen.some(o => o.key === "download");
  const d = modal(`<h2>CONFIRM PERMANENT DELETE</h2>
    <p class="hint top0">This cannot be undone. You are about to delete:</p><ul>${chosen.map(o => `<li>${esc(o.label)}</li>`).join("")}</ul>
    ${redo ? '<p class="hint">Deleted transcripts and snapshot sets are not backed up. Because the lessons will count as “not done”, the next run can recreate them if the video is still linked.</p>' : ""}
    ${dl ? '<p class="hint">Downloaded videos are removed from videos/Web videos. Pasting the link again will download it again.</p>' : ""}
    ${needType ? '<p class="hint">Type <b>DELETE</b> to confirm:</p><input type="text" id="dType" autocomplete="off" spellcheck="false">' : ""}
    <div class="row mt"><button class="btn danger" id="dGo" ${needType ? "disabled" : ""}>DELETE FOREVER</button><button class="btn" id="dBack">CANCEL</button></div>`, "bad");
  $("#dBack").onclick = closeModal;
  if (needType) { const t = $("#dType"); t.focus(); t.oninput = () => $("#dGo").disabled = t.value.trim() !== "DELETE"; t.onkeydown = e => { if (e.key === "Enter" && !$("#dGo").disabled) $("#dGo").click(); }; }
  $("#dGo").onclick = async () => {
    $("#dGo").disabled = true; $("#dGo").textContent = "DELETING…";
    const r = await post("/api/delete", { items });
    closeModal();
    if (r.error || r.ok === false) { toast("NOT DELETED: " + (r.error || "UNKNOWN ERROR"), true); return; }
    toast(`DELETED ${r.files} FILES (${bytes(r.bytes)})${r.errors && r.errors.length ? ". PROBLEMS: " + r.errors.join("; ") : "."}`, !!(r.errors && r.errors.length));
    TREEVER++; treeDirty = true; await loadTree(true); poll();
  };
}

/* ============================== what to process: selection lists ============================== */
let SRC = null;
async function loadSources() {
  try { SRC = (await get("/api/sources")).videos; } catch (e) { return; }
  scopeTr.sync(); scopeSn.sync(); renderWebList();
}
class Scope {
  constructor(el, kind) {
    this.el = el; this.kind = kind; this.sel = new Set(); this.touched = false; this.open = new Set(); this.inited = false;
    el.addEventListener("click", e => this.onClick(e));
    el.addEventListener("change", e => this.onChange(e));
  }
  redo() { return this.kind === "snapshots" && $("#redo").checked; }
  off() { return this.kind === "transcribe" && $("#watch").checked; }
  key() { return $("#capture").value || "all"; }
  can(v) { return !v.broken && (this.redo() || (this.kind === "transcribe" ? !v.done_tr : !v.snaps[this.key()])); }
  selection() { return this.off() ? null : [...this.sel]; }
  sync() {                                           /* default: everything that is waiting; keep the user's own choices once they've made some */
    const ok = new Set((SRC || []).filter(v => this.can(v)).map(v => v.rel));
    this.sel = this.touched ? new Set([...this.sel].filter(r => ok.has(r))) : ok;
    this.render();
  }
  groups() {
    const g = new Map();
    (SRC || []).forEach(v => {
      if (!g.has(v.course)) g.set(v.course, { name: v.course, kind: v.kind, mods: new Map() });
      const c = g.get(v.course); if (!c.mods.has(v.module)) c.mods.set(v.module, []); c.mods.get(v.module).push(v);
    });
    return [...g.values()];
  }
  render() {
    const el = this.el; if (!el) return;
    const tr = this.kind === "transcribe", verb = tr ? "TRANSCRIBED" : "SNAPSHOTTED";
    if (SRC === null) { el.innerHTML = '<div class="note">LOADING…</div>'; return; }
    el.classList.toggle("off", this.off());
    if (!SRC.length) { el.innerHTML = '<div class="note">NO VIDEOS FOUND YET. ADD A COURSE FOLDER, PICK FILES, OR DOWNLOAD SOME IN THE SOURCES TAB.</div>'; this.button(0); return; }
    const old = el.querySelector(".scope-body"), top = old ? old.scrollTop : 0, groups = this.groups();
    if (!this.inited) { this.inited = true; if (SRC.length <= 30) groups.forEach(c => { this.open.add("c:" + c.name); c.mods.forEach((v, m) => this.open.add("m:" + c.name + "|" + m)); }); }
    const tags = { course: "COURSE", single: "PICKED FILES", web: "WEB VIDEOS" };
    let h = `<div class="scope-top"><span class="ttl">PICK WHAT TO ${tr ? "TRANSCRIBE" : "SNAPSHOT"}</span>
      <button class="btn small" data-act="all">SELECT ALL WAITING</button><button class="btn small" data-act="none">NONE</button>
      <button class="btn small ghost" data-act="expand">EXPAND / COLLAPSE</button><button class="btn small ghost" data-act="refresh" title="Re-read the video list">↻</button>
      ${SRC.some(v => v.broken) ? `<button class="btn small danger" data-act="clear" title="Remove the shortcuts whose original files are gone">CLEAR ${SRC.filter(v => v.broken).length} MISSING</button>` : ""}</div><div class="scope-body">`;
    const row = v => {
      const can = this.can(v), done = !can && !v.broken;
      const meta = v.broken ? "ORIGINAL NOT FOUND" : done ? (tr ? "✓ DONE" : "✓ HAS THESE SNAPSHOTS") : (v.dur ? dur(v.dur) : "WAITING");
      return `<label class="srow ${done ? "done" : ""} ${v.broken ? "broken" : ""}"><input type="checkbox" data-v="${esc(v.rel)}" ${this.sel.has(v.rel) ? "checked" : ""} ${can ? "" : "disabled"}><span class="t" title="${esc(v.title)}">${esc(v.title)}</span><span class="m">${meta}</span></label>`;
    };
    groups.forEach(c => {
      const all = [...c.mods.values()].flat(), waiting = all.filter(v => this.can(v)).length, ck = "c:" + c.name, copen = this.open.has(ck);
      const label = c.kind === "single" ? "SINGLE FILES" : c.kind === "web" ? "WEB VIDEOS" : (c.name || "(LOOSE FILES)");
      h += `<div class="sg-row"><input type="checkbox" data-g="${esc(ck)}" ${waiting ? "" : "disabled"} aria-label="Select all in ${esc(label)}"><button class="sg-h ${copen ? "open" : ""}" data-tog="${esc(ck)}"><span class="cv">▶</span><span class="nm">${esc(label)}</span><span class="tag">${tags[c.kind]}</span><span class="ct">${waiting} WAITING · ${all.length}</span></button></div>`;
      if (!copen) return;
      c.mods.forEach((vs, m) => {
        if (m) {
          const mk = "m:" + c.name + "|" + m, mopen = this.open.has(mk), mw = vs.filter(v => this.can(v)).length;
          h += `<div class="sg-row sg-mod"><input type="checkbox" data-g="${esc(mk)}" ${mw ? "" : "disabled"} aria-label="Select all in ${esc(m)}"><button class="sg-h ${mopen ? "open" : ""}" data-tog="${esc(mk)}"><span class="cv">▶</span><span class="nm">${esc(m)}</span><span class="ct">${mw} WAITING · ${vs.length}</span></button></div>`;
          if (mopen) h += vs.map(v => row(v).replace('class="srow', 'class="srow sg-mod2')).join("");
        } else h += vs.map(row).join("");
      });
    });
    const chosen = SRC.filter(v => this.sel.has(v.rel)), secs = chosen.reduce((a, v) => a + (v.dur || 0), 0), skipped = SRC.filter(v => !this.can(v) && !v.broken).length;
    h += `</div><div class="scope-sum">${this.off()
      ? "WATCH MODE IS ON: EVERYTHING NEW IN ALL SOURCES WILL BE TRANSCRIBED AS IT ARRIVES. THE SELECTION IS NOT USED."
      : `WILL ${tr ? "TRANSCRIBE" : "TAKE SNAPSHOTS OF"} <b>${chosen.length}</b> OF ${SRC.length} VIDEOS${secs ? ` · ABOUT <b>${etaTxt(secs)}</b> OF VIDEO` : ""} · ${skipped} ALREADY ${verb} (SKIPPED)${chosen.length ? "" : " · <b>NOTHING SELECTED</b>"}`}</div>`;
    el.innerHTML = h;
    const nb = el.querySelector(".scope-body"); if (nb) nb.scrollTop = top;
    $$("[data-g]", el).forEach(cb => {                                   /* tri-state group boxes */
      const vs = this.under(cb.dataset.g).filter(v => this.can(v)), n = vs.filter(v => this.sel.has(v.rel)).length;
      cb.checked = vs.length > 0 && n === vs.length; cb.indeterminate = n > 0 && n < vs.length;
    });
    this.button(chosen.length);
  }
  under(g) {                                                           /* videos under a course ("c:name") or module ("m:name|module") */
    if (g.startsWith("c:")) return SRC.filter(v => v.course === g.slice(2));
    const i = g.indexOf("|"); return SRC.filter(v => v.course === g.slice(2, i) && v.module === g.slice(i + 1));
  }
  button(n) {
    const b = this.kind === "transcribe" ? $("#go") : $("#snap"), run = ST && ST.running, w = this.kind === "transcribe" ? "START TRANSCRIBING" : "TAKE SNAPSHOTS";
    b.textContent = this.off() ? "START WATCHING" : (n ? `${w} (${n})` : w);
    b.disabled = !!run || (!this.off() && n === 0);
  }
  onClick(e) {
    const tog = e.target.closest("[data-tog]"), act = e.target.closest("[data-act]");
    if (tog) { const k = tog.dataset.tog; this.open.has(k) ? this.open.delete(k) : this.open.add(k); this.render(); }
    if (!act) return;
    if (act.dataset.act === "all") { this.touched = false; this.sync(); }
    if (act.dataset.act === "none") { this.touched = true; this.sel = new Set(); this.render(); }
    if (act.dataset.act === "refresh") { loadSources(); toast("VIDEO LIST REFRESHED."); }
    if (act.dataset.act === "clear") clearMissingFlow();
    if (act.dataset.act === "expand") {
      const anyOpen = this.open.size > 0; this.open = new Set();
      if (!anyOpen) this.groups().forEach(c => { this.open.add("c:" + c.name); c.mods.forEach((v, m) => this.open.add("m:" + c.name + "|" + m)); });
      this.render();
    }
  }
  onChange(e) {
    const cb = e.target; this.touched = true;
    if (cb.dataset.v) cb.checked ? this.sel.add(cb.dataset.v) : this.sel.delete(cb.dataset.v);
    if (cb.dataset.g) this.under(cb.dataset.g).filter(v => this.can(v)).forEach(v => cb.checked ? this.sel.add(v.rel) : this.sel.delete(v.rel));
    this.render();
  }
}
const scopeTr = new Scope($("#scopeTr"), "transcribe"), scopeSn = new Scope($("#scopeSn"), "snapshots");

function renderWebList() {
  const el = $("#webList"), items = (SRC || []).filter(v => v.kind === "web");
  if (!items.length) { el.className = "list empty"; el.textContent = "NOTHING DOWNLOADED YET"; return; }
  el.className = "list";
  el.innerHTML = items.map(v => `<div class="item"><div class="nm">${esc(v.title)}</div>
    <div class="acts"><button class="btn small" data-wv="${esc(v.rel)}">VIEW FILES</button></div>
    <div class="meta">${esc(v.module || "SINGLE VIDEOS")} · ${v.done_tr ? '<span class="ok">✓ TRANSCRIBED</span>' : '<span class="no">NOT TRANSCRIBED YET</span>'}${v.size ? " · " + bytes(v.size) : ""}${v.dur ? " · " + dur(v.dur) : ""}</div></div>`).join("");
}
$("#webList").addEventListener("click", e => {
  const b = e.target.closest("[data-wv]"); if (!b) return;
  const rel = b.dataset.wv.replace(/\.[^./]+$/, "");
  if (!LES[rel]) { toast("NOTHING TO SHOW YET: TRANSCRIBE IT FIRST.", true); return; }
  SEL = { t: "lesson", rel }; V.tab = null; OPEN.add("c:" + LES[rel].course); OPEN.add("m:" + LES[rel].course + "|" + LES[rel].module_path); $("#files").dataset.pane = "view"; setTab("files"); renderTree(); renderView();
});

/* ============================== clear dead shortcuts (originals that are gone) ============================== */
async function clearMissingFlow() {
  if (ST && ST.running) { toast("A JOB IS RUNNING. WAIT FOR IT TO FINISH FIRST.", true); return; }
  const r = await post("/api/clear-missing", { dry_run: true });
  const names = r.names || [];
  if (!names.length) { toast("NOTHING MISSING."); loadSources(); loadSingles(); return; }
  const d = modal(`<h2>CLEAR MISSING FILES</h2>
    <p class="hint top0">These ${names.length} shortcut${names.length === 1 ? "" : "s"} point to files that no longer exist (moved or deleted):</p>
    <ul>${names.slice(0, 25).map(n => `<li>${esc(n)}</li>`).join("")}${names.length > 25 ? `<li>…and ${names.length - 25} more</li>` : ""}</ul>
    <p class="hint">This only removes the dead shortcuts. Nothing else is touched: transcripts and snapshots already made stay (you can delete them in the FILES tab).</p>
    <div class="row mt"><button class="btn primary" id="cmGo">REMOVE ${names.length} SHORTCUT${names.length === 1 ? "" : "S"}</button><button class="btn" id="cmNo">CANCEL</button></div>`);
  $("#cmNo").onclick = closeModal;
  $("#cmGo").onclick = async () => {
    $("#cmGo").disabled = true;
    const x = await post("/api/clear-missing", {});
    closeModal();
    if (x.error) { toast(x.error, true); return; }
    toast(`REMOVED ${x.names.length} DEAD SHORTCUT${x.names.length === 1 ? "" : "S"}.`);
    await loadSources(); loadSingles(); poll();
  };
}

/* ============================== themed drop-down menus ============================== */
const DDS = [];
function closeAllDD(except) { DDS.forEach(d => { if (d !== except) d.close(); }); }
document.addEventListener("pointerdown", e => { if (!e.target.closest(".dd, .dd-list")) closeAllDD(); }, true);
addEventListener("resize", () => closeAllDD());
addEventListener("scroll", e => { if (!(e.target.closest && e.target.closest(".dd-list"))) closeAllDD(); }, true);
function enhanceSelect(sel) {
  if (sel._dd) return;
  const wrap = document.createElement("div"); wrap.className = "dd";
  const btn = document.createElement("button"); btn.type = "button"; btn.className = "dd-btn"; btn.setAttribute("aria-haspopup", "listbox"); btn.setAttribute("aria-expanded", "false");
  wrap.appendChild(btn); sel.classList.add("dd-native"); sel.tabIndex = -1; sel.setAttribute("aria-hidden", "true"); sel.after(wrap);
  const ul = document.createElement("ul"); ul.className = "dd-list"; ul.setAttribute("role", "listbox"); ul.hidden = true; document.body.appendChild(ul);
  const longest = Math.max(0, ...[...sel.options].map(o => o.text.length));
  btn.style.setProperty("--dd-min", `calc(${longest + 2}ch + ${(longest * 0.04).toFixed(2)}em + 34px)`);   /* phones override this in CSS */
  let act = -1, typed = "", typedT;
  const refresh = () => { const o = sel.options[sel.selectedIndex]; btn.textContent = o ? o.text : ""; btn.disabled = sel.disabled; wrap.classList.toggle("off", sel.disabled); };
  const mark = () => $$(".dd-opt", ul).forEach((li, i) => li.classList.toggle("act", i === act));
  const dd = {
    close(focus) { if (ul.hidden) return; ul.hidden = true; wrap.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); if (focus) btn.focus(); },
    open() {
      if (sel.disabled) return; closeAllDD(dd);
      ul.innerHTML = [...sel.options].map((o, i) => `<li class="dd-opt" role="option" data-i="${i}" aria-selected="${i === sel.selectedIndex}">${esc(o.text)}</li>`).join("");
      act = sel.selectedIndex; mark();
      const r = btn.getBoundingClientRect(), limit = innerHeight - ($("#dock") ? $("#dock").offsetHeight : 0) - 8;
      ul.style.minWidth = r.width + "px"; ul.style.maxWidth = Math.min(innerWidth - 16, 640) + "px"; ul.style.visibility = "hidden"; ul.hidden = false;
      const h = ul.offsetHeight, w = ul.offsetWidth;
      let top = r.bottom + 4; if (top + h > limit && r.top - h - 4 > 8) top = r.top - h - 4; else if (top + h > limit) { top = Math.max(8, limit - h); ul.style.maxHeight = (limit - top) + "px"; }
      ul.style.top = top + "px"; ul.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px"; ul.style.visibility = "";
      wrap.classList.add("open"); btn.setAttribute("aria-expanded", "true");
      const a = ul.children[act]; if (a) a.scrollIntoView({ block: "nearest" });
    },
    choose(i) { if (i < 0 || i >= sel.options.length) return; const changed = i !== sel.selectedIndex; sel.selectedIndex = i; refresh(); dd.close(true); if (changed) sel.dispatchEvent(new Event("change", { bubbles: true })); },
    refresh
  };
  const move = d => { act = Math.max(0, Math.min(sel.options.length - 1, act + d)); mark(); const a = ul.children[act]; if (a) a.scrollIntoView({ block: "nearest" }); };
  btn.addEventListener("click", () => ul.hidden ? dd.open() : dd.close());
  btn.addEventListener("keydown", e => {
    const isOpen = !ul.hidden;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); isOpen ? move(e.key === "ArrowDown" ? 1 : -1) : dd.open(); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); isOpen ? dd.choose(act) : dd.open(); }
    else if (e.key === "Escape" && isOpen) { e.preventDefault(); e.stopPropagation(); dd.close(true); }
    else if (e.key === "Tab" && isOpen) dd.close();
    else if (e.key === "Home" && isOpen) { e.preventDefault(); act = 0; mark(); ul.scrollTop = 0; }
    else if (e.key === "End" && isOpen) { e.preventDefault(); act = sel.options.length - 1; mark(); ul.scrollTop = ul.scrollHeight; }
    else if (e.key.length === 1 && !e.metaKey && !e.ctrlKey) {                                   /* type-ahead */
      typed += e.key.toLowerCase(); clearTimeout(typedT); typedT = setTimeout(() => typed = "", 700);
      const i = [...sel.options].findIndex(o => o.text.toLowerCase().startsWith(typed));
      if (i >= 0) { if (isOpen) { act = i; mark(); const a = ul.children[i]; if (a) a.scrollIntoView({ block: "nearest" }); } else dd.choose(i); }
    }
  });
  ul.addEventListener("pointerdown", e => e.preventDefault());
  ul.addEventListener("click", e => { const li = e.target.closest(".dd-opt"); if (li) dd.choose(+li.dataset.i); });
  ul.addEventListener("pointermove", e => { const li = e.target.closest(".dd-opt"); if (li && +li.dataset.i !== act) { act = +li.dataset.i; mark(); } });
  const lbl = sel.closest("label");
  if (lbl) lbl.addEventListener("click", e => { if (e.target.closest(".dd")) return; e.preventDefault(); btn.focus(); dd.open(); });
  const desc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");     /* keep the button in step when code sets .value */
  Object.defineProperty(sel, "value", { configurable: true, get() { return desc.get.call(sel); }, set(v) { desc.set.call(sel, v); refresh(); } });
  new MutationObserver(refresh).observe(sel, { attributes: true, attributeFilter: ["disabled"] });
  sel._dd = dd; DDS.push(dd); refresh();
}
$$("select").forEach(enhanceSelect);

/* ============================== AI tab: prompt builder + notes ============================== */
const AIQ = { course: "", module: "", lesson: "" };
let aiTimer = null;
function aiParams() {
  return new URLSearchParams({ task: $("#aiTask").value, course: AIQ.course, module: AIQ.module, lesson: AIQ.lesson, goal: $("#aiGoal").value });
}
async function aiFetchPrompt(extra) {
  const q = new URLSearchParams(extra || aiParams());
  return (await get("/api/ai/prompt?" + q.toString())).prompt;
}
async function copyAiPrompt(focus) {
  try {
    const text = await aiFetchPrompt({ task: $("#aiTask").value, course: focus.course || "", module: focus.module || "", lesson: focus.lesson || "", goal: "" });
    toast(await copyText(text) ? "AI PROMPT COPIED. PASTE IT INTO YOUR AI." : "COULDN'T COPY. OPEN THE AI TAB TO COPY IT BY HAND.", false);
  } catch (e) { toast("COULDN'T BUILD THE PROMPT: " + e.message, true); }
}
function setSelect(sel, items, value) {                       /* items: [[value, label]] */
  sel.innerHTML = items.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  sel.value = items.some(i => i[0] === value) ? value : items[0][0];
  if (sel._dd) sel._dd.refresh();
}
function aiFillSelects() {
  if (!TREE) return;
  const courses = TREE.courses;
  setSelect($("#aiCourse"), [["", "ALL COURSES"], ...courses.map(c => [c.name, c.name || "(LOOSE FILES)"])], AIQ.course);
  AIQ.course = $("#aiCourse").value;
  const c = courses.find(x => x.name === AIQ.course);
  const mods = c ? c.modules.filter(m => m.path) : [];
  setSelect($("#aiModule"), [["", mods.length ? "ALL MODULES" : "(NO MODULES)"], ...mods.map(m => [m.path, m.module])], AIQ.module);
  AIQ.module = $("#aiModule").value;
  let ls = [];
  if (c) ls = (AIQ.module ? c.modules.filter(m => m.path === AIQ.module) : c.modules).flatMap(m => m.lessons);
  setSelect($("#aiLesson"), [["", c ? "ALL LESSONS" : "(PICK A COURSE FIRST)"], ...ls.map(l => [l.rel, l.title])], AIQ.lesson);
  AIQ.lesson = $("#aiLesson").value;
}
async function aiBuild() {
  try { $("#aiPrompt").value = await aiFetchPrompt(); $("#aiMsg").textContent = ""; }
  catch (e) { $("#aiPrompt").value = ""; $("#aiMsg").textContent = "COULDN'T BUILD THE PROMPT: " + e.message; }
}
async function aiStatus() {
  let s; try { s = await get("/api/ai/status"); } catch (e) { return; }
  const f = s.findings, ok = b => b ? '<span class="ok">✓ READY</span>' : '<span class="no">NOT CREATED YET</span>';
  $("#aiStatus").innerHTML = `ROOT FOLDER: <code>${esc(s.root)}</code><br>AI-GUIDE.MD (layout, formats, how to take notes): ${ok(s.guide)}<br>LIBRARY.MD (map of every course, module and lesson): ${ok(s.library)}<br>AI NOTES (findings/): <b>${f.total}</b> FILE${f.total === 1 ? "" : "S"} · ${f.done} DONE · ${f["in-progress"]} IN PROGRESS · ${f["not-started"]} NOT STARTED`;
}
async function aiOpen() {
  if (!TREE) await loadTree();
  aiFillSelects(); aiBuild(); aiStatus();
}
["aiCourse", "aiModule", "aiLesson"].forEach(id => $("#" + id).addEventListener("change", () => {
  AIQ.course = $("#aiCourse").value; if (id === "aiCourse") { AIQ.module = ""; AIQ.lesson = ""; }
  if (id === "aiModule") { AIQ.module = $("#aiModule").value; AIQ.lesson = ""; }
  if (id === "aiLesson") AIQ.lesson = $("#aiLesson").value;
  aiFillSelects(); aiBuild();
}));
$("#aiTask").addEventListener("change", aiBuild);
$("#aiGoal").addEventListener("input", () => { clearTimeout(aiTimer); aiTimer = setTimeout(aiBuild, 350); });
$("#aiCopy").onclick = async () => { const ok = await copyText($("#aiPrompt").value); $("#aiMsg").textContent = ok ? "COPIED ✓ PASTE IT INTO YOUR AI" : "COULDN'T COPY: SELECT THE TEXT AND PRESS ⌘C"; setTimeout(() => $("#aiMsg").textContent = "", 5000); };
$("#aiRefresh").onclick = async () => { toast("REFRESHING THE GUIDE FILES…"); const r = await post("/api/ai/refresh"); if (r.error) { toast(r.error, true); return; } toast("GUIDE AND LIBRARY MAP REFRESHED."); treeDirty = true; await loadTree(true); aiFillSelects(); aiBuild(); aiStatus(); };
$("#aiOpenFindings").onclick = async () => { const r = await post("/api/reveal", { root: "findings", rel: "" }); if (r.ok === false) toast("NO NOTES FOLDER YET.", true); };
$$("[data-aiview]").forEach(b => b.onclick = async () => {
  const kind = { guide: "aiguide", library: "library", findingsindex: "findingsindex" }[b.dataset.aiview];
  let t; try { t = await get(`/api/text?kind=${kind}&rel=`); } catch (e) { toast(e.message, true); return; }
  const d = modal(`<h2>${esc(b.textContent.replace("VIEW ", ""))}</h2><p class="hint top0">${t.missing ? "Not created yet. Click REFRESH GUIDE FILES first." : "This is what your AI is told to read."}</p>
    <div class="viewer md">${esc(t.text || "")}</div><div class="row mt"><button class="btn" id="mCopy">COPY</button><button class="btn" id="mClose">CLOSE</button></div>`);
  d.classList.add("wide"); $("#mClose").onclick = closeModal; $("#mCopy").onclick = async () => toast(await copyText(t.text || "") ? "COPIED." : "COULDN'T COPY.");
});

/* ============================== start-up ============================== */
let pollTimer;
/* keep the page's bottom padding in step with the dock's height (it grows when a job runs or the log is open) */
(function dockFit() {
  const d = $("#dock"), fit = () => { document.body.style.paddingBottom = (d.offsetHeight + 28) + "px"; $("#toast").style.bottom = (d.offsetHeight + 16) + "px"; };
  if (window.ResizeObserver) new ResizeObserver(fit).observe(d); else addEventListener("resize", fit);
  fit();
})();
(function init() {
  applyPreset();
  const sub = store.get("sub"); if (sub) { const b = $(`#srcSeg [data-sub="${sub}"]`); if (b) b.click(); }
  setTab((location.hash || "").slice(1) || store.get("tab") || "sources", false);
  poll().then(() => { loadSources(); if (!TREE) setTimeout(() => loadTree(), 600); });
  pollTimer = setInterval(poll, 1500);
  addEventListener("hashchange", () => setTab((location.hash || "").slice(1), false));
})();
