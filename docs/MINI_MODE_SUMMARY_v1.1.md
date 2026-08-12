# Mini Mode — Final Summary v1.1 — For Review (No Code Yet)

> Owner decisions locked 7 Aug 2026. Height = standard title bar, width may increase, innovative seek loved.

## 1. What It Is
- **Shell state, NOT a 4th ModeSpec.** Like Fullscreen.
- `miniModeActive` bool in `ui/Main.qml`. When true, hides TitleBar, left PanelHost, right InfoPanel, Stage.
- Stage kept **alive hidden** (not destroyed) — ring buffer still fills, no texture upload while hidden = no black flash on return.
- Only Local mode, only when media loaded.

## 2. Toggle Button
- Location: **TitleBar left of minimize** as `[mini][ ─ ][ □ ][ ✕]`
- Glyph: compact/mini relevant icon, tooltip "Mini Mode"
- Enabled only when `activeModeId=="local"` && `hasMedia`. Grayed/disabled in M3U/Web/no media.
- Binds to `Actions.toggleMiniMode` — single implementation §4.1

## 3. Bar Size — Fits on Word Title Bar
- **Theme.titleBarHeight = 44px** — Mini height = 44px exact, so it sits cleanly on MS Word / File Explorer title bar without excess space.
- **Width = 400-420px** — you allowed increase from 320 to accommodate controls. Still title-bar sized, fits in free space of Word title bar middle.
- Fixed size: `min==max==400×44`, no resize, 8 resize handles hidden in mini.

## 4. Layout (44px tall)
```
┌─────────────────────────────────────────────────────┐ 3px hairline seek = top edge
│●━━━━━━○··············································│ 2px rest -> 6px hover + knob
├─────────────────────────────────────────────────────┤
│ ⋮⋮  ⏮  ⏪  ▶  ⏹  ⏭  ⏩  🔊  ⤢ │ 44px = titleBarHeight
│ 24  40  40  44  40  40  40  40  40│ grip only drags
└─────────────────────────────────────────────────────┘
         400-420px fixed, frameless, always-on-top
```

Controls (8 + grip):
- Grip `⋮⋮` 24px — ONLY draggable part via `startSystemMove()`, cursor open-hand. No whole-bar drag = simple, no accidental drags.
- Prev Track `⏮` — `Actions.prev`
- Seek -10s `⏪` — `Actions.seekRelative(-10s)`
- Play/Pause `▶/⏸` 44px slightly larger — `Actions.playPause` — **circular progress ring** around it (0-100% fill) = glanceable progress, zero width
- Stop `⏹` — `Actions.stop`
- Next Track `⏭` — `Actions.next`
- Seek +10s `⏩` — `Actions.seekRelative(+10s)`
- Volume/Mute `🔊` — click = mute toggle, hover = vertical GlassPanel slider 140px tall pops ABOVE bar (overlay, no width increase)
- Return `⤢` — `Actions.toggleMiniMode` back to normal

All from `IconButton` vocabulary, Theme tokens only §B.1.

## 5. Innovative Seek Bar — Zero Width Increase — You Loved

1. **Top-edge hairline seek:** Top 3px of MiniBar IS the seek bar. Rest: 2px thin, played = accent gradient, buffered = trackBuffered. Hover thickens to 6px + knob + time tooltip, live scrub, click/drag anywhere on top edge.
2. **Circular play ring:** Border of play button fills circularly with accent colour = current position.

Together = precise + glanceable, 0px width increase, perfect for title-bar sit.

## 6. Behaviour Locked

- Always-on-top: `StayOnTopHint` in mini, normal otherwise.
- First time: top-center `x = screen.x + screen.width/2 - miniWidth/2, y = screen.y+12`. After drag, save `miniBarPos` to settings.
- No close from mini: Alt+F4 / taskbar X in mini = return to normal, not quit. Only normal mode can quit.
- Playlist finished (no next, repeat off) while in mini = auto-return to normal (calls toggle).
- No auto-hide, no cursor hide. User works in other windows leaving it playing.
- No PiP conflict: PiP only M3U, Mini only Local, one-tuner already stops M3U when switching to Local.
- Fullscreen lockout: mini toggle disabled while fullscreen.

## 7. Challenges — Simplest Solutions (Left to expert)

- **Black flash on return:** Keep Stage alive hidden, skip `createTextureFromImage` while hidden.
- **Geometry restore:** Save normal x,y,w,h,wasMaximized,wasFullscreen before entering mini, restore on return.
- **Turbo HWND:** On entering mini, force soft I420 path, on return restore if setting ON.
  *(Updated 2026-08-12, §V.) Implemented as `App.setMiniMode(true/false)`: the controller
  forces the effective route to Soft while Mini is up and re-resolves the selected
  `Video mode` — including `Auto` landing on Turbo — on return, falling back to Soft if
  native setup fails. Mini deliberately writes **nothing** to settings; the old
  `playback.turboMode` save/restore is gone along with the checkbox itself.)*
- **Close intercept:** `onClosing` in mini -> return to normal.

## 8. Files Touched (Disclosed v4.1)

- `ui/shell/MiniBar.qml` new
- `ui/shell/TitleBar.qml` add button
- `ui/Actions.qml` add toggleMiniMode
- `ui/Main.qml` bool + show/hide + fixed size + StayOnTop + save/restore
- `core/settings.py` miniBarPos
- Maybe `Theme.qml` token for miniBarWidth if needed — height reuses titleBarHeight

## 9. Acceptance Checklist

- Toggle renders left of minimize, only enabled Local+media
- Click -> 400×44 fixed glass bar, always-on-top, top-center first time
- Shows grip + 8 controls balanced
- Only grip drags
- Top hairline seek 2px->6px hover + seek + buffered
- Circular ring 0-100%
- Volume vertical pop-up
- All controls same Actions as Local
- Video hidden audio continues, CPU not higher
- Return via return/Esc/Alt+F4 -> instant video no black flash
- Finished -> auto-return
- No close from mini
- Sits on Word title bar (44px height)
- Isolation passes, regression passes

---
*This summary derived from HALCYON_PLAN.md v4.1 §M and CHECKLIST.md Phase 4. No commit/push done yet, local edits only.*
