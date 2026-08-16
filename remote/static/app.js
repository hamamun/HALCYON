/* Halcyon mobile remote — phone-side logic (§R.3).
   One SSE stream from /api/events carries the whole snapshot (PC is the
   source of truth); every button tap posts a small command to /api/cmd.
   The server marshals commands onto the Qt thread, so the phone is a
   second doorway, never a second implementation (§4.1). */
"use strict";

/* ----------------------------- helpers ----------------------------- */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

function fmtTime(sec) {
  if (!isFinite(sec) || sec < 0) sec = 0;
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = (h > 0 && m < 10 ? "0" : "") + m;
  const ss = (s < 10 ? "0" : "") + s;
  return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;
}

function cmd(action, payload) {
  payload = payload || {};
  return fetch("/api/cmd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, payload }),
  }).catch((e) => console.warn("cmd failed", action, e));
}

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

/* ----------------------------- state ----------------------------- */
let SNAP = null;         // latest snapshot
let FILE = { path: null, mode: "play" };   // drive browser state
let SUBL = new Set();    // subtitle language selection
let WEBM = null;         // last web media status
let WM_VOLUME_PENDING = null;
let WM_VOLUME_FRAME = null;
// NOTE: the collapsible Local sections keep their own open/closed state inside
// makeCollapser() below, so snapshots can never re-open or close them.
let M3U_EXPANDED = null; // remembered expanded groups (null = auto first time)
let M3U_LAST_HTML = "";  // cached html to avoid DOM churn + innerHTML normalization mismatch
let M3U_LAST_COUNT = -1;
let M3U_LAST_GROUPING = "";
let PL_LAST_CUR = -1;    // last rendered playlist currentIndex (autoscroll guard)

/* ----------------------------- chips ----------------------------- */
function setChip(mode) {
  document.querySelectorAll(".chip").forEach((c) =>
    c.classList.toggle("active", c.dataset.mode === mode));
  ["local", "m3u", "web"].forEach((m) => {
    const el = $("screen-" + m);
    if (el) el.hidden = (m !== mode);
  });
}

document.querySelectorAll(".chip").forEach((btn) => {
  btn.addEventListener("click", () => {
    cmd("switchMode", { id: btn.dataset.mode });
    setChip(btn.dataset.mode);      // optimistic; snapshot confirms
  });
});

/* ----------------------------- transport ----------------------------- */
document.querySelectorAll("[data-cmd]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const c = btn.dataset.cmd;
    if (c === "seekBack") cmd("seekRelative", { ms: -10000 });
    else if (c === "seekFwd") cmd("seekRelative", { ms: 10000 });
    else cmd(c, {});
  });
});

$("seek").addEventListener("input", (e) => {
  const f = Number(e.target.value) / 1000;
  const dur = (SNAP && SNAP.player.duration > 0) ? SNAP.player.duration : 0;
  $("tCur").textContent = dur ? fmtTime(f * dur) : fmtTime(f * 3600);
});
$("seek").addEventListener("change", (e) => {
  cmd("seekFraction", { f: Number(e.target.value) / 1000 });
});

let PLAYER_VOLUME_PENDING = null;
let PLAYER_VOLUME_FRAME = null;

// Native-player volume uses the same range-input rule as Web media: `input`
// gives live updates while dragging, while `change` guarantees the final
// value is committed after the finger/mouse is released.
function sendPlayerVolume(value, commit) {
  const next = Math.max(0, Math.min(100, Number(value) || 0));
  PLAYER_VOLUME_PENDING = next;

  if (commit) {
    if (PLAYER_VOLUME_FRAME !== null) {
      cancelAnimationFrame(PLAYER_VOLUME_FRAME);
      PLAYER_VOLUME_FRAME = null;
    }
    const finalValue = PLAYER_VOLUME_PENDING;
    PLAYER_VOLUME_PENDING = null;
    cmd("setVolume", { volume: finalValue });
    return;
  }

  if (PLAYER_VOLUME_FRAME !== null) return;
  PLAYER_VOLUME_FRAME = requestAnimationFrame(() => {
    PLAYER_VOLUME_FRAME = null;
    const frameValue = PLAYER_VOLUME_PENDING;
    PLAYER_VOLUME_PENDING = null;
    if (frameValue !== null) {
      cmd("setVolume", { volume: frameValue });
    }
  });
}

function bindVolume(sliderId) {
  $(sliderId).addEventListener("input", (e) => {
    sendPlayerVolume(e.target.value, false);
  });
  $(sliderId).addEventListener("change", (e) => {
    sendPlayerVolume(e.target.value, true);
  });
}
bindVolume("vol");
bindVolume("vol2");

// While the user is dragging a slider, the live snapshot must not fight the
// drag by overwriting the value under their finger.
function isDragging(el) { return el === document.activeElement; }

if ($("muteBtn")) $("muteBtn").addEventListener("click", () => cmd("toggleMute", {}));
if ($("muteBtn2")) $("muteBtn2").addEventListener("click", () => cmd("toggleMute", {}));
$("rate").addEventListener("change", (e) => cmd("setRate", { rate: Number(e.target.value) }));

$("subDelayMinus").addEventListener("click", () => cmd("adjustSubtitleDelay", { delta: -500 }));
$("subDelayPlus").addEventListener("click", () => cmd("adjustSubtitleDelay", { delta: 500 }));

$("audioTrack").addEventListener("change", (e) => cmd("setAudioTrack", { id: Number(e.target.value) }));
$("subTrack").addEventListener("change", (e) => cmd("setSubtitleTrack", { id: Number(e.target.value) }));

/* ----------------------------- playlist ----------------------------- */
$("shuffleBtn").addEventListener("click", () => cmd("toggleShuffle", {}));
$("repeatBtn").addEventListener("click", () => cmd("cycleRepeat", {}));
$("clearPlBtn").addEventListener("click", () => {
  if (confirm("Clear the whole playlist?")) cmd("clearPlaylist", {});
});

