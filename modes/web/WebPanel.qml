import QtQuick

// Placeholder left dock panel for Web mode — never shown because
// ModeSpec.panel_enabled is False (§P3.1, §P3.3).
Item {
    id: webPanelPlaceholder
    width: 0
    height: 0
    visible: false
}
