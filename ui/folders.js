"use strict";
/* MY FOLDERS: your own folders for sorting lessons in the FILES tab.
   They are labels only. No transcript, snapshot or video is ever moved, renamed or deleted here.
   State (MODE, FOLD, FM, PLACE, INF) is declared in app.js; the data is saved by organizer.py. */

const NAT = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
const MSEL = new Set();                 /* lessons ticked in the folder pane */
let MFID = null, DRAG = null;
const allLessons = () => Object.values(LES);

/* ------------------------------------------------------------ placement */
function folderOf(l) {
  const a = FOLD.assign || {}, keys = ["l:" + l.rel], segs = l.module_path ? l.module_path.split("/") : [];
  for (let i = segs.length; i >= 1; i--) keys.push("m:" + (l.course ? l.course + "/" : "") + segs.slice(0, i).join("/"));
  if (l.course) keys.push("c:" + l.course);
  for (const k of keys) if (k in a) return a[k];
  return "";
}
function indexFolders() {
  FM = {}; (FOLD.folders || []).forEach(f => FM[f.id] = f);
  PLACE = {}; INF = {};
  allLessons().forEach(l => { const id = FM[folderOf(l)] ? folderOf(l) : ""; PLACE[l.rel] = id; (INF[id] = INF[id] || []).push(l); });
  MSEL.forEach(r => { if (!LES[r]) MSEL.delete(r); });
}
const kidsOf = id => (FOLD.folders || []).filter(f => (f.parent || null) === (id || null)).sort((a, b) => NAT.compare(a.name, b.name));
function pathOf(id) { const out = []; let cur = FM[id], n = 0; while (cur && n++ < 20) { out.unshift(cur); cur = cur.parent ? FM[cur.parent] : null; } return out; }
const pathName = id => pathOf(id).map(f => f.name).join(" / ");
const countAll = id => (INF[id] || []).length + kidsOf(id).reduce((a, k) => a + countAll(k.id), 0);
const countShown = id => (INF[id] || []).filter(lessonMatches).length + kidsOf(id).reduce((a, k) => a + countShown(k.id), 0);
function descendants(id) { const out = new Set(); const walk = x => kidsOf(x).forEach(k => { out.add(k.id); walk(k.id); }); walk(id); return out; }

/* Turn ticked lessons into the fewest labels: a whole channel (or module) becomes ONE label, so lessons added later follow it. */
function groupBy(list, fn) { const o = {}; list.forEach(x => { const k = fn(x); (o[k] = o[k] || []).push(x); }); return o; }
function compress(rels) {
  const sel = new Set(rels), keys = [], wholes = [], byC = groupBy(allLessons(), l => l.course);
  Object.keys(byC).forEach(c => {
    const ls = byC[c], picked = ls.filter(l => sel.has(l.rel));
    if (!picked.length) return;
    if (c !== "" && picked.length === ls.length) { keys.push("c:" + c); wholes.push(c); return; }
    const byM = groupBy(ls, l => l.module_path);
    Object.keys(byM).forEach(p => {
      const ms = byM[p], pk = ms.filter(l => sel.has(l.rel));
      if (!pk.length) return;
      const nested = Object.keys(byM).some(q => q !== p && q.startsWith(p + "/"));
      if (c !== "" && p !== "" && !nested && pk.length === ms.length) { keys.push("m:" + c + "/" + p); wholes.push(c + " / " + ms[0].module); }
      else pk.forEach(l => keys.push("l:" + l.rel));
    });
  });
  return { keys, wholes, lessonKeys: rels.map(r => "l:" + r) };
}

