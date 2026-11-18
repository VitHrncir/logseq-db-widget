#!/usr/bin/env python3
"""
Headless integration test for the widget's QML.

Loads the real FullRepresentation.qml (and everything it uses) in a Qt Quick
engine with stand-in KDE modules from ./stubs. The stand-in DataSource really
runs commands through bash like Plasma's executable engine, so the full path is
exercised: QML -> Backend.qml -> logseq_helper.py -> fake `logseq` CLI.

Any QML warning or error coming from the widget's own files fails the test.

Run:  QT_QPA_PLATFORM=offscreen python3 tests/qml/run_ui_test.py
Needs: pip install PySide6-Essentials
"""
import json
import os
import urllib.parse
import stat
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import (QObject, QProcess, QUrl, QTimer, Signal, Slot, Property,
                            QMetaObject, Q_ARG, qInstallMessageHandler, QtMsgType)
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType, QJSValue
from PySide6.QtQuick import QQuickWindow

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
UI_DIR = os.path.join(ROOT, "package", "contents", "ui")
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_helper import FAKE_CLI  # noqa: E402


class DataSource(QObject):
    """Minimal stand-in for Plasma5Support's executable DataSource."""
    engine_available = True  # tests flip this to simulate a missing engine
    history = []             # every command string Plasma would be asked to run
    newData = Signal(str, "QVariantMap")
    engineChanged = Signal()
    connectedSourcesChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = ""
        self._sources = []
        self._procs = {}
        self._done = []

    def _get_engine(self):
        return self._engine

    def _set_engine(self, value):
        self._engine = value
        self.engineChanged.emit()

    engine = Property(str, _get_engine, _set_engine, notify=engineChanged)

    def _get_sources(self):
        return self._sources

    def _set_sources(self, value):
        self._sources = list(value)
        self.connectedSourcesChanged.emit()

    connectedSources = Property("QVariantList", _get_sources, _set_sources,
                                notify=connectedSourcesChanged)

    def _get_valid(self):
        return DataSource.engine_available and self._engine == "executable"

    valid = Property(bool, _get_valid, constant=True)

    @Slot(str)
    def connectSource(self, source):
        DataSource.history.append(source)
        proc = QProcess(self)
        self._procs[source] = proc

        def done(code, _status, source=source, proc=proc):
            out = bytes(proc.readAllStandardOutput()).decode()
            err = bytes(proc.readAllStandardError()).decode()
            self.newData.emit(source, {"stdout": out, "stderr": err, "exit code": code})
            self._done.append(proc)  # keep alive; Plasma owns these in the real thing

        proc.finished.connect(done)
        proc.start("bash", ["-c", source])

    @Slot(str)
    def disconnectSource(self, source):
        self._procs.pop(source, None)


class Localizer(QObject):
    """Stand-in for KLocalizedContext: i18n()/i18np() with %1 substitution."""

    @staticmethod
    def _fill(text, args):
        for i, a in enumerate(args, 1):
            text = text.replace("%%%d" % i, str(a))
        return text

    @Slot(str, result=str)
    @Slot(str, "QVariant", result=str)
    @Slot(str, "QVariant", "QVariant", result=str)
    def i18n(self, text, *args):
        return self._fill(text, args)

    @Slot(str, str, result=str)
    @Slot(str, str, "QVariant", result=str)
    @Slot(str, str, "QVariant", "QVariant", result=str)
    def i18nc(self, context, text, *args):
        return self._fill(text, args)

    @Slot(str, str, "QVariant", result=str)
    def i18np(self, singular, plural, n):
        return self._fill(singular if n == 1 else plural, [n])


HARNESS = """
import QtQuick
import QtQuick.Window
import org.kde.plasma.plasmoid
import "%s" as UI

Window {
    width: 480; height: 720; visible: true
    QtObject { id: fakeItem; property bool expanded: true; property string detectedGraph: "" }
    UI.Backend {
        id: logseqBackend; objectName: "backend"; cliPath: harnessCli
        graph: Plasmoid.configuration.graphName || fakeItem.detectedGraph   // as in main.qml
    }
    UI.FullRepresentation { anchors.fill: parent; backend: logseqBackend; plasmoidItem: fakeItem }
    UI.SyncKeeper { objectName: "keeper"; backend: logseqBackend; active: false; startDelaySeconds: 1 }
}
"""


