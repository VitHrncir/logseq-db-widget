import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami
import "logic.js" as Logic

// One block of a page outline. The owning ListView must provide
// `backend` and a `linkActivated(string)` signal.
Item {
    id: row

    required property var modelData
    required property int index

    readonly property var listView: ListView.view
    readonly property var backend: listView ? listView.backend : null
    // A status you added has no ident, so the helper also reports isTask.
    readonly property bool isTask: !!modelData.isTask || !!modelData.status
    readonly property bool closed: Logic.isClosed(modelData.status)
    property bool editing: false
    // The block's text when editing started, sent along on save so a block
    // that changed meanwhile isn't silently overwritten.
    property string originalTitle: ""
    property bool deleteArmed: false

    width: listView ? listView.width : 0
    implicitHeight: layout.implicitHeight + Kirigami.Units.smallSpacing

    function startEdit() {
        if (!backend)
            return;
        var editor = editField;
        backend.call("raw", { id: modelData.id }, function (ok, data) {
            if (!ok)
                return;
            if (data.hasRefs) {
                backend.notify(i18n("This block contains references to other blocks. Edit it in Logseq instead."));
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
        if (text.length === 0 || text === modelData.title) {
            editing = false;
            return;
        }
        editing = false;
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
            leftMargin: row.modelData.depth * Kirigami.Units.gridUnit
        }
        spacing: Kirigami.Units.smallSpacing

        // Bullet, or a checkbox for tasks.
        Item {
            Layout.alignment: Qt.AlignTop
            implicitWidth: row.isTask ? taskBox.implicitWidth : Kirigami.Units.iconSizes.smallMedium
            implicitHeight: row.isTask ? taskBox.implicitHeight : Kirigami.Units.iconSizes.smallMedium

            Rectangle {
                visible: !row.isTask
                anchors.centerIn: parent
                width: Math.round(Kirigami.Units.gridUnit / 3)
                height: width
                radius: width / 2
                color: Kirigami.Theme.textColor
                opacity: 0.55
            }

            PlasmaComponents3.CheckBox {
                id: taskBox
                visible: row.isTask
                anchors.centerIn: parent
                checked: Logic.isDone(row.modelData.status)
                onToggled: row.backend.call("taskSet", {
                    id: row.modelData.id,
                    status: checked ? Logic.STATUS_DONE : Logic.STATUS_TODO
                })
                QQC2.ToolTip.text: Logic.plain(row.modelData.statusTitle || "")
                QQC2.ToolTip.visible: hovered && !!row.modelData.statusTitle
            }
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

            PlasmaComponents3.Label {
                // Status other than plain todo/done gets a small hint.
                visible: !row.editing && row.isTask && !!row.modelData.statusTitle
                         && row.modelData.status !== Logic.STATUS_TODO
                         && row.modelData.status !== Logic.STATUS_DONE
                textFormat: Text.PlainText
                text: row.modelData.statusTitle || ""
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }

            PlasmaComponents3.TextField {
                id: editField
                visible: row.editing
                Layout.fillWidth: true
                onAccepted: row.saveEdit()
                Keys.onEscapePressed: row.editing = false
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
                  ? i18n("Click again to move this block and its children to Logseq's Recycle")
                  : i18n("Delete (restorable from Logseq's Recycle for 30 days)")
            onClicked: row.remove()
            QQC2.ToolTip.text: text
            QQC2.ToolTip.visible: hovered || row.deleteArmed
        }
    }
}