/* ------------------------------------------------------------ talking to the server */
async function applyAssign(keys, folder) {
  const before = Object.assign({}, PLACE);
  const r = await post("/api/folders/assign", { keys, folder: folder || null });
  if (r.ok === false || r.error) { toast(r.error || "COULDN'T MOVE THAT.", true); return false; }
  FOLD = { folders: r.folders, assign: r.assign }; indexFolders();
  const n = Object.keys(PLACE).filter(k => before[k] !== PLACE[k]).length;
  if (folder) OPEN.add("f:" + folder);
  toast(n ? `MOVED ${n} LESSON${n === 1 ? "" : "S"} TO ${folder ? "“" + pathName(folder) + "”" : "UNSORTED"}.` : "THEY WERE ALREADY THERE.");
  renderTree(); renderView(); return true;
}
async function folderCall(act, body) {
  const r = await post("/api/folders/" + act, body);
  if (r.ok === false || r.error) throw new Error(r.error || "That didn't work.");
  FOLD = { folders: r.folders, assign: r.assign }; indexFolders(); return r;
}

/* ------------------------------------------------------------ dialogs */
/* One folder chooser used for: move lessons, move a folder, make a folder.
   o: { title, note, exclude:Set, rootLabel, start (null | "" | id), okLabel, keep:{label}, createOnly } -> {value, keep} | null */
function pickFolder(o) {
  return new Promise(resolve => {
    let chosen = o.start === undefined ? null : o.start, done = false;
    const exclude = o.exclude || new Set();
    const rows = (parent, depth) => kidsOf(parent).filter(f => !exclude.has(f.id)).map(f =>
      `<button class="pk ${chosen === f.id ? "on" : ""}" data-v="${f.id}" style="padding-left:${10 + depth * 16}px"><span class="pkn">${esc(f.name)}</span><span class="pkc">${countAll(f.id)}</span></button>` + rows(f.id, depth + 1)).join("");
    const d = modal(`<h2>${esc(o.title)}</h2>${o.note ? `<p class="hint top0">${o.note}</p>` : ""}
      <div class="pklist" id="pkList"></div>
      <div class="pknew"><input type="text" id="pkName" maxlength="80" placeholder="NEW FOLDER NAME…" autocomplete="off" spellcheck="false"><button class="btn small" id="pkMake">CREATE</button></div>
      <p class="hint bad-t" id="pkErr" hidden></p>
      ${o.keep ? `<label class="chk mfkeep"><input type="checkbox" id="pkKeep" checked><span>${o.keep.label}</span></label>` : ""}
      <div class="row mt">${o.createOnly ? "" : `<button class="btn primary" id="pkOk" disabled>${esc(o.okLabel || "MOVE HERE")}</button>`}<button class="btn" id="pkCancel">${o.createOnly ? "CLOSE" : "CANCEL"}</button></div>`, "mf");
    const draw = () => {
      $("#pkList").innerHTML = `<button class="pk root ${chosen === "" ? "on" : ""}" data-v=""><span class="pkn">${esc(o.rootLabel)}</span></button>` + rows(null, 0);
      const mk = $("#pkMake"); mk.textContent = chosen ? "CREATE INSIDE THE SELECTED FOLDER" : "CREATE AT TOP LEVEL";
      const ok = $("#pkOk"); if (ok) ok.disabled = chosen === null;
    };
    const finish = v => { if (done) return; done = true; closeModal(); resolve(v); };
    draw();
    $("#pkList").onclick = e => { const b = e.target.closest(".pk"); if (!b) return; chosen = b.dataset.v; draw(); };
    $("#pkCancel").onclick = () => finish(null);
    if ($("#pkOk")) $("#pkOk").onclick = () => finish({ value: chosen, keep: $("#pkKeep") ? $("#pkKeep").checked : false });
    const make = async () => {
      const name = $("#pkName").value.trim(), err = $("#pkErr"); err.hidden = true;
      if (!name) { err.textContent = "TYPE A NAME FIRST."; err.hidden = false; return; }
      try {
        const r = await folderCall("create", { name, parent: chosen || null });
        if (chosen) OPEN.add("f:" + chosen);
        OPEN.add("f:" + r.id); chosen = r.id; $("#pkName").value = "";
        renderTree();
        if (o.createOnly) { toast(`FOLDER “${pathName(r.id)}” CREATED.`); finish({ value: r.id, created: true }); return; }
        draw();
      } catch (e) { err.textContent = e.message.toUpperCase(); err.hidden = false; }
    };
    $("#pkMake").onclick = make;
    $("#pkName").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); make(); } };
    if (o.createOnly) $("#pkName").focus();
    if (d.querySelector(".pk.on")) d.querySelector(".pk.on").scrollIntoView({ block: "nearest" });
  });
}
function textDialog(title, value, okLabel, note) {
  return new Promise(resolve => {
    modal(`<h2>${esc(title)}</h2>${note ? `<p class="hint top0">${note}</p>` : ""}<input type="text" id="tdIn" maxlength="80" autocomplete="off" spellcheck="false" value="${esc(value)}">
      <p class="hint bad-t" id="tdErr" hidden></p><div class="row mt"><button class="btn primary" id="tdOk">${esc(okLabel)}</button><button class="btn" id="tdNo">CANCEL</button></div>`, "mf");
    const inp = $("#tdIn"); inp.focus(); inp.select();
    $("#tdNo").onclick = () => { closeModal(); resolve(null); };
    const go = () => { const v = inp.value.trim(); if (!v) { $("#tdErr").textContent = "TYPE A NAME FIRST."; $("#tdErr").hidden = false; return; } closeModal(); resolve(v); };
    $("#tdOk").onclick = go; inp.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); go(); } };
  });
}
function confirmDialog(title, html, okLabel, cls) {
  return new Promise(resolve => {
    modal(`<h2>${esc(title)}</h2>${html}<div class="row mt"><button class="btn ${cls || "primary"}" id="cfOk">${esc(okLabel)}</button><button class="btn" id="cfNo">CANCEL</button></div>`, cls === "danger" ? "bad" : "");
    $("#cfNo").onclick = () => { closeModal(); resolve(false); };
    $("#cfOk").onclick = () => { closeModal(); resolve(true); };
  });
}