function renderPlaylist(pl) {
  const box = $("playlist");
  // track count stays visible on the header while the list is collapsed
  const plc = $("plCount");
  if (plc) plc.textContent = pl.rows.length ? String(pl.rows.length) : "";
  if (!pl.rows.length) {
    if (box.innerHTML !== '<div class="status">Playlist is empty</div>') {
      box.innerHTML = '<div class="status">Playlist is empty</div>';
    }
    return;
  }
  let html = "";
  pl.rows.forEach((row, i) => {
    html += `<div class="row${i === pl.currentIndex ? " current" : ""}">
      <button class="play" data-pl="play" data-i="${i}" title="Play">▶</button>
      <div class="rname">${esc(row.title)}</div>
      <button data-pl="up" data-i="${i}" title="Move up">▲</button>
      <button data-pl="down" data-i="${i}" title="Move down">▼</button>
      <button data-pl="remove" data-i="${i}" title="Remove">✕</button>
    </div>`;
  });
  if (box.innerHTML !== html) {
    box.innerHTML = html;
    box.querySelectorAll("button[data-pl]").forEach((b) => {
      b.addEventListener("click", () => {
        const i = Number(b.dataset.i);
        const act = b.dataset.pl;
        if (act === "play") cmd("playIndex", { index: i });
        else if (act === "up") cmd("moveItem", { from: i, to: Math.max(0, i - 1) });
        else if (act === "down") cmd("moveItem", { from: i, to: Math.min(pl.rows.length - 1, i + 1) });
        else if (act === "remove") cmd("clearSelected", { rows: [i] });
      });
    });
  }
  // autoscroll the current row into the visible window (7 rows) — only when
  // the current track actually changed, so the list doesn't fight the user's
  // own scrolling on every 500 ms snapshot push.
  if (pl.currentIndex >= 0 && pl.currentIndex !== PL_LAST_CUR) {
    const el = box.querySelector(".row.current");
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  PL_LAST_CUR = pl.currentIndex >= 0 ? pl.currentIndex : -1;
  $("shuffleBtn").classList.toggle("on", pl.shuffle);
  const rl = ["Repeat off", "Repeat all", "Repeat one"];
  $("repeatBtn").textContent = pl.repeatMode === 1 ? "🔂" : "🔁";
  $("repeatBtn").title = rl[pl.repeatMode] || rl[0];
}

/* ----------------------------- drive browser ----------------------------- */
let fbMode = "play";   // "play" | "subtitle"

$("browseBtn").addEventListener("click", () => openFileBrowser("play"));
$("subsFileBtn").addEventListener("click", () => openFileBrowser("subtitle"));
$("addFolderBtn").addEventListener("click", () => {
  if (confirm("Browse and add a folder to the playlist?")) openFileBrowser("addfolder");
});

function openFileBrowser(mode) {
  fbMode = mode;
  FILE.path = null;
  $("fbTitle").textContent = mode === "play" ? "Select file to play"
    : mode === "subtitle" ? "Select subtitle file" : "Select folder to add";
  const addBtn = $("fbAddFolderBtn");
  if (addBtn) addBtn.hidden = true;
  $("fileOverlay").hidden = false;
  loadDrives();
}

$("fbClose").addEventListener("click", () => { $("fileOverlay").hidden = true; });
$("fbUp").addEventListener("click", () => {
  if (FILE.path == null) return;
  const p = FILE.parent;
  if (p == null) loadDrives(); else browseDir(p);
});
// Add-folder mode: confirm the folder currently open (adds its media to the
// playlist, matching the PC's Add Folder behaviour).
$("fbAddFolderBtn").addEventListener("click", () => {
  if (FILE.path) {
    cmd("addPaths", { paths: [FILE.path] });
    $("fileOverlay").hidden = true;
  }
});

async function loadDrives() {
  FILE.path = null; FILE.parent = null;
  $("fbPath").textContent = "My PC";
  try {
    const data = await getJSON("/api/drives");
    $("fbBody").innerHTML = data.drives.map((d) =>
      `<div class="row"><button class="play">💽</button><div class="rname">${esc(d.name)}</div><button class="play" data-drive="${esc(d.path)}">›</button></div>`
    ).join("") || '<div class="status">No drives found</div>';
    $("fbBody").querySelectorAll("[data-drive]").forEach((b) =>
      b.addEventListener("click", () => browseDir(b.dataset.drive)));
  } catch (e) {
    $("fbBody").innerHTML = '<div class="status err">Could not read drives</div>';
  }
}

async function browseDir(path) {
  try {
    const data = await getJSON("/api/browse?path=" + encodeURIComponent(path));
    FILE.path = data.path; FILE.parent = data.parent;
    $("fbPath").textContent = data.path || "My PC";
    let html = "";
    data.folders.forEach((f) => {
      html += `<div class="row"><button class="play">📁</button><div class="rname">${esc(f.name)}</div>` +
              `<button class="play" data-dir="${esc(f.path)}">›</button></div>`;
    });
    data.files.forEach((f) => {
      const icon = f.kind === "video" ? "🎬" : f.kind === "audio" ? "🎵" : "📝";
      html += `<div class="row"><button class="play">${icon}</button><div class="rname">${esc(f.name)}</div>`;
      if (fbMode === "play") {
        // spec: ▶ = play on PC · ＋ = add to playlist without playing
        html += `<button class="play" data-file-add="${esc(f.path)}" title="Add to playlist">＋</button>`;
        html += `<button class="play" data-file-play="${esc(f.path)}" title="Play on PC">▶</button>`;
      } else if (fbMode === "subtitle" && f.kind === "subtitle") {
        html += `<button class="play" data-file-sub="${esc(f.path)}">Load</button>`;
      }
      html += "</div>";
    });
    html = html || '<div class="status">No media files here</div>';
    $("fbBody").innerHTML = html;
    // In add-folder mode the confirm button at the bottom of the sheet acts on
    // the folder currently open.
    const addBtn = $("fbAddFolderBtn");
    if (addBtn) { addBtn.hidden = fbMode !== "addfolder" || !FILE.path; }
    $("fbBody").querySelectorAll("[data-dir]").forEach((b) =>
      b.addEventListener("click", () => browseDir(b.dataset.dir)));
    $("fbBody").querySelectorAll("[data-file-play]").forEach((b) =>
      b.addEventListener("click", () => { cmd("openPath", { path: b.dataset.filePlay }); $("fileOverlay").hidden = true; }));
    $("fbBody").querySelectorAll("[data-file-add]").forEach((b) =>
      b.addEventListener("click", () => { cmd("addPaths", { paths: [b.dataset.fileAdd] }); }));
    $("fbBody").querySelectorAll("[data-file-sub]").forEach((b) =>
      b.addEventListener("click", () => { cmd("loadSubtitleFile", { path: b.dataset.fileSub }); $("fileOverlay").hidden = true; }));
  } catch (e) {
    $("fbBody").innerHTML = '<div class="status err">Cannot open this folder</div>';
  }
}

/* ----------------------------- subtitle download ----------------------------- */
$("subsDownloadBtn").addEventListener("click", () => {
  const name = SNAP && SNAP.subs && SNAP.subs.mediaName;
  if (name && !$("sbQuery").value.trim()) $("sbQuery").value = name;
  $("subsOverlay").hidden = false;
});
$("sbClose").addEventListener("click", () => { $("subsOverlay").hidden = true; });
$("sbSearch").addEventListener("click", () => cmd("subs.search", { query: $("sbQuery").value }));
$("sbQuery").addEventListener("keydown", (e) => {
  if (e.key === "Enter") cmd("subs.search", { query: $("sbQuery").value });
});

function renderSubs(subs) {
  $("sbQuery").placeholder = subs.mediaName ? "Search — e.g. " + subs.mediaName : "Search…";
  $("sbStatus").textContent = subs.status || "";
  $("sbStatus").className = "status" + (subs.statusIsError ? " err" : subs.status ? " ok" : "");
  const langs = subs.languages || [];
  const langHtml = langs.map((l) =>
    `<button class="langchip${SUBL.has(l) ? " on" : ""}" data-lang="${esc(l)}">${esc(l)}</button>`).join("");
  if ($("sbLangs").innerHTML !== langHtml) {
    $("sbLangs").innerHTML = langHtml;
    $("sbLangs").querySelectorAll(".langchip").forEach((b) =>
      b.addEventListener("click", () => {
        const l = b.dataset.lang;
        if (SUBL.has(l)) SUBL.delete(l); else SUBL.add(l);
        cmd("subs.languages", { languages: [...SUBL] });
      }));
  }
  let html = "";
  const renderItem = (items, label) => {
    if (!items.length) return;
    html += `<div class="group-head">${label}</div>`;
    items.forEach((it) => {
      html += `<div class="sb-item"><div class="sname">${esc(it.file_name || it.name || it.title || "")}` +
        (it.lang ? ` <span style="color:var(--dim)">${esc(it.lang)}</span>` : "") + `</div>` +
        `<button class="mini" data-subs-dl="${esc(it.idx)}"${subs.busyIndex === it.idx ? " disabled" : ""}>⬇</button></div>`;
    });
  };
  renderItem(subs.best || [], "Best");
  renderItem(subs.others || [], "Others");
  html = html || '<div class="status">No results yet</div>';
  if ($("sbResults").innerHTML !== html) {
    $("sbResults").innerHTML = html;
    $("sbResults").querySelectorAll("[data-subs-dl]").forEach((b) =>
      b.addEventListener("click", () => cmd("subs.download", { index: Number(b.dataset.subsDl) })));
  }
}

/* ------------------------- collapsible sections -------------------------
   Snapshots stream in ~3x/second and re-render these cards, so open/closed
   state lives in JS (never re-derived from the snapshot) and the body is
   only shown/hidden — a section can never snap shut under the user's finger. */
function makeCollapser(headId, bodyId, arrowId, open) {
  const head = $(headId), body = $(bodyId), arrow = $(arrowId);
  if (!head || !body) return { get open() { return false; }, set: () => {} };
  const state = { open: !!open };
  const apply = () => {
    body.hidden = !state.open;
    head.classList.toggle("open", state.open);
    head.setAttribute("aria-expanded", state.open ? "true" : "false");
    if (arrow) arrow.textContent = state.open ? "▾" : "▸";
  };
  const toggle = () => { state.open = !state.open; apply(); };
  head.addEventListener("click", toggle);
  head.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
  });
  apply();
  return state;
}

