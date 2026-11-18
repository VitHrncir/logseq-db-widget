import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    id: page

    property alias cfg_graphName: graphField.text
    property alias cfg_cliPath: cliField.text
    property alias cfg_appImagePath: appImageField.text
    property alias cfg_pythonCommand: pythonField.text
    property alias cfg_refreshMinutes: refreshSpin.value
    property alias cfg_showCompletedTasks: showClosed.checked
    property alias cfg_backgroundSync: backgroundSyncBox.checked

    property var detectedGraphs: []
    property string detectStatus: ""

    function detect() {
        detectStatus = i18n("Looking for graphs…");
        probe.call("graphs", {}, function (ok, data, error) {
            if (!ok) {
                page.detectStatus = error;
                page.detectedGraphs = [];
                return;
            }
            page.detectedGraphs = data.graphs;
            page.detectStatus = data.graphs.length > 0
                ? i18np("Found %1 graph.", "Found %1 graphs.", data.graphs.length)
                : i18n("The CLI found no DB graphs under ~/logseq/graphs.");
        });
    }

    // Uses the CLI and Python settings as currently typed, before applying.
    Backend {
        id: probe
        cliPath: cliField.text
        appImagePath: appImageField.text
        pythonCommand: pythonField.text || "python3"
    }

    Kirigami.FormLayout {
        RowLayout {
            Kirigami.FormData.label: i18n("Graph:")

            QQC2.TextField {
                id: graphField
                Layout.fillWidth: true
                placeholderText: i18n("CLI's current graph")
            }
            QQC2.Button {
                text: i18n("Detect")
                icon.name: "search"
                enabled: !probe.busy
                onClicked: page.detect()
            }
        }

        QQC2.ComboBox {
            visible: page.detectedGraphs.length > 0
            model: page.detectedGraphs
            displayText: i18n("Choose a detected graph…")
            onActivated: graphField.text = currentText
        }

        QQC2.Label {
            visible: page.detectStatus.length > 0
            Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            wrapMode: Text.Wrap
            text: page.detectStatus
            opacity: 0.8
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
        }

        QQC2.TextField {
            id: appImageField
            Kirigami.FormData.label: i18n("Logseq AppImage:")
            Layout.fillWidth: true
            placeholderText: i18n("Automatic")
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            wrapMode: Text.Wrap
            opacity: 0.8
            text: i18n("Found automatically from the launcher Logseq installs in ~/.local/bin, or in ~/AppImages, ~/Applications and ~/Downloads. The widget unpacks one copy per Logseq version into ~/.cache/logseq-db-widget.")
        }

        QQC2.TextField {
            id: cliField
            Kirigami.FormData.label: i18n("Other logseq CLI:")
            Layout.fillWidth: true
            placeholderText: i18n("Only for non-AppImage installs")
        }

        QQC2.TextField {
            id: pythonField
            Kirigami.FormData.label: i18n("Python command:")
            Layout.fillWidth: true
            placeholderText: "python3"
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
        }

        QQC2.SpinBox {
            id: refreshSpin
            Kirigami.FormData.label: i18n("Refresh every:")
            from: 1
            to: 120
            textFromValue: (value, locale) => i18np("%1 minute", "%1 minutes", value)
            valueFromText: (text, locale) => parseInt(text) || 5
        }

        QQC2.CheckBox {
            id: backgroundSyncBox
            Kirigami.FormData.label: i18n("Logseq Sync:")
            text: i18n("Keep syncing while Logseq Desktop is closed")
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            wrapMode: Text.Wrap
            opacity: 0.8
            text: backgroundSyncBox.checked
                  ? i18n("Changes from your other devices appear here even when Logseq is closed. This needs the CLI to be signed in (see the README). Trade-off: Logseq's database process then stays running, and it accepts unauthenticated connections from this computer.")
                  : i18n("When Logseq Desktop is closed, the widget stops its own database process shortly after you stop using it. Changes from other devices arrive the next time you open Logseq.")
        }

        QQC2.CheckBox {
            id: showClosed
            Kirigami.FormData.label: i18n("TODO list:")
            text: i18n("Show completed and canceled tasks by default")
        }
    }
}