/* ------------------------------------------------------------ moving */
async function moveLessons(rels) {
  if (!rels.length) return;
  const plan = compress(rels), n = rels.length;
  const wl = plan.wholes.slice(0, 2).map(w => `“${esc(w)}”`).join(", ") + (plan.wholes.length > 2 ? " …" : "");
  const r = await pickFolder({
    title: `MOVE ${n} LESSON${n === 1 ? "" : "S"} TO…`, rootLabel: "UNSORTED (NO FOLDER)", start: null, okLabel: "MOVE HERE",
    note: "Only labels change. Your transcripts, snapshots and videos stay exactly where they are.",
    keep: plan.wholes.length ? { label: `ALSO PUT FUTURE LESSONS FROM ${wl} IN THIS FOLDER` } : null,
  });
  if (r) applyAssign(r.keep ? plan.keys : plan.lessonKeys, r.value);
}
function moveGroup(course, path, lessons) {            /* a whole channel or module from the BY CHANNEL view */
  const whole = course !== "" && (path === null || path !== "");
  if (!whole) return moveLessons(lessons.map(l => l.rel));
  const key = path === null ? "c:" + course : "m:" + course + "/" + path, label = path === null ? course : lessons[0].module;
  const nested = path !== null && allLessons().some(l => l.course === course && l.module_path.startsWith(path + "/"));
  if (nested) return moveLessons(lessons.map(l => l.rel));
  pickFolder({ title: `MOVE “${label}” TO…`, rootLabel: "UNSORTED (NO FOLDER)", start: null, okLabel: "MOVE HERE",
    note: "Moves all of its lessons, and lessons added to it later. Only labels change; no files are moved." })
    .then(r => { if (r) applyAssign([key], r.value); });
}

