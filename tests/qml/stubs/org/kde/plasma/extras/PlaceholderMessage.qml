import QtQuick
import QtQuick.Controls as T
import QtQuick.Layouts
ColumnLayout {
    property string iconName
    property string text
    property string explanation
    T.Label { text: parent.text; Layout.fillWidth: true; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; font.bold: true }
    T.Label { text: parent.explanation; Layout.fillWidth: true; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
}
