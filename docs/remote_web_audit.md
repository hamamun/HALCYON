# Remote Web Mode Audit — Bookmarks + Media Controls

**Scope:** remote-only, web chip only. Issues reported:
1. Bookmark list shows, Add Current works, but tapping bookmark does NOT open new tab; response is very slow.
2. No working unified media control (play/pause/seek/volume/mute/fullscreen) for any active page media.

Date: 2026-08-09
Branch: arena/019fe5c7-halcyon

---

## 1. Current Architecture (Web remote path)

```
[Phone] index.html #screen-web
  -> app.js renderWeb(): web.bookmarks, web.activeTab, web.media
  -> cmd("web.navigate" / "web.media" / "web.bookmarkAdd")
[Server] remote/server.py
  /api/events SSE (sleep 0.4s loop, version check)
  /api/cmd -> bridge.request() emit signal QueuedConnection
[Bridge] remote/bridge.py (Qt thread)
  poll 500ms: StatusStore snapshot = player, playlist, m3u, web, eq, subs
  _web_snapshot() reads BrowserContext: tabCount, tabs, activeTab, bookmarks(bookmarkItems), media_status()
  _cmd_web_navigate -> BrowserContext.navigateActive(url)
  _cmd_web_media -> BrowserContext.mediaControl(action, value)
[BrowserContext] modes/web/browser.py
  owns tabs list, activeIndex, bookmarks store, hosts (WebViewHost)
  navigateActive(): resolves URL/search, if no tab -> addTab(resolved) else _navigate_tab(tab,resolved)
  _navigate_tab(): creates host if needed, host.navigate()
  addTab(url): creates _BrowserTab, set active, emit tabsChanged/activeTabChanged, navigate if url
  mediaControl(): delegates to host.media_control()
  media_status(): delegates to host.media_status()
[WebViewHost] modes/web/webview2_host.py
  owns one CoreWebView2 controller child HWND
  injects get_media_probe_script() onDocCreated: every 600ms picks largest video element, postMessage {halcyon:'media', found, paused, currentTime, duration, volume, muted, hasVideo}
  WebMessageReceived callback parses JSON -> _media_status dict + mediaStatusChanged signal
  media_control(action,value): ExecuteScriptAsync JS that picks same largest element and calls play/pause/toggle/seek/seekBy/volume/mute/fullscreen
[Runtime] modes/web/webview2_runtime.py
  get_media_probe_script() string
```

Remote UI in `remote/static/index.html` currently:
- Active page title/url display
- Bookmarks list: 🌐 open, ✕ delete, ⭐ Add current page
- Media card: `#webMediaNone` + `#webMediaBody` hidden until media.found true
  - transports: Back(-15), Play/Pause, Fwd(+15)
  - seekrow: cur, #wmSeek, dur
  - volrow: icon, #wmVol, Fullscreen button
  - MISSING per spec: dedicated mute button, separate volume bar logic independent of video element's own controls, explicit mute state.

---

## 2. Bug #1 — Bookmarks not opening new tab + slow

### Observed flow in app.js
```js
$bmOpen -> cmd("web.navigate", {url: it.url})
```
This reuses active tab.

### Root causes

**A. Semantics mismatch — reuse vs new tab:**
User expects "opening tab at new page" (new tab). Current implementation reuses active tab. If active tab is internal `halcyon://bookmarks`, `_ensure_tab_host` must create a host after converting internal->normal. That path works but is heavier than `addTab`, and if Web tab count == 0 (fresh launch) navigateActive -> addTab anyway. User confusion comes from not seeing new tab appear.

**B. Missing mode switch:**
Tap bookmark does NOT also issue `switchMode({id:"web"})`. If phone is showing web chip optimistically but PC mode is still Local/M3U, PC window stays on Local/M3U stage. `setStageActive(false)` in BrowserContext then hides hosts (`_sync_hosts usable = stage_active && runtime_available...`). So navigation happens in background but not visible until user revisits web mode on PC or waits for next snapshot to flick chip. The SSE snapshot causes chip flicker: `setChip(snap.mode)` reverts optimistic web chip to local after 400-900ms.

**C. Performance stack — 3 latencies adding up:**
1. `server.py _handle_events` sleep 0.4s loop polling version.
2. `bridge.py POLL_MS=500ms` rebuild snapshot; navigate triggers controller creation which may take 100-300ms plus _wait_for_task (pumps Qt events).
3. `browser.py` tab creation -> `host.init_controller` may need to wait for HWND ready (retry up to 20x50ms). Bookmark JSON `_save()` does sync file write on Qt thread.
Total perceived: 0.9-1.7s from tap to visible new page. No optimistic UI (title/url still shows old until next SSE). User calls "too slow".