/* ------------------------------------------------------------ tree (left side) */
function renderFoldTree() {
  const el = $("#tree"), out = [], isSel = id => SEL && ((SEL.t === "mf" && SEL.id === id) || (SEL.t === "lesson" && (PLACE[SEL.rel] || "_") === id));
  const draw = (f, depth) => {
    const ks = kidsOf(f.id), n = countShown(f.id);
    if (FILTER && !n) return;
    const key = "f:" + f.id, open = (FILTER || OPEN.has(key)) && ks.length;
    out.push(`<button class="tnode tfold ${open ? "open" : ""} ${isSel(f.id) ? "sel" : ""}" draggable="true" style="padding-left:${10 + depth * 14}px" data-k="${key}" data-fid="${f.id}" data-sel='${esc(JSON.stringify({ t: "mf", id: f.id }))}'><span class="cv" ${ks.length ? "" : 'style="visibility:hidden"'}>▶</span><span class="tt">${esc(f.name)}</span><span class="bd">${n}</span></button>`);
    if (open) ks.forEach(k => draw(k, depth + 1));
  };
  kidsOf(null).forEach(f => draw(f, 0));
  const un = (INF[""] || []).filter(lessonMatches).length;
  if (!FOLD.folders.length) out.unshift('<div class="placeholder small">NO FOLDERS YET.<br>MAKE ONE WITH + NEW FOLDER, THEN SORT YOUR LESSONS INTO IT.</div>');
  out.push(`<div class="tsep"></div><button class="tnode tun ${isSel("_") ? "sel" : ""}" data-fid="_" data-sel='${esc(JSON.stringify({ t: "mf", id: "_" }))}'><span class="cv" style="visibility:hidden">▶</span><span class="tt">UNSORTED</span><span class="bd">${un}</span></button>`);
  el.innerHTML = out.join("");
  const sel = el.querySelector(".sel"); if (sel && !FILTER) sel.scrollIntoView({ block: "nearest" });
}

/* ------------------------------------------------------------ folder pane (right side) */
function folderTag(rels) {
  if (!rels.length || !FOLD.folders.length) return "";
  const ids = [...new Set(rels.map(r => PLACE[r] || ""))];
  if (ids.length !== 1) return `<div class="mf-in">MY FOLDERS: SPLIT ACROSS ${ids.length} PLACES</div>`;
  if (!ids[0]) return `<div class="mf-in">MY FOLDERS: <a data-gof="_">UNSORTED</a></div>`;
  return `<div class="mf-in">MY FOLDER: ${pathOf(ids[0]).map(f => `<a data-gof="${f.id}">${esc(f.name)}</a>`).join(" / ")}</div>`;
}
function backToFolderBtn(l) { const id = PLACE[l.rel] || "_"; return `<button class="btn small" data-gof="${id}">← ${esc(id === "_" ? "UNSORTED" : FM[id].name)}</button>`; }
function gotoFolder(id) { if (MODE !== "mf") setMode("mf", true); pathOf(id).slice(0, -1).forEach(f => OPEN.add("f:" + f.id)); select({ t: "mf", id }); }

