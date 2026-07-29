import QtQuick
import Halcyon.Ui

// One labelled segmented choice — §B.1, the third sibling of SettingRow
// (a toggle) and SettingSelect (a dropdown).
//
// Why this exists as a component, and why it holds its own state
// --------------------------------------------------------------
// The "Search results: Best match / All results" picker was written inline in
// SettingsDialog, and every segment decided whether it was the current one with
//
//     readonly property bool isCurrent: Settings.get("subs.online.matchMode", "best") === modelData.id
//
// `Settings.get` is a **Slot**, not a Q_PROPERTY. QML records a dependency on
// properties, not on function calls, so that binding was evaluated exactly once
// — when the delegate was created — and never again. Clicking "All results"
// therefore wrote the setting and changed nothing on screen: the highlight, and
// the explanatory paragraph below it, both stayed on whatever the value had
// been when the dialog was first built. It looked precisely like "it will not
// let me switch to All results", and then — once the value *had* moved, on the
// next construction — like "it will not let me switch back to Best match".
//
// The fix has two halves and needs both:
//
//   1. `value` is a real QML property here, so everything that reads it is a
//      live binding. A click updates it immediately, which is what makes the
//      control feel like a control.
//   2. A `Connections` on `Settings.changed` re-reads it, so the control also
//      tracks changes made anywhere else — including a `set()` that the store
//      coalesced away, and any future second view of the same key.
//
// Writing goes through Settings exactly once, in `_choose`, so a segment cannot
// drift from what is persisted.
Item {
    id: root

    property string label: ""
    property string description: ""
    //: `[{ id, label }]` — `id` is the persisted value, `label` is what is drawn.
    property var options: []
    //: The settings key this control owns. Reading and writing both go through
    //: it, so there is one source of truth rather than a value passed in and a
    //: setter passed back that could disagree.
    property string settingKey: ""
    property string defaultValue: ""

    //: The live value. Seeded from Settings, kept in step by the Connections
    //: below, and read by every binding in here.
    property string value: root._read()

    //: Width of the label column, matched to SettingRow/SettingSelect so the
    //: three line up in the same dialog.
    property int labelWidth: 140

    signal chosen(string value)

    implicitHeight: column.implicitHeight

    function _read() {
        if (typeof Settings === "undefined" || !Settings || settingKey === "")
            return defaultValue;
        return String(Settings.get(settingKey, defaultValue));
    }

    function _choose(next) {
        if (String(next) === value)
            return;
        value = String(next);
        if (typeof Settings !== "undefined" && Settings && settingKey !== "")
            Settings.set(settingKey, value);
        root.chosen(value);
    }

    // Re-read on any external change. `Settings.changed` is emitted for every
    // key, so filter — otherwise an unrelated write would still cost a read.
    Connections {
        target: (typeof Settings !== "undefined" && Settings) ? Settings : null
        enabled: target !== null

        function onChanged(key, newValue) {
            if (key === root.settingKey)
                root.value = String(newValue);
        }
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
                width: root.labelWidth
                anchors.verticalCenter: parent.verticalCenter
                text: root.label
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                color: Theme.text
            }

            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spaceXs

                Repeater {
                    model: root.options

                    delegate: Rectangle {
                        id: segment
                        required property var modelData
                        // A live binding now: `root.value` is a property, so
                        // this re-evaluates the instant a segment is clicked.
                        readonly property bool isCurrent: root.value === String(modelData.id)

                        width: 104
                        height: 30
                        radius: Theme.radiusSmall
                        color: isCurrent ? Theme.accentDim
                             : segmentMouse.containsMouse ? Theme.glassFillHover
                             : Theme.glassFill
                        border.width: 1
                        border.color: isCurrent ? Theme.accent : Theme.glassBorder

                        Behavior on color {
                            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                        }

                        Text {
                            anchors.centerIn: parent
                            text: segment.modelData.label
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            color: segment.isCurrent ? Theme.accent : Theme.textMuted
                        }

                        MouseArea {
                            id: segmentMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root._choose(segment.modelData.id)
                        }
                    }
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
