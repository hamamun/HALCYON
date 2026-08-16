import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// M3U's left panel — §P2.4, owner decisions of 2026-08-02.
//
// The toolbar holds EXACTLY TWO buttons: Playlists… (the one home for every
// way a source enters M3U, §4.1) and Clear Playlist. The body is the channel
// list from the loaded source: name, group tag, tvg-logo thumbnail, a filter
// box, a grouping selector (By category / By country / By language / No group
// — remembered), and a favourites-only toggle. Single click plays. The
// playing channel is always and kept visible. There is no right dock in this mode and nothing here is
// shared with Local (§A.1).
Item {
    id: root

    // Exposed by main.py as <id-capitalised>Playlist — "m3u" -> "M3uPlaylist".
    property var ctx: typeof M3uPlaylist !== "undefined" ? M3uPlaylist : null

    function showSaveFavouritePrompt() {
        sourcesDialog.openForFavourites("Save this playlist first to use favourites.");
    }

    // ------------------------------------------------------------ toolbar --
    PanelToolbar {
        id: toolbar
        width: parent.width
        anchors.top: parent.top

        IconButton {
            glyph: Glyphs.playlist
            tooltip: "Playlists…"
            onClicked: sourcesDialog.openNormal()    // the ONE home (§4.1)
        }
        IconButton {
            glyph: Glyphs.clearAll
            tooltip: "Clear playlist"
            enabled: root.ctx && root.ctx.channels.totalCount > 0
            onClicked: clearConfirm.open()
        }
    }

    // ------------------------------------------------- current source line --
    // Plain text, not a trigger: which playlist you are watching (§P2.4).
    Item {
        id: sourceStrip
        anchors.top: toolbar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: 30

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.right: countLabel.left
            anchors.leftMargin: Theme.spaceMd
            anchors.rightMargin: Theme.spaceSm
            text: root.ctx && root.ctx.currentSourceName.length > 0
                  ? root.ctx.currentSourceName : "No playlist loaded"
            elide: Text.ElideMiddle
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            font.weight: Theme.weightMedium
            color: root.ctx && root.ctx.currentSourceName.length > 0
                   ? Theme.text : Theme.textFaint
        }
        Text {
            id: countLabel
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: Theme.spaceMd
            text: root.ctx ? root.ctx.channels.count + " ch" : ""
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }
    }

    // ------------------------------------------------------- grouping row --
    // By category (default) / By country / By language / No group — remembered (§P2.4).
    Row {
        id: groupRow
        anchors.top: sourceStrip.bottom
        anchors.left: parent.left
        anchors.leftMargin: Theme.spaceSm
        height: 40
        spacing: Theme.spaceXs

        Repeater {
            model: [
                { "key": "category", "glyph": Glyphs.category,
                  "tooltip": "Group by category" },
                { "key": "country",  "glyph": Glyphs.country,
                  "tooltip": "Group by country" },
                { "key": "language", "glyph": Glyphs.language,
                  "tooltip": "Group by language" },
                { "key": "none",     "glyph": Glyphs.noGroup,
                  "tooltip": "No grouping" }
            ]
            delegate: IconButton {
                anchors.verticalCenter: parent.verticalCenter
                glyph: modelData.glyph
                tooltip: modelData.tooltip
                active: root.ctx && root.ctx.channels.grouping === modelData.key
                onClicked: if (root.ctx) root.ctx.persistGrouping(modelData.key)
            }
        }

        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            glyph: Glyphs.bookmark
            tooltip: root.ctx && root.ctx.channels.favouritesOnly
                     ? "Show all channels" : "Show favourites only"
            active: root.ctx && root.ctx.channels.favouritesOnly
            enabled: root.ctx && root.ctx.channels.totalCount > 0
            onClicked: {
                if (!root.ctx)
                    return;
                var outcome = root.ctx.toggleFavouritesOnly();
                if (outcome === "save-required")
                    root.showSaveFavouritePrompt();
            }
        }
    }

    // ------------------------------------------------------------ filter --
    GlassField {
        id: filterField
        anchors.top: groupRow.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Theme.spaceSm
        anchors.bottomMargin: 0
        placeholderText: "Filter channels…"
        clearable: true
        clearTooltip: "Clear filter"
        // Debounced, not per-keystroke. Every filter change rebuilds the view
        // and resets the model, which destroys and recreates every delegate —
        // so typing a six-letter channel name used to tear down and restart
        // the whole visible list six times, cancelling and re-issuing its
        // logo requests each time. One rebuild per pause in typing does the
        // same job invisibly. Clearing the shared field assigns an empty
        // string, which runs this same path and restores the full list.
        onTextChanged: filterDebounce.restart()
    }

    Timer {
        id: filterDebounce
        interval: 250
        repeat: false
        onTriggered: if (root.ctx) root.ctx.channels.setFilter(filterField.text)
    }

    // -------------------------------------------------------- status strip --
    // Load status is surfaced through the shared toast; there is no inline
    // retry action in the M3U panel.
    Rectangle {
        id: statusStrip
        anchors.top: filterField.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: Theme.spaceSm
        height: visible ? 32 : 0
        visible: root.ctx && root.ctx.statusMessage.length > 0
        color: root.ctx && root.ctx.statusIsError ? Qt.rgba(0.97, 0.44, 0.44, 0.10)
                                                  : Theme.glassFill
        radius: Theme.radiusSmall

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: Theme.spaceMd
            anchors.rightMargin: Theme.spaceMd
            text: root.ctx ? root.ctx.statusMessage : ""
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            color: root.ctx && root.ctx.statusIsError ? Theme.danger : Theme.textMuted
        }
    }

    // -------------------------------------------------------- stream error toast --
    // Stream play failures show as a toast, not in the panel (§M2.4).
    Connections {
        target: root.ctx
        function onStreamError(message) {
            // osdLayer is provided by the shell; show a toast for stream errors.
            if (typeof osdLayer !== "undefined" && osdLayer)
                osdLayer.show(message, Glyphs.alert);
        }
    }

    // ---------------------------------------------------- logo throttling --
    // A public IPTV playlist is thousands of *other people's* logo URLs, and a
    // collapsed accordion still builds a delegate for every row it contains
    // (zero-height rows all "fit" on screen, so the view instantiates the lot).
    // Left alone, opening M3U fires one image request per channel at once —
    // hundreds of streams on a single HTTP/2 connection — and servers answer
    // exactly as you would expect: "excessive load detected", GOAWAY, protocol
    // errors, and a wave of timeouts for the requests that never got a turn.
    //
    // Two rules fix that, and both live here rather than in the model:
    //
    //   1. a row that is not in the expanded group asks for nothing at all
    //      (`wanted` below is empty for collapsed rows — invisible and
    //      zero-height does NOT stop an Image from loading; only an empty
    //      source does);
    //   2. no more than `maxActive` requests are in flight at any moment, the
    //      rest queue.
    //
    // Once a picture has arrived its slot is released but its source is kept,
    // so nothing is ever re-fetched to make room for the next row.
    QtObject {
        id: logoQueue

        // Six is the conventional per-host browser limit and comfortably more
        // than a screenful of rows, so scrolling never feels gated.
        readonly property int maxActive: 6
        property int activeCount: 0
        // Plain JS array: it is a work queue, nothing binds to it.
        property var pending: []

        function restart(slot) {
            // Idempotent on purpose: this runs both from Component.onCompleted
            // and from onWantedChanged, and those can fire in either order
            // while a row is being built. Without the early-outs the second
            // call would abort the request the first one just started — the
            // very churn this queue exists to remove.
            if (slot.wanted.length === 0) {
                withdraw(slot);
                return;
            }
            if (slot.granted === slot.wanted)
                return;                       // already loading it, or showing it
            if (pending.indexOf(slot) !== -1)
                return;                       // already queued; grant() reads
                                              // `wanted` fresh at its turn
            withdraw(slot);
            if (activeCount < maxActive)
                grant(slot);
            else
                pending.push(slot);
        }

        function grant(slot) {
            if (slot.holdsSlot)
                return;                       // never count one row twice
            activeCount += 1;
            slot.holdsSlot = true;
            slot.granted = slot.wanted;
        }

        // The request finished (either way). Free the slot, keep the picture.
        function done(slot) {
            if (!slot.holdsSlot)
                return;
            slot.holdsSlot = false;
            activeCount = Math.max(0, activeCount - 1);
            pump();
        }

        // The row no longer wants what it asked for — recycled by the view,
        // scrolled out, or its group collapsed.
        function withdraw(slot) {
            var i = pending.indexOf(slot);
            if (i !== -1)
                pending.splice(i, 1);
            slot.granted = "";
            done(slot);
        }

        function pump() {
            while (activeCount < maxActive && pending.length > 0) {
                var next = pending.shift();
                // Rows destroyed while queued are gone from `pending` already;
                // this guards the one that changed its mind in between.
                if (next && next.wanted.length > 0)
                    grant(next);
            }
        }
    }

    // ---------------------------------------------------------------- list --
    ListView {
        id: list
        anchors.top: statusStrip.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Theme.spaceSm
        anchors.topMargin: Theme.spaceSm
        clip: true
        model: root.ctx ? root.ctx.channels : null
        spacing: 0
        visible: root.ctx && root.ctx.channels.count > 0
        boundsBehavior: Flickable.StopAtBounds

        // Grouped view: sections come from the model's groupKey role; the
        // selector above turns them off entirely with "No group".
        section.property: root.ctx && root.ctx.channels.grouping !== "none" ? "groupKey" : ""
        section.criteria: ViewSection.FullString
        section.labelPositioning: ViewSection.CurrentLabelAtStart | ViewSection.InlineLabels
        section.delegate: Rectangle {
            id: sectionHeader
            width: list.width
            height: 28
            color: headerArea.containsMouse ? Theme.glassFillHover : Theme.glassFill
            radius: Theme.radiusSmall

            readonly property bool isExpanded: root.ctx && root.ctx.channels.expandedGroup === section
            readonly property string displayName: section.length > 0 ? section
                  : (root.ctx && (root.ctx.channels.grouping === "country"
                                  || root.ctx.channels.grouping === "language")
                     ? "Unknown" : "Ungrouped")
            readonly property int count: root.ctx ? root.ctx.channels.groupCount(section) : 0

            Row {
                anchors.left: parent.left
                anchors.leftMargin: Theme.spaceSm
                anchors.right: parent.right
                anchors.rightMargin: Theme.spaceSm
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spaceSm

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: sectionHeader.isExpanded ? Glyphs.chevronDown : "\u203A"
                    font.family: sectionHeader.isExpanded ? Theme.fontFamilyIcons : Theme.fontFamily
                    font.pixelSize: sectionHeader.isExpanded ? 12 : 16
                    font.weight: Font.Bold
                    color: sectionHeader.isExpanded ? Theme.accent : Theme.textMuted
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: sectionHeader.count > 0
                          ? sectionHeader.displayName + " (" + sectionHeader.count + ")"
                          : sectionHeader.displayName
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeTiny
                    font.weight: Theme.weightBold
                    color: sectionHeader.isExpanded ? Theme.text : Theme.textMuted
                }
            }

            // 1px bottom separator so headers stay visually distinct when
            // collapsed (no ListView.spacing to do it for us).
            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.leftMargin: Theme.spaceSm
                anchors.right: parent.right
                anchors.rightMargin: Theme.spaceSm
                height: 1
                color: Theme.glassBorder
            }

            MouseArea {
                id: headerArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (root.ctx) root.ctx.channels.toggleGroup(section)
            }
        }

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            width: 6
        }

        delegate: ListRow {
            id: row
            required property int index
            required property string name
            required property string group
            required property string logo
            required property bool isCurrent
            required property bool isGroupExpanded
            required property bool isFavourite

            width: ListView.view.width
            height: isGroupExpanded ? Theme.listRowHeight : 0
            visible: isGroupExpanded
            current: isCurrent

            onClicked: if (root.ctx) root.ctx.play_index(index)

            Row {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: Theme.spaceSm

                // tvg-logo thumbnail: throttled by logoQueue, requested only
                // for rows in the open group, with a typed fallback — never a
                // broken-image icon (§M2.3: graceful fallback). URLs that
                // cannot work (SVG, image share pages) and URLs that have
                // failed before never reach here: the model returns an empty
                // logo for those.
                Item {
                    id: logoCell
                    width: 34
                    height: 22
                    anchors.verticalCenter: parent.verticalCenter

                    // What this row would show if it were allowed to load now.
                    readonly property string wanted:
                        (row.isGroupExpanded && row.logo.length > 0) ? row.logo : ""
                    // What the queue has actually let it fetch. Never cleared
                    // on success: the picture stays, only the slot is handed on.
                    property string granted: ""
                    property bool holdsSlot: false

                    onWantedChanged: logoQueue.restart(logoCell)
                    Component.onCompleted: logoQueue.restart(logoCell)
                    Component.onDestruction: logoQueue.withdraw(logoCell)

                    Image {
                        id: logoImage
                        anchors.fill: parent
                        source: logoCell.granted
                        asynchronous: true
                        cache: true
                        fillMode: Image.PreserveAspectFit
                        visible: status === Image.Ready
                        onStatusChanged: {
                            if (status === Image.Ready) {
                                logoQueue.done(logoCell);
                            } else if (status === Image.Error) {
                                // Tell the mode, so this URL is not requested
                                // again in this session or the next one.
                                if (root.ctx && logoCell.granted.length > 0)
                                    root.ctx.noteLogoFailed(logoCell.granted);
                                logoQueue.done(logoCell);
                            }
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: logoImage.status !== Image.Ready
                        text: Glyphs.globe
                        font.family: Theme.fontFamilyIcons
                        font.pixelSize: 12
                        color: row.current ? Theme.accent : Theme.textFaint
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 34 - 30
                           - (groupTag.visible ? groupTag.width : 0)
                           - Theme.spaceSm * (groupTag.visible ? 4 : 3)
                    text: row.name
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: row.current ? Theme.accent : Theme.text
                }
                Text {
                    id: groupTag
                    anchors.verticalCenter: parent.verticalCenter
                    visible: root.ctx && root.ctx.channels.grouping === "none"
                    text: row.group
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeTiny
                    color: Theme.textFaint
                }
                IconButton {
                    id: favouriteButton
                    anchors.verticalCenter: parent.verticalCenter
                    width: 30
                    height: 30
                    iconSize: 14
                    showRing: hovered || active
                    glyph: Glyphs.bookmark
                    active: row.isFavourite
                    tooltip: row.isFavourite ? "Remove from favourites" : "Add to favourites"
                    onClicked: {
                        if (!root.ctx)
                            return;
                        var outcome = root.ctx.toggleFavourite(row.index);
                        if (outcome === "save-required")
                            root.showSaveFavouritePrompt();
                    }
                }
            }
        }
    }

    // The playing channel ALWAYS shows (§P2.3 v3.3): follow the highlight
    // when zapping with prev/next, even in a long list.
    Connections {
        target: root.ctx ? root.ctx.channels : null
        enabled: target !== null
        function onCurrentIndexChanged() {
            if (target.currentIndex >= 0)
                list.positionViewAtIndex(target.currentIndex, ListView.Contain);
        }
    }

    // -------------------------------------------------------- empty states --
    Column {
        anchors.centerIn: parent
        width: parent.width - Theme.spaceXl * 2
        spacing: Theme.spaceMd
        visible: !root.ctx || (!root.ctx.loading && root.ctx.channels.count === 0
                               && root.ctx.statusMessage.length === 0)

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Glyphs.globe
            font.family: Theme.fontFamilyIcons
            font.pixelSize: 34
            color: Theme.textFaint
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: root.ctx && root.ctx.channels.totalCount > 0
                  ? (root.ctx.channels.favouritesOnly
                     ? (root.ctx.channels.favouriteCount > 0
                        ? "No favourite channels match your filter."
                        : "No favourite channels yet.\nShow all channels and click a bookmark to add one.")
                     : "No channels match your filter.")
                  : "No playlist loaded.\nAdd a stream URL or a saved .m3u file, or drop one here."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textFaint
            lineHeight: 1.35
        }
        IconButton {
            anchors.horizontalCenter: parent.horizontalCenter
            glyph: Glyphs.playlist
            tooltip: "Playlists"
            onClicked: sourcesDialog.openNormal()    // same trigger as the toolbar
        }
    }

    Text {
        anchors.centerIn: parent
        visible: root.ctx && root.ctx.loading
        text: "Loading playlist…"
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSmall
        color: Theme.textMuted
    }

    // ------------------------------ drop: open a playlist file on the panel --
    // The SAME handler Add File reaches (§4.1 bind) — one pipeline, never
    // auto-saved to the seven. The window-wide drop below this panel feeds
    // Local's queue, exactly as in Phase 1; that is its one home too.
    DropArea {
        anchors.fill: parent
        onDropped: function(drop) {
            if (!drop.hasUrls || !root.ctx)
                return;
            // Only playlists belong to M3U — anything else falls to the
            // window-level drop, whose one home is Local's queue (§4.1).
            for (var i = 0; i < drop.urls.length; i++) {
                var u = drop.urls[i].toString().split("?")[0].toLowerCase();
                if (u.endsWith(".m3u") || u.endsWith(".m3u8")) {
                    root.ctx.openFiles(drop.urls);
                    drop.accept();
                    return;
                }
            }
        }
    }

    // --------------------------------------------------------------- dialogs --
    M3USourcesDialog {
        id: sourcesDialog
        ctx: root.ctx
    }

    ConfirmDialog {
        id: clearConfirm
        title: "Clear playlist"
        message: root.ctx && root.ctx.channels.totalCount > 1
                 ? "Remove all " + root.ctx.channels.totalCount + " channels from the list?"
                 : "Remove this channel from the list?"
        onConfirmed: Actions.clearPlaylist()       // the one action home
    }
}
