import QtQuick
import Halcyon.Ui

// Minimal tab stack — shows one child at a time with the house fade.
// QtQuick.Layouts' StackLayout would do, but it pulls in a layout engine we do
// not otherwise need and animates nothing; this keeps motion on the §7 curve.
Item {
    id: root

    property int currentIndex: 0

    onCurrentIndexChanged: _apply()
    Component.onCompleted: _apply()
    onChildrenChanged: _apply()

    function _apply() {
        for (var i = 0; i < children.length; i++) {
            var child = children[i];
            child.visible = (i === root.currentIndex);
            child.anchors.fill = root;
        }
    }
}
