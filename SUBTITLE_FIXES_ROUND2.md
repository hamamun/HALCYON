# Subtitle download box — second pass

Five reports came back after the first round of fixes. Each of them had a real
remaining cause; the first pass had addressed the symptom, or had fixed a
neighbouring thing and left the actual defect in place. This is what was
actually wrong and what was changed.

Every fix below has behavioural tests, not source-grep tests. Two of the old
checks in `tests/test_subtitle_naming.py` asserted that a specific *line of
source* existed — they passed happily while the behaviour was broken, and then
failed the moment the line was improved. They have been replaced with tests
that call the code.

---

## 1. Audio → "Off" would not stay off

**Where:** `core/app.py`, `_auto_select_default_audio`.

Turning audio off is a selection of libVLC's track id `-1`. The rescue added in
the previous round — "if nothing is selected, select the first real track", for
files libVLC opens silent — ran on **every** `_refresh_tracks`.

libVLC raises `tracksChanged` freely: on `ESAdded`, on `ESDeleted`, when an
`.srt` is attached, when a demuxer is re-opened. Every one of those refreshes
saw *"current is -1 and real tracks exist"* and switched the audio straight back
on. The rescue was overwriting the user, once per event, so Off could never be
made to stick — it would light up for an instant and snap back.

**Fixed** with two latches, because they answer two different questions:

| latch | question | set by |
|---|---|---|
| `_audio_user_choice` | did the user express an intent for this file? | `setAudioTrack`, `cycleAudioTrack` |
| `_audio_auto_selected` | have we already had our one go? | the rescue itself |

Both reset in `openPath` and `_on_media_changed`, so the next file still gets
its own one-shot rescue. The latch in the setters is taken **before** the engine
call, because setting a track makes libVLC raise `tracksChanged` synchronously —
latching afterwards would let that re-entrant refresh undo the switch to Off
before the setter had finished making it.

Subtitles are deliberately left alone: they default to off on purpose, and
auto-selecting one would put unwanted text over every video.

## 2. Download needed a double click

**Where:** `ui/components/ListRow.qml`.

Not a subtitle bug at all — a stacking-order bug in the shared row.

QML siblings stack in declaration order, so the row's `MouseArea`, declared
*after* the content `Item`, sat on top of everything the row contained. The
per-result **Download** button never saw the press; the row did. Only the row's
`doubleClicked` — wired to the same download — appeared to work, which is
exactly the reported symptom.

**Fixed** by declaring the hit area before the content. Plain `Text`/`Item`
children accept no mouse events, so clicks still fall through to it and rows
stay clickable; real controls placed in a row now work on the first click.

This fixes the same latent bug for every other user of `ListRow` (the playlist,
the track sections) rather than only the search dialog.

## 3. Button labels were left-aligned

**Where:** `ui/components/TextButton.qml`.

The `contentItem` was the label `Row` itself, with `anchors.centerIn: parent`.
A `Control` positions and resizes its own `contentItem`, so those anchors were
silently ignored — the Row kept its implicit width and sat at x = 0.

Invisible while a button hugged its label, and plainly wrong the moment anything
set an explicit width. The search dialog's full-width **Search** button and the
footer's **Close** button both do, which is why those two were the ones noticed.

**Fixed** by making the `contentItem` a plain `Item` the control is free to
stretch, with the glyph+label Row centred inside *that*. `implicitWidth` still
reports the label's size, so an unsized button is exactly as wide as before —
nothing else in the UI moves. Padding now uses the shared `Theme.spaceLg` token
through `leftPadding`/`rightPadding` rather than being open-coded.

## 4. Loaded subtitles still showed "Track xx"

**Where:** `engine/vlc_engine.py`, `subtitle_tracks` and a new `_subtitle_label`.

Two independent causes, both fixed.

**(a) The name was claimed by matching the label.** The engine looked for a
track whose name matched a hand-written list of libVLC's placeholder wordings
(`Subtitle Track 1`, `Track 1`, …). Any build or locale that phrased it
differently — `Track 4 - [Undetermined]`, `Subtitle track #1`, a bare language
code — failed the regex and kept its number. Worse, the *first* generic-looking
row won, so an unnamed **embedded** track could be given the sidecar's name
while the sidecar itself kept its number.

Claiming is now by **track id**. `_known_spu_ids` records which SPU ids existed
before each slave was attached; anything outside that set appeared since, and
`add_slave` is the only thing that adds a subtitle track mid-playback. Ids are
compared, not prose, so this holds in every locale and on every libVLC build.

Names are claimed from the **tail** of the fresh ids. Auto-load fires on
`mediaChanged` and can beat libVLC's discovery of the file's embedded subtitle
streams, so one refresh may surface two embedded tracks and the slave at once —
all "fresh". libVLC appends slaves last, so the last N fresh ids are the N
tracks `add_slave` produced. Claiming from the front would have named an
embedded track after the sidecar, which is the same bug in a different hat.

