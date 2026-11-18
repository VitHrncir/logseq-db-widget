import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import "logic.js" as Logic

// Shown instead of the sections until the widget has a CLI and a graph.
ColumnLayout {
    id: panel
    objectName: "setupPanel"

    property string problem: "starting"
    property string message: ""
    property var graphs: []
    property bool busy: false
    property int elapsed: 0
    property string diagnostics: ""
    property string logPath: ""
    readonly property bool working: problem === "starting" || problem === "preparing" || problem === "checking"
    readonly property bool helperTimedOut: problem === "no-helper" && message.indexOf("did not answer") !== -1

    signal retry()
    signal graphChosen(string name)

    readonly property bool canChoose: (problem === "choose-graph" || problem === "graph-missing")
                                      && graphs.length > 0

    readonly property string heading: {
        switch (problem) {
        case "starting": return i18n("Starting…");
        case "no-helper": return i18n("Plasma couldn't run the widget's helper");
        case "widget-error": return i18n("The widget hit an internal error");
        case "preparing": return i18n("Preparing Logseq…");
        case "checking": return i18n("Looking for your graphs…");
        case "no-cli": return i18n("Logseq's command line tool wasn't found");
        case "no-graphs": return i18n("No Logseq graphs on this computer yet");
        case "graph-missing": return i18n("The graph \"%1\" isn't on this computer", message);
        case "choose-graph": return i18n("Choose a graph");
        }
        return i18n("Couldn't reach Logseq");
    }

    readonly property string explanation: {
        switch (problem) {
        case "starting":
            return "";
        case "no-helper":
            return panel.helperTimedOut
                ? i18n("Plasma never ran the helper script. Widgets run commands through Plasma's \"executable\" data engine, which comes with the plasma5support package; check that it is installed.")
                : panel.message;
        case "widget-error":
            return panel.message;
        case "preparing":
            return i18n("The first time, the widget unpacks a copy of your Logseq AppImage so it can work while Logseq is closed. That can take a minute.");
        case "checking":
            return i18n("The first time, Logseq loads the graph into its database process. Large graphs can take a while.");
        case "no-cli":
            return panel.message.length > 0 ? panel.message
                : i18n("Start Logseq Desktop (DB version) once, or set the path to your Logseq AppImage in the widget settings.");
        case "no-graphs":
            return i18n("This widget reads the copy of your graph that Logseq Desktop keeps on this computer, so it never asks for your Logseq Sync login. Open Logseq Desktop, sign in to Logseq Sync and open your synced graph once so it downloads. Then press Try again.");
        case "graph-missing":
            return i18n("Open it once in Logseq Desktop so it downloads to this computer, or pick one of the graphs that are here.");
        case "choose-graph":
            return i18n("There are several graphs on this computer. Pick the one this widget should show.");
        }
        return panel.message;
    }

    spacing: Kirigami.Units.largeSpacing

    Item { Layout.fillHeight: true }

    PlasmaComponents3.BusyIndicator {
        Layout.alignment: Qt.AlignHCenter
        visible: panel.working
        running: visible
    }

    PlasmaExtras.PlaceholderMessage {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit
        Layout.rightMargin: Kirigami.Units.gridUnit
        iconName: panel.working ? "" : (panel.problem === "error" ? "dialog-error" : "view-calendar-day")
        text: Logic.plain(panel.heading)
        explanation: Logic.plain(panel.explanation)
    }

    PlasmaComponents3.Label {
        objectName: "progressLabel"
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit
        Layout.rightMargin: Kirigami.Units.gridUnit
        visible: panel.working && panel.elapsed >= 5
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        opacity: 0.8
        text: panel.elapsed >= 30
              ? i18n("Still working (%1 s). Each step is logged in %2.", panel.elapsed, panel.logPath)
              : i18n("%1 s", panel.elapsed)
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit
        Layout.rightMargin: Kirigami.Units.gridUnit
        visible: !panel.working && panel.problem === "error"
                 && panel.message.indexOf("helper.log") === -1
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        opacity: 0.8
        text: i18n("Each step is logged in %1.", panel.logPath)
    }

    // Selectable, so it can be copied into a bug report.
    TextEdit {
        objectName: "diagnosticsText"
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit
        Layout.rightMargin: Kirigami.Units.gridUnit
        visible: panel.diagnostics.length > 0 && !panel.working
        readOnly: true
        selectByMouse: true
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.Wrap
        horizontalAlignment: TextEdit.AlignHCenter
        color: Kirigami.Theme.textColor
        font: Kirigami.Theme.smallFont
        opacity: 0.8
        text: i18n("Details: %1", panel.diagnostics)
    }

    RowLayout {
        Layout.alignment: Qt.AlignHCenter
        visible: panel.canChoose

        PlasmaComponents3.ComboBox {
            id: graphBox
            objectName: "graphBox"
            textRole: "text"
            valueRole: "value"
            model: panel.graphs.map(function (g) { return { text: Logic.plain(g), value: g }; })
        }

        PlasmaComponents3.Button {
            text: i18n("Use this graph")
            icon.name: "dialog-ok-apply"
            onClicked: panel.graphChosen(graphBox.currentValue)
        }
    }

    PlasmaComponents3.Button {
        Layout.alignment: Qt.AlignHCenter
        visible: !panel.working && !panel.canChoose
        enabled: !panel.busy
        text: i18n("Try again")
        icon.name: "view-refresh"
        onClicked: panel.retry()
    }

    Item { Layout.fillHeight: true }
}