function renderMF(sel) {
  const un = sel.id === "_", f = un ? null : FM[sel.id];
  if (!un && !f) { SEL = null; return renderView(); }
  const id = un ? "" : f.id, subs = un ? [] : kidsOf(id), mine = INF[id] || [], here = mine.filter(lessonMatches);
  if (MFID !== sel.id) { MSEL.clear(); MFID = sel.id; }
  [...MSEL].forEach(r => { if (!here.some(l => l.rel === r)) MSEL.delete(r); });
  const deep = countAll(id) - mine.length, tr = mine.filter(l => l.transcript), words = tr.reduce((a, l) => a + (l.words || 0), 0);
  const crumbs = un ? "MY FOLDERS" : ["MY FOLDERS"].concat(pathOf(id).slice(0, -1).map(x => `<a data-gof="${x.id}">${esc(x.name)}</a>`)).join(" / ");
  const byC = new Map();
  here.forEach(l => { if (!byC.has(l.course)) byC.set(l.course, new Map()); const m = byC.get(l.course); if (!m.has(l.module_path)) m.set(l.module_path, []); m.get(l.module_path).push(l); });
  const chk = (extra) => `<label class="mfc"><input type="checkbox" ${extra || ""}></label>`;
  const rows = [];
  byC.forEach((mods, course) => {
    if (course !== "") rows.push(`<div class="mfg" draggable="true" data-g='${esc(JSON.stringify(["c", course]))}'>${chk()}<span class="mfn">${esc(courseLabel(course))}</span><span class="m">${[...mods.values()].reduce((a, x) => a + x.length, 0)}</span></div>`);
    mods.forEach((ls, path) => {
      if (path !== "") rows.push(`<div class="mfg d1" draggable="true" data-g='${esc(JSON.stringify(["m", course, path]))}'>${chk()}<span class="mfn">${esc(ls[0].module)}</span><span class="m">${ls.length}</span></div>`);
      const d = path !== "" ? "d2" : course !== "" ? "d1" : "";
      ls.forEach(l => rows.push(`<div class="mfl ${d}" draggable="true" data-r="${esc(l.rel)}">${chk()}<button class="mft" data-open="${esc(l.rel)}" title="${esc(l.title)}">${esc(l.title)}</button><span class="m">${badges(l)}${l.dur ? " · " + dur(l.dur) : ""}</span></div>`));
    });
  });
  const folderBtns = un ? "" : `<button class="btn small" id="mfSub">+ NEW SUBFOLDER</button><button class="btn small" id="mfRen">RENAME</button><button class="btn small" id="mfMv">MOVE FOLDER…</button><button class="btn small danger" id="mfDel">DELETE FOLDER…</button>`;
  $("#fview").innerHTML = `<button class="btn small back" data-back>← MY FOLDERS</button><div class="fhead"><div class="crumbs">${crumbs}</div><h2>${un ? "UNSORTED" : esc(f.name)}</h2></div>
    <div class="stat4"><div><small>LESSONS HERE</small><b>${mine.length}</b></div>${un ? "" : `<div><small>IN SUBFOLDERS</small><b>${deep}</b></div>`}<div><small>TRANSCRIBED</small><b>${tr.length}</b></div><div><small>WORDS</small><b>${num(words)}</b></div></div>
    ${un ? '<p class="hint top0">Lessons you have not put in a folder yet. Tick some, then MOVE SELECTED, or drag them onto a folder on the left.</p>' : `<div class="toolbar">${folderBtns}</div>`}
    ${subs.length ? `<div class="rows mfsub">${subs.map(k => `<div class="rw" data-f="${k.id}" data-fid="${k.id}"><span class="t">▣ ${esc(k.name)}</span><span class="m">${countShown(k.id)} LESSONS${kidsOf(k.id).length ? " · " + kidsOf(k.id).length + " SUBFOLDERS" : ""}</span></div>`).join("")}</div>` : ""}
    ${here.length ? `<div class="toolbar mfbar"><label class="chk"><input type="checkbox" id="mfAll"><span>SELECT ALL</span></label><span class="hint nm" id="mfCnt"></span><span class="grow"></span><button class="btn small primary" id="mfMove" disabled>MOVE SELECTED…</button></div>` : ""}
    <div id="mfBody" class="mfbody">${rows.join("") || (FILTER ? '<div class="placeholder small">NO LESSONS HERE MATCH THE FILTER.</div>' : `<div class="placeholder small">${un ? "EVERYTHING IS SORTED INTO A FOLDER." : "NOTHING IN THIS FOLDER YET.<br>OPEN BY CHANNEL, OR UNSORTED, AND MOVE LESSONS HERE."}</div>`)}</div>`;
  const body = $("#mfBody");
  const groupRels = g => { const p = JSON.parse(g); return here.filter(l => l.course === p[1] && (p[0] === "c" || l.module_path === p[2])).map(l => l.rel); };
  const sync = () => {
    $$(".mfl", body).forEach(r => r.querySelector("input").checked = MSEL.has(r.dataset.r));
    $$(".mfg", body).forEach(h => { const rs = groupRels(h.dataset.g), n = rs.filter(r => MSEL.has(r)).length, i = h.querySelector("input"); i.checked = n > 0 && n === rs.length; i.indeterminate = n > 0 && n < rs.length; });
    const all = $("#mfAll"); if (all) { all.checked = here.length > 0 && MSEL.size === here.length; all.indeterminate = MSEL.size > 0 && MSEL.size < here.length; }
    const c = $("#mfCnt"), b = $("#mfMove"); if (c) c.textContent = MSEL.size ? `${MSEL.size} SELECTED` : `${here.length} LESSON${here.length === 1 ? "" : "S"}`; if (b) b.disabled = !MSEL.size;
  };
  sync();
  body.onchange = e => {
    const row = e.target.closest(".mfl, .mfg"); if (!row) return;
    const rs = row.dataset.r ? [row.dataset.r] : groupRels(row.dataset.g);
    rs.forEach(r => e.target.checked ? MSEL.add(r) : MSEL.delete(r)); sync();
  };
  body.onclick = e => { const o = e.target.closest("[data-open]"); if (o) { SEL = { t: "lesson", rel: o.dataset.open }; V.tab = null; renderTree(); renderView(); window.scrollTo(0, 0); } };
  if ($("#mfAll")) $("#mfAll").onchange = e => { here.forEach(l => e.target.checked ? MSEL.add(l.rel) : MSEL.delete(l.rel)); sync(); };
  if ($("#mfMove")) $("#mfMove").onclick = () => moveLessons([...MSEL]);
  $$("#fview .mfsub .rw").forEach(r => r.onclick = () => gotoFolder(r.dataset.f));
  if (!un) {
    $("#mfSub").onclick = () => pickFolder({ title: "NEW SUBFOLDER", rootLabel: "TOP LEVEL", start: id, createOnly: true, note: "Type a name. It is created inside the folder that is highlighted." });
    $("#mfRen").onclick = async () => { const v = await textDialog("RENAME FOLDER", f.name, "RENAME"); if (v && v !== f.name) { try { await folderCall("rename", { id, name: v }); toast("RENAMED."); renderTree(); renderView(); } catch (e) { toast(e.message.toUpperCase(), true); } } };
    $("#mfMv").onclick = async () => {
      const r = await pickFolder({ title: `MOVE “${f.name}” TO…`, rootLabel: "TOP LEVEL", start: null, exclude: new Set([id, ...descendants(id)]), okLabel: "MOVE HERE", note: "The folder keeps everything inside it." });
      if (!r || (r.value || null) === (f.parent || null)) return;
      try { await folderCall("move", { id, parent: r.value || null }); if (r.value) OPEN.add("f:" + r.value); toast("FOLDER MOVED."); renderTree(); renderView(); } catch (e) { toast(e.message.toUpperCase(), true); }
    };
    $("#mfDel").onclick = async () => {
      const up = f.parent ? "“" + FM[f.parent].name + "”" : "UNSORTED", nSub = kidsOf(id).length;
      const ok = await confirmDialog("DELETE FOLDER", `<p class="hint top0"><b>${esc(f.name)}</b></p><p class="hint">Only the folder is removed. <b>No transcripts, snapshots or videos are deleted.</b> The ${mine.length} lesson${mine.length === 1 ? "" : "s"} directly inside${nSub ? " and " + nSub + " subfolder" + (nSub === 1 ? "" : "s") : ""} move up to ${up}.</p>`, "DELETE FOLDER", "danger");
      if (!ok) return;
      try { await folderCall("delete", { id }); toast("FOLDER DELETED. YOUR LESSONS WERE NOT TOUCHED."); SEL = f.parent ? { t: "mf", id: f.parent } : { t: "mf", id: "_" }; renderTree(); renderView(); } catch (e) { toast(e.message.toUpperCase(), true); }
    };
  }
}

