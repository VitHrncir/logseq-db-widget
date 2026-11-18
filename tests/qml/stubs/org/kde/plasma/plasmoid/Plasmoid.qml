pragma Singleton
import QtQuick
QtObject {
    property int formFactor: 2 // Horizontal panel, so "shown" depends on expanded
    property QtObject configuration: QtObject {
        property string graphName: ""
        property string cliPath: ""
        property string appImagePath: ""
        property string pythonCommand: "python3"
        property int refreshMinutes: 5
        property bool showCompletedTasks: false
        property bool backgroundSync: false
        property int lastTab: 0
        property int taskTagFilter: -1
        property string page1: "Projects"
        property string page2: "Reading"
        property string page3: ""
        property string page4: ""
        property string page5: ""
        property string page6: ""
        property string taskTargetPage: ""
    }
}
