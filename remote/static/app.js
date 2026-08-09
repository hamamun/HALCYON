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
let EQOPEN = true;       // equalizer accordion
let M3U_EXPANDED = null; // remembered expanded groups (null = auto first time)
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

function bindVolume(sliderId) {
  $(sliderId).addEventListener("change", (e) => {
    cmd("setVolume", { volume: Number(e.target.value) });
  });
}
bindVolume("vol");
bindVolume("vol2");

// While the user is dragging a slider, the live snapshot must not fight the
// drag by overwriting the value under their finger.
function isDragging(el) { return el === document.activeElement; }

$("muteBtn").addEventListener("click", () => cmd("toggleMute", {}));
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
    if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
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

/* ----------------------------- equalizer ----------------------------- */
$("eqToggle").addEventListener("click", () => {
  EQOPEN = !EQOPEN;
  $("eqBody").hidden = !EQOPEN;
  $("eqToggle").textContent = "Equalizer " + (EQOPEN ? "▾" : "▸");
});

$("eqPreset").addEventListener("change", (e) => cmd("eq.preset", { index: Number(e.target.value) }));
$("eqPreamp").addEventListener("input", (e) => { $("eqPreampVal").textContent = e.target.value + " dB"; });
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
    $("eqPreampVal").textContent = eq.preamp + " dB";
  }
  let html = "";
  (eq.bands || []).forEach((label, i) => {
    const val = (eq.amps && eq.amps[i]) || 0;
    html += `<label class="lbl">${esc(label)}
      <input type="range" class="eqband" data-band="${i}" min="-15" max="15" step="0.5" value="${val}">
      <span class="val">${val} dB</span></label>`;
  });
  // Only update bands if none of the sliders are being dragged and content changed
  const bandsBox = $("eqBands");
  const anyBandDragging = Array.from(bandsBox.querySelectorAll(".eqband")).some(isDragging);
  if (!anyBandDragging && bandsBox.innerHTML !== html) {
    bandsBox.innerHTML = html;
    bandsBox.querySelectorAll(".eqband").forEach((s) => {
      s.addEventListener("input", () => {
        s.nextElementSibling.textContent = s.value + " dB";
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

$("m3uFilter").addEventListener("input", (e) => cmd("m3u.setFilter", { text: e.target.value }));
$("m3uGrouping").addEventListener("change", (e) => cmd("m3u.setGrouping", { mode: e.target.value }));
$("m3uFavOnly").addEventListener("change", (e) => cmd("m3u.setFavouritesOnly", { on: e.target.checked }));

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

  $("m3uGrouping").value = m3u.grouping || "category";
  $("m3uFavOnly").checked = !!m3u.favouritesOnly;

  // channels: flat view in snapshot order — play by array index (§P2.3)
  const channels = m3u.channels || [];
  const grouping = m3u.grouping || "none";
  const box = $("m3uChannels");
  if (!channels.length) {
    const emptyHtml = m3u.loading ? '<div class="status">Loading channels…</div>'
      : '<div class="status">Load a source to see channels</div>';
    if (box.innerHTML !== emptyHtml) box.innerHTML = emptyHtml;
    return;
  }
  if (grouping === "none") {
    const flatHtml = channels.map((ch, i) => channelRow(ch, i)).join("");
    if (box.innerHTML !== flatHtml) {
      box.innerHTML = flatHtml;
      bindChannelActions(box, channels.length);
    }
    return;
  }
  // Group key must match the server's grouping mode — category/country/
  // language — so the phone's groups agree with the PC's (§R.2).
  const groupKey = (ch) => {
    const raw = grouping === "country" ? ch.country
      : grouping === "language" ? ch.language : ch.group;
    return raw || (grouping === "none" ? "" : "Unknown");
  };
  const groups = {};
  channels.forEach((ch, i) => {
    const key = groupKey(ch);
    (groups[key] = groups[key] || []).push(i);
  });
  // Remember the user's expand/collapse across snapshot pushes (500 ms).
  if (M3U_EXPANDED === null) {
    M3U_EXPANDED = new Set();
    Object.keys(groups).forEach((k, i) => {
      if (i < 3 || channels[groups[k][0]].current) M3U_EXPANDED.add(k);
    });
  } else {
    M3U_EXPANDED = new Set(Object.keys(groups).filter((k) => M3U_EXPANDED.has(k)));
  }
  let html = "";
  Object.keys(groups).forEach((k) => {
    const open = M3U_EXPANDED.has(k);
    html += `<div class="group"><div class="group-head" data-g="${esc(k)}">${open ? "▾" : "▸"} ${esc(k)} <span class="gcount">${groups[k].length}</span></div>`;
    if (open) html += groups[k].map((i) => channelRow(channels[i], i)).join("");
    html += "</div>";
  });
  if (box.innerHTML !== html) {
    box.innerHTML = html;
    box.querySelectorAll(".group-head").forEach((h) =>
      h.addEventListener("click", () => {
        const g = h.dataset.g;
        const body = h.nextElementSibling;
        if (body) { body.hidden = !body.hidden; h.firstChild.textContent = body.hidden ? "▸ " : "▾ "; }
        if (body.hidden) M3U_EXPANDED.delete(g); else M3U_EXPANDED.add(g);
      }));
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
    b.addEventListener("click", () => {
      const i = Number(b.dataset.chPlay);
      if (i >= 0 && i < count) cmd("m3u.playRow", { row: i });
    }));
  box.querySelectorAll("[data-ch-fav]").forEach((b) =>
    b.addEventListener("click", () => {
      const i = Number(b.dataset.chFav);
      const ch = (SNAP && SNAP.m3u.channels && SNAP.m3u.channels[i]) || null;
      if (ch) cmd("m3u.setFavourite", { url: ch.url, on: !ch.fav });
    }));
}

/* ----------------------------- Web ----------------------------- */
$("addBmBtn").addEventListener("click", () => {
  if (SNAP && SNAP.web.activeTab && SNAP.web.activeTab.url) {
    cmd("web.bookmarkAdd", { title: SNAP.web.activeTab.title || "", url: SNAP.web.activeTab.url });
  }
});

function renderWeb(web) {
  $("webTitle").textContent = (web.activeTab && web.activeTab.title) || "—";
  $("webUrl").textContent = (web.activeTab && web.activeTab.url) || "—";
  const bm = $("webBookmarks");
  const bmHtml = (web.bookmarks || []).map((b, i) =>
    `<div class="row"><button class="play" data-bm-open="${i}">🌐</button>` +
    `<div class="rname">${esc(b.title || b.url)}</div>` +
    `<button data-bm-del="${i}" title="Remove">✕</button></div>`).join("")
    || '<div class="status">No bookmarks yet</div>';
  if (bm.innerHTML !== bmHtml) {
    bm.innerHTML = bmHtml;
    bm.querySelectorAll("[data-bm-open]").forEach((b) =>
      b.addEventListener("click", () => {
        const it = (web.bookmarks || [])[Number(b.dataset.bmOpen)];
        if (it) cmd("web.navigate", { url: it.url });
      }));
    bm.querySelectorAll("[data-bm-del]").forEach((b) =>
      b.addEventListener("click", () => {
        const it = (web.bookmarks || [])[Number(b.dataset.bmDel)];
        if (it) cmd("web.bookmarkRemove", { url: it.url });
      }));
  }

  // media control
  const media = web.media;
  const hasMedia = media && media.found;
  $("webMediaNone").hidden = hasMedia;
  $("webMediaBody").hidden = !hasMedia;
  if (hasMedia) {
    WEBM = media;
    $("wmPlay").textContent = media.paused ? "▶" : "⏸";
    $("wmCur").textContent = fmtTime(media.currentTime || 0);
    $("wmDur").textContent = fmtTime(media.duration || 0);
    if (media.duration > 0 && !isDragging($("wmSeek"))) {
      const f = ((media.currentTime || 0) / media.duration) * 1000;
      $("wmSeek").value = Math.max(0, Math.min(1000, f));
    }
    if (!isDragging($("wmVol"))) {
      $("wmVol").value = Math.round((media.volume || 0) * 100);
    }
    $("wmVolIcon").textContent = media.muted || media.volume === 0 ? "🔇" : "🔊";
  }
}

$("wmPlay").addEventListener("click", () => cmd("web.media", { action: "toggle" }));
$("wmBack").addEventListener("click", () => cmd("web.media", { action: "seekBy", value: -15 }));
$("wmFwd").addEventListener("click", () => cmd("web.media", { action: "seekBy", value: 15 }));
$("wmSeek").addEventListener("change", (e) => {
  if (WEBM && WEBM.duration > 0) {
    cmd("web.media", { action: "seek", value: (Number(e.target.value) / 1000) * WEBM.duration });
  }
});
$("wmVol").addEventListener("change", (e) => cmd("web.media", { action: "volume", value: Number(e.target.value) / 100 }));
$("wmFs").addEventListener("click", () => cmd("web.media", { action: "fullscreen" }));

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