/* ------------------------------------------------------------ mode switch, new folder, links */
function setMode(m, keep) {
  MODE = m; store.set("fmode", m);
  $$("#fmodeSeg button").forEach(b => b.classList.toggle("on", b.dataset.fm === m));
  $("#fnew").hidden = m !== "mf";
  $("#fsearch").placeholder = m === "mf" ? "FILTER LESSONS IN FOLDERS…  ( / )" : "FILTER LESSONS…  ( / )";
  if (!keep) { if (!(SEL && SEL.t === "lesson")) SEL = null; if (SEL) $("#files").dataset.pane = "view"; else $("#files").dataset.pane = "tree"; }
  renderTree(); renderView();
}
$("#fmodeSeg").addEventListener("click", e => { const b = e.target.closest("[data-fm]"); if (b && b.dataset.fm !== MODE) setMode(b.dataset.fm); });
$("#fnewBtn").onclick = () => pickFolder({ title: "NEW FOLDER", rootLabel: "TOP LEVEL", start: SEL && SEL.t === "mf" && SEL.id !== "_" ? SEL.id : "", createOnly: true,
  note: "Type a name and press CREATE. Highlight a folder first to make it a subfolder." });
document.addEventListener("click", e => { const a = e.target.closest("[data-gof]"); if (a && a.dataset.gof !== undefined) { e.preventDefault(); gotoFolder(a.dataset.gof); } });
setMode(MODE, true);

