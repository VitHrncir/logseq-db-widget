import QtQuick

// Runs background-sync maintenance on a schedule. It lives in main.qml, which
// Plasma always creates, because in a panel the widget's main view is only
// created when you first open it; without this, "Keep syncing" would not
// start after a reboot until you clicked the widget.
Item {
    id: keeper
    visible: false

    required property var backend
    property bool active: false
    property int startDelaySeconds: 15
    property int intervalMinutes: 5

    Timer {
        // Shortly after login, once Plasma has settled.
        interval: keeper.startDelaySeconds * 1000
        running: keeper.active
        onTriggered: keeper.backend.maintainNow()
    }

    Timer {
        interval: keeper.intervalMinutes * 60 * 1000
        repeat: true
        running: keeper.active
        onTriggered: keeper.backend.maintainNow()
    }
}
