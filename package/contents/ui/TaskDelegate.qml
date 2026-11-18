import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami
import "logic.js" as Logic

// One task in the TODO list. The owning ListView provides `backend`,
// `openStatusMenu(task)`, `openPriorityMenu(task)`,
// `setTagFilter(id)` and a `linkActivated(string)` signal.
Item {
    id: row

    required property var modelData
    required property int index

    readonly property var listView: ListView.view
    readonly property var backend: listView ? listView.backend : null
    readonly property bool closed: Logic.isClosed(modelData.status)
    readonly property string priority: Logic.priorityKey(modelData.priority)
    readonly property bool hasPriority: !!modelData.priority
                                        || (modelData.priorityId !== null && modelData.priorityId !== undefined)
    property bool editing: false
    // The block's text when editing started, sent along on save so a block
    // that changed meanwhile isn't silently overwritten.
    property string originalTitle: ""
    property bool deleteArmed: false

    width: listView ? listView.width : 0
    implicitHeight: layout.implicitHeight + Kirigami.Units.smallSpacing * 2

    function formatDate(ms) {
        return new Date(ms).toLocaleDateString(Qt.locale(), Locale.ShortFormat);
    }

    function isOverdue(ms) {
        return !row.closed && ms < Date.now();
    }

    function priorityColor(key) {
        if (key === "urgent" || key === "high")
            return Kirigami.Theme.negativeTextColor;
        if (key === "medium")
            return Kirigami.Theme.neutralTextColor;
        if (key === "low")
            return Kirigami.Theme.disabledTextColor;
        return Kirigami.Theme.textColor; // a priority you added
    }

    function priorityTitle(key) {
        switch (key) {
        case "urgent": return i18n("Urgent");
        case "high": return i18n("High");
        case "medium": return i18n("Medium");
        case "low": return i18n("Low");
        }
        return i18n("No priority");
    }

    function startEdit() {
        var editor = editField;
        backend.call("raw", { id: modelData.id }, function (ok, data) {
            if (!ok)
                return;
            if (data.hasRefs) {
                backend.notify(i18n("This task contains references to other blocks. Edit it in Logseq instead."));
                return;
            }
            row.originalTitle = data.title;
            editor.text = data.title;
            row.editing = true;
            editor.forceActiveFocus();
            editor.selectAll();
        });
    }

    function saveEdit() {
        var text = editField.text.trim();
        editing = false;
        if (text.length > 0 && text !== modelData.title)
            backend.call("edit", { id: modelData.id, text: text, expected: originalTitle });
    }

    function remove() {
        if (!deleteArmed) {
            deleteArmed = true;
            disarm.restart();
            return;
        }
        deleteArmed = false;
        backend.call("remove", { id: modelData.id });
    }

    Timer {
        id: disarm
        interval: 3000
        onTriggered: row.deleteArmed = false
    }

    HoverHandler {
        id: hover
    }

    RowLayout {
        id: layout
        anchors {
            left: parent.left
            right: parent.right
            top: parent.top
            topMargin: Kirigami.Units.smallSpacing
        }
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents3.CheckBox {
            Layout.alignment: Qt.AlignTop
            checked: Logic.isDone(row.modelData.status)
            onToggled: row.backend.call("taskSet", {
                id: row.modelData.id,
                status: checked ? Logic.STATUS_DONE : Logic.STATUS_TODO
            })
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            PlasmaComponents3.Label {
                id: label
                visible: !row.editing
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                textFormat: Text.MarkdownText
                text: Logic.toMarkdown(row.modelData.title)
                opacity: row.closed ? 0.6 : 1
                font.strikeout: Logic.isDone(row.modelData.status)
                onLinkActivated: link => row.listView.linkActivated(link)
                // Shows where a link really goes before you click it.
                QQC2.ToolTip.text: Logic.plain(Logic.describeLink(label.hoveredLink))
                QQC2.ToolTip.visible: label.hoveredLink.length > 0

                HoverHandler {
                    cursorShape: label.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor
                }
            }

            PlasmaComponents3.TextField {
                id: editField
                visible: row.editing
                Layout.fillWidth: true
                onAccepted: row.saveEdit()
                Keys.onEscapePressed: row.editing = false
            }

            // Status, priority and dates.
            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents3.ToolButton {
                    id: statusButton
                    text: Logic.plain(row.modelData.statusTitle || i18n("No status"))
                    font: Kirigami.Theme.smallFont
                    flat: true
                    onClicked: row.listView.openStatusMenu(row.modelData)
                    QQC2.ToolTip.text: i18n("Change status")
                    QQC2.ToolTip.visible: hovered
                }

                PlasmaComponents3.Label {
                    id: priorityLabel
                    height: statusButton.height
                    leftPadding: Kirigami.Units.smallSpacing
                    rightPadding: Kirigami.Units.smallSpacing
                    verticalAlignment: Text.AlignVCenter
                    font: Kirigami.Theme.smallFont
                    text: row.hasPriority
                          ? Logic.plain(row.modelData.priorityTitle || row.priorityTitle(row.priority))
                          : i18n("Set priority")
                    color: row.hasPriority ? row.priorityColor(row.priority) : Kirigami.Theme.disabledTextColor
                    opacity: row.hasPriority || hover.hovered ? 1 : 0
                    QQC2.ToolTip.text: i18n("Change priority")
                    QQC2.ToolTip.visible: priorityHover.hovered && opacity > 0

                    HoverHandler {
                        id: priorityHover
                        cursorShape: Qt.PointingHandCursor
                    }
                    TapHandler {
                        enabled: priorityLabel.opacity > 0
                        onTapped: row.listView.openPriorityMenu(row.modelData)
                    }
                }

                // Tags; clicking one filters the list by it.
                Repeater {
                    model: row.modelData.tags || []

                    PlasmaComponents3.Label {
                        id: tagLabel
                        required property var modelData
                        height: statusButton.height
                        leftPadding: Kirigami.Units.smallSpacing
                        rightPadding: Kirigami.Units.smallSpacing
                        verticalAlignment: Text.AlignVCenter
                        font: Kirigami.Theme.smallFont
                        color: Kirigami.Theme.linkColor
                        textFormat: Text.PlainText
                        text: "#" + modelData.title
                        QQC2.ToolTip.text: Logic.plain(i18n("Show only #%1 tasks", modelData.title))
                        QQC2.ToolTip.visible: tagHover.hovered

                        HoverHandler {
                            id: tagHover
                            cursorShape: Qt.PointingHandCursor
                        }
                        TapHandler {
                            onTapped: row.listView.setTagFilter(tagLabel.modelData.id)
                        }
                    }
                }

                PlasmaComponents3.Label {
                    visible: typeof row.modelData.deadline === "number"
                    height: statusButton.height
                    verticalAlignment: Text.AlignVCenter
                    font: Kirigami.Theme.smallFont
                    text: visible ? i18n("Due %1", row.formatDate(row.modelData.deadline)) : ""
                    color: visible && row.isOverdue(row.modelData.deadline)
                           ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                }

                PlasmaComponents3.Label {
                    visible: typeof row.modelData.scheduled === "number"
                    height: statusButton.height
                    verticalAlignment: Text.AlignVCenter
                    font: Kirigami.Theme.smallFont
                    opacity: 0.8
                    text: visible ? i18n("Scheduled %1", row.formatDate(row.modelData.scheduled)) : ""
                }
            }
        }

        PlasmaComponents3.ToolButton {
            Layout.alignment: Qt.AlignTop
            opacity: hover.hovered || row.editing ? 1 : 0
            enabled: opacity > 0
            icon.name: row.editing ? "dialog-ok-apply" : "document-edit"
            display: QQC2.AbstractButton.IconOnly
            text: row.editing ? i18n("Save") : i18n("Edit")
            onClicked: row.editing ? row.saveEdit() : row.startEdit()
            QQC2.ToolTip.text: text
            QQC2.ToolTip.visible: hovered
        }

        PlasmaComponents3.ToolButton {
            Layout.alignment: Qt.AlignTop
            opacity: (hover.hovered && !row.editing) || row.deleteArmed ? 1 : 0
            enabled: opacity > 0
            icon.name: row.deleteArmed ? "edit-delete-remove" : "edit-delete"
            icon.color: row.deleteArmed ? Kirigami.Theme.negativeTextColor : "transparent"
            display: QQC2.AbstractButton.IconOnly
            text: row.deleteArmed
                  ? i18n("Click again to move this task to Logseq's Recycle")
                  : i18n("Delete (restorable from Logseq's Recycle for 30 days)")
            onClicked: row.remove()
            QQC2.ToolTip.text: text
            QQC2.ToolTip.visible: hovered || row.deleteArmed
        }
    }
}
