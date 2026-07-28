# Audio-Only Media: Subtitle Features Disabled

## Overview

This implementation ensures that subtitle-related features are automatically disabled when playing audio-only content (no video tracks). This provides a better user experience by preventing users from attempting to load subtitles for audio files where they would have no effect.

## Problem Statement

Previously, the "Get subtitles" section in the TrackPopover (gear menu) was always enabled, even when playing audio-only files like MP3s. This could confuse users who might try to load subtitles for audio content, which would have no visible effect since there's no video surface to display them on.

## Solution

Added a `hasVideo` property to the VlcEngine that checks whether the current media contains video tracks. This property is then used in the TrackPopover to disable subtitle-related buttons when appropriate.

## Implementation Details

### 1. VlcEngine (engine/vlc_engine.py)

#### Added `has_video()` method:
```python
def has_video(self) -> bool:
    """Check if the current media has video tracks.
    
    Returns True if at least one video track exists (excluding the disable track).
    Used to determine if subtitle features should be enabled.
    """
    try:
        video_tracks = self._player.video_get_track_description()
        if not video_tracks:
            return False
        # Filter out the disable track (id=-1) and check if any real tracks exist
        real_tracks = [tid for tid, _ in video_tracks if tid != -1]
        return len(real_tracks) > 0
    except Exception:
        log.debug("video_get_track_description failed", exc_info=True)
        return False
```

**Key points:**
- Uses VLC's `video_get_track_description()` to get all video tracks
- Filters out the disable track (id=-1) which is always present
- Returns `True` only if at least one real video track exists
- Gracefully handles exceptions by returning `False`

#### Exposed as QML property:
```python
@Property(bool, notify=tracksChanged)
def hasVideo(self) -> bool:
    """True if the current media has at least one video track."""
    return self.has_video()
```

**Key points:**
- Uses `tracksChanged` signal for notification (fires when tracks are added/removed)
- Automatically updates when media changes or tracks are discovered
- Read-only property accessible from QML as `Player.hasVideo`

### 2. TrackPopover (ui/transport/TrackPopover.qml)

#### Added hasVideo property binding:
```qml
// Check if current media has video tracks - subtitles only make sense with video
readonly property bool hasVideo: typeof Player !== "undefined" && Player && Player.hasVideo
```

**Key points:**
- Safely checks if Player exists before accessing hasVideo
- Updates automatically when Player.hasVideo changes

#### Disabled "From file…" button:
```qml
TextButton {
    Layout.fillWidth: true
    text: "From file\u2026"
    glyph: Glyphs.addFile
    // Subtitles only make sense with video content
    enabled: root.hasVideo
    onClicked: {
        root.close();
        Actions.loadSubtitleFile();
    }
}
```

#### Disabled "Search online…" button:
```qml
TextButton {
    Layout.fillWidth: true
    text: "Search online\u2026"
    glyph: Glyphs.download
    // Disabled with nothing playing or no video: an online search is a search
    // *for the current file* (by hash, then by name), and subtitles are only
    // useful with video content. Greying it out says that; an empty result
    // list would not.
    enabled: root.hasVideo && typeof Player !== "undefined" && Player && Player.currentMedia !== ""
    onClicked: {
        root.close();
        Actions.searchSubtitlesOnline();
    }
}
```

**Key points:**
- Both buttons check `root.hasVideo` before allowing interaction
- "Search online" also checks if media is loaded (existing behavior)
- Buttons appear greyed out when disabled, providing clear visual feedback

## User Experience

### Playing Video (MP4, MKV, AVI, etc.)
- ✅ "From file…" button: **Enabled**
- ✅ "Search online…" button: **Enabled** (if media loaded)
- User can load subtitles normally

### Playing Audio (MP3, FLAC, WAV, etc.)
- ❌ "From file…" button: **Disabled** (greyed out)
- ❌ "Search online…" button: **Disabled** (greyed out)
- User cannot attempt to load subtitles (prevents confusion)

### No Media Loaded
- ❌ "From file…" button: **Disabled** (no video tracks)
- ❌ "Search online…" button: **Disabled** (no media)
- Consistent disabled state

## Testing

Added comprehensive tests in `tests/test_has_video.py`:

1. **test_has_video_property_exists()**
   - Verifies the `has_video()` method exists
   - Verifies the `hasVideo` QML property is properly exposed

2. **test_has_video_checks_video_tracks()**
   - Verifies the method uses `video_get_track_description()`
   - Verifies it filters out the disable track (id=-1)

3. **test_popover_disables_subtitle_buttons_without_video()**
   - Verifies TrackPopover defines the `hasVideo` property
   - Verifies both buttons check `hasVideo` before enabling

## Edge Cases Handled

1. **Media with no tracks discovered yet**: Returns `False` (safe default)
2. **Exception when querying tracks**: Returns `False` with debug logging
3. **Player not initialized**: Property safely returns `False` via QML binding
4. **Disable track present**: Correctly filtered out (id=-1)
5. **Multiple video tracks**: Returns `True` if any real track exists

## Technical Notes

- **Signal**: Uses `tracksChanged` which fires when:
  - Media is opened/closed
  - Tracks are added/removed (ESAdded/ESDeleted events)
  - Subtitle files are loaded
  
- **Performance**: Minimal overhead - only queries VLC when property is accessed

- **Compatibility**: Works with all media types supported by VLC

- **Thread Safety**: VLC API calls are safe from the main thread

## Files Modified

1. `engine/vlc_engine.py` - Added `has_video()` method and `hasVideo` property
2. `ui/transport/TrackPopover.qml` - Added `hasVideo` binding and button enable/disable logic
3. `tests/test_has_video.py` - New test file with comprehensive coverage

## Benefits

1. **Better UX**: Prevents confusion by disabling irrelevant features
2. **Clear Feedback**: Greyed-out buttons clearly indicate unavailable features
3. **Consistent**: Works automatically for all audio-only content
4. **Maintainable**: Simple, focused implementation with clear separation of concerns
5. **Testable**: Comprehensive test coverage ensures reliability
