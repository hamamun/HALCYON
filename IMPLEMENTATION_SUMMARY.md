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
- Panels slide in/out from the edges

### Technical Implementation

**Modified Files:**
- `ui/Main.qml` — Restructured layout hierarchy
- Panels now use `z: 10` to float above the stage
- Stage uses full width (`anchors.left: parent.left; anchors.right: parent.right`)
- Transport bar remains inside Stage but Stage is now full-width

**Click-Outside-to-Close:**
- Added a transparent MouseArea at `z: 5` (below panels, above stage)
- Only visible when at least one panel is open
- Uses `propagateComposedEvents: true` so video clicks still work
- Checks mouse X position to determine if click is on a panel or empty space
- Clicks on panels: pass through to panel (no action)
- Clicks on empty stage area: close both panels + pass click to stage (video play/pause works)

### User Experience

- Open left panel (Ctrl+L) → slides in from left, overlays video
- Open right panel (Ctrl+I) → slides in from right, overlays video
- Both panels can be open simultaneously
- Click anywhere on the video (outside panels) → both panels close
- Video play/pause still works by clicking the video
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

1. **ui/Main.qml** (72 lines changed)
   - Restructured layout: Stage full-width, panels as overlays
   - Added click-outside-to-close MouseArea
   - Updated layout comments

2. **ui/panels/InfoPanel.qml** (42 lines added)
   - Added `lyricsExpanded` property
   - Added width animation logic
   - Added expand/collapse button in toolbar
   - Added GlassPanel width animation
   - Reset expand state when switching tabs

3. **ui/Theme.qml** (1 line added)
   - Added `rightPanelExpandedWidth: 560` constant

4. **ui/components/Glyphs.qml** (4 lines added)
   - Added `expandPanel` glyph (U+E902)
   - Added `collapsePanel` glyph (U+E903)

---

## Testing Recommendations

1. **Panel Toggle:**
   - Open/close left panel (Ctrl+L) — should slide in/out
   - Open/close right panel (Ctrl+I) — should slide in/out
   - Both panels open at same time — should work
   - Video should always be full-width

2. **Click-Outside-to-Close:**
   - Open a panel, click on video area — panel should close
   - Click should also trigger video play/pause
   - Click on panel itself — should interact with panel, not close it

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

---

## Known Limitations

1. **Click-Outside Behavior:**
   - Clicking outside a panel closes BOTH panels (not just the one you clicked outside of)
   - This is intentional — simpler mental model than tracking which panel to close

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