/* Tracks & Subtitles — collapsed by default */
const TRK = makeCollapser("trkHead", "trkBody", "trkArrow", false);

/* Playlist — starts expanded; shuffle/repeat/clear stay live while collapsed */
const PLC = makeCollapser("plHead", "playlist", "plArrow", true);

/* ----------------------------- equalizer ----------------------------- */
/* Equalizer — collapsed by default; bands are a nested section, also closed */
const EQC = makeCollapser("eqToggle", "eqBody", "eqArrow", false);
const EQB = makeCollapser("eqBandsHead", "eqBands", "eqBandsArrow", false);

/* VLC hands back raw floats (a preset band is 4.800000190734863), which would
   overflow the fixed-width dB column and wrap the row. Round to 1 decimal and
   drop a trailing ".0" so the readout is never wider than "-12.5 dB". */
function fmtDb(v) {
  const n = Number(v);
  if (!isFinite(n)) return "0";
  return String(Math.round(n * 10) / 10);
}

$("eqPreset").addEventListener("change", (e) => cmd("eq.preset", { index: Number(e.target.value) }));
$("eqPreamp").addEventListener("input", (e) => { $("eqPreampVal").textContent = fmtDb(e.target.value) + " dB"; });
$("eqPreamp").addEventListener("change", (e) => cmd("eq.preamp", { value: Number(e.target.value) }));
$("eqReset").addEventListener("click", () => cmd("eq.reset", {}));