**(b) The name it stored was unreadable anyway.** The raw stem was queued, and a
downloaded subtitle is saved as `<media stem>.<lang>.srt`. The row therefore read
`Andor.S02E01.1080p.WEB-DL.x265-GROUP.en`, which in a 340px popover elides to
`Andor.S02E01.1080p.WEB…` — identical for every subtitle of that film, and so
distinguishing nothing.

`_subtitle_label` strips the media's own name off the front and reads what is
left:

| file | label |
|---|---|
| `Andor.S02E01.en.srt` | English |
| `Movie.en.sdh.srt` | English SDH |
| `Movie.pt-BR.srt` | Portuguese (BR) |
| `Movie.eng.forced.srt` | English forced |
| `my-custom-subs.srt` | my-custom-subs *(verbatim — the user's own naming)* |
| `Movie.srt` | Movie *(nothing to add, never blank)* |

Labelling is fully guarded and never fails the attach: the slave is already
loaded by that point, so failing to work out a pretty name must cost the name,
not the subtitle.

### Also fixed here: downloads did not come back

`core/subtitles._save` writes `<media stem>.<lang>.srt` so two languages can sit
side by side, and the Settings row promises the file lands *"beside the media
file so they auto-load next time"*. But `_auto_load_subtitle` only ever tried
`Path.with_suffix` — `Movie.srt`. `Movie.en.srt` was on disk, correct, and never
looked for, so a downloaded subtitle worked for the session it was fetched in
and then silently vanished.

Auto-load now falls back to a stem-prefixed scan (glob-escaped, so
`Movie [2021].mkv` is not read as a character class), filtered to subtitle
extensions so a sibling `Movie.en.mkv` is never attached as a subtitle. Exactly
one is loaded — several are usually the same subtitle in several languages, and
attaching them all buries the track list.

## 5. Match mode would not switch, in either direction

**Where:** `ui/panels/SettingsDialog.qml`, now `ui/panels/SettingChoice.qml`,
and `core/subtitles.py`.

Also two causes.

**(a) The picker was inert.** Each segment decided whether it was current with

```qml
readonly property bool isCurrent: Settings.get("subs.online.matchMode", "best") === modelData.id
```

`Settings.get` is a `Slot`, not a `Q_PROPERTY`. QML records binding dependencies
on *properties*, not on function calls, so that expression was evaluated once —
when the delegate was created — and never again. Clicking a segment wrote the
setting correctly and changed nothing on screen. The explanatory paragraph below
it had the identical dead binding. That is the report exactly: it would not
switch to All results, and once the value had moved (on the next construction)
it would not switch back to Best.

**Fixed** by extracting `SettingChoice` — the third sibling of `SettingRow` (a
toggle) and `SettingSelect` (a dropdown), per §B.1, since inline is where the
bug lived. `value` is a real QML property, so everything reading it is a live
binding, and a `Connections` on `Settings.changed` keeps it in step with writes
made anywhere else. Writing goes through `Settings` in exactly one place.

**(b) "Best match" genuinely returned nothing.** Best sent
`moviehash_match=only`, asking OpenSubtitles to discard everything its hash index
does not vouch for. That index covers a small slice of the site, so for most real
files the server returned an **empty payload** — Best said *"No subtitles found,
try All results"*, All then returned fifty rows, and the two modes read as "one
of them is broken" rather than as narrow versus wide. The advice was also
self-defeating: the file often had perfectly good title matches that Best was
never shown, because they had been filtered out server-side where no amount of
client ranking could recover them.

The hash is still sent — it is what earns the "exact" badge and drives the whole
Best ordering — but as `include`. Narrowing now happens once, client-side, in
`rank_results`, which already implemented exactly that policy: hash matches
first, then strict title/episode matches, then a short tail of best-effort
candidates. Same promise to the user, actually kept.

---

## Verification

```
352 passed, 18 skipped
```

New behavioural coverage:

* `tests/test_track_selection.py` — Off sticks through a burst of refreshes and
  through cycling; the rescue still fires once for a fresh file, does not fire
  twice, and a new file gets its own; subtitles are never auto-selected.
* `tests/test_subtitle_naming.py` — a fresh track takes the pending name and
  keeps it; embedded tracks keep theirs; a name waits for a track that has not
  been published yet; the late-embedded-tracks race; every `_subtitle_label`
  shape above; the qualified-sidecar auto-load, including glob escaping.
* `tests/test_track_popover_layout.py` — row hit area precedes content; single
  click download; the button centres its label and still hugs it when unsized;
  the choice control binds a property, tracks external changes and writes once.
* `tests/test_subtitle_search.py` — the hash never filters server-side; both
  modes send one query shape; Best narrows the same payload All would show and
  still returns rows when nothing hash-matched.

`pyside6-qmllint` reports no errors on any changed QML (only the pre-existing
"unqualified access" warnings for context properties, which every file in the
project has).
