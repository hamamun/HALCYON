import QtQuick
import Halcyon.Ui
import Halcyon.Engine

// The default stage: video (§0.3, §P1.2).
//
// This is `ModeSpec.stage_qml`'s default. Local and M3U both use it unchanged —
// the same pipeline, the same surface, no per-mode video code. Web overrides it
// (§P3.3).
//
// Two pixel paths, chosen at runtime by what the ring actually holds:
//   planar (I420) -> ShaderEffect samples Y/U/V, BT.709 in a fragment shader
//   packed (RV32) -> the surface draws itself, no shader
Item {
    id: root

    readonly property alias surface: videoSurface
    readonly property bool hasVideo: videoSurface.hasVideo
    readonly property rect contentRect: videoSurface.contentRect

    VideoSurface {
        id: videoSurface
        anchors.fill: parent
        fillMode: 1                      // PreserveAspectFit

        Component.onCompleted: {
            if (typeof Player !== "undefined")
                setSource(Player);
        }

        // RV32 fallback draws through the item itself; in planar mode the item
        // contributes nothing and the ShaderEffect below does the drawing.
        visible: !isPlanar
    }

    // YUV -> RGB. Only instantiated on the planar path, and only once the
    // compiled shader exists (tools/build_shaders.py).
    ShaderEffect {
        id: yuvEffect
        visible: videoSurface.isPlanar && videoSurface.hasVideo
        x: videoSurface.contentRect.x
        y: videoSurface.contentRect.y
        width: videoSurface.contentRect.width
        height: videoSurface.contentRect.height

        property variant y: videoSurface.planeY
        property variant u: videoSurface.planeU
        property variant v: videoSurface.planeV

        fragmentShader: "qrc:/ui/shaders/yuv420p.frag.qsb"

        onStatusChanged: {
            if (status === ShaderEffect.Error)
                console.warn("YUV shader failed to load — run tools/build_shaders.py;"
                             + " set video.backend='rv32' to fall back:", log);
        }
    }

    // Double-click toggles fullscreen — the *same* action as the transport
    // button and the F key (§4.1). Not a second implementation.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onDoubleClicked: Actions.toggleFullscreen()
        onClicked: Actions.playPause()
    }
}
