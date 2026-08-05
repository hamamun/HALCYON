import QtQuick
import QtQuick.Controls
import QtQuick.Window
import Halcyon.Ui

// A real native popup window for Web chrome.
//
// A QML Popup is scene-graph content and therefore sits *under* the WebView2
// native child HWND whenever it extends into pageArea.  BrowserPopup is an
// owned Qt.Popup window instead, so bookmark menus/dialogs stay above the page
// without opening an external browser window.
Window {
    id: root
    // True for dialogs that must take focus (bookmark forms with text input);
    // false for autocomplete-style overlays that must never steal focus from
    // the address bar or the WebView2 page (tooltip-like, no activation).
    //
    // Windows quirk (the "only one letter typed" bug): a Qt.Popup window grabs
    // keyboard focus when it is shown, even combined with
    // Qt.WindowDoesNotAcceptFocus — so the very first keystroke that opened the
    // suggestions popup made the address bar lose focus and every later key
    // went nowhere.  Tooltip-style flags are the Qt recipe for this: on
    // Windows they map to WS_EX_NOACTIVATE, i.e. the window is shown without
    // ever being activated, so focus stays in the address bar exactly like
    // Edge's in-window dropdown.
    property bool acceptsFocus: true
    flags: acceptsFocus
           ? Qt.Popup | Qt.FramelessWindowHint
           : Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
             | Qt.WindowDoesNotAcceptFocus
    color: "transparent"
    visible: false

    property var hostWindow: null
    default property alias content: panel.data

    function showBelow(anchorItem, ownerWindow) {
        if (!anchorItem || !ownerWindow)
            return
        hostWindow = ownerWindow
        transientParent = ownerWindow
        var point = anchorItem.mapToGlobal(anchorItem.width - root.width,
                                           anchorItem.height + Theme.spaceXs)
        x = Math.round(point.x)
        y = Math.round(point.y)
        visible = true
        raise()
        if (acceptsFocus)
            requestActivate()
    }

    function hidePopup() {
        visible = false
    }

    onClosing: function(close) {
        // Keep the component alive for the next click; a popup is chrome, not
        // a document window that should be destroyed when dismissed.
        close.accepted = false
        visible = false
    }

    Rectangle {
        id: panel
        anchors.fill: parent
        radius: Theme.radiusControl
        color: Theme.baseElevated
        border.width: 1
        border.color: Theme.glassBorderStrong
    }

    Shortcut {
        sequence: "Esc"
        enabled: root.visible
        onActivated: root.hidePopup()
    }
}