function renderEq(eq) {
  const sel = $("eqPreset");
  const presetHtml = (eq.presets || []).map((p, i) =>
    `<option value="${i}"${i === eq.currentPreset ? " selected" : ""}>${esc(p)}</option>`).join("")
    || '<option value="-1">—</option>';
  if (sel.innerHTML !== presetHtml && !isDragging(sel)) sel.innerHTML = presetHtml;

  if (!isDragging($("eqPreamp"))) {
    $("eqPreamp").value = eq.preamp;
    $("eqPreampVal").textContent = fmtDb(eq.preamp) + " dB";
  }
  let html = "";
  (eq.bands || []).forEach((label, i) => {
    const val = (eq.amps && eq.amps[i]) || 0;
    // fixed-width label/value columns keep every slider on the same left and
    // right edge, so a flat EQ reads as a straight line (§ band alignment)
    html += `<div class="eqband-row"><span class="eqlabel">${esc(label)}</span>` +
      `<input type="range" class="eqband" data-band="${i}" min="-15" max="15" step="0.5" value="${val}">` +
      `<span class="val">${fmtDb(val)} dB</span></div>`;
  });
  const bandCount = (eq.bands || []).length;
  const bc = $("eqBandsCount");
  if (bc) bc.textContent = bandCount ? String(bandCount) : "";
  // Only update bands if none of the sliders are being dragged and content changed
  const bandsBox = $("eqBands");
  const anyBandDragging = Array.from(bandsBox.querySelectorAll(".eqband")).some(isDragging);
  if (!anyBandDragging && bandsBox.innerHTML !== html) {
    bandsBox.innerHTML = html;
    bandsBox.querySelectorAll(".eqband").forEach((s) => {
      s.addEventListener("input", () => {
        s.nextElementSibling.textContent = fmtDb(s.value) + " dB";
      });
      s.addEventListener("change", () => {
        cmd("eq.band", { band: Number(s.dataset.band), value: Number(s.value) });
      });
    });
  }
}

/* ----------------------------- M3U ----------------------------- */
$("pipBtn").addEventListener("click", () => cmd("pip", {}));
$("fsBtn").addEventListener("click", () => cmd("fullscreen", {}));

$("addSourceBtn").addEventListener("click", () => { $("srcOverlay").hidden = false; });
$("srcCancel").addEventListener("click", () => { $("srcOverlay").hidden = true; });
$("srcOk").addEventListener("click", () => {
  const name = $("srcName").value.trim();
  const url = $("srcUrl").value.trim();
  if (name && url) {
    cmd("m3u.addSource", { name, url });
    $("srcOverlay").hidden = true;
    $("srcName").value = ""; $("srcUrl").value = "";
  }
});

$("m3uFilter").addEventListener("input", (e) => {
  cmd("m3u.setFilter", { text: e.target.value });
  // show clear filter affordance immediately
  const cf = $("clearM3uFilterBtn");
  if (cf) cf.style.display = e.target.value.trim() ? "" : ($("m3uFavOnly").checked ? "" : "none");
});
$("m3uGrouping").addEventListener("change", (e) => {
  M3U_LAST_HTML = ""; // grouping change forces rebuild
  cmd("m3u.setGrouping", { mode: e.target.value });
});
$("m3uFavOnly").addEventListener("change", (e) => {
  M3U_LAST_HTML = "";
  cmd("m3u.setFavouritesOnly", { on: e.target.checked });
});

const clearM3uBtn = $("clearM3uBtn");
if (clearM3uBtn) {
  clearM3uBtn.addEventListener("click", () => {
    if (confirm("Clear loaded playlist? This removes all channels and stops playback.")) {
      M3U_EXPANDED = null;
      M3U_LAST_HTML = "";
      cmd("clearPlaylist", {});
    }
  });
}
const clearM3uFilterBtn = $("clearM3uFilterBtn");
if (clearM3uFilterBtn) {
  clearM3uFilterBtn.addEventListener("click", () => {
    $("m3uFilter").value = "";
    M3U_LAST_HTML = "";
    cmd("m3u.setFilter", { text: "" });
    if ($("m3uFavOnly").checked) {
      $("m3uFavOnly").checked = false;
      cmd("m3u.setFavouritesOnly", { on: false });
    }
    clearM3uFilterBtn.style.display = "none";
  });
}

