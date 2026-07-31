# Implementation Summary: Floating Panels + Expandable Lyrics

## Overview

Two UI improvements have been successfully implemented:
1. **Floating Panels** — Left and right panels now overlay the video area instead of squeezing it
2. **Expandable Lyrics** — Lyrics tab can expand for better readability

Both features work together to provide a better user experience without breaking any existing functionality.

---

## Part 1: Floating Panels

### What Changed

**Before:**
- Layout was three columns: Left Panel | Stage+Transport | Right Panel
- Opening a panel squeezed the middle column (video + transport bar)
- Transport bar moved and resized when panels opened/closed

**After:**
- Stage (video) takes full width always
- Transport bar sits at bottom, full-width, never moves
- Both panels float on top of the video area as overlays
- Both panels stop at the top edge of the transport bar, so the controls are
  never covered (see `body.transportInset` in `ui/Main.qml`)
- Panels slide in/out from the edges
- Panels are opened and closed **only** by their toggles (toolbar buttons and
  Ctrl+L / Ctrl+I). Clicking the video does not dismiss them.

### Technical Implementation

**Modified Files:**
- `ui/Main.qml` — Restructured layout hierarchy
- Panels now use `z: 10` to float above the stage
- Stage uses full width (`anchors.left: parent.left; anchors.right: parent.right`)
- Transport bar remains inside Stage but Stage is now full-width

**Panel Height (stopping at the transport bar):**
- `body.transportInset` reports the mode bar's height, read from
  `transportLoader.height` rather than hardcoded, so each mode's own bar height
  is respected (§B.2) and a mode with no bar reports 0
- Both docks set `anchors.bottomMargin: body.transportInset`
- Gated on `chromeVisible`: when the bar fades under fullscreen auto-hide the
  inset drops to 0 and the panels reclaim the full height, animated over
  `Theme.durAutoHide` so the panel edge and the bar move together

**Panel Dismissal:**
- Panels close *only* via `Actions.toggleLeftPanel()` / `toggleRightPanel()`,
  reached from the transport-bar buttons and Ctrl+L / Ctrl+I
- There is deliberately **no** click-outside-to-close overlay: a click on the
  stage means play/pause and nothing else

### User Experience

- Open left panel (Ctrl+L) → slides in from left, overlays video
- Open right panel (Ctrl+I) → slides in from right, overlays video
- Both panels can be open simultaneously
- Panels stay open until their toggle is pressed again — clicking the video
  play/pauses and leaves the docks alone
- Both panels end at the top of the transport bar; the controls stay visible
  and clickable with either dock open
- Transport bar never moves or resizes

---

## Part 2: Expandable Lyrics Panel

### What Changed

**Added:**
- Expand/collapse button in the Lyrics tab toolbar (right side)
- Smooth width animation when toggling
- Panel expands from 320px to up to 560px (or 45% of window width, whichever is smaller)
- Only visible when on the Lyrics tab (tab index 1)

### Technical Implementation

**Modified Files:**
- `ui/panels/InfoPanel.qml` — Added expand state and animation
- `ui/Theme.qml` — Added `rightPanelExpandedWidth: 560` constant
- `ui/components/Glyphs.qml` — Added `expandPanel` and `collapsePanel` glyphs

**Behavior:**
- `lyricsExpanded` property tracks expand state
- Width calculation: `(currentTab === 1 && lyricsExpanded) ? expandedWidth : normalWidth`
- GlassPanel animates width changes smoothly
- Switching away from Lyrics tab resets `lyricsExpanded` to false
- Expand button only visible when `currentTab === 1`

### User Experience

- Open right panel (Ctrl+I) → defaults to Info tab at 320px
- Click Lyrics tab → see expand button in toolbar (right side)
- Click expand button → panel smoothly grows to ~560px
- Lyrics are now easier to read with more horizontal space
- Click collapse button → panel returns to 320px
- Switch to Equalizer tab → panel shrinks back to 320px automatically
- Switch back to Lyrics → starts at 320px (expand state resets)

---

## Visual Layout (ASCII Diagram)

