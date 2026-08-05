import QtQuick
import QtQuick.Layouts
import Halcyon.Ui

// Omnibox-style suggestions: local tabs + bookmarks + free Google search suggestions.
// Uses BrowserPopup (native Qt.Popup Window) so it stays above the WebView2 HWND.
// The popup is tooltip-style non-activating (acceptsFocus: false): it never
// steals focus from the address bar or the page while typing.
BrowserPopup {
    id: root

    // Bound from AddressBar
    property var browser: null
    property string queryText: ""
    property int selectedIndex: -1
    property bool hasSelection: selectedIndex >= 0 && selectedIndex < suggestionsModel.count

    // Internal
    property int maxVisible: 10
    readonly property int rowHeight: 44

    // Suggestions are chrome, not a dialog: never take activation/focus
    acceptsFocus: false

    width: 480
    // Height is driven only by updateHeight() through desiredHeight, so the
    // declarative `height` binding is never overwritten imperatively
    // (avoids "QML Binding: overwriting binding" warnings).
    property int desiredHeight: 0
    height: desiredHeight

    signal suggestionAccepted(string text)

    function updateHeight() {
        var count = suggestionsModel.count
        if (count === 0) {
            desiredHeight = 0
            return
        }
        var visibleCount = Math.min(count, maxVisible)
        desiredHeight = Math.min(visibleCount * rowHeight + Theme.spaceSm * 2, 400)
    }

    function hidePopup() {
        visible = false
        selectedIndex = -1
        queryText = ""
        debounceTimer.stop()
        // keep model until next show to avoid flicker when hiding
    }

    function showFor(anchorItem, ownerWindow, text) {
        if (!anchorItem || !ownerWindow)
            return
        var trimmed = (text || "").trim()
        if (trimmed.length === 0) {
            hidePopup()
            return
        }
        queryText = trimmed
        selectedIndex = -1
        rebuildLocal(trimmed)

        // Position below anchor (url field)
        hostWindow = ownerWindow
        transientParent = ownerWindow
        var pt = anchorItem.mapToGlobal(0, anchorItem.height + Theme.spaceXs)
        x = Math.round(pt.x)
        y = Math.round(pt.y)
        width = Math.round(anchorItem.width)

        // If we already have local results, show immediately; remote will append later
        if (suggestionsModel.count > 0) {
            updateHeight()
            visible = true
            raise()
        } else {
            // No local yet — keep hidden until remote arrives, but still prepare to show
            visible = false
        }

        // Debounce Google fetch
        debounceTimer.restart()
    }

    function rebuildLocal(text) {
        suggestionsModel.clear()
        if (!text || !browser)
            return
        var qLow = text.toLowerCase()
        // 1) Open tabs
        try {
            var tabs = browser.tabs || []
            var count = 0
            for (var i = 0; i < tabs.length; ++i) {
                var t = tabs[i]
                if (!t || !t.url) continue
                if (t.internal) continue
                var titleMatch = t.title && t.title.toLowerCase().indexOf(qLow) !== -1
                var urlMatch = t.url && t.url.toLowerCase().indexOf(qLow) !== -1
                if (titleMatch || urlMatch) {
                    // avoid duplicate of same url
                    var dup = false
                    for (var d = 0; d < suggestionsModel.count; ++d) {
                        if (suggestionsModel.get(d).url === t.url) { dup = true; break }
                    }
                    if (dup) continue
                    suggestionsModel.append({
                        type: "tab",
                        glyph: Glyphs.globe,
                        title: t.title || t.url,
                        url: t.url,
                        displayUrl: t.url
                    })
                    count++
                    if (count >= 3) break
                }
            }
        } catch (e) { }

        // 2) Bookmarks
        try {
            var bms = browser.bookmarkItems || []
            for (var j = 0; j < bms.length; ++j) {
                var b = bms[j]
                if (!b || !b.url) continue
                var bTitleMatch = b.title && b.title.toLowerCase().indexOf(qLow) !== -1
                var bUrlMatch = b.url && b.url.toLowerCase().indexOf(qLow) !== -1
                if (bTitleMatch || bUrlMatch) {
                    var dup2 = false
                    for (var d2 = 0; d2 < suggestionsModel.count; ++d2) {
                        if (suggestionsModel.get(d2).url === b.url) { dup2 = true; break }
                    }
                    if (dup2) continue
                    suggestionsModel.append({
                        type: "bookmark",
                        glyph: Glyphs.bookmark,
                        title: b.title || b.url,
                        url: b.url,
                        displayUrl: b.url
                    })
                    if (suggestionsModel.count >= 6) break
                }
            }
        } catch (e2) { }
    }

    function fetchGoogleSuggestions(q) {
        var trim = (q || "").trim()
        if (trim.length === 0) return
        // Capture the query that triggered this fetch to discard stale results
        var requestedQuery = trim
        var url = "https://suggestqueries.google.com/complete/search?client=firefox&q=" + encodeURIComponent(trim)
        var xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE) {
                // If user typed something else while this request was in flight, ignore stale result
                if (root.queryText !== requestedQuery) return
                if (xhr.status === 200) {
                    try {
                        var data = JSON.parse(xhr.responseText)
                        var arr = (data && data.length > 1) ? data[1] : []
                        if (!arr || arr.length === 0) {
                            if (suggestionsModel.count === 0) {
                                hidePopup()
                            }
                            return
                        }
                        // Append remote, avoiding duplicates with local urls/titles
                        for (var i = 0; i < arr.length; ++i) {
                            var sug = arr[i]
                            if (!sug) continue
                            // skip if already in model as title
                            var exists = false
                            for (var k = 0; k < suggestionsModel.count; ++k) {
                                if (suggestionsModel.get(k).title.toLowerCase() === sug.toLowerCase()) { exists = true; break }
                            }
                            if (exists) continue
                            if (suggestionsModel.count >= maxVisible + 4) break
                            suggestionsModel.append({
                                type: "search",
                                glyph: Glyphs.search,
                                title: sug,
                                url: sug,
                                displayUrl: "Search Google"
                            })
                        }
                        if (suggestionsModel.count > 0) {
                            updateHeight()
                            if (!visible) {
                                visible = true
                                raise()
                            }
                        }
                    } catch (e) {
                        // ignore parse error - keep local results
                    }
                } else {
                    // network failure - keep local, if no local hide
                    if (suggestionsModel.count === 0) {
                        hidePopup()
                    }
                }
            }
        }
        xhr.open("GET", url)
        xhr.send()
    }

    function selectNext() {
        if (suggestionsModel.count === 0) return
        selectedIndex = (selectedIndex + 1) % suggestionsModel.count
        suggestionsList.positionViewAtIndex(selectedIndex, ListView.Contain)
    }

    function selectPrev() {
        if (suggestionsModel.count === 0) return
        selectedIndex = (selectedIndex - 1 + suggestionsModel.count) % suggestionsModel.count
        suggestionsList.positionViewAtIndex(selectedIndex, ListView.Contain)
    }

    function acceptSelection() {
        if (!hasSelection) return
        var item = suggestionsModel.get(selectedIndex)
        if (!item) return
        suggestionAccepted(item.url)
        hidePopup()
    }

    Timer {
        id: debounceTimer
        interval: 220
        repeat: false
        onTriggered: {
            if (queryText.trim().length === 0) return
            fetchGoogleSuggestions(queryText)
        }
    }

    ListModel {
        id: suggestionsModel
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceSm
        spacing: 0

        ListView {
            id: suggestionsList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: suggestionsModel
            spacing: 2
            delegate: Rectangle {
                id: row
                required property string title
                required property string url
                required property string glyph
                required property string type
                required property string displayUrl
                required property int index

                width: suggestionsList.width
                height: root.rowHeight
                radius: Theme.radiusSmall
                color: {
                    if (root.selectedIndex === index) return Theme.glassFillHover
                    return rowArea.containsMouse ? Theme.glassFill : "transparent"
                }
                border.width: root.selectedIndex === index ? 1 : 0
                border.color: Theme.accentDim

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceMd
                    anchors.topMargin: Theme.spaceXs
                    anchors.bottomMargin: Theme.spaceXs
                    spacing: Theme.spaceSm

                    Text {
                        text: row.glyph
                        font.family: Theme.fontFamilyIcons
                        font.pixelSize: Theme.iconSize - 2
                        color: {
                            if (row.type === "bookmark") return Theme.accent
                            if (row.type === "tab") return Theme.textMuted
                            return Theme.textMuted
                        }
                        verticalAlignment: Text.AlignVCenter
                        Layout.preferredWidth: 20
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1

                        Text {
                            Layout.fillWidth: true
                            text: row.title
                            color: Theme.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            elide: Text.ElideRight
                            maximumLineCount: 1
                        }
                        Text {
                            Layout.fillWidth: true
                            text: row.displayUrl
                            color: Theme.textMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeTiny
                            elide: Text.ElideRight
                            maximumLineCount: 1
                        }
                    }
                }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.selectedIndex = row.index
                        root.acceptSelection()
                    }
                }
            }
        }

        Text {
            visible: suggestionsModel.count === 0 && root.queryText.length > 0
            text: "No suggestions"
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            Layout.alignment: Qt.AlignCenter
            Layout.topMargin: Theme.spaceSm
            Layout.bottomMargin: Theme.spaceSm
        }
    }
}