**D. Render churn:**
`renderWeb` rebuilds entire bookmarks innerHTML if differs, rebinds click listeners each snapshot (500ms+400ms). If bookmarks list is moderately large, string compare and innerHTML reset is costly on low-end phones. No `requestAnimationFrame` or diff keyed.

**E. No new-tab API in bridge:**
Bridge only exposes `web.navigate`, `web.back`, `forward`, `reload`, `bookmarkAdd/Remove`, `web.media`. No `web.openInNewTab` or `web.addTab`. So frontend cannot choose new-tab semantics without backend change.

---

## 3. Bug #2 — Media controls absent / not working

### Why user sees "no media control"

**A. Critical bug — missing `import json` in webview2_host.py**
File imports: `logging, sys, typing, PySide6`. Functions `web_message_received` uses `json.loads(raw)` and `media_control` uses `json.dumps()`. Without import, NameError is caught only by outer try? Actually inside web_message_received:
```python
raw = ...
try: msg = json.loads(raw) except...
```
This raises NameError: name 'json' not defined, caught by outer `except (TypeError, ValueError)`? No, NameError not caught -> propagates out of lambda, logged nowhere? Actually callback `web_message_received` is called from .NET event thread? If it raises, pythonnet may swallow. Result: `_media_status` never updates, stays `{"found": False}`. Then bridge snapshot `web.media = {found:False}` -> frontend hides `webMediaBody` and shows `No video on this page`. So even if video playing, controls invisible.

Similarly `media_control` payload building raises NameError, so Play/Pause etc never executed even when user somehow triggers.

First fix mandatory: add `import json` at top of webview2_host.py.

**B. Media probe limitations:**
- Probe script injected via AddScriptToExecuteOnDocumentCreatedAsync only. If page already loaded before controller creation, it still runs due to 600ms interval after injection, but if injection fails (host not ready), no probe.
- Probe picks largest video by `videoWidth*videoHeight`. For YouTube, works. For audio-only, or iframe-hosted video (e.g., embedded player inside shadowRoot), `querySelectorAll('video,audio')` on main document misses shadowRoot videos (though pause_media does shadow search, probe does not). Should unify logic.
- Probe reports every 600ms, bridge polls every 500ms → staleness up to ~1.1s. Seekbar would lag.
- No `mediaStatusChanged` -> `publish_now` connection. Bridge only polls; if user pauses via page's own controls, remote UI lags 0.5s+0.4s.
- Audio-only pages: `hasVideo = m.tagName=='VIDEO'` false for audio, but card titled "Media on page" still says "No video". Should be "No media" and show controls for audio too.

**C. Frontend incomplete vs spec:**
Spec requires: play/pause, seekbar, volume bar, mute, fullscreen — working on any active page media.

Current UI has:
- Play/pause toggle done (`wmPlay`)
- Seekbar only on `change` (not live `input`), no time tooltip, fights drag detection but `isDragging` guard incomplete.
- Volume bar only slider, no mute button. `wmVolIcon` shows mute state but not clickable. Missing dedicated mute button per requirement.
- Fullscreen button exists but calls media fullscreen (element.requestFullscreen), not browser window fullscreen. That triggers `contentFullscreen` path which should work, but missing feedback.
- No handling for `hasVideo` vs audio — fullscreen hidden for audio should be disabled.
- Seek amount fixed to ±15s, but no ±10s like local. OK but inconsistent.
- When media not found, entire body hidden. For UX, better to keep card but disabled, or show last known duration.

**D. Bridge serialization:**
`media_status()` returns dict with `found, paused, currentTime, duration, volume, muted, hasVideo`. Bridge _web_snapshot copies via `probe()` which may return incomplete keys if NameError path. Also `volume` from JS `m.volume || 0` returns 0 when volume is 0 — same as missing. Should preserve.
No caching like M3U, so rebuilt every poll.

---

## 4. Proposed Fixes (no code yet, plan)

### Fix Group 1 — Bookmarks open NEW tab, fast

**Backend:**
- In `modes/web/browser.py`, add new public slot:
  `openInNewTab(url: str)` -> resolve, check MAX_TABS, if limit show message, else addTab(resolved) and return True. Ensure it calls setActiveTab to newly added.
- Add alternative if want to reuse existing blank tab: logic if active tab is blank (`not tab.url`) then navigate in place, else new tab.
- In `remote/bridge.py`, add:
  `_cmd_web_openInNewTab(payload)` -> `ctx.addTab(url)` or `ctx.openInNewTab(url)` + ensure web mode active: if controller.activeMode != "web", call `controller.setActiveMode("web")` (same as chip does). Invalidate M3U cache not needed.
  Keep existing `_cmd_web_navigate` for address bar use.