function renderM3U(m3u) {
  const srcBox = $("m3uSources");
  const srcHtml = (m3u.sources || []).map((s, i) =>
    `<div class="row">
       <button class="play" data-src-load="${esc(s.id)}" title="Load">▶</button>
       <div class="rname">${esc(s.name || s.id)}</div>
       <div class="rsub">${esc(s.location || s.url || "")}</div>
       <button data-src-del="${esc(s.id)}" title="Remove">✕</button>
     </div>`).join("")
    || '<div class="status">No sources yet — add one below</div>';
  if (srcBox.innerHTML !== srcHtml) {
    srcBox.innerHTML = srcHtml;
    srcBox.querySelectorAll("[data-src-load]").forEach((b) =>
      b.addEventListener("click", () => cmd("m3u.loadSource", { id: b.dataset.srcLoad })));
    srcBox.querySelectorAll("[data-src-del]").forEach((b) =>
      b.addEventListener("click", () => { if (confirm("Remove this source?")) cmd("m3u.removeSource", { id: b.dataset.srcDel }); }));
  }

  $("m3uStatus").textContent = m3u.status || "";
  $("m3uStatus").className = "status" + (m3u.statusIsError ? " err" : m3u.status ? " ok" : "");

  if (!isDragging($("m3uGrouping"))) $("m3uGrouping").value = m3u.grouping || "category";
  if (!isDragging($("m3uFavOnly"))) $("m3uFavOnly").checked = !!m3u.favouritesOnly;

  const clearBtn = $("clearM3uBtn");
  if (clearBtn) clearBtn.hidden = !(m3u.channels && m3u.channels.length);
  const cfBtn = $("clearM3uFilterBtn");
  if (cfBtn) {
    const hasFilter = !!($("m3uFilter").value.trim() || m3u.favouritesOnly);
    cfBtn.style.display = hasFilter ? "" : "none";
  }

  // channels: flat view in snapshot order — play by array index (§P2.3)
  const channels = m3u.channels || [];
  const grouping = m3u.grouping || "none";
  const box = $("m3uChannels");

  if (!channels.length) {
    const emptyHtml = m3u.loading ? '<div class="status">Loading channels…</div>'
      : '<div class="status">Load a source to see channels</div>';
    if (M3U_LAST_HTML !== emptyHtml || M3U_LAST_COUNT !== 0) {
      box.innerHTML = emptyHtml;
      M3U_LAST_HTML = emptyHtml;
      M3U_LAST_COUNT = 0;
      M3U_LAST_GROUPING = grouping;
      M3U_EXPANDED = null;
    }
    return;
  }

  const LIMIT_NONE = 400;
  const LIMIT_GROUP = 600;

  // ------------------------------------------------- no grouping: flat, limited
  if (grouping === "none") {
    const truncated = channels.length > LIMIT_NONE;
    const display = truncated ? channels.slice(0, LIMIT_NONE) : channels;
    let flatHtml = display.map((ch, i) => channelRow(ch, i)).join("");
    if (truncated) flatHtml += `<div class="status">Showing ${LIMIT_NONE} of ${channels.length} – use search or grouping to narrow</div>`;
    // Use content hash that includes fav/current so star fill updates
    const sig = grouping + "|" + channels.length + "|" + (channels[0]?.url || "") + "|" + channels.filter(c=>c.fav).length + "|" + channels.filter(c=>c.current).length;
    if (M3U_LAST_HTML !== flatHtml || M3U_LAST_COUNT !== channels.length || M3U_LAST_GROUPING !== sig) {
      box.innerHTML = flatHtml;
      M3U_LAST_HTML = flatHtml;
      M3U_LAST_COUNT = channels.length;
      M3U_LAST_GROUPING = sig;
      bindChannelActions(box, channels.length);
    }
    return;
  }

  // ------------------------------------------------- grouped view
  const groupKey = (ch) => {
    const raw = grouping === "country" ? ch.country
      : grouping === "language" ? ch.language : ch.group;
    return raw || "Unknown";
  };
  const groups = {};
  channels.forEach((ch, i) => {
    const key = groupKey(ch);
    (groups[key] = groups[key] || []).push(i);
  });

  // Remember expand/collapse across snapshots, but init with current playing + first 3
  if (M3U_EXPANDED === null) {
    M3U_EXPANDED = new Set();
    const keys = Object.keys(groups);
    // Sort keys for deterministic first-3
    keys.sort((a,b)=>a.toLowerCase().localeCompare(b.toLowerCase()));
    keys.forEach((k, idx) => {
      const hasCurrent = groups[k].some(ii => channels[ii].current);
      if (idx < 3 || hasCurrent) M3U_EXPANDED.add(k);
    });
  } else {
    const existing = new Set(Object.keys(groups));
    M3U_EXPANDED = new Set([...M3U_EXPANDED].filter(k => existing.has(k)));
    if (M3U_EXPANDED.size === 0) {
      for (const k of Object.keys(groups)) {
        if (groups[k].some(ii => channels[ii].current)) { M3U_EXPANDED.add(k); break; }
      }
    }
  }

  const sortedKeys = Object.keys(groups).sort((a,b)=>a.toLowerCase().localeCompare(b.toLowerCase()));
  let html = "";
  sortedKeys.forEach((k) => {
    const open = M3U_EXPANDED.has(k);
    const count = groups[k].length;
    html += `<div class="group"><div class="group-head" data-g="${esc(k)}"><span class="garrow">${open ? "▾" : "▸"}</span> ${esc(k)} <span class="gcount">${count}</span></div>`;
    html += `<div class="gbody"${open ? "" : ' hidden'}>`;
    if (open) {
      let idxs = groups[k];
      const truncated = idxs.length > LIMIT_GROUP;
      if (truncated) idxs = idxs.slice(0, LIMIT_GROUP);
      html += idxs.map(i => channelRow(channels[i], i)).join("");
      if (truncated) html += `<div class="status">Showing ${LIMIT_GROUP} of ${count} in this group – search to narrow</div>`;
    }
    html += `</div></div>`;
  });

  const favSig = channels.filter(c=>c.fav).length;
  const curSig = channels.findIndex(c=>c.current);
  const sig = grouping + "|" + channels.length + "|" + sortedKeys.length + "|" + [...M3U_EXPANDED].sort().join(",") + "|" + favSig + "|" + curSig;

  if (M3U_LAST_HTML !== html || M3U_LAST_GROUPING !== sig) {
    box.innerHTML = html;
    M3U_LAST_HTML = html;
    M3U_LAST_GROUPING = sig;
    M3U_LAST_COUNT = channels.length;

    box.querySelectorAll(".group-head").forEach((h) => {
      h.addEventListener("click", () => {
        const g = h.dataset.g;
        if (!g) return;
        if (M3U_EXPANDED.has(g)) M3U_EXPANDED.delete(g);
        else M3U_EXPANDED.add(g);
        // Immediate re-render using current snapshot, no need to wait for SSE
        M3U_LAST_HTML = "";
        renderM3U(m3u);
      });
    });
    bindChannelActions(box, channels.length);
  }
}

function channelRow(ch, i) {
  return `<div class="row${ch.current ? " current" : ""}">
    <button class="play" data-ch-play="${i}" title="Play">▶</button>
    <div class="rname">${esc(ch.name)}</div>
    ${ch.current ? '<div class="rsub">● playing</div>' : ""}
    <button class="${ch.fav ? "on" : ""}" data-ch-fav="${i}" title="Favourite">${ch.fav ? "★" : "☆"}</button>
  </div>`;
}

function bindChannelActions(box, count) {
  box.querySelectorAll("[data-ch-play]").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const i = Number(b.dataset.chPlay);
      if (i >= 0 && i < count) cmd("m3u.playRow", { row: i });
    }));
  box.querySelectorAll("[data-ch-fav]").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const i = Number(b.dataset.chFav);
      const ch = (SNAP && SNAP.m3u.channels && SNAP.m3u.channels[i]) || null;
      if (ch) {
        // optimistic UI: toggle immediately so star fills without waiting 400ms
        const rowEl = b.closest(".row");
        if (rowEl) {
          b.textContent = ch.fav ? "☆" : "★";
          b.classList.toggle("on", !ch.fav);
        }
        cmd("m3u.setFavourite", { url: ch.url, on: !ch.fav });
      }
    }));
}

