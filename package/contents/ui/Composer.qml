import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3

// Enter adds a block, Ctrl+Enter (or the checkbox button) adds a task.
RowLayout {
    id: composer

    property alias placeholderText: field.placeholderText
    property bool allowTask: true

    signal submitted(string text, bool asTask)

    function clear() {
        field.text = "";
    }

    function submit(asTask) {
        var text = field.text.trim();
        if (text.length > 0)
            submitted(text, asTask);
    }

    PlasmaComponents3.TextField {
        id: field
        Layout.fillWidth: true
        clearButtonShown: true
        Keys.onReturnPressed: event => {
            composer.submit(composer.allowTask && (event.modifiers & Qt.ControlModifier));
            event.accepted = true;
        }
        Keys.onEnterPressed: event => {
            composer.submit(composer.allowTask && (event.modifiers & Qt.ControlModifier));
            event.accepted = true;
        }
    }

    PlasmaComponents3.ToolButton {
        icon.name: "list-add"
        display: QQC2.AbstractButton.IconOnly
        text: i18n("Add block")
        enabled: field.text.trim().length > 0
        onClicked: composer.submit(false)
        QQC2.ToolTip.text: i18n("Add block (Enter)")
        QQC2.ToolTip.visible: hovered
    }

    PlasmaComponents3.ToolButton {
        visible: composer.allowTask
        icon.name: "checkbox"
        display: QQC2.AbstractButton.IconOnly
        text: i18n("Add task")
        enabled: field.text.trim().length > 0
        onClicked: composer.submit(true)
        QQC2.ToolTip.text: i18n("Add as task (Ctrl+Enter)")
        QQC2.ToolTip.visible: hovered
    }
}
