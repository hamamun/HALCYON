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
    flags: Qt.Popup | Qt.FramelessWindowHint
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
