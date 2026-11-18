import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import "logic.js" as Logic

// A page heading, its outline, and a composer that appends to it.
ColumnLayout {
    id: pane

    required property var backend
    property string title: ""
    property var blocks: []
    property bool loaded: false
    // Set when loading failed; stays visible until the next successful load.
    property string errorText: ""
    // "" means today's journal (the helper resolves it).
    property string targetPage: ""
    property string openUrl: ""

    property string placeholderIcon: "document-new"
    property string placeholderText: ""
    property string placeholderExplanation: ""
    property string composerPlaceholder: i18n("Write something…")

    signal linkActivated(string link)

    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true
        visible: pane.title.length > 0

        PlasmaExtras.Heading {
            Layout.fillWidth: true
            level: 3
            textFormat: Text.PlainText
            text: pane.title
            elide: Text.ElideRight
        }

        PlasmaComponents3.ToolButton {
            visible: pane.openUrl.length > 0
            icon.name: "document-open"
            display: QQC2.AbstractButton.IconOnly
            text: i18n("Open in Logseq")
            onClicked: Qt.openUrlExternally(pane.openUrl)
            QQC2.ToolTip.text: text
            QQC2.ToolTip.visible: hovered
        }
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        PlasmaComponents3.ScrollView {
            anchors.fill: parent

            ListView {
                id: list
                // Read by BlockDelegate through ListView.view.
                property var backend: pane.backend
                signal linkActivated(string link)
                onLinkActivated: link => pane.linkActivated(link)

                clip: true
                spacing: Kirigami.Units.smallSpacing
                boundsBehavior: Flickable.StopAtBounds
                model: pane.blocks
                delegate: BlockDelegate {}
            }
        }

        PlasmaExtras.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 2
            visible: pane.blocks.length === 0
                     && (pane.errorText.length > 0 || (pane.loaded && pane.placeholderText.length > 0))
            iconName: pane.errorText.length > 0 ? "dialog-error" : pane.placeholderIcon
            text: pane.errorText.length > 0 ? i18n("Couldn't load this") : Logic.plain(pane.placeholderText)
            explanation: Logic.plain(pane.errorText.length > 0 ? pane.errorText : pane.placeholderExplanation)
        }

        PlasmaComponents3.BusyIndicator {
            anchors.centerIn: parent
            visible: !pane.loaded && pane.errorText.length === 0 && pane.backend.busy
            running: visible
        }
    }

    Composer {
        id: composer
        Layout.fillWidth: true
        placeholderText: Logic.plain(pane.composerPlaceholder)
        onSubmitted: (text, asTask) => {
            pane.backend.call(asTask ? "taskAdd" : "append", { text: text, page: pane.targetPage }, function (ok) {
                if (ok)
                    composer.clear();
            });
        }
    }
}
