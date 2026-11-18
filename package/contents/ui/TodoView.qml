import QtQuick
import QtQml.Models
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import "logic.js" as Logic

ColumnLayout {
    id: todo
    objectName: "todoView"

    required property var backend
    // Where new tasks go; "" means today's journal.
    property string targetPage: ""
    property bool showClosedByDefault: false

    property var tasks: []
    property var statuses: []
    property var priorities: []
    property bool loaded: false
    property string errorText: ""
    property bool stale: true
    // "open", "all", or a status choice's value (its id, or ident for built-ins).
    property var filterValue: showClosedByDefault ? "all" : "open"

    // Tag filter: a tag's id, ALL_TAGS or NO_TAG.
    readonly property int allTags: -1
    readonly property int noTag: -2
    property int tagFilterId: allTags
    property var tagSummary: []
    readonly property var tagFilterTag: {
        for (var i = 0; i < tagSummary.length; ++i) {
            if (tagSummary[i].id === tagFilterId)
                return tagSummary[i];
        }
        return null;
    }

    function setTagFilter(id) {
        tagFilterId = id;
    }

    function matchesTag(task) {
        if (tagFilterId === allTags)
            return true;
        var tags = task.tags || [];
        if (tagFilterId === noTag)
            return tags.length === 0;
        for (var i = 0; i < tags.length; ++i) {
            if (tags[i].id === tagFilterId)
                return true;
        }
        return false;
    }

    onTagFilterIdChanged: tagBox.currentIndex = Math.max(0, tagBox.indexOfValue(tagFilterId))
    onFilterValueChanged: filterBox.currentIndex = Math.max(0, filterBox.indexOfValue(filterValue))

    signal linkActivated(string link)

    spacing: Kirigami.Units.smallSpacing

    readonly property var visibleTasks: {
        var out = [];
        for (var i = 0; i < tasks.length; ++i) {
            var t = tasks[i];
            var statusOk = filterValue === "open" ? !Logic.isClosed(t.status)
                    : filterValue === "all" ? true
                    : t.statusId === filterValue || t.status === filterValue;
            if (statusOk && matchesTag(t))
                out.push(t);
        }
        return out;
    }

    readonly property var filterModel: {
        var model = [
            { text: i18n("Open tasks"), value: "open" },
            { text: i18n("All tasks"), value: "all" }
        ];
        for (var i = 0; i < statuses.length; ++i)
            model.push({ text: Logic.plain(statuses[i].title), value: statuses[i].value });
        return model;
    }

    readonly property var tagModel: {
        var model = [
            { text: i18n("All tags"), value: allTags },
            { text: i18n("No tag"), value: noTag }
        ];
        for (var i = 0; i < tagSummary.length; ++i) {
            var t = tagSummary[i];
            model.push({ text: Logic.plain(i18nc("tag name and number of open tasks", "#%1 (%2)", t.title, t.open)), value: t.id });
        }
        return model;
    }

    function refresh() {
        stale = false;
        backend.call("tasks", { includeClosed: true }, function (ok, data, error) {
            if (!ok) {
                todo.errorText = error || "";
                return;
            }
            todo.errorText = "";
            // Choices come with every refresh, so ones you add appear here.
            todo.statuses = data.statuses || [];
            todo.priorities = data.priorities || [];
            todo.tagSummary = data.tags || [];
            // A remembered tag that no longer exists falls back to all tags.
            if (todo.tagFilterId >= 0 && todo.tagFilterTag === null)
                todo.tagFilterId = todo.allTags;
            todo.tasks = data.tasks;
            todo.loaded = true;
        });
    }

    function addTask() {
        var text = newTask.text.trim();
        if (text.length === 0)
            return;
        var params = { text: text, page: targetPage };
        // With a tag filter active, new tasks get that tag.
        if (tagFilterTag)
            params.tags = [tagFilterTag.title];
        if (newPriority.currentValue !== "" && newPriority.currentValue !== undefined)
            params.priority = newPriority.currentValue;
        backend.call("taskAdd", params, function (ok) {
            if (ok) {
                newTask.text = "";
                newPriority.currentIndex = 0;
            }
        });
    }

    // Quick add.
    RowLayout {
        Layout.fillWidth: true

        PlasmaComponents3.TextField {
            id: newTask
            objectName: "newTask"
            Layout.fillWidth: true
            clearButtonShown: true
            placeholderText: Logic.plain(todo.tagFilterTag
                             ? (todo.targetPage.length > 0
                                ? i18n("New #%1 task on %2…", todo.tagFilterTag.title, todo.targetPage)
                                : i18n("New #%1 task in today's journal…", todo.tagFilterTag.title))
                             : (todo.targetPage.length > 0
                                ? i18n("New task on %1…", todo.targetPage)
                                : i18n("New task in today's journal…")))
            onAccepted: todo.addTask()
        }

        PlasmaComponents3.ComboBox {
            id: newPriority
            textRole: "text"
            valueRole: "value"
            model: [{ text: i18n("No priority"), value: "" }].concat(todo.priorities.map(function (p) {
                return { text: Logic.plain(p.title), value: p.value };
            }))
        }

        PlasmaComponents3.ToolButton {
            icon.name: "list-add"
            display: QQC2.AbstractButton.IconOnly
            text: i18n("Add task")
            enabled: newTask.text.trim().length > 0
            onClicked: todo.addTask()
            QQC2.ToolTip.text: text
            QQC2.ToolTip.visible: hovered
        }
    }

    RowLayout {
        Layout.fillWidth: true

        PlasmaComponents3.ComboBox {
            id: filterBox
            Layout.fillWidth: true
            textRole: "text"
            valueRole: "value"
            model: todo.filterModel
            onActivated: todo.filterValue = currentValue
            // The model is rebuilt when statuses load; keep the selection.
            onModelChanged: currentIndex = Math.max(0, indexOfValue(todo.filterValue))
            Component.onCompleted: currentIndex = Math.max(0, indexOfValue(todo.filterValue))
        }

        PlasmaComponents3.ComboBox {
            id: tagBox
            objectName: "tagBox"
            Layout.fillWidth: true
            textRole: "text"
            valueRole: "value"
            model: todo.tagModel
            onActivated: todo.tagFilterId = currentValue
            onModelChanged: currentIndex = Math.max(0, indexOfValue(todo.tagFilterId))
            Component.onCompleted: currentIndex = Math.max(0, indexOfValue(todo.tagFilterId))
        }

        PlasmaComponents3.Label {
            text: i18np("%1 task", "%1 tasks", todo.visibleTasks.length)
            opacity: 0.7
        }
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        PlasmaComponents3.ScrollView {
            anchors.fill: parent

            ListView {
                id: list
                property var backend: todo.backend
                signal linkActivated(string link)
                onLinkActivated: link => todo.linkActivated(link)

                function openStatusMenu(task) {
                    statusMenu.task = task;
                    statusMenu.popup();
                }
                function setTagFilter(id) {
                    todo.setTagFilter(id);
                }
                function openPriorityMenu(task) {
                    priorityMenu.task = task;
                    priorityMenu.popup();
                }

                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: todo.visibleTasks
                delegate: TaskDelegate {}
            }
        }

        PlasmaExtras.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 2
            visible: todo.visibleTasks.length === 0 && (todo.loaded || todo.errorText.length > 0)
            iconName: todo.errorText.length > 0 ? "dialog-error" : "checkmark"
            text: Logic.plain(todo.errorText.length > 0 ? i18n("Couldn't load tasks")
                  : todo.tagFilterTag && todo.filterValue === "open" ? i18n("Nothing left to do in #%1", todo.tagFilterTag.title)
                  : todo.filterValue === "open" && todo.tagFilterId === todo.allTags ? i18n("Nothing left to do")
                  : i18n("No tasks here"))
            explanation: Logic.plain(todo.errorText.length > 0 ? todo.errorText
                  : todo.filterValue === "open" ? i18n("Tasks tagged #Task anywhere in your graph show up here.") : "")
        }

        PlasmaComponents3.BusyIndicator {
            anchors.centerIn: parent
            visible: !todo.loaded && todo.errorText.length === 0 && todo.backend.busy
            running: visible
        }
    }

    PlasmaComponents3.Menu {
        id: statusMenu
        property var task: null

        Instantiator {
            model: todo.statuses
            delegate: PlasmaComponents3.MenuItem {
                required property var modelData
                text: Logic.plain(modelData.title)
                checkable: true
                checked: statusMenu.task !== null
                         && Logic.sameChoice(statusMenu.task.statusId, statusMenu.task.status, modelData)
                onTriggered: todo.backend.call("taskSet", { id: statusMenu.task.id, status: modelData.value })
            }
            onObjectAdded: (index, object) => statusMenu.insertItem(index, object)
            onObjectRemoved: (index, object) => statusMenu.removeItem(object)
        }
    }

    PlasmaComponents3.Menu {
        id: priorityMenu
        property var task: null

        function setPriority(value) {
            todo.backend.call("taskSet", { id: task.id, priority: value });
        }

        Instantiator {
            model: todo.priorities
            delegate: PlasmaComponents3.MenuItem {
                required property var modelData
                text: Logic.plain(modelData.title)
                checkable: true
                checked: priorityMenu.task !== null
                         && Logic.sameChoice(priorityMenu.task.priorityId, priorityMenu.task.priority, modelData)
                onTriggered: priorityMenu.setPriority(modelData.value)
            }
            onObjectAdded: (index, object) => priorityMenu.insertItem(index, object)
            onObjectRemoved: (index, object) => priorityMenu.removeItem(object)
        }

        PlasmaComponents3.MenuSeparator {}
        PlasmaComponents3.MenuItem {
            text: i18n("No priority")
            checkable: true
            checked: priorityMenu.task !== null && !priorityMenu.task.priority
                     && (priorityMenu.task.priorityId === null || priorityMenu.task.priorityId === undefined)
            onTriggered: priorityMenu.setPriority("")
        }
    }
}