/* ----------------------------- Web ----------------------------- */
let WEB_BM_LAST_HTML = "";
let WEB_BM_LAST_SIG = "";
let WEB_BM_OPEN = false;      // bookmarks accordion — collapsed by default
let WEB_TABS_LAST_HTML = "";  // cached tab rows to avoid DOM churn every snapshot
let WEB_TABS_LAST_ACTIVE = "";

/* Bookmarks accordion: collapsed on load, tap the title to expand. */
function setBookmarksOpen(open) {
  WEB_BM_OPEN = !!open;
  const head = $("bmHead"), body = $("bmBody"), arrow = $("bmArrow");
  if (!head || !body) return;
  body.hidden = !WEB_BM_OPEN;
  head.classList.toggle("open", WEB_BM_OPEN);
  head.setAttribute("aria-expanded", WEB_BM_OPEN ? "true" : "false");
  if (arrow) arrow.textContent = WEB_BM_OPEN ? "▾" : "▸";
}

if ($("bmHead")) {
  $("bmHead").addEventListener("click", () => setBookmarksOpen(!WEB_BM_OPEN));
  $("bmHead").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setBookmarksOpen(!WEB_BM_OPEN); }
  });
  setBookmarksOpen(false);
}

if ($("webNewTabBtn")) {
  $("webNewTabBtn").addEventListener("click", () => {
    cmd("switchMode", { id: "web" });
    setChip("web");
    cmd("web.newTab", {});
  });
}

$("addBmBtn").addEventListener("click", () => {
  if (SNAP && SNAP.web.activeTab && SNAP.web.activeTab.url) {
    cmd("web.bookmarkAdd", { title: SNAP.web.activeTab.title || "", url: SNAP.web.activeTab.url });
  }
});

if ($("webBackBtn")) {
  $("webBackBtn").addEventListener("click", () => cmd("web.back", {}));
  $("webFwdBtn").addEventListener("click", () => cmd("web.forward", {}));
  $("webReloadBtn").addEventListener("click", () => cmd("web.reload", {}));
}

