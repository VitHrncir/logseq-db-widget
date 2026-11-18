pragma Singleton
import QtQuick
QtObject {
    property color textColor: "black"
    property color negativeTextColor: "red"
    property color positiveTextColor: "green"
    property color neutralTextColor: "orange"
    property color disabledTextColor: "gray"
    property color linkColor: "#2980b9"
    property font smallFont: Qt.font({ pointSize: 8 })
}