class Runner:
    def __init__(self):
        self.app = QGuiApplication(sys.argv)
        self.problems = []
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "cli.log")
        open(self.log, "w").close()
        cli = os.path.join(self.tmp, "logseq")
        with open(cli, "w") as f:
            f.write(FAKE_CLI)
        os.chmod(cli, os.stat(cli).st_mode | stat.S_IEXEC)
        os.environ["FAKE_LOG"] = self.log
        os.environ["LOGSEQ_WIDGET_PROC"] = tempfile.mkdtemp()  # no Logseq Desktop "running"
        os.environ["LOGSEQ_WIDGET_GRAPHS"] = tempfile.mkdtemp()  # no real graph folders
        os.environ["FAKE_MODE"] = "normal"

        qInstallMessageHandler(self.on_message)
        qmlRegisterType(DataSource, "org.kde.plasma.plasma5support", 1, 0, "DataSource")

        self.engine = QQmlApplicationEngine()
        self.engine.addImportPath(os.path.join(HERE, "stubs"))
        self.localizer = Localizer()
        self.engine.rootContext().setContextObject(self.localizer)
        self.engine.rootContext().setContextProperty("harnessCli", cli)

        harness = os.path.join(self.tmp, "Harness.qml")
        with open(harness, "w") as f:
            f.write(HARNESS % QUrl.fromLocalFile(UI_DIR).toString())
        self.engine.load(QUrl.fromLocalFile(harness))
        if not self.engine.rootObjects():
            raise SystemExit("Harness failed to load:\n" + "\n".join(self.problems))
        self.root = self.engine.rootObjects()[0]
        self.backend = self.root.findChild(QObject, "backend")

    def on_message(self, mode, context, message):
        if message.startswith("Logseq widget"):
            return  # the widget's own diagnostics, written on purpose
        text = "%s (%s:%s)" % (message, context.file, context.line)
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            if "package/contents/ui" in (context.file or "") or "package/contents/ui" in message:
                self.problems.append(text)
            elif "Harness.qml" in (context.file or ""):
                self.problems.append(text)

    def find(self, name):
        obj = self.root.findChild(QObject, name)
        assert obj is not None, "object %r not found" % name
        return obj

    def wait_idle(self, timeout=20):
        """Pump the event loop until the backend queue is empty and stays empty."""
        deadline = time.time() + timeout
        quiet_since = None
        while time.time() < deadline:
            self.app.processEvents()
            if self.backend.property("pendingCount") == 0:
                quiet_since = quiet_since or time.time()
                if time.time() - quiet_since > 0.4:
                    return
            else:
                quiet_since = None
            time.sleep(0.01)
        raise AssertionError("backend did not go idle")

    def shot(self, name):
        out = os.environ.get("SHOT_DIR")
        if out:
            for _ in range(10):
                self.app.processEvents()
                time.sleep(0.02)
            QQuickWindow.grabWindow(self.root).save(os.path.join(out, name + ".png"))

    def fresh_log(self):
        """Empty the CLI call log and the fake CLI's state (tags, stopped processes)."""
        open(self.log, "w").close()
        for suffix in (".tags", ".stopped", ".stopped-sync", ".synced"):
            if os.path.exists(self.log + suffix):
                os.remove(self.log + suffix)

    def raw_calls(self):
        """CLI invocations, with --flag=value expanded to --flag value."""
        with open(self.log) as f:
            return [json.loads(line)["norm"] for line in f if line.strip()]

    def calls(self):
        """CLI invocations with the global --output/--graph flags removed."""
        out = []
        with open(self.log) as f:
            for line in f:
                if not line.strip():
                    continue
                args, rest, i = json.loads(line)["norm"], [], 0
                while i < len(args):
                    if args[i] in ("--output", "--graph", "--timeout-ms", "--root-dir", "--config"):
                        i += 2
                        continue
                    rest.append(args[i])
                    i += 1
                out.append(rest)
        return out

    def invoke(self, obj, method, *args):
        QMetaObject.invokeMethod(obj, method, *[Q_ARG("QVariant", a) for a in args])


def prop(obj, name):
    value = obj.property(name)
    return value.toVariant() if isinstance(value, QJSValue) else value


