import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import "logic.js" as Logic

PlasmoidItem {
    id: root

    // Graph chosen by the setup step when none is configured: the CLI's
    // current graph, or the only graph on this computer.
    property string detectedGraph: ""
    readonly property string graph: Plasmoid.configuration.graphName || detectedGraph

    toolTipMainText: i18n("Logseq")
    toolTipSubText: i18n("Today's journal, tasks and pinned pages")

    // On the desktop show everything; in a panel show an icon with a popup.
    preferredRepresentation: Plasmoid.formFactor === PlasmaCore.Types.Planar
                             ? fullRepresentation : compactRepresentation

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Open Logseq")
            icon.name: "document-open"
            visible: root.graph.length > 0
            onTriggered: Qt.openUrlExternally(Logic.logseqUrl(root.graph, ""))
        }
    ]

    Backend {
        id: logseqBackend
        cliPath: Plasmoid.configuration.cliPath
        appImagePath: Plasmoid.configuration.appImagePath
        graph: root.graph
        pythonCommand: Plasmoid.configuration.pythonCommand || "python3"
        backgroundSync: Plasmoid.configuration.backgroundSync
    }

    SyncKeeper {
        backend: logseqBackend
        active: logseqBackend.backgroundSync
    }

    fullRepresentation: FullRepresentation {
        backend: logseqBackend
        plasmoidItem: root
    }
}