function renderWeb(web) {
  const tab = web.activeTab || {};
  const title = tab.title || tab.url || "—";
  const url = tab.url || "—";
  $("webTitle").textContent = title;
  $("webUrl").textContent = url;
  const tabs = Array.isArray(web.tabs) ? web.tabs : [];
  const activeIdx = (typeof web.activeTabIndex === "number" && web.activeTabIndex >= 0)
    ? web.activeTabIndex
    : (tab.id ? tabs.findIndex((t) => t && t.id === tab.id) : -1);
  const tc = $("webTabCount");
  if (tc) {
    const count = web.tabCount || tabs.length || 0;
    const idx = activeIdx >= 0 ? activeIdx + 1 : 0;
    tc.textContent = count ? (idx ? `Tab ${idx}/${count}` : `${count} tabs`) : "";
  }

  // --- Open tabs: tap to switch, ✕ to close (cached to avoid DOM churn) ---
  const tl = $("webTabs");
  if (tl) {
    const activeId = (activeIdx >= 0 && tabs[activeIdx]) ? (tabs[activeIdx].id || "") : "";
    let tabsHtml = "";
    if (tabs.length) {
      tabsHtml = tabs.map((t, i) => {
        const cur = i === activeIdx ? " current" : "";
        const name = (t && (t.title || t.url)) || "New Tab";
        const sub = ((t && t.url) || "").replace(/^https?:\/\//, "");
        return `<div class="row${cur}" data-tab-sel="${i}" data-tab-id="${esc((t && t.id) || "")}">` +
          `<span class="tnum">${i + 1}</span>` +
          `<div class="rname">${esc(name)}</div>` +
          (sub ? `<div class="rsub" style="max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(sub)}</div>` : "") +
          `<button class="tclose" data-tab-close="${i}" title="Close tab">✕</button></div>`;
      }).join("");
    } else {
      tabsHtml = '<div class="status">No open tabs</div>';
    }
    if (tabsHtml !== WEB_TABS_LAST_HTML) {
      tl.innerHTML = tabsHtml;
      WEB_TABS_LAST_HTML = tabsHtml;
      tl.querySelectorAll("[data-tab-sel]").forEach((row) => {
        row.addEventListener("click", (e) => {
          if (e.target.closest("[data-tab-close]")) return;   // ✕ handled below
          const id = row.dataset.tabId || "";
          const index = Number(row.dataset.tabSel);
          // Optimistic highlight; the next snapshot confirms.
          tl.querySelectorAll(".row").forEach((r) => r.classList.remove("current"));
          row.classList.add("current");
          cmd("switchMode", { id: "web" });
          setChip("web");
          cmd("web.selectTab", id ? { id, index } : { index });
        });
      });
      tl.querySelectorAll("[data-tab-close]").forEach((b) => {
        b.addEventListener("click", (e) => {
          e.stopPropagation();
          const row = b.closest("[data-tab-sel]");
          const id = (row && row.dataset.tabId) || "";
          const index = Number(b.dataset.tabClose);
          b.disabled = true;
          cmd("web.closeTab", id ? { id, index } : { index });
        });
      });
    }
    // keep the active tab visible in the 4-row window, without fighting scrolling
    if (activeId !== WEB_TABS_LAST_ACTIVE) {
      const cur = tl.querySelector(".row.current");
      if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest" });
      WEB_TABS_LAST_ACTIVE = activeId;
    }
  }
  const ntb = $("webNewTabBtn");
  if (ntb) {
    ntb.disabled = !!web.atMaxTabs;
    ntb.title = web.atMaxTabs ? "Maximum 15 tabs reached" : "Open a new tab";
  }

  // --- Bookmarks with caching for perf ---
  const bm = $("webBookmarks");
  const list = web.bookmarks || [];
  const bmc = $("bmCount");
  if (bmc) bmc.textContent = list.length ? String(list.length) : "";
  const sig = list.length + "|" + (list[0]?.url||"") + "|" + list.filter(b=>b.title).length + "|" + (list.map(b=>b.url).join(",").slice(0,200));
  let bmHtml = "";
  if (list.length) {
    bmHtml = list.map((b, i) =>
      `<div class="row"><button class="play" data-bm-open="${i}" title="Open in new tab">🌐</button>` +
      `<div class="rname">${esc(b.title || b.url)}</div>` +
      `<div class="rsub" style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc((b.url||'').replace(/^https?:\/\//,''))}</div>` +
      `<button data-bm-del="${i}" title="Remove">✕</button></div>`).join("");
  } else {
    bmHtml = '<div class="status">No bookmarks yet</div>';
  }
  if (sig !== WEB_BM_LAST_SIG || bmHtml !== WEB_BM_LAST_HTML) {
    bm.innerHTML = bmHtml;
    WEB_BM_LAST_HTML = bmHtml;
    WEB_BM_LAST_SIG = sig;
    bm.querySelectorAll("[data-bm-open]").forEach((b) => {
      b.addEventListener("click", () => {
        const it = (web.bookmarks || [])[Number(b.dataset.bmOpen)];
        if (!it) return;
        // Optimistic UI: show opening immediately, switch chip to web, and open NEW TAB
        $("webTitle").textContent = it.title || it.url;
        $("webUrl").textContent = it.url;
        b.disabled = true;
        b.textContent = "⏳";
        cmd("switchMode", { id: "web" });
        setChip("web");
        cmd("web.openInNewTab", { url: it.url });
        setTimeout(() => { b.disabled = false; b.textContent = "🌐"; }, 800);
      });
    });
    bm.querySelectorAll("[data-bm-del]").forEach((b) =>
      b.addEventListener("click", () => {
        const it = (web.bookmarks || [])[Number(b.dataset.bmDel)];
        if (it) cmd("web.bookmarkRemove", { url: it.url });
      }));
  }

  // media control – unified remote for page's main media element
  const media = web.media;
  const hasMedia = !!(media && media.found);
  $("webMediaNone").hidden = hasMedia;
  $("webMediaBody").hidden = !hasMedia;
  if (hasMedia) {
    WEBM = media;
    $("wmPlay").textContent = media.paused ? "▶" : "⏸";
    $("wmCur").textContent = fmtTime(media.currentTime || 0);
    $("wmDur").textContent = fmtTime(media.duration || 0);
    const mt = $("webMediaType");
    if (mt) mt.textContent = media.hasVideo ? "Video" : "Audio";
    if (media.duration > 0 && !isDragging($("wmSeek"))) {
      const f = ((media.currentTime || 0) / media.duration) * 1000;
      $("wmSeek").value = Math.max(0, Math.min(1000, f));
    }
    if (!isDragging($("wmVol"))) {
      $("wmVol").value = Math.round((media.volume || 0) * 100);
    }
    const muted = !!(media.muted || media.volume === 0);
    $("wmVolIcon").textContent = muted ? "🔇" : "🔊";
    if ($("wmMute")) $("wmMute").textContent = muted ? "Unmute" : "Mute";
    if ($("wmFs")) $("wmFs").disabled = !media.hasVideo;
  } else {
    WEBM = null;
    const mt2 = $("webMediaType");
    if (mt2) mt2.textContent = "";
  }
}

// Media volume is sent at the browser's paint rate while the finger/mouse is
// moving.  The old handler only sent the final `change` event, so the page
// received one large jump instead of the intermediate slider values.
function sendWebVolume(value, commit) {
  const next = Math.max(0, Math.min(1, Number(value) || 0));
  WM_VOLUME_PENDING = next;

  if (commit) {
    if (WM_VOLUME_FRAME !== null) {
      cancelAnimationFrame(WM_VOLUME_FRAME);
      WM_VOLUME_FRAME = null;
    }
    const finalValue = WM_VOLUME_PENDING;
    WM_VOLUME_PENDING = null;
    cmd("web.media", { action: "volume", value: finalValue });
    return;
  }

  if (WM_VOLUME_FRAME !== null) return;
  WM_VOLUME_FRAME = requestAnimationFrame(() => {
    WM_VOLUME_FRAME = null;
    const frameValue = WM_VOLUME_PENDING;
    WM_VOLUME_PENDING = null;
    if (frameValue !== null) {
      cmd("web.media", { action: "volume", value: frameValue });
    }
  });
}

// Media control handlers – live input + change commit
if ($("wmPlay")) {
  $("wmPlay").addEventListener("click", () => {
    if (WEBM) {
      $("wmPlay").textContent = WEBM.paused ? "⏸" : "▶";
      WEBM.paused = !WEBM.paused;
    }
    cmd("web.media", { action: "toggle" });
  });
  if ($("wmBack")) $("wmBack").addEventListener("click", () => cmd("web.media", { action: "seekBy", value: -10 }));
  if ($("wmFwd")) $("wmFwd").addEventListener("click", () => cmd("web.media", { action: "seekBy", value: 15 }));
  if ($("wmSeek")) {
    $("wmSeek").addEventListener("input", (e) => {
      if (WEBM && WEBM.duration > 0) {
        const sec = (Number(e.target.value) / 1000) * WEBM.duration;
        $("wmCur").textContent = fmtTime(sec);
      }
    });
    $("wmSeek").addEventListener("change", (e) => {
      if (WEBM && WEBM.duration > 0) {
        const sec = (Number(e.target.value) / 1000) * WEBM.duration;
        cmd("web.media", { action: "seek", value: sec });
      }
    });
  }
  if ($("wmVol")) {
    $("wmVol").addEventListener("input", (e) => {
      const v = Number(e.target.value) / 100;
      if (WEBM) {
        WEBM.volume = v;
        WEBM.muted = false;
      }
      $("wmVolIcon").textContent = v === 0 ? "🔇" : "🔊";
      if ($("wmMute")) $("wmMute").textContent = v === 0 ? "Unmute" : "Mute";
      sendWebVolume(v, false);
    });
    $("wmVol").addEventListener("change", (e) => {
      sendWebVolume(Number(e.target.value) / 100, true);
    });
  }
  const doMuteToggle = () => {
    if (!WEBM) return;
    const newMuted = !WEBM.muted;
    WEBM.muted = newMuted;
    $("wmVolIcon").textContent = newMuted ? "🔇" : "🔊";
    if ($("wmMute")) $("wmMute").textContent = newMuted ? "Unmute" : "Mute";
    cmd("web.media", { action: "mute", value: newMuted });
  };
  if ($("wmVolIcon")) $("wmVolIcon").addEventListener("click", doMuteToggle);
  if ($("wmMute")) $("wmMute").addEventListener("click", doMuteToggle);
  if ($("wmFs")) $("wmFs").addEventListener("click", () => cmd("web.media", { action: "fullscreen" }));
}


/* ----------------------------- power ----------------------------- */
$("powerToggle").addEventListener("click", () => {
  const body = $("powerBody");
  body.hidden = !body.hidden;
  $("powerToggle").textContent = body.hidden ? "▸ ⚡ Power" : "▾ ⚡ Power";
});
$("sleepBtn").addEventListener("click", () => {
  if (confirm("Put the PC to sleep?")) cmd("power.sleep", {});
});
$("shutdownBtn").addEventListener("click", () => {
  if (confirm("Shut down the PC?")) cmd("power.shutdown", {});
});

/* ----------------------------- render ----------------------------- */
function render(snap) {
  SNAP = snap;
  const conn = $("connDot"), txt = $("connText");
  conn.className = "dot on"; txt.textContent = "connected";

  setChip(snap.mode || "local");

  const np = snap.nowPlaying || {};
  const title = np.label || np.stem || "Nothing playing";
  $("npTitle").textContent = title;
  $("npSub").textContent = (snap.m3u && snap.m3u.currentChannel && snap.mode === "m3u")
    ? "M3U · " + snap.m3u.currentChannel : (np.label ? "Local" : "");

  const p = snap.player || {};
  // The engine reports player clock values in milliseconds. The web-media
  // API below uses seconds, so keep this conversion local to the native-player
  // remote UI.
  $("tCur").textContent = fmtTime((p.time || 0) / 1000);
  $("tDur").textContent = fmtTime((p.duration || 0) / 1000);
  if (p.duration > 0) {
    const f = ((p.position != null ? p.position : (p.time || 0) / p.duration) * 1000);
    if (!isDragging($("seek"))) $("seek").value = Math.max(0, Math.min(1000, f));
  }
  if (!isDragging($("vol"))) $("vol").value = p.volume != null ? p.volume : 80;
  if (!isDragging($("vol2"))) $("vol2").value = p.volume != null ? p.volume : 80;
  $("volIcon").textContent = p.muted || p.volume === 0 ? "🔇" : "🔊";
  $("volIcon2").textContent = p.muted || p.volume === 0 ? "🔇" : "🔊";
  $("muteBtn").textContent = p.muted ? "Unmute" : "Mute";
  if ($("muteBtn2")) $("muteBtn2").textContent = p.muted ? "Unmute" : "Mute";

  // Resume is a one-shot choice for the media open that triggered it. The
  // bridge clears it after Start Over, stop, or a new open.
  const resume = p.resume || {};
  const resumeBox = $("resumeBox");
  if (resumeBox) {
    resumeBox.hidden = !resume.available;
    if (resume.available) {
      $("resumeText").textContent = "Resume from " + fmtTime((resume.time || 0) / 1000) + "?";
      $("resumeStartOver").onclick = () => cmd("startOver", { path: resume.path });
    }
  }

  // play/pause button state
  document.querySelectorAll(".tbtn.big").forEach((b) => {
    b.textContent = p.playing ? "⏸" : "▶";
  });

  // tracks
  const tr = snap.tracks || {};
  const audioSel = $("audioTrack");
  const audioHtml = (tr.audio || []).map((t) =>
    `<option value="${t.id}"${t.id === tr.currentAudio ? " selected" : ""}>${esc(t.label)}</option>`).join("")
    || '<option value="-1">—</option>';
  if (audioSel.innerHTML !== audioHtml && !isDragging(audioSel)) audioSel.innerHTML = audioHtml;
  audioSel.disabled = (tr.audio || []).length <= 1;

  const subSel = $("subTrack");
  const subHtml = (tr.subtitle || []).map((t) =>
    `<option value="${t.id}"${t.id === tr.currentSubtitle ? " selected" : ""}>${esc(t.label)}</option>`).join("")
    || '<option value="-1">Off</option>';
  if (subSel.innerHTML !== subHtml && !isDragging(subSel)) subSel.innerHTML = subHtml;
  subSel.disabled = !p.hasVideo || (tr.subtitle || []).length <= 1;

  // show/hide subtitle delay and buttons based on video/subs availability
  const subExtra = $("subDelayMinus").parentElement;
  if (subExtra) subExtra.hidden = !p.hasVideo;
  if ($("subsDownloadBtn")) $("subsDownloadBtn").hidden = !p.hasVideo;
  if ($("subsFileBtn")) $("subsFileBtn").hidden = !p.hasVideo;

  renderPlaylist(snap.playlist || { rows: [] });
  renderM3U(snap.m3u || {});
  renderWeb(snap.web || {});
  renderEq(snap.eq || {});
  renderSubs(snap.subs || {});
}

/* ----------------------------- SSE ----------------------------- */
function connect() {
  const es = new EventSource("/api/events");
  es.onopen = () => { $("connDot").className = "dot on"; $("connText").textContent = "connected"; };
  es.onmessage = (e) => {
    try { render(JSON.parse(e.data)); }
    catch (err) { console.warn("bad snapshot", err); }
  };
  es.onerror = () => {
    $("connDot").className = "dot off";
    $("connText").textContent = "reconnecting…";
    // EventSource auto-reconnects; also fall back to polling status once.
    fetch("/api/status").then((r) => r.json()).then(render).catch(() => {});
  };
}
connect();