def main():
    r = Runner()
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    # 1. Startup: journal loads, graph name gets detected.
    r.wait_idle()
    journal = r.find("journalView")
    blocks = prop(journal, "blocks")
    check("journal loads blocks", len(blocks) == 2, blocks)
    check("journal title", journal.property("title") == "Oct 7th, 2026", journal.property("title"))
    check("journal open-in-Logseq url uses detected graph",
          journal.property("openUrl") == "logseq://graph/work?page=Oct%207th%2C%202026",
          journal.property("openUrl"))
    lv = [c for c in journal.findChildren(QObject) if c.metaObject().className().startswith("QQuickListView")]
    check("journal list instantiates delegates", lv and lv[0].property("count") == 2,
          lv and lv[0].property("count"))

    r.shot("journal")

    # 2. TODO tab.
    tabs = r.find("tabs")
    tabs.setProperty("currentIndex", 1)
    r.wait_idle()
    todo = r.find("todoView")
    visible = prop(todo, "visibleTasks")
    check("todo shows open tasks in priority order", [t["id"] for t in visible] == [3, 4, 1],
          [t["id"] for t in visible])
    check("todo statuses loaded, yours included",
          [s["title"] for s in prop(todo, "statuses")] == ["Todo", "Doing", "Waiting", "Done"],
          prop(todo, "statuses"))
    check("todo priorities loaded, yours included",
          [p["title"] for p in prop(todo, "priorities")] == ["Low", "High", "Idea"],
          prop(todo, "priorities"))
    todo.setProperty("filterValue", "all")
    r.app.processEvents()
    check("todo 'all' filter includes done", len(prop(todo, "visibleTasks")) == 4)
    todo.setProperty("filterValue", "logseq.property/status.done")
    r.app.processEvents()
    check("todo status filter", [t["id"] for t in prop(todo, "visibleTasks")] == [2])
    todo.setProperty("filterValue", "open")
    r.app.processEvents()

    # Tags.
    tag_box = r.find("tagBox")
    check("tag summary loaded", [t["title"] for t in prop(todo, "tagSummary")] == ["shopping", "work"],
          prop(todo, "tagSummary"))
    check("tag dropdown lists all, none and each tag", tag_box.property("count") == 4,
          tag_box.property("count"))
    todo.setProperty("tagFilterId", 50)  # work
    r.app.processEvents()
    check("filter by tag", [t["id"] for t in prop(todo, "visibleTasks")] == [4, 1],
          [t["id"] for t in prop(todo, "visibleTasks")])
    check("dropdown follows filter", tag_box.property("currentText").startswith("#work"),
          tag_box.property("currentText"))
    r.shot("todo-tag-filter")
    todo.setProperty("tagFilterId", -2)
    r.app.processEvents()
    check("'No tag' shows untagged tasks", [t["id"] for t in prop(todo, "visibleTasks")] == [3],
          [t["id"] for t in prop(todo, "visibleTasks")])
    todo.setProperty("tagFilterId", 51)  # shopping
    r.find("newTask").setProperty("text", "Oat milk")
    r.fresh_log()
    r.invoke(todo, "addTask")
    r.wait_idle()
    check("quick add tags the task with the active filter",
          any(c[:3] == ["upsert", "block", "--id"] and c[-2:] == ["--update-tags", '["shopping"]']
              for c in r.calls()), r.calls())
    check("quick add clears the field", r.find("newTask").property("text") == "")
    todo.setProperty("tagFilterId", 999)  # a tag that was deleted
    r.invoke(todo, "refresh")
    r.wait_idle()
    check("vanished tag falls back to all tags", todo.property("tagFilterId") == -1,
          todo.property("tagFilterId"))
    menus = [m for m in todo.findChildren(QObject) if m.inherits("QQuickMenu")]
    counts = sorted(m.property("count") for m in menus)
    check("status and priority menus built from the graph's choices", counts == [4, 5], counts)
    r.shot("todo")

    # 3. A write refreshes the current view.
    before = sum(1 for c in r.calls() if c[:2] == ["list", "task"])
    r.invoke(r.backend, "call", "taskSet", {"id": 3, "status": "logseq.property/status.done"}, None)
    r.wait_idle()
    calls = r.calls()
    check("taskSet reached the CLI",
          any(c == ["upsert", "block", "--id", "3", "--update-properties",
                    "{:logseq.property/status :logseq.property/status.done}"] for c in calls), calls)
    after = sum(1 for c in calls if c[:2] == ["list", "task"])
    check("write triggers refresh", after == before + 1, (before, after))

    # 4. Clicking a [[link]] opens it in the Pages tab.
    full = journal.parent().parent().parent()  # StackLayout > ColumnLayout > FullRepresentation
    r.invoke(full, "handleLink", "logseq-page:Page%20A")
    r.wait_idle()
    pages = r.find("pagesView")
    check("link switches to Pages tab", tabs.property("currentIndex") == 2)
    check("link opens that page", pages.property("current") == "Page A", pages.property("current"))
    check("page show called", any(c[:3] == ["show", "--page", "Page A"] for c in r.calls()))

    r.shot("pages")

    # 5. Pinned page buttons and a missing page.
    r.invoke(pages, "open", "Missing")
    r.wait_idle()
    check("missing page handled", pages.property("current") == "Missing")

    pages.setProperty("current", "")
    r.invoke(pages, "refresh")
    r.wait_idle()
    check("Pages tab defaults to first pinned page", pages.property("current") == "Projects",
          pages.property("current"))

    # 6. Errors surface in the banner.
    os.environ["FAKE_MODE"] = "garbage"
    r.invoke(pages, "refresh")
    r.wait_idle()
    banner = r.find("banner")
    check("banner shows error", banner.property("visible") and "Segmentation fault" in banner.property("text"),
          banner.property("text"))
    os.environ["FAKE_MODE"] = "normal"

    # 7. Load errors stay visible in the section, not just in the banner.
    tabs.setProperty("currentIndex", 0)
    os.environ["FAKE_MODE"] = "garbage"
    r.invoke(journal, "refresh")
    r.wait_idle()
    check("journal keeps its error visible", "Segmentation fault" in journal.property("errorText"),
          journal.property("errorText"))
    os.environ["FAKE_MODE"] = "normal"
    r.invoke(journal, "refresh")
    r.wait_idle()
    check("error clears after a successful load", journal.property("errorText") == "")

    # 8. Setup: no graphs on this computer (e.g. a Sync graph never downloaded).
    panel = r.find("setupPanel")
    sections = r.find("sections")
    os.environ["FAKE_MODE"] = "nographs"
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("no graphs -> setup panel", full.property("setupState") == "no-graphs"
          and panel.property("visible") and not sections.property("visible"),
          full.property("setupState"))
    check("no graphs explains Sync download", "Logseq Sync" in panel.property("explanation"),
          panel.property("explanation"))
    r.shot("setup-no-graphs")

    # 9. Setup: several graphs and no current one -> choose in the widget.
    os.environ["FAKE_MODE"] = "nocurrent"
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("several graphs -> chooser", full.property("setupState") == "choose-graph"
          and panel.property("canChoose"), full.property("setupState"))
    r.shot("setup-choose")
    r.fresh_log()
    QMetaObject.invokeMethod(panel, "graphChosen", Q_ARG("QString", "personal"))
    r.wait_idle()
    check("choosing a graph makes the widget ready", full.property("ready"), full.property("setupState"))
    check("chosen graph is used for requests",
          any(c[:4] == ["--output", "json", "--graph", "personal"] and "show" in c for c in r.raw_calls()),
          r.raw_calls()[-3:])

    # 10. Setup: the configured graph is gone.
    os.environ["FAKE_MODE"] = "nographs"
    r.invoke(full, "runSetup")
    r.wait_idle()
    os.environ["FAKE_MODE"] = "normal"
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("recovers after the graph appears", full.property("ready"), full.property("setupState"))

    # 11. A hung step becomes an error instead of waiting forever.
    r.backend.setProperty("timeouts", {"prepare": 3, "setup": 3, "_default": 3})
    os.environ["FAKE_MODE"] = "hang"
    r.invoke(full, "runSetup")
    deadline = time.time() + 2.5
    while time.time() < deadline:
        r.app.processEvents()
        time.sleep(0.02)
    check("shows which step is running", full.property("setupState") == "checking",
          full.property("setupState"))
    r.wait_idle(timeout=10)
    check("watchdog turns a hang into an error", full.property("setupState") == "error",
          full.property("setupState"))
    check("error points to the log", "helper.log" in full.property("setupMessage"),
          full.property("setupMessage"))
    r.shot("setup-timeout")
    # Let the abandoned request finish late; it must be ignored.
    os.environ["FAKE_MODE"] = "normal"
    deadline = time.time() + 5
    while time.time() < deadline:
        r.app.processEvents()
        time.sleep(0.02)
    check("late answer from abandoned request ignored", full.property("setupState") == "error",
          full.property("setupState"))
    r.backend.setProperty("timeouts", {"prepare": 900, "setup": 300, "_default": 180})
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("recovers after a timeout", full.property("ready"), full.property("setupState"))

    # 12. The helper path Plasma reports is unusable: fall back to the install location.
    fake_home = tempfile.mkdtemp()
    installed = os.path.join(fake_home, ".local/share/plasma/plasmoids/io.github.logseqdbwidget/contents/code")
    os.makedirs(installed)
    import shutil
    shutil.copy(os.path.join(ROOT, "package/contents/code/logseq_helper.py"), installed)
    real_home = os.environ["HOME"]
    real_path = r.backend.property("helperPath")
    os.environ["HOME"] = fake_home
    r.backend.setProperty("helperPath", "/nonexistent/qrc-style/logseq_helper.py")
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("falls back to the installed helper", full.property("ready"), full.property("setupMessage"))
    log_path = os.path.join(fake_home, ".cache", "logseq-db-widget", "helper.log")
    check("helper log created", os.path.exists(log_path))
    os.environ["HOME"] = real_home
    r.backend.setProperty("helperPath", real_path)

    # 13. Python missing: explained, not stuck.
    r.backend.setProperty("pythonCommand", "/nonexistent/python3")
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("missing python -> no-helper", full.property("setupState") == "no-helper",
          full.property("setupState"))
    check("missing python is named", "python3" in full.property("setupMessage"),
          full.property("setupMessage"))

    # 14. Plasma's runner never answers: quick, specific error.
    sleeper = os.path.join(r.tmp, "sleepy-python")
    with open(sleeper, "w") as f:
        f.write("#!/bin/sh\nsleep 8\n")
    os.chmod(sleeper, 0o755)
    r.backend.setProperty("pythonCommand", sleeper)
    r.backend.setProperty("timeouts", {"ping": 2, "prepare": 900, "setup": 300, "_default": 180})
    r.invoke(full, "runSetup")
    r.wait_idle(timeout=8)
    panel = r.find("setupPanel")
    check("unresponsive runner -> no-helper within seconds",
          full.property("setupState") == "no-helper" and panel.property("helperTimedOut"),
          (full.property("setupState"), full.property("setupMessage")))
    r.shot("setup-no-helper")
    r.backend.setProperty("pythonCommand", "python3")
    r.backend.setProperty("timeouts", {"ping": 20, "prepare": 900, "setup": 300, "_default": 180})
    deadline = time.time() + 7  # let the sleeper finish; its output must be ignored
    while time.time() < deadline:
        r.app.processEvents()
        time.sleep(0.02)
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("recovers after helper problems", full.property("ready"), full.property("setupState"))

    # 15. Plasma's executable engine missing: said immediately, with details.
    DataSource.engine_available = False
    started = time.time()
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("missing engine reported at once", full.property("setupState") == "no-helper"
          and time.time() - started < 3, (full.property("setupState"), time.time() - started))
    check("missing engine names plasma5support", "plasma5support" in full.property("setupMessage"),
          full.property("setupMessage"))
    check("diagnostics shown", "runner valid: false" in full.property("diagnostics"),
          full.property("diagnostics"))
    r.shot("setup-no-engine")
    DataSource.engine_available = True

    # 16. Start guard: even if the backend never calls back, "Starting" ends.
    full.setProperty("startGuardSeconds", 2)
    r.backend.setProperty("pythonCommand", sleeper)
    r.backend.setProperty("timeouts", {"ping": 100, "prepare": 900, "setup": 300, "_default": 180})
    r.invoke(full, "runSetup")
    deadline = time.time() + 3.5
    while time.time() < deadline:
        r.app.processEvents()
        time.sleep(0.02)
    check("start guard ends 'Starting'", full.property("setupState") == "no-helper",
          full.property("setupState"))
    check("guard diagnostics show the stuck request", "running: ping" in full.property("diagnostics"),
          full.property("diagnostics"))
    r.shot("setup-guard")
    # Clean up: let the stuck request time out, restore settings, recover.
    r.backend.setProperty("timeouts", {"ping": 1, "prepare": 900, "setup": 300, "_default": 180})
    r.wait_idle(timeout=12)
    r.backend.setProperty("pythonCommand", "python3")
    r.backend.setProperty("timeouts", {"ping": 20, "prepare": 900, "setup": 300, "_default": 180})
    full.setProperty("startGuardSeconds", 25)
    deadline = time.time() + 9
    while time.time() < deadline:
        r.app.processEvents()
        time.sleep(0.02)
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("recovers after guard", full.property("ready"), full.property("setupState"))

    # 17. An internal error during setup is shown on screen, not frozen at "Starting".
    full.setProperty("backend", None)
    r.invoke(full, "runSetup")
    for _ in range(20):
        r.app.processEvents()
        time.sleep(0.01)
    check("internal error shown", full.property("setupState") == "widget-error",
          full.property("setupState"))
    check("internal error text shown", "TypeError" in full.property("setupMessage")
          or "null" in full.property("setupMessage"), full.property("setupMessage"))
    check("diagnostics survive a missing backend", "backend missing" in full.property("diagnostics"),
          full.property("diagnostics"))
    r.shot("setup-widget-error")
    full.setProperty("backend", r.backend)
    r.invoke(full, "runSetup")
    r.wait_idle()
    check("recovers after internal error", full.property("ready"), full.property("setupState"))

    # 24. Statuses and priorities you added in Logseq.
    os.environ["FAKE_MODE"] = "custom"
    tabs.setProperty("currentIndex", 1)
    todo.setProperty("filterValue", "all")
    r.invoke(todo, "refresh")
    r.wait_idle()
    vt = prop(todo, "visibleTasks")
    check("task with your status and priority is listed",
          [(t["statusTitle"], t["priorityTitle"]) for t in vt] == [("Waiting", "Idea")], vt)
    todo.setProperty("filterValue", 75)  # filter by your "Waiting" status
    r.app.processEvents()
    check("filter by your status", [t["id"] for t in prop(todo, "visibleTasks")] == [5],
          prop(todo, "visibleTasks"))
    check("status dropdown follows the filter", r.find("todoView").findChildren(QObject) is not None
          and any(c.property("currentText") == "Waiting" for c in todo.findChildren(QObject)
                  if c.inherits("QQuickComboBox")), "dropdown text")
    r.shot("todo-custom-choices")
    r.fresh_log()
    r.invoke(r.backend, "call", "taskSet", {"id": 5, "status": 71}, None)
    r.wait_idle()
    check("setting a status sends the choice id",
          ["upsert", "block", "--id", "5", "--update-properties", "{:logseq.property/status 71}"]
          in r.calls(), r.calls())
    tabs.setProperty("currentIndex", 0)
    r.invoke(journal, "refresh")
    r.wait_idle()
    check("journal block with your status shows as a task", prop(journal, "blocks")[0]["isTask"],
          prop(journal, "blocks"))
    os.environ["FAKE_MODE"] = "normal"
    todo.setProperty("filterValue", "open")

    # 22. Deleting a task: it goes to Logseq's Recycle and stays out of the list.
    tabs.setProperty("currentIndex", 1)
    todo.setProperty("filterValue", "all")
    r.invoke(todo, "refresh")
    r.wait_idle()
    check("task 3 listed before deletion", 3 in [t["id"] for t in prop(todo, "visibleTasks")])
    os.environ["FAKE_MODE"] = "recycled"   # what the CLI reports once 3 is recycled
    r.fresh_log()
    r.invoke(r.backend, "call", "remove", {"id": 3}, None)
    r.wait_idle()
    check("remove reached the CLI", ["remove", "block", "--id", "3"] in r.calls(), r.calls())
    check("deleted task gone after the automatic refresh",
          3 not in [t["id"] for t in prop(todo, "visibleTasks")],
          [t["id"] for t in prop(todo, "visibleTasks")])
    check("task on a deleted page hidden too", 1 not in [t["id"] for t in prop(todo, "visibleTasks")])
    os.environ["FAKE_MODE"] = "normal"
    todo.setProperty("filterValue", "open")

    # 23. #tags typed into new entries become real tags.
    if os.path.exists(r.log + ".tags"):
        os.remove(r.log + ".tags")
    r.fresh_log()
    r.invoke(r.backend, "call", "append", {"text": "Lecture notes #University", "page": ""}, None)
    r.wait_idle()
    calls = r.calls()
    check("journal entry with a new tag creates the tag",
          ["upsert", "tag", "--name", "University"] in calls, calls)
    check("journal entry sent as Markdown so the tag is real",
          any(c[:3] == ["upsert", "block", "--blocks"] and c[3] == "- Lecture notes #University"
              for c in calls), calls)
    tabs.setProperty("currentIndex", 1)
    r.fresh_log()
    r.find("newTask").setProperty("text", "Essay draft #University")
    r.invoke(todo, "addTask")
    r.wait_idle()
    calls = r.calls()
    check("task with a tag is made a task after creation",
          any(c[:4] == ["upsert", "task", "--id", "999"] for c in calls), calls)
    check("task quick-add field cleared after success", r.find("newTask").property("text") == "")
    banner = r.find("banner")
    check("no error shown for tagged entries", not banner.property("visible"), banner.property("text"))

    # 25. The sync marker: where your changes are.
    def marker_text():
        return r.find("syncLabel").property("text")
    def settle_status(seconds=3):
        end = time.time() + seconds
        while time.time() < end:
            r.app.processEvents()
            time.sleep(0.02)
        r.wait_idle()
    tabs.setProperty("currentIndex", 0)
    os.environ["FAKE_MODE"] = "normal"
    os.environ["FAKE_SERVER"], os.environ["FAKE_SYNC"] = "electron", "open"
    os.environ["FAKE_PENDING"] = "0"
    r.fresh_log()
    r.invoke(r.backend, "call", "append", {"text": "marker test", "page": ""}, None)
    check("a change in progress shows as saving", r.backend.property("syncState") == "saving",
          r.backend.property("syncState"))
    r.wait_idle()
    settle_status()
    check("synced change shows as in the cloud", r.backend.property("syncState") == "cloud",
          (r.backend.property("syncState"), r.backend.property("syncDetail")))
    check("marker text: synced", marker_text() == "Synced to the cloud", marker_text())
    r.shot("marker-cloud")
    os.environ["FAKE_PENDING"] = "2"
    r.invoke(r.backend, "checkSyncNow")
    settle_status(2)
    check("pending changes show as uploading", r.backend.property("syncState") == "uploading"
          and "uploading 2 changes" in marker_text(), marker_text())
    os.environ["FAKE_PENDING"] = "0"
    settle_status(7)
    check("the marker follows the upload until it's done",
          r.backend.property("syncState") == "cloud", r.backend.property("syncState"))
    os.environ["FAKE_SYNC"] = "closed"
    r.invoke(r.backend, "checkSyncNow")
    settle_status(2)
    check("offline shows as saved locally", r.backend.property("syncState") == "local"
          and "offline" in r.backend.property("syncDetail"), r.backend.property("syncDetail"))
    r.shot("marker-local")
    os.environ["FAKE_SERVER"] = "none"
    r.invoke(r.backend, "checkSyncNow")
    settle_status(2)
    check("nothing running shows as saved locally", r.backend.property("syncState") == "local",
          r.backend.property("syncState"))
    os.environ["FAKE_MODE"] = "garbage"
    r.invoke(r.backend, "call", "append", {"text": "will fail", "page": ""}, None)
    r.wait_idle()
    settle_status(2.5)
    check("a failed change shows as not saved, and stays", r.backend.property("syncState") == "failed"
          and marker_text() == "Not saved", (r.backend.property("syncState"), marker_text()))
    r.shot("marker-failed")
    os.environ["FAKE_MODE"] = "normal"
    os.environ["FAKE_SERVER"], os.environ["FAKE_SYNC"] = "electron", "open"
    r.invoke(r.backend, "call", "append", {"text": "works again", "page": ""}, None)
    r.wait_idle()
    settle_status()
    check("the next saved change clears it", r.backend.property("syncState") == "cloud",
          r.backend.property("syncState"))
    for k in ("FAKE_SERVER", "FAKE_SYNC", "FAKE_PENDING"):
        os.environ.pop(k, None)

    # 26. "Keep syncing" while you use the widget (the reported bug): sync must
    #     start within seconds of a change, not after two idle minutes, and the
    #     marker must end on "Synced to the cloud".
    os.environ["FAKE_SERVER"] = "none"           # Logseq Desktop closed, nothing running
    r.fresh_log()
    r.backend.setProperty("idleSeconds", 120)    # the real idle stop delay
    r.backend.setProperty("backgroundIdleSeconds", 1)
    r.backend.setProperty("backgroundSync", True)
    settle_status(3)
    r.fresh_log()
    r.backend.setProperty("syncState", "unknown")
    r.invoke(r.backend, "call", "append", {"text": "while using it", "page": ""}, None)
    r.wait_idle()
    settle_status(9)
    calls = r.calls()
    check("keep syncing starts sync within seconds of a change",
          ["sync", "start"] in [c[:2] for c in calls], calls)
    check("the marker then shows the change in the cloud",
          r.backend.property("syncState") == "cloud",
          (r.backend.property("syncState"), r.backend.property("syncDetail")))
    # The background process dies (say, Plasma restarted): the next status
    # check notices and restarts sync by itself.
    for suffix in (".synced",):
        if os.path.exists(r.log + suffix):
            os.remove(r.log + suffix)
    r.backend.setProperty("_lastAutoStart", 0)
    r.fresh_log()
    r.invoke(r.backend, "checkSyncNow")
    settle_status(9)
    calls = r.calls()
    check("a stopped background sync is restarted by the next status check",
          ["sync", "start"] in [c[:2] for c in calls]
          and r.backend.property("syncState") == "cloud",
          (r.backend.property("syncState"), calls))
    # Logseq accepts "sync start" but skips it: the widget must say so, not
    # claim sync started.
    for suffix in (".synced",):
        if os.path.exists(r.log + suffix):
            os.remove(r.log + suffix)
    os.environ["FAKE_SYNC_START"], os.environ["FAKE_SYNC"] = "timeout", "stopped"
    r.backend.setProperty("_lastAutoStart", 0)
    r.backend.setProperty("_lastMaintainError", "")
    banner = r.find("banner")
    banner.setProperty("visible", False)
    r.fresh_log()
    r.invoke(r.backend, "call", "append", {"text": "skipped start", "page": ""}, None)
    r.wait_idle()
    settle_status(9)
    check("a skipped sync start is reported in the banner",
          banner.property("visible") and "start-skipped" in banner.property("text"),
          banner.property("text"))
    check("and explained in the marker's tooltip",
          r.backend.property("syncState") == "local"
          and "start-skipped" in r.backend.property("syncDetail"),
          (r.backend.property("syncState"), r.backend.property("syncDetail")))
    r.shot("marker-skipped")
    os.environ.pop("FAKE_SYNC_START", None)
    os.environ.pop("FAKE_SYNC", None)
    # The reported case: a background session stuck reconnecting with an
    # expired login. The next maintenance check hands it a fresh login.
    os.environ["FAKE_SERVER"], os.environ["FAKE_SYNC"] = "cli", "closed"
    r.backend.setProperty("_lastSyncProblem", "")
    r.fresh_log()
    r.invoke(r.backend, "checkSyncNow")
    settle_status(2)
    check("a stuck session shows as not synced", r.backend.property("syncState") == "local"
          and "offline" in r.backend.property("syncDetail"), r.backend.property("syncDetail"))
    r.invoke(r.backend, "maintainNow")
    settle_status(9)
    check("the next check renews its login, and it syncs again",
          ["sync", "start"] in [c[-2:] for c in r.calls()]
          and r.backend.property("syncState") == "cloud",
          (r.backend.property("syncState"), r.calls()))
    os.environ.pop("FAKE_SYNC", None)
    r.backend.setProperty("backgroundSync", False)
    r.backend.setProperty("backgroundIdleSeconds", 5)
    settle_status(2)
    os.environ.pop("FAKE_SERVER", None)

    # ===================== security =====================
    import http.server, socketserver, threading
    from PySide6.QtGui import QDesktopServices

    # 18. Hostile note content never makes Plasma fetch anything.
    hits = []
    class Pixel(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()
        def log_message(self, *a):
            pass
    pixel = socketserver.TCPServer(("127.0.0.1", 0), Pixel)
    threading.Thread(target=pixel.serve_forever, daemon=True).start()
    os.environ["FAKE_PIXEL"] = "http://127.0.0.1:%d" % pixel.server_address[1]
    os.environ["FAKE_MODE"] = "evil"
    tabs.setProperty("currentIndex", 0)
    r.invoke(journal, "refresh")
    r.wait_idle()
    tabs.setProperty("currentIndex", 1)
    todo.setProperty("statuses", [])
    r.invoke(todo, "refresh")
    r.wait_idle()
    todo.setProperty("tagFilterId", 60)  # show the hostile tag title in the dropdown
    tabs.setProperty("currentIndex", 2)
    r.invoke(pages, "open", "Hostile")
    r.wait_idle()
    deadline = time.time() + 2
    while time.time() < deadline:
        r.app.processEvents()
        time.sleep(0.02)
    check("hostile content triggers no network requests", hits == [], hits)
    check("hostile content was actually displayed", len(prop(journal, "blocks")) == 2,
          prop(journal, "blocks"))
    tabs.setProperty("currentIndex", 1)
    r.shot("security-hostile-todo")
    tabs.setProperty("currentIndex", 0)
    r.shot("security-hostile-journal")
    os.environ["FAKE_MODE"] = "normal"
    todo.setProperty("tagFilterId", -1)
    todo.setProperty("statuses", [])

    # 19. Only web and mail links open; others are blocked with a notice.
    opened = []
    class UrlSink(QObject):
        @Slot(QUrl)
        def handle(self, url):
            opened.append(url.toString())
    sink = UrlSink()
    for scheme in ("https", "http", "file", "mailto", "steam"):
        QDesktopServices.setUrlHandler(scheme, sink, "handle")
    banner = r.find("banner")
    r.invoke(full, "handleLink", "file:///home/someone/run.desktop")
    r.invoke(full, "handleLink", "steam://run/1")
    r.app.processEvents()
    check("file: and app links are blocked", opened == [], opened)
    check("blocked link is reported", "Blocked" in banner.property("text"), banner.property("text"))
    r.invoke(full, "handleLink", "https://example.org/x")
    r.invoke(full, "handleLink", "mailto:me@example.org")
    r.app.processEvents()
    check("web and mail links still open", opened == ["https://example.org/x", "mailto:me@example.org"],
          opened)

    # 20. Requests travel in the environment, not on the command line.
    marker = "Very private note 7f3a"
    DataSource.history.clear()
    tabs.setProperty("currentIndex", 0)
    r.invoke(r.backend, "call", "append", {"text": marker, "page": ""}, None)
    r.wait_idle()
    sent = [c for c in DataSource.history if "append" in urllib.parse.unquote(c)]
    check("request found in the command Plasma runs", len(sent) == 1, DataSource.history)
    if sent:
        after_exec = sent[0].split("; exec ", 1)[1]
        check("helper command line carries no request data",
              "LOGSEQ_WIDGET_REQUEST" not in after_exec and "%" not in after_exec, after_exec)
        check("request is exported to the environment", "export LOGSEQ_WIDGET_REQUEST=" in sent[0])
    check("the note itself still reached Logseq",
          any(c[:2] == ["upsert", "block"] and marker in c for c in r.calls()))

    # 21. Background process maintenance.
    r.backend.setProperty("idleSeconds", 1)
    r.backend.setProperty("backgroundIdleSeconds", 1)
    def settle(seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            r.app.processEvents()
            time.sleep(0.02)
        r.wait_idle()
    os.environ["FAKE_SERVER"], os.environ["FAKE_SYNC"] = "cli", "stopped"
    r.fresh_log()
    r.invoke(journal, "refresh")
    r.wait_idle()
    settle(2.5)
    check("idle CLI process is stopped", ["server", "stop"] in [c[:2] for c in r.calls()], r.calls())
    os.environ["FAKE_SERVER"] = "electron"
    r.fresh_log()
    r.invoke(journal, "refresh")
    settle(2.5)
    check("Logseq Desktop's process is never stopped",
          ["server", "stop"] not in [c[:2] for c in r.calls()], r.calls())
    os.environ["FAKE_SERVER"], os.environ["FAKE_SYNC"] = "cli", "open"
    r.fresh_log()
    r.invoke(journal, "refresh")
    settle(2.5)
    check("a process that is syncing is left running",
          ["server", "stop"] not in [c[:2] for c in r.calls()], r.calls())
    os.environ["FAKE_SERVER"], os.environ["FAKE_SYNC"] = "none", "stopped"
    r.fresh_log()
    r.backend.setProperty("backgroundSync", True)
    settle(2.5)
    check("background sync starts sync", ["sync", "start"] in [c[:2] for c in r.calls()], r.calls())
    r.backend.setProperty("backgroundSync", False)
    settle(2.5)
    before = r.backend.property("lastUserActivity")
    r.backend.setProperty("backgroundMode", True)
    r.invoke(journal, "refresh")
    r.backend.setProperty("backgroundMode", False)
    r.wait_idle()
    check("background refreshes don't count as use",
          r.backend.property("lastUserActivity") == before)
    # The keeper starts background sync on its own, with no request from the
    # widget's main view (as for a panel widget never opened since login).
    r.backend.setProperty("backgroundSync", False)
    settle(2.5)
    os.environ["FAKE_SERVER"], os.environ["FAKE_SYNC"] = "none", "stopped"
    r.fresh_log()
    r.backend.setProperty("lastUserActivity", 0)
    r.backend.setProperty("_needsMaintenance", False)
    keeper = r.find("keeper")
    r.backend.setProperty("backgroundSync", True)   # this alone triggers one maintenance run
    settle(2.5)
    r.fresh_log()                         # so only the keeper's run is counted
    keeper.setProperty("active", True)
    settle(4)
    check("sync keeper starts background sync without the main view",
          ["sync", "start"] in [c[:2] for c in r.calls()], r.calls())
    keeper.setProperty("active", False)
    r.backend.setProperty("backgroundSync", False)
    settle(2.5)
    for k in ("FAKE_SERVER", "FAKE_SYNC"):
        os.environ.pop(k, None)
    r.backend.setProperty("idleSeconds", 120)
    r.backend.setProperty("backgroundIdleSeconds", 5)

    for _ in range(20):  # flush any late warnings
        r.app.processEvents()
        time.sleep(0.01)

    ok = True
    for name, passed, detail in checks:
        ok &= passed
        print("%s  %s%s" % ("PASS" if passed else "FAIL", name, "" if passed else "   -> %r" % (detail,)))
    if r.problems:
        ok = False
        print("\nQML warnings from widget files:")
        for p in r.problems:
            print("  " + p)
    print("\n%s" % ("ALL UI CHECKS PASSED" if ok else "UI CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
