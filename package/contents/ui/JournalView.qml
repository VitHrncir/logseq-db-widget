import QtQuick
import "logic.js" as Logic

BlockPane {
    id: journal
    objectName: "journalView"

    property string graph: ""
    property bool stale: true

    function refresh() {
        stale = false;
        backend.call("journal", {}, function (ok, data, error) {
            if (!ok) {
                journal.errorText = error || "";
                return;
            }
            journal.errorText = "";
            journal.title = data.title;
            journal.blocks = data.blocks;
            journal.loaded = true;
        });
    }

    targetPage: ""
    openUrl: Logic.logseqUrl(graph, title)
    placeholderIcon: "view-calendar-day"
    placeholderText: i18n("Nothing in today's journal yet")
    placeholderExplanation: i18n("Write below. Enter adds a block, Ctrl+Enter adds a task.")
    composerPlaceholder: i18n("Add to today's journal…")
}
