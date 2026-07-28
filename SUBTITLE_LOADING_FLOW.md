# Subtitle Loading Flow: Video Transition

This document explains how subtitles (both local sidecar and embedded) are loaded when one video finishes and the next starts playing.

## Scenario
- Video 1: "black baby" (has local sidecar .srt + embedded subtitles)
- Video 2: "white adult" (has local sidecar .srt + embedded subtitles)
- "black baby" finishes → "white adult" starts automatically

## Flow

### Step 1: "black baby" Finishes
```
endReached signal → _on_end_reached() → target.play_next()
```

### Step 2: "white adult" Opens
```
play_next() → controller.openPath("white adult.mkv")
  → VlcEngine.open("white adult.mkv")
    → ✅ CLEARS subtitle state:
       - _external_subtitle_names.clear()
       - _pending_external_subtitles.clear()
    → Starts playing "white adult"
```

**Why clear?** Track IDs are per-media. Old mappings from "black baby" are meaningless for "white adult". Without clearing, stale pending names could incorrectly rename tracks in "white adult".

### Step 3: Media Changed Signal
```
VlcEngine emits mediaChanged → _on_media_changed("white adult.mkv")
  → Sets _resume_path = "white adult.mkv"
  → Resets _audio_restored = False, _subtitle_restored = False
  → Calls _auto_load_subtitle("white adult.mkv")
  → Calls _refresh_tracks()
```

### Step 4: Auto-Load Sidecar Subtitles
```
_auto_load_subtitle("white adult.mkv")
  → Looks for "white adult.srt", "white adult.ass", etc.
  → If found: _engine.add_subtitle_file("white adult.srt")
    → VlcEngine.add_subtitle_file():
      → Calls libVLC add_slave()
      → ✅ QUEUES filename: _pending_external_subtitles.append("white adult")
```

**Note:** VLC assigns track IDs asynchronously. The filename is queued and matched to the track later.

### Step 5: Refresh Tracks (First Pass)
```
_refresh_tracks()
  → Gets tracks from engine:
    - audio_tracks() → embedded audio tracks
    - subtitle_tracks() → embedded + external subtitles
      → Processes _pending_external_subtitles
      → If VLC discovered the track: assigns filename, removes from pending
      → If VLC hasn't discovered yet: keeps in pending list
  → _restore_remembered_tracks()
    → Checks if user previously watched "white adult" and selected specific tracks
    → If yes: restores those tracks
    → If no: does nothing
  → _auto_select_default_audio()
    → If no audio track selected (current == -1): selects first real track
    → If track already selected: does nothing
  → _refresh_current_tracks()
    → Publishes current track IDs to UI
  → Emits tracksChanged signal
```

### Step 6: VLC Discovers External Subtitle (Asynchronous)
```
VLC fires ESAdded event → tracksChanged signal → _refresh_tracks() (again)
  → subtitle_tracks() now sees the external subtitle track
  → Matches pending filename "white adult" to the track with generic name
  → Replaces "Subtitle Track 1" with "white adult"
  → Caches mapping in _external_subtitle_names
```

## Result

When "white adult" starts playing, the subtitle section shows:

**Embedded Subtitles:**
- Show original names from container metadata (e.g., "English", "Japanese SDH")
- Not affected by my changes (they already have proper names)

**Local Sidecar Subtitles:**
- Show actual filename (e.g., "white adult" instead of "Subtitle Track 1")
- Loaded automatically via `_auto_load_subtitle()`
- Renamed via the pending list mechanism

**Audio Tracks:**
- If user previously selected a track for "white adult": restored
- Otherwise: first track auto-selected (if none was selected by VLC)

## Edge Cases Handled

1. **Multiple sidecar subtitles:** All are loaded and renamed correctly
2. **No sidecar subtitle:** Only embedded subtitles shown
3. **No embedded subtitles:** Only sidecar subtitle shown (if exists)
4. **User had remembered tracks:** Restored correctly
5. **VLC hasn't discovered track yet:** Filename stays in pending list, assigned on next refresh
6. **Generic-named embedded track:** Not renamed (only external subtitles are renamed)

## Verification

The flow is correct because:
1. ✅ Subtitle state is cleared when new media opens (prevents cross-contamination)
2. ✅ Sidecar subtitles are loaded for the new media
3. ✅ Filenames are queued and matched to tracks asynchronously
4. ✅ Remembered tracks are restored for the new media
5. ✅ Audio auto-selection works for the new media
6. ✅ All operations happen in the correct order

## Code References

- `VlcEngine.open()`: Clears subtitle state
- `AppController._on_media_changed()`: Orchestrates the transition
- `AppController._auto_load_subtitle()`: Loads sidecar subtitles
- `VlcEngine.add_subtitle_file()`: Queues filename
- `VlcEngine.subtitle_tracks()`: Processes pending list and renames tracks
- `AppController._refresh_tracks()`: Publishes tracks to UI
- `AppController._restore_remembered_tracks()`: Restores user preferences
- `AppController._auto_select_default_audio()`: Auto-selects first audio track