- Optional: `_cmd_web_openBookmark` that also triggers mode switch for explicitness.

**Frontend (`app.js` + `index.html`):**
- Change bookmark open handler from `web.navigate` to `web.openInNewTab`.
- Implement optimistic UI: on click, immediately set `webTitle` to bookmark title, `webUrl` to url with loading spinner, disable button with "Opening…". Don't wait for SSE.
- Add Tabs UI to remote web section? Currently remote shows no tabs list — only bookmarks and media. User cannot see if new tab opened. At minimum show `Active page` card with count `Tab 2/3` and maybe prev/next tab buttons? Simplest increment: show tab strip or at least show activeTab.title updating via snapshot.
- Ensure after cmd, call `cmd("switchMode", {id:"web"})` optimistically + `setChip("web")` immediately so PC switches to web stage quickly and hosts become visible (`setStageActive(true)`).

**Performance fixes:**
- `remote/server.py`: reduce SSE sleep 0.4s -> 0.15s or 0.2s. Better: replace polling loop with `asyncio.Event` woken by `store.update()`. Add method in StatusStore to expose version event? Quick win: sleep 0.15s, and after `request` we already schedule publish_now in 40ms, so SSE will see version bump within 150ms.
- `remote/bridge.py`: reduce POLL_MS from 500ms to 250ms for web-active mode? Or keep 500 but trigger extra `publish_now` on `mediaStatusChanged`/`tabsChanged`. Connect BrowserContext signals `tabsChanged`, `activeTabChanged`, `bookmarksChanged` to a slot that schedules `publish_now` immediate. That gives near-instant feedback for bookmark nav.
- `bookmarks.py`: make `_save` async or debounced? For now keep sync but wrap in try; file is tiny (< few KB). Not major slow source.
- `app.js`: avoid rebuilding bookmark list HTML every snapshot. Use caching like M3U: compute hash `bmSig = bookmarks.length + bookmarks[0]?.url + etc` and only update DOM when changed. Already pattern in M3U rendering. Apply same.
- Also add `requestAnimationFrame` debounce for seekbar updates to avoid fighting drag.

### Fix Group 2 — Media controls unified

**Backend fixes:**
1. `modes/web/webview2_host.py`:
   - Add `import json` top.
   - Unify probe picker with pause_media shadowRoot traversal: search main doc + shadowRoots + iframes for media elements, pick largest video (or first playing). Current pause_media already does shadow+iframe search; probe should reuse same.
   - Make probe report every 400ms (instead of 600ms) for smoother seekbar; ensure it also listens to `timeupdate` event for low-latency seek updates (attach `m.addEventListener('timeupdate', report)` + `play/pause/volumechange`).
   - Ensure `media_control` JSON payload uses escaped payload safely, and handles `volume` clamping, `muted` boolean.
   - Emit `mediaStatusChanged` after each WebMessageReceived, and BrowserContext forwards to bridge via signal.
   - Test `media_status()` returns dict with all keys, default `found=False` if none.

2. `modes/web/webview2_runtime.py`:
   - Update `get_media_probe_script()` to include shadowRoot + iframe search and event listeners, and robust `postMessage` guard.
   - Ensure script doesn't error on CSP pages (wrap in try).

3. `modes/web/browser.py`:
   - Add signal forwarding: connect host.mediaStatusChanged to BrowserContext activeTabChanged? Actually host emits mediaStatusChanged; BrowserContext should listen and emit activeTabChanged or new signal `mediaStatusChanged` that bridge listens.
   - In `BrowserContext`, connect each host's `mediaStatusChanged` to `self.activeTabChanged.emit()` or dedicated signal.
   - Ensure `media_status()` returns last known even when tab not ready: return `{"found":False}` safe.

4. `remote/bridge.py`:
   - Add connection: when web context registers, connect its media status signals to `publish_now` scheduling for low latency.
   - Or simply rely on existing 500ms poll once probe works; but better to trigger immediate publish on mediaStatusChanged.
   - `_web_snapshot` already calls `media_status()`; keep.

**Frontend (`remote/static/index.html` + `app.js`):**