/* ------------------------------------------------------------ drag and drop (mouse): lessons or groups onto a folder, folders onto a folder */
const clearDrop = () => $$(".drop").forEach(x => x.classList.remove("drop"));
document.addEventListener("dragstart", e => {
  const lesson = e.target.closest && e.target.closest(".mfl"), grp = e.target.closest && e.target.closest(".mfg"), fold = e.target.closest && e.target.closest(".tfold");
  DRAG = null;
  if (lesson) {
    const rels = MSEL.has(lesson.dataset.r) ? [...MSEL] : [lesson.dataset.r];
    DRAG = { keys: rels.map(r => "l:" + r), n: rels.length };
  } else if (grp) {
    const p = JSON.parse(grp.dataset.g), rels = allLessons().filter(l => PLACE[l.rel] === (SEL && SEL.id !== "_" ? SEL.id : "") && l.course === p[1] && (p[0] === "c" || l.module_path === p[2])).map(l => l.rel);
    DRAG = { keys: compress(rels).keys, n: rels.length };
  } else if (fold) DRAG = { folder: fold.dataset.fid };
  if (DRAG) { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", "transcriber-folder-move"); }
});
document.addEventListener("dragover", e => {
  const t = DRAG && e.target.closest && e.target.closest("[data-fid]"); if (!t) return;
  if (DRAG.folder && (t.dataset.fid === "_" || t.dataset.fid === DRAG.folder || descendants(DRAG.folder).has(t.dataset.fid))) return;
  e.preventDefault(); clearDrop(); t.classList.add("drop");
});
document.addEventListener("dragleave", e => { const t = e.target.closest && e.target.closest("[data-fid]"); if (t && !t.contains(e.relatedTarget)) t.classList.remove("drop"); });
document.addEventListener("dragend", () => { DRAG = null; clearDrop(); });
document.addEventListener("drop", async e => {
  const t = DRAG && e.target.closest && e.target.closest("[data-fid]"); if (!t) return;
  e.preventDefault(); const d = DRAG; DRAG = null; clearDrop();
  if (d.folder) {
    try { await folderCall("move", { id: d.folder, parent: t.dataset.fid }); OPEN.add("f:" + t.dataset.fid); toast("FOLDER MOVED."); renderTree(); renderView(); } catch (err) { toast(err.message.toUpperCase(), true); }
  } else applyAssign(d.keys, t.dataset.fid === "_" ? "" : t.dataset.fid);
});
