# Borderless Mode — Implementation Summary

> Owner decisions locked 13 Aug 2026: drag from the hover/inline chrome only,
> window buttons + badge on the hover overlay (Local/M3U) / inline in the tab
> strip (Web), toggle via Settings + Ctrl+Shift+B.

## 1. What It Is
- **Shell state, NOT a 4th ModeSpec** — the same class as Fullscreen and Mini Mode.
- `borderlessActive` (persisted) + `borderlessEffective` (derived gate) in `ui/Main.qml`.
- `borderlessEffective = borderlessActive && !miniModeActive && !fullscreen` — it
  never stacks with Mini or Fullscreen, both of which already hide the title bar
  their own way. This single derived gate is why every state transition
  (borderless⇄fullscreen⇄mini) is clean: nothing imperative to sequence.
- The window is **already frameless** at all times (`Qt.FramelessWindowHint`), so
  borderless changes **no window flags** — it only hides the title-bar *content*.
  No OS-level window churn, so it cannot break window management.

## 2. Toggle
- **Settings ▸ General ▸ Window ▸ "Borderless"** (a new "Window" section placed
  directly above "Mobile Remote"/QR).
- **Ctrl+Shift+B** — global `Shortcut`, plain-windowed only (ignored in
  Mini/Fullscreen because `borderlessEffective` gates the visuals).
- Both routes drive `borderlessActive`; the property persists itself via
  `onBorderlessActiveChanged`. It is seeded from settings in
  `Component.onCompleted` (plain-bool convention, so the write-back never
  clobbers a declared binding — same rule as `leftPanelOpen`).

## 3. Where the controls go
| Mode | Window buttons + badge | Drag surface |
|---|---|---|
| **Local / M3U** | Hover overlay strip at the top (fades with `chromeVisible`) | "⤧ Drag to move" zone in that strip → `startSystemMove()` |
| **Web** | Inline at the right end of `TabsRow` (its own layout slot, no Mini button) | Empty area of the tab strip → `startSystemMove()` |

- The button/badge cluster is extracted **once** into
  `ui/components/WindowButtons.qml` (registered in `Halcyon.Ui`). The title bar,
  the borderless overlay and the Web tab strip all render *that* component — one
  source of truth (§B.1), not three lookalikes.
- The AS/AT/T/S badge stays a read-out only; it never appears in Web (no video route).

## 4. Auto-hide / dragging tradeoff
- `autoHideActive = fullscreen || borderlessEffective` — the transport bar and
  the overlay follow the existing fade-in-on-move / fade-out-when-idle cycle.
- **Cursor blanking stays fullscreen-only** (`window.fullscreen && !chromeVisible`)
  — a windowed frame keeps its pointer; only the chrome fades.
- Consequence (accepted): while a video plays and the overlay has faded, the
  window is momentarily un-draggable until a mouse-move re-reveals the strip —
  the same behaviour fullscreen already has.

## 5. Layout safety (the two collisions the owner flagged)
- **Local/M3U docks** (playlist `PanelHost`, `InfoPanel`) run the full height to
  the top edge. `body.borderlessTopInset` (= title-bar height while the overlay
  is shown) pushes their `top` down so the drag strip and buttons are never
  covered. It is the exact top-side twin of the existing bottom `transportInset`.
  The OSD gets the same top margin so toasts stay clear.
- **Web** is excluded from the overlay/inset entirely; its buttons take a
  reserved layout slot in the tab row, so they can never overlap the tab chips,
  and the native page surface is never touched.
- **WebView2 viewport**: removing the 44px title bar shifts the page area's
  on-screen origin without changing its local coords, so `WebStage` watches the
  host `borderlessEffective` flag and re-runs `scheduleBrowserSurfaceSync()`.

## 6. Files touched
- `ui/components/WindowButtons.qml` — **new** shared cluster.
- `Halcyon/Ui/qmldir` — registers it.
- `ui/shell/TitleBar.qml` — delegates its button Row to `WindowButtons` (keeps
  `videoBadgeVisible` as its public/tested contract).
- `ui/Main.qml` — state, action, shortcut, title-bar gating, overlay, dock insets,
  auto-hide gate, cursor-blanker narrowing, dialog `hostWindow` wiring.
- `ui/panels/SettingsDialog.qml` — the "Window ▸ Borderless" toggle + `hostWindow`.
- `modes/web/TabsRow.qml`, `modes/web/WebStage.qml` — inline buttons + drag +
  viewport resync in Web.
- `tools/check_isolation.py` — `PHASE_B_DISCLOSED` (documents the frozen-path edits).
- `tests/test_chrome_behaviour.py`, `tests/test_video_mode_badge.py` — updated to
  the new (correct) structure.

## 7. Verification
- Full suite: **562 passed** (up from 560), 0 new failures. The 11 failures / 16
  errors present are pre-existing and environmental only (no `libGL`, no
  `aiohttp` in the sandbox) — identical on the untouched base commit.
- `python tools/check_isolation.py --phase 3/4` — green, including the
  frozen-path rule.
- All changed QML files parse (`qmlformat`) and lint (`qmllint`) with no errors;
  `WindowButtons` resolves as a type in all three consumers.

## 8. Known cosmetic note
- In borderless *windowed* (non-maximized) mode the rounded window corners at the
  very top show video slightly squared, because the app has never masked video to
  the corner radius anywhere (pre-existing characteristic; corners are 0 when
  maximized/fullscreen). Not a regression; can be masked later if desired.

## 9. Not verifiable in this sandbox
- Live QML instantiation needs a `QGuiApplication`, which needs `libGL.so.1`
  (absent here) — so the GUI-instantiation tests skip and I could not click the
  toggle. Validation was lint + parse + full logic suite. A visual pass on
  Windows is recommended for final sign-off.
