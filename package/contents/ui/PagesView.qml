import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import "logic.js" as Logic

// Up to six pages pinned in the settings, plus any page opened by name or
// by clicking a [[link]] elsewhere in the widget.
ColumnLayout {
    id: pagesView
    objectName: "pagesView"

    required property var backend
    property string graph: ""
    property var configuredPages: []
    property string current: ""
    property bool stale: true

    spacing: Kirigami.Units.smallSpacing

    signal linkActivated(string link)

    function open(name) {
        name = (name || "").trim();
        if (name.length === 0)
            return;
        if (name !== current) {
            current = name;
            pane.loaded = false;
            pane.blocks = [];
            pane.missing = false;
            pane.errorText = "";
            pane.title = name;
        }
        refresh();
    }

    function refresh() {
        stale = false;
        if (current.length === 0) {
            if (configuredPages.length === 0)
                return;
            open(configuredPages[0]);
            return;
        }
        var name = current;
        backend.call("page", { name: name }, function (ok, data, error) {
            if (name !== pagesView.current)
                return;
            if (!ok) {
                pane.errorText = error || "";
                return;
            }
            pane.errorText = "";
            pane.title = data.title || name;
            pane.blocks = data.blocks;
            pane.missing = !!data.missing;
            pane.loaded = true;
        });
    }

    onConfiguredPagesChanged: {
        if (current.length === 0 && configuredPages.length > 0)
            stale = true;
    }

    Flow {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Repeater {
            model: pagesView.configuredPages

            PlasmaComponents3.ToolButton {
                required property string modelData
                text: Logic.plain(modelData)
                checked: pagesView.current === modelData
                onClicked: pagesView.open(modelData)
            }
        }

        PlasmaComponents3.TextField {
            id: openField
            width: Kirigami.Units.gridUnit * 9
            placeholderText: i18n("Open page…")
            onAccepted: {
                pagesView.open(text);
                text = "";
            }
        }
    }

    BlockPane {
        id: pane
        property bool missing: false

        visible: pagesView.current.length > 0
        Layout.fillWidth: true
        Layout.fillHeight: true
        backend: pagesView.backend
        targetPage: pagesView.current
        openUrl: pane.missing ? "" : Logic.logseqUrl(pagesView.graph, pane.title)
        placeholderIcon: pane.missing ? "document-new" : "document-edit"
        placeholderText: pane.missing ? i18n("This page doesn't exist yet") : i18n("This page is empty")
        placeholderExplanation: pane.missing ? i18n("Adding a block will create it.") : ""
        composerPlaceholder: i18n("Add to %1…", pagesView.current)
        onLinkActivated: link => pagesView.linkActivated(link)
    }

    Item {
        visible: pagesView.current.length === 0
        Layout.fillWidth: true
        Layout.fillHeight: true

        PlasmaExtras.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 2
            iconName: "document-multiple"
            text: i18n("No pages pinned yet")
            explanation: i18n("Pin up to six pages in the widget settings, type a page name above, or click a link in your journal.")
        }
    }
}