```
┌──────────────────────────────────────────────────────────┐
│ Title Bar (always full-width)                            │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Stage (video) — ALWAYS full-width                      │
│                                                          │
│  ┌─────────┐                          ┌─────────────┐   │
│  │ Left    │                          │ Right       │   │
│  │ Panel   │   Video Area             │ Panel       │   │
│  │ (float) │   (full width)           │ (float)     │   │
│  │ z:10    │                          │ z:10        │   │
│  └─────────┘                          └─────────────┘   │
│                                                          │
│  Transport Bar (full-width, never moves)                │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## What Did NOT Change

- All playback controls work identically
- All keyboard shortcuts unchanged
- All panel contents unchanged (playlist, Info, Lyrics, Equalizer)
- All settings and preferences unchanged
- Fullscreen mode unchanged
- Drag-and-drop unchanged
- OSD (on-screen display) unchanged
- Auto-hide behavior unchanged

---

## Files Modified

1. **ui/Main.qml**
   - Restructured layout: Stage full-width, panels as overlays
   - Added `body.transportInset` and anchored both docks above the transport bar
   - Updated layout comments

2. **ui/panels/InfoPanel.qml** (42 lines added)
   - Added `lyricsExpanded` property
   - Added width animation logic
   - Added expand/collapse button in toolbar
   - Added GlassPanel width animation
   - Reset expand state when switching tabs

3. **ui/Theme.qml** (1 line added)
   - Added `rightPanelExpandedWidth: 560` constant

4. **ui/components/Glyphs.qml**
   - `expandPanel` / `collapsePanel` alias the existing `chevronLeft` (U+E76B)
     and `chevronRight` (U+E76C)
   - Do **not** use U+E902/U+E903 here: E902 is "Group" (an unrelated glyph) and
     E903 is unassigned in Segoe Fluent Icons, so it renders as tofu

---

## Testing Recommendations

1. **Panel Toggle:**
   - Open/close left panel (Ctrl+L) — should slide in/out
   - Open/close right panel (Ctrl+I) — should slide in/out
   - Both panels open at same time — should work
   - Video should always be full-width

2. **Panel Dismissal:**
   - Open a panel, click on the video area — the panel must stay open and the
     click should play/pause
   - The only things that close a dock are its toolbar button and Ctrl+L / Ctrl+I

3. **Lyrics Expand:**
   - Open right panel, switch to Lyrics tab
   - Click expand button — panel should grow smoothly
   - Click collapse button — panel should shrink
   - Switch to Info or Equalizer — panel should shrink automatically
   - Switch back to Lyrics — should start at normal width

4. **Transport Bar:**
   - Open/close panels — transport bar should never move
   - Play/pause, seek, volume — all should work normally
   - Transport bar position should be identical whether panels are open or closed
   - With either dock open, every control in the bar must remain visible and
     clickable — nothing overlaps it
   - Fullscreen: let the bar auto-hide with a dock open — the panel should grow
     to fill the freed space, and shrink back when the bar returns

---

## Known Limitations

1. **Panel Dismissal:**
   - Docks are dismissed only by their own toggles; there is no click-away
     shortcut. This is intentional — a click on the video is play/pause, and one
     gesture should not mean two things.

2. **Lyrics Expand:**
   - Expanded state resets when switching tabs (by design)
   - No memory of preference across sessions (could be added later if desired)

3. **Panel Width:**
   - Expanded width is capped at 560px or 45% of window width (whichever is smaller)
   - On very wide windows, panels won't take more than 45% to keep video visible

---

## Future Enhancements (Optional)

1. **Remember Lyrics Expand Preference:**
   - Save to settings, restore on next session
   - Add a toggle in Settings dialog

2. **Auto-Expand Lyrics:**
   - Automatically expand when lyrics are loaded
   - Collapse when no lyrics available

3. **Panel Opacity Control:**
   - Adjust panel transparency when floating over video
   - Make video more/less visible through panels

4. **Keyboard Shortcut for Lyrics Expand:**
   - Add a hotkey (e.g., Ctrl+Shift+L) to toggle expand without clicking

---

## Conclusion

Both features are fully implemented and integrated. The UI is now more modern (floating panels like Spotify/Discord) and more usable (expandable lyrics for better reading). No existing functionality was broken, and all changes follow the existing code style and architecture.
