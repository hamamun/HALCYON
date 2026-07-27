import QtQuick
import Halcyon.Ui

// Shared transport part — §B.4.
//
// ONE click target, TWO states: elapsed/total <-> remaining (§P1.5). Not two
// widgets, not a widget plus a menu item. The plan calls this out specifically
// because it is the smallest, clearest example of the Single-Placement Rule.
Item {
    id: root

    property int elapsed: 0        // ms
    property int duration: 0       // ms
    property bool showRemaining: false

    signal toggled()

    implicitWidth: label.implicitWidth + Theme.spaceMd
    implicitHeight: Theme.hitTarget
    width: implicitWidth

    function format(ms) {
        if (!isFinite(ms) || ms < 0) ms = 0;
        var total = Math.floor(ms / 1000);
        var h = Math.floor(total / 3600);
        var m = Math.floor((total % 3600) / 60);
        var s = total % 60;
        var mm = (h > 0 && m < 10 ? "0" : "") + m;
        var ss = (s < 10 ? "0" : "") + s;
        return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.showRemaining
              ? "-" + root.format(Math.max(0, root.duration - root.elapsed))
              : root.format(root.elapsed) + " / " + root.format(root.duration)
        font.family: Theme.fontFamilyMono
        font.pixelSize: Theme.fontSizeSmall
        color: mouse.containsMouse ? Theme.text : Theme.textMuted

        Behavior on color {
            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled()
    }
}
