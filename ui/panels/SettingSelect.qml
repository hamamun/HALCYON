import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// One labelled dropdown — §B.1, the sibling of SettingRow.
//
// Video backend was the only combo in Settings, so it was written inline with
// its own background and contentItem. Adding a second (subtitle language) would
// have meant copying thirty lines and letting the two drift, which is exactly
// what §B.1 forbids. Both now use this.
Item {
    id: root

    property string label: ""
    property string description: ""
    //: Either plain strings, or objects addressed by textRole/valueRole.
    property var model: []
    property string textRole: ""
    property string valueRole: ""
    property var value: ""

    signal activated(var value)

    implicitHeight: column.implicitHeight

    function _valueAt(index) {
        if (index < 0 || index >= combo.count)
            return "";
        return root.valueRole !== "" ? combo.valueAt(index) : combo.textAt(index);
    }

    function _indexOfValue(v) {
        if (root.valueRole !== "")
            return combo.indexOfValue(v);
        for (var i = 0; i < combo.count; i++)
            if (combo.textAt(i) === v)
                return i;
        return -1;
    }

    Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.spaceXs

        Row {
            width: parent.width
            spacing: Theme.spaceSm

            Text {
                width: 140
                anchors.verticalCenter: parent.verticalCenter
                text: root.label
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                color: Theme.text
            }

            ComboBox {
                id: combo
                width: parent.width - 140 - Theme.spaceSm
                model: root.model
                textRole: root.textRole
                valueRole: root.valueRole
                currentIndex: Math.max(0, root._indexOfValue(root.value))
                onActivated: root.activated(root._valueAt(currentIndex))

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: Theme.glassFill
                    border.width: 1
                    border.color: Theme.glassBorder
                }
                contentItem: Text {
                    leftPadding: Theme.spaceMd
                    text: combo.displayText
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.text
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }

        Text {
            width: parent.width
            text: root.description
            visible: text.length > 0
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }
    }
}
