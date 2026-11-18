import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami
import "logic.js" as Logic

Item {
    id: full

    required property var backend
    required property var plasmoidItem

    // Graph name for logseq:// links: the configured one, or the CLI's current graph.
    readonly property string graph: Plasmoid.configuration.graphName || plasmoidItem.detectedGraph
    readonly property bool shown: plasmoidItem.expanded
                                  || Plasmoid.formFactor === PlasmaCore.Types.Planar
    property double lastRefresh: 0

    // "preparing" (finding/unpacking Logseq), "checking" (finding graphs),
    // "ready", or a problem reported by the helper:
    // "no-cli", "no-graphs", "graph-missing", "choose-graph", "error".
    property string setupState: "starting"
    property string setupMessage: ""
    property var availableGraphs: []
    readonly property bool ready: setupState === "ready"
    // Second safety net: "starting" never lasts longer than this.
    property int startGuardSeconds: 25
    property string diagnostics: ""
    readonly property bool working: setupState === "starting" || setupState === "preparing"
                                    || setupState === "checking"

    readonly property var configuredPages: {
        var c = Plasmoid.configuration;
        return [c.page1, c.page2, c.page3, c.page4, c.page5, c.page6]
            .map(function (p) { return (p || "").trim(); })
            .filter(function (p) { return p.length > 0; });
    }

    Layout.preferredWidth: Kirigami.Units.gridUnit * 26
    Layout.preferredHeight: Kirigami.Units.gridUnit * 32
    Layout.minimumWidth: Kirigami.Units.gridUnit * 18
    Layout.minimumHeight: Kirigami.Units.gridUnit * 16

    function views() {
        return [journalView, todoView, pagesView];
    }

    // Short text for the sync marker; the tooltip has the full explanation.
    function syncLabel(state, pending) {
        switch (state) {
        case "cloud": return i18n("Synced to the cloud");
        case "uploading": return i18np("Saved locally, uploading %1 change", "Saved locally, uploading %1 changes", pending);
        case "local": return i18n("Saved locally, not synced to the cloud");
        case "local-only": return i18n("Saved locally (this graph doesn't sync)");
        case "saving": return i18n("Saving…");
        case "failed": return i18n("Not saved");
        }
        return i18n("Sync status not checked yet");
    }

    function syncColor(state) {
        switch (state) {
        case "cloud": return Kirigami.Theme.positiveTextColor;
        case "local": return Kirigami.Theme.neutralTextColor;
        case "failed": return Kirigami.Theme.negativeTextColor;
        case "unknown": return Kirigami.Theme.disabledTextColor;
        }
        return Kirigami.Theme.textColor;
    }

    function refreshCurrent() {
        if (!ready)
            return;
        lastRefresh = Date.now();
        views()[tabs.currentIndex].refresh();
    }

    // Find the CLI and a graph before loading anything, so a missing piece
    // is explained instead of leaving the sections empty.
    // Internal state for bug reports; never throws.
    function safeDiagnostics() {
        try {
            if (!backend)
                return "backend missing (" + typeof backend + ")";
            return backend.diagnostics();
        } catch (err) {
            return "diagnostics failed: " + String(err);
        }
    }

    // Shows an internal error on screen instead of leaving the setup frozen.
    function showWidgetError(where, err) {
        console.warn("Logseq widget: error in", where, err);
        startGuard.stop();
        diagnostics = safeDiagnostics();
        setupMessage = i18n("Internal widget error in %1: %2", where, String(err));
        setupState = "widget-error";
    }

    function runSetup() {
        setupState = "starting";
        startGuard.restart();
        try {
            startSetup();
        } catch (err) {
            showWidgetError("setup", err);
        }
    }

    function startSetup() {
        banner.visible = false;
        diagnostics = "";
        plasmoidItem.detectedGraph = "";
        // A quick round trip that doesn't involve Logseq at all: if this
        // fails, the problem is Plasma or Python, not Logseq.
        backend.call("ping", {}, function (ok, data, error) {
            if (full.setupState !== "starting")
                return; // the start guard already gave up
            startGuard.stop();
            if (!ok) {
                full.diagnostics = full.safeDiagnostics();
                full.setupMessage = error || "";
                full.setupState = "no-helper";
                return;
            }
            full.prepareLogseq();
        });
    }

    function prepareLogseq() {
        setupState = "preparing";
        backend.call("prepare", {}, function (ok, data, error) {
            if (!ok) {
                full.setupMessage = error || "";
                full.setupState = "error";
                return;
            }
            if (data.problem) {
                full.setupMessage = data.message || "";
                full.setupState = data.problem;
                return;
            }
            full.findGraphs();
        });
    }

    function findGraphs() {
        setupState = "checking";
        backend.call("setup", {}, function (ok, data, error) {
            if (!ok) {
                full.setupMessage = error || "";
                full.setupState = "error";
                return;
            }
            full.availableGraphs = data.graphs || [];
            full.setupMessage = data.message || "";
            if (data.problem) {
                full.setupState = data.problem;
                return;
            }
            if (!Plasmoid.configuration.graphName)
                full.plasmoidItem.detectedGraph = data.current;
            todoView.statuses = [];
            full.markAllStale();
            full.setupState = "ready";
            full.refreshCurrent();
        });
    }

    function markAllStale() {
        var all = views();
        for (var i = 0; i < all.length; ++i)
            all[i].stale = true;
    }

    function handleLink(link) {
        var page = Logic.pageFromLink(link);
        if (page.length > 0) {
            tabs.currentIndex = 2;
            pagesView.open(page);
        } else if (Logic.isSafeExternalLink(link)) {
            Qt.openUrlExternally(link);
        } else {
            backend.notify(i18n("Blocked a link to %1. Only web and email links open from the widget.", link));
        }
    }

    onShownChanged: {
        if (!shown)
            return;
        // Reopening retries setup (say, after the graph was downloaded), or
        // refreshes if the data is older than a minute.
        if (!ready && !working)
            runSetup();
        else if (views()[tabs.currentIndex].stale || Date.now() - lastRefresh > 60000)
            refreshCurrent();
    }

    Component.onCompleted: {
        try {
            tabs.currentIndex = Math.max(0, Math.min(2, Plasmoid.configuration.lastTab));
        } catch (err) {
            console.warn("Logseq widget: could not restore tab", err);
        }
        runSetup();
    }

    Connections {
        target: full.backend || null
        function onChanged() {
            full.markAllStale();
            full.refreshCurrent();
        }
        function onNotice(text) {
            // Errors stay until closed: a failed change must not go unnoticed.
            banner.text = Logic.plain(text);
            banner.visible = true;
        }
    }

    Connections {
        target: Plasmoid.configuration
        function onGraphNameChanged() {
            full.runSetup();
        }
        function onCliPathChanged() {
            full.runSetup();
        }
        function onAppImagePathChanged() {
            full.runSetup();
        }
    }

    Timer {
        interval: Math.max(1, Plasmoid.configuration.refreshMinutes) * 60000
        repeat: true
        running: true
        onTriggered: {
            full.markAllStale();
            if (full.shown && full.ready) {
                // Timer refreshes are background work: they don't keep the
                // CLI's database process alive.
                full.backend.backgroundMode = true;
                try {
                    full.refreshCurrent();
                } finally {
                    full.backend.backgroundMode = false;
                }
            }
            else if (full.shown && !full.working)
                full.runSetup();
        }
    }

    Timer {
        id: startGuard
        interval: full.startGuardSeconds * 1000
        onTriggered: {
            if (full.setupState !== "starting")
                return;
            full.diagnostics = full.safeDiagnostics();
            console.warn("Logseq widget: no answer from helper:", full.diagnostics);
            full.setupMessage = i18n("The widget's helper did not answer.");
            full.setupState = "no-helper";
        }
    }


    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true

            PlasmaComponents3.TabBar {
                id: tabs
                objectName: "tabs"
                Layout.fillWidth: true
                enabled: full.ready

                PlasmaComponents3.TabButton {
                    text: i18n("Journal")
                    icon.name: "view-calendar-day"
                }
                PlasmaComponents3.TabButton {
                    text: i18n("TODO")
                    icon.name: "checkbox"
                }
                PlasmaComponents3.TabButton {
                    text: i18n("Pages")
                    icon.name: "document-multiple"
                }

                onCurrentIndexChanged: {
                    if (Plasmoid.configuration.lastTab !== currentIndex)
                        Plasmoid.configuration.lastTab = currentIndex;
                    var view = full.views()[currentIndex];
                    if (full.ready && view && view.stale)
                        view.refresh();
                }
            }

            PlasmaComponents3.BusyIndicator {
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: implicitWidth
                running: !!full.backend && full.backend.busy
                opacity: running ? 1 : 0
            }

            PlasmaComponents3.ToolButton {
                icon.name: "view-refresh"
                display: QQC2.AbstractButton.IconOnly
                text: i18n("Refresh")
                onClicked: {
                    if (!full.ready) {
                        full.runSetup();
                        return;
                    }
                    full.markAllStale();
                    full.refreshCurrent();
                }
                QQC2.ToolTip.text: text
                QQC2.ToolTip.visible: hovered
            }
        }

        Kirigami.InlineMessage {
            id: banner
            objectName: "banner"
            Layout.fillWidth: true
            type: Kirigami.MessageType.Error
            showCloseButton: true
            visible: false
        }

        SetupPanel {
            visible: !full.ready
            Layout.fillWidth: true
            Layout.fillHeight: true
            problem: full.setupState
            message: full.setupMessage
            graphs: full.availableGraphs
            busy: !!full.backend && full.backend.busy
            elapsed: full.backend ? full.backend.currentElapsed : 0
            diagnostics: full.diagnostics
            logPath: full.backend ? full.backend.logPath : ""
            onRetry: full.runSetup()
            onGraphChosen: name => {
                if (Plasmoid.configuration.graphName === name)
                    full.runSetup();
                else
                    Plasmoid.configuration.graphName = name;
            }
        }

        StackLayout {
            objectName: "sections"
            visible: full.ready
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabs.currentIndex

            JournalView {
                id: journalView
                backend: full.backend
                graph: full.graph
                onLinkActivated: link => full.handleLink(link)
            }

            TodoView {
                id: todoView
                backend: full.backend
                targetPage: (Plasmoid.configuration.taskTargetPage || "").trim()
                showClosedByDefault: Plasmoid.configuration.showCompletedTasks
                tagFilterId: Plasmoid.configuration.taskTagFilter
                onTagFilterIdChanged: {
                    if (Plasmoid.configuration.taskTagFilter !== tagFilterId)
                        Plasmoid.configuration.taskTagFilter = tagFilterId;
                }
                onLinkActivated: link => full.handleLink(link)
            }

            PagesView {
                id: pagesView
                backend: full.backend
                graph: full.graph
                configuredPages: full.configuredPages
                onLinkActivated: link => full.handleLink(link)
            }
        }

        // Where your changes are: in the cloud, only in the local graph, or not saved.
        RowLayout {
            id: syncMarker
            objectName: "syncMarker"
            visible: full.ready && !!full.backend
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            readonly property string syncState: full.backend ? full.backend.syncState : "unknown"

            Kirigami.Icon {
                source: Logic.syncIcon(syncMarker.syncState)
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
            }

            PlasmaComponents3.Label {
                id: syncLabelText
                objectName: "syncLabel"
                Layout.fillWidth: true
                textFormat: Text.PlainText
                elide: Text.ElideRight
                font: Kirigami.Theme.smallFont
                color: full.syncColor(syncMarker.syncState)
                text: full.syncLabel(syncMarker.syncState, full.backend ? full.backend.syncPending : 0)
            }

            HoverHandler {
                id: syncHover
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                // Check again now.
                onTapped: full.backend.checkSyncNow()
            }
            QQC2.ToolTip.visible: syncHover.hovered
            QQC2.ToolTip.text: Logic.plain((full.backend ? full.backend.syncDetail : "") + "\n"
                                           + i18n("Click to check again."))
        }
    }
}