*UI completeness per requirement*:
- Keep existing card but enhance:
  - Top row: Show thumbnail? Not needed.
  - Transport: add explicit Mute button `#wmMute` next to volume icon; icon click toggles mute.
  - Seekbar: handle `input` for live scrub preview, `change` for commit. Show buffered? Not needed.
  - Volume bar: separate vertical or horizontal slider + mute. Volume slider `input` live.
  - Fullscreen: keep but disable if `hasVideo==False` or audio-only.
  - Show status line: "Audio" vs "Video" based on `hasVideo`.
  - Always show body even if no media found but disabled (grayed), to prove control exists? Spec says card should show "Media on page" and "No video on this page" when none — current does. But when media found, show controls.

- Logic:
  ```js
  renderWeb:
    hasMedia = media && media.found
    if hasMedia:
      show controls, update play/pause icon, cur/dur, seek fraction, vol slider, mute icon, fullscreen enabled.
    else:
      hide body, show none.

  wmPlay: toggle
  wmBack: seekBy -10 (or -15)
  wmFwd: seekBy +15
  wmSeek: on input -> update cur label optimistically (fmtTime), on change -> cmd seek.
  wmVol: on input -> update icon, on change -> cmd volume
  wmMute: cmd media mute toggle (action mute with !muted)
  wmFs: cmd fullscreen
  ```

- Also ensure volume handling: JS media volume 0-1, UI slider 0-100. Bridge already converts.

- Add extra controls: ensure remote media control works on ANY active page media: host picker already picks largest video, which satisfies "any active page media". Document that DRM pages may not allow JS control (Netflix etc) — expected limit.

- Add CSS for controls alignment, disabled opacity.

- Add touch friendliness: larger hit area, throttle seek.

### Fix Group 3 — Testing & Stability

- Write/fix tests:
  - `test_web_browser_context.py`: test new `openInNewTab` slot, TAB limit, internal tab conversion.
  - `test_webview2_host.py`: add test for media_control payload building and json import existence, media_status parsing.
  - `test_remote_bridge.py`: add fake Web context with tabs/bookmarks/media, assert new commands `web.openInNewTab` produce correct calls, snapshot includes bookmarks and media.

- Manual verification on Windows box:
  1. Launch Halcyon, enable Remote, open phone remote.
  2. Web chip: verify bookmarks list shows, Add Current adds.
  3. Tap bookmark → should open new tab within <500ms, PC switches to Web mode, new page loads, tab count increments.
  4. Play YouTube video → remote Media card appears within ~1s, play/pause toggles, seek drag seeks, volume slider changes, mute toggles mute icon, fullscreen triggers PC fullscreen.
  5. Test audio page (soundcloud) → controls still appear, fullscreen disabled.
  6. Test rapid bookmark taps → no crash, popup burst protection not triggered for bookmarks, tab limit message after 15 tabs.
  7. Test with no tabs initially → Add Bookmark then tap opens first tab fast.

### Files to Touch (when coding allowed)

- `modes/web/webview2_host.py` — fix json import, improve probe, improve media_control
- `modes/web/webview2_runtime.py` — improved media_probe script with shadowRoot+iframe search + event listeners
- `modes/web/browser.py` — add `openInNewTab` slot, connect mediaStatusChanged to notify, handle blank tab reuse logic
- `remote/bridge.py` — add `_cmd_web_openInNewTab`, connect media signals to publish_now, optional switchMode on bookmark open
- `remote/server.py` — reduce SSE sleep 0.4→0.15, add wake mechanism
- `remote/static/index.html` — add mute button, maybe tab count display, ensure structure
- `remote/static/app.js` — change bookmark handler to openInNewTab + switchMode, optimistic UI, caching for bookmarks rendering, enhance media rendering with mute handling, input vs change listeners.

### Questions for Product Owner (before coding)

1. Should bookmark tap always open NEW tab (spec says "opening tab at new page") or reuse active if blank? Propose: if active tab blank/new, reuse; else new tab.
2. Should tapping bookmark also auto-switch PC to Web mode? Yes for remote UX (proposed).
3. Do we want tabs list visible in remote web section (like M3U channels) to manage tabs, or keep hidden and only show active? Current remote shows no tabs; adding minimal tabs row would help confirm new tab opened.
4. Media controls: volume bar horizontal is fine? Should mute be separate button or tapping volume icon toggles?
5. Performance target: <300ms tap-to-navigation-start perceived? Reducing SSE to 150ms + optimistic UI achieves.

---

## Summary Checklist (no code stage)

- [ ] Root cause confirmed: missing json import kills media probe
- [ ] Root cause confirmed: bookmark reuse vs new tab semantics + mode switch missing
- [ ] Performance: SSE 400ms + poll 500ms + controller init = >1s
- [ ] UI: mute button missing, seekbar only on change, no optimistic update
- [ ] Plan written above for backend+frontend
- [ ] Await go-ahead to code
