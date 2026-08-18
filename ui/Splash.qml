import QtQuick
import QtQuick.Window

Window {
    id: splash

    width: 420
    height: 260
    visible: false
    color: "transparent"
    opacity: 1.0
    flags: Qt.SplashScreen
         | Qt.FramelessWindowHint
         | Qt.WindowStaysOnTopHint
         | Qt.WindowDoesNotAcceptFocus

    Rectangle {
        anchors.fill: parent
        radius: 28
        color: "#F20B0E14"
        border.width: 1
        border.color: "#2FFFFFFF"

        Column {
            anchors.centerIn: parent
            spacing: 14

            Image {
                width: 112
                height: 112
                anchors.horizontalCenter: parent.horizontalCenter
                source: Qt.resolvedUrl("../assets/halcyon.png")
                fillMode: Image.PreserveAspectFit
                asynchronous: false
                cache: true
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "HALCYON"
                color: "#F2F5F9"
                font.family: "Segoe UI Variable Display, Segoe UI, sans-serif"
                font.pixelSize: 24
                font.weight: Font.DemiBold
                font.letterSpacing: 4
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Loading\u2026"
                color: "#9EF2F5F9"
                font.family: "Segoe UI Variable Text, Segoe UI, sans-serif"
                font.pixelSize: 13
            }
        }
    }

    function dismiss() {
        if (!fadeOut.running)
            fadeOut.start();
    }

    NumberAnimation {
        id: fadeOut
        target: splash
        property: "opacity"
        from: 1.0
        to: 0.0
        duration: 160
        easing.type: Easing.OutCubic
        onFinished: splash.close()
    }
}
