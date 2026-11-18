#!/usr/bin/env python3
"""Tests for tools/purge-logseq-widget.py and tools/logseq-sync-sessions.py.

Everything runs in a throwaway home directory, with fake systemctl,
kpackagetool6 and pgrep commands that log what they were asked to do, and a
fake Logseq CLI unpacked where the widget would have put it.

Run:  python3 tests/test_tools.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
SESSIONS = os.path.join(TOOLS, "logseq-sync-sessions.py")
PURGE = os.path.join(TOOLS, "purge-logseq-widget.py")
sys.path.insert(0, HERE)
from test_helper import FAKE_CLI, FAKE_APPRUN, FAKE_ELECTRON, fake_proc, DESKTOP  # noqa: E402

FAKE_TOOL = """#!/bin/sh
echo "$(basename "$0") $*" >> "$TOOL_LOG"
case "$(basename "$0") $1 $2" in
  "systemctl --user is-active") [ -f "$HOME/.plasma-active" ] && exit 0 || exit 3 ;;
  "systemctl --user stop") rm -f "$HOME/.plasma-active" ;;
  "systemctl --user start") touch "$HOME/.plasma-active" ;;
  "kpackagetool6 -t Plasma/Applet") rm -rf "$HOME/.local/share/plasma/plasmoids/$4" ;;
  "pgrep "*) exit 1 ;;
esac
exit 0
"""

APPLETSRC = """[ActionPlugins][0]
RightButton;NoModifier=org.kde.contextmenu

[Containments][1]
plugin=org.kde.plasma.folder

[Containments][1][Applets][7]
immutability=1
plugin=io.github.logseqdbwidget

[Containments][1][Applets][7][Configuration][General]
graphName=Logseq-ExFile
backgroundSync=true

[Containments][1][Applets][8]
plugin=org.kde.plasma.digitalclock

[Containments][1][Applets][8][Configuration][Appearance]
showSeconds=2

[Containments][1][General]
ItemGeometries-1920x1080=Applet-7:0,0,400,600;Applet-8:500,0,200,100;

[Containments][2][Applets][30]
plugin=io.github.logseqdbwidget-but-not-really
"""


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        h = self.home
        self.bin = os.path.join(h, "bin")
        os.makedirs(self.bin)
        for tool in ("systemctl", "kpackagetool6", "pgrep"):
            path = os.path.join(self.bin, tool)
            with open(path, "w") as f:
                f.write(FAKE_TOOL)
            os.chmod(path, 0o755)
        # The widget's unpacked copy of Logseq, with the fake CLI inside.
        root = os.path.join(h, ".cache/logseq-db-widget/appimage-abc/squashfs-root")
        os.makedirs(os.path.join(root, "resources/app.asar/js"))
        for name, body in (("AppRun", FAKE_APPRUN), ("logseq", FAKE_ELECTRON),
                           ("resources/app.asar/js/logseq-cli.js", FAKE_CLI)):
            with open(os.path.join(root, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(root, name), 0o755)
        os.makedirs(os.path.join(h, ".cache/plasmashell/qmlcache"))
        os.makedirs(os.path.join(h, ".local/share/plasma/plasmoids/io.github.logseqdbwidget/contents"))
        os.makedirs(os.path.join(h, ".config"))
        with open(os.path.join(h, ".config/plasma-org.kde.plasma.desktop-appletsrc"), "w") as f:
            f.write(APPLETSRC)
        os.makedirs(os.path.join(h, "logseq/graphs/work"))  # a graph: must survive
        open(os.path.join(h, ".plasma-active"), "w").close()
        self.cli_log = os.path.join(h, "cli.log")
        self.tool_log = os.path.join(h, "tools.log")
        open(self.cli_log, "w").close()
        open(self.tool_log, "w").close()

    def env(self, **extra):
        e = {"HOME": self.home, "PATH": self.bin + ":/usr/bin:/bin", "FAKE_LOG": self.cli_log,
             "TOOL_LOG": self.tool_log, "FAKE_SERVER": "cli", "FAKE_SYNC": "open"}
        e.update(extra)
        return e

    def run_tool(self, script, *args, stdin=None, **extra):
        return subprocess.run([sys.executable, script, *args], capture_output=True, text=True,
                              env=self.env(**extra), timeout=120, input=stdin)

    def cli_calls(self):
        with open(self.cli_log) as f:
            calls = [json.loads(l)["norm"][2:] for l in f if l.strip()]
        return [c for c in calls if c]  # "--version" has no command words

    def tool_calls(self):
        with open(self.tool_log) as f:
            return [l.strip() for l in f if l.strip()]

    # ---- logseq-sync-sessions.py ----------------------------------------
    def test_list_changes_nothing(self):
        out = self.run_tool(SESSIONS, "--list", "--proc", fake_proc())
        self.assertIn("owner cli", out.stdout)
        self.assertIn("sync open", out.stdout)
        self.assertEqual(out.returncode, 1, "a CLI session is running")
        self.assertFalse(any("stop" in c for c in self.cli_calls()), self.cli_calls())

    def test_closes_sync_then_process(self):
        out = self.run_tool(SESSIONS, "--proc", fake_proc())
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        calls = self.cli_calls()
        stops = [(c[1], c[-2]) for c in calls if c[-2:] in (["sync", "stop"], ["server", "stop"])]
        # The fake reports two graphs; each one's sync stops before its process.
        self.assertEqual(stops, [("work", "sync"), ("work", "server"),
                                 ("personal", "sync"), ("personal", "server")])
        self.assertIn("No CLI database processes or sync sessions are running", out.stdout)

    def test_refuses_while_desktop_runs(self):
        out = self.run_tool(SESSIONS, "--proc", fake_proc(DESKTOP))
        self.assertIn("Logseq Desktop is running", out.stdout)
        self.assertFalse(any(c[-1] == "stop" for c in self.cli_calls()))
        out = self.run_tool(SESSIONS, "--force", "--proc", fake_proc(DESKTOP))
        self.assertTrue(any(c[-2:] == ["server", "stop"] for c in self.cli_calls()))

    def test_leaves_desktop_owned_process_alone(self):
        out = self.run_tool(SESSIONS, "--proc", fake_proc(), FAKE_SERVER="electron")
        self.assertEqual(out.returncode, 0)
        self.assertIn("Left alone (owner electron)", out.stdout)
        self.assertFalse(any(c[-1] == "stop" for c in self.cli_calls()))

    def test_unregistered_process_ended_only_with_force(self):
        # A real stray process that looks like a CLI database process.
        stray = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                                  "/x/db-worker-node.js", "--repo", "logseq_db_old",
                                  "--owner-source", "cli"])
        try:
            time.sleep(0.3)
            out = self.run_tool(SESSIONS, FAKE_SERVER="none")
            self.assertIn("pid %d" % stray.pid, out.stdout)
            self.assertIsNone(stray.poll(), "must not be ended without --force")
            self.assertEqual(out.returncode, 1)
            out = self.run_tool(SESSIONS, "--force", FAKE_SERVER="none")
            self.assertIsNotNone(stray.wait(timeout=10), out.stdout)
        finally:
            if stray.poll() is None:
                stray.kill()

    def test_process_of_another_version_is_never_queried(self):
        # Querying it would make Logseq shut it down (see the widget's version guard).
        out = self.run_tool(SESSIONS, "--list", "--proc", fake_proc(DESKTOP),
                            FAKE_SERVER="electron", FAKE_SERVER_REV="rev-OLD")
        self.assertIn("different Logseq version", out.stdout)
        self.assertFalse(any(c[-2:] == ["sync", "status"] for c in self.cli_calls()),
                         self.cli_calls())
        # A CLI-started one is left alone too while Logseq Desktop is open, even with --force.
        out = self.run_tool(SESSIONS, "--force", "--proc", fake_proc(DESKTOP),
                            FAKE_SERVER="cli", FAKE_SERVER_REV="rev-OLD")
        self.assertIn("Restart Logseq Desktop first", out.stdout)
        self.assertFalse(any(c[-1] == "stop" for c in self.cli_calls()), self.cli_calls())

    def test_no_cli_falls_back_to_process_list(self):
        shutil.rmtree(os.path.join(self.home, ".cache/logseq-db-widget"))
        out = self.run_tool(SESSIONS, "--list", "--proc", fake_proc())
        self.assertIn("none found", out.stdout)

    def test_set_e2ee_password(self):
        secret = "-starts-with-a-dash"
        out = self.run_tool(SESSIONS, "--set-e2ee-password", "work", "--proc", fake_proc(),
                            stdin=secret + "\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        with open(self.cli_log) as f:
            parsed = [json.loads(l) for l in f if l.strip()]
        start = [p for p in parsed if p["pos"] == ["sync", "start"]]
        self.assertEqual(len(start), 1)
        self.assertEqual(start[0]["opts"].get("e2ee-password"), secret,
                         "the real CLI must see the whole password as the value")
        self.assertEqual(start[0]["opts"].get("graph"), "work")
        self.assertNotIn(secret, out.stdout)
        self.assertIn("Saved for the current sign-in", out.stdout)

    def test_set_e2ee_password_picks_the_only_graph(self):
        out = self.run_tool(SESSIONS, "--set-e2ee-password", "--proc", fake_proc(),
                            stdin="pw\n", FAKE_MODE="onegraph")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("sync started for solo", out.stdout)
        out = self.run_tool(SESSIONS, "--set-e2ee-password", "--proc", fake_proc(), stdin="pw\n")
        self.assertEqual(out.returncode, 1)
        self.assertIn("Name the graph", out.stdout)

    def test_set_e2ee_password_waits_for_desktop_to_close(self):
        out = self.run_tool(SESSIONS, "--set-e2ee-password", "work", "--proc", fake_proc(DESKTOP),
                            stdin="pw\n")
        self.assertEqual(out.returncode, 1)
        self.assertIn("Close Logseq Desktop first", out.stdout)
        self.assertFalse(any(c[-2:] == ["sync", "start"] for c in self.cli_calls()))

    # ---- make-release.sh -------------------------------------------------
    def test_release_has_the_built_widget_in_bin(self):
        import tarfile, zipfile, io
        repo = os.path.join(HERE, "..")
        with open(os.path.join(repo, "package", "metadata.json")) as f:
            version = json.load(f)["KPlugin"]["Version"]
        out = subprocess.run(["bash", os.path.join(TOOLS, "make-release.sh"), self.home],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        path = os.path.join(self.home, "logseq-db-widget-%s.tar.gz" % version)
        self.assertEqual(out.stdout.strip(), path)
        with tarfile.open(path) as tar:
            names = tar.getnames()
            top = "logseq-db-widget-%s" % version
            self.assertIn(top + "/bin/logseq-db.plasmoid", names)
            self.assertIn(top + "/package/metadata.json", names)
            self.assertFalse([n for n in names if "__pycache__" in n])
            mode = tar.getmember(top + "/tools/purge-logseq-widget.py").mode
            self.assertTrue(mode & 0o111, "scripts stay executable")
            plasmoid = tar.extractfile(top + "/bin/logseq-db.plasmoid").read()
        with zipfile.ZipFile(io.BytesIO(plasmoid)) as z:
            self.assertIsNone(z.testzip())
            meta = json.loads(z.read("metadata.json"))
            self.assertEqual(meta["KPlugin"]["Version"], version, "built from this version")
            self.assertIn("contents/ui/main.qml", z.namelist())
            self.assertIn("contents/code/logseq_helper.py", z.namelist())

    # ---- purge-logseq-widget.py -----------------------------------------
    def test_dry_run_changes_nothing(self):
        before = open(os.path.join(self.home, ".config/plasma-org.kde.plasma.desktop-appletsrc")).read()
        out = self.run_tool(PURGE, "--dry-run")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        # One instance is ours; "...logseqdbwidget-but-not-really" must not match.
        self.assertIn("remove 1 widget instance(s)", out.stdout)
        after = open(os.path.join(self.home, ".config/plasma-org.kde.plasma.desktop-appletsrc")).read()
        self.assertEqual(before, after)
        for path in (".cache/logseq-db-widget", ".local/share/plasma/plasmoids/io.github.logseqdbwidget"):
            self.assertTrue(os.path.exists(os.path.join(self.home, path)))
        self.assertFalse(any(c[-1] == "stop" for c in self.cli_calls()))
        self.assertNotIn("systemctl --user stop plasma-plasmashell.service", self.tool_calls())

    def test_purge_removes_everything_but_graphs(self):
        out = self.run_tool(PURGE, "--yes")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        h = self.home
        cfg = os.path.join(h, ".config/plasma-org.kde.plasma.desktop-appletsrc")
        text = open(cfg).read()
        self.assertNotIn("plugin=io.github.logseqdbwidget\n", text)
        self.assertNotIn("graphName=Logseq-ExFile", text, "instance settings go too")
        self.assertIn("plugin=org.kde.plasma.digitalclock", text, "other widgets stay")
        self.assertIn("showSeconds=2", text)
        self.assertIn("plugin=io.github.logseqdbwidget-but-not-really", text, "exact id match only")
        self.assertTrue([f for f in os.listdir(os.path.join(h, ".config")) if ".bak-logseq-" in f])
        for path in (".cache/logseq-db-widget", ".cache/plasmashell/qmlcache",
                     ".local/share/plasma/plasmoids/io.github.logseqdbwidget"):
            self.assertFalse(os.path.exists(os.path.join(h, path)), path)
        self.assertTrue(os.path.isdir(os.path.join(h, "logseq/graphs/work")), "graphs survive")
        tools = self.tool_calls()
        self.assertLess(tools.index("systemctl --user stop plasma-plasmashell.service"),
                        tools.index("systemctl --user start plasma-plasmashell.service"))
        calls = self.cli_calls()
        self.assertIn(["server", "stop"], [c[-2:] for c in calls], "sessions closed first")
        self.assertNotIn(["logout"], [c[-1:] for c in calls], "the shared sign-in is never touched")

    def test_purge_without_instances_leaves_plasma_running(self):
        os.remove(os.path.join(self.home, ".config/plasma-org.kde.plasma.desktop-appletsrc"))
        out = self.run_tool(PURGE, "--yes")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertNotIn("systemctl --user stop plasma-plasmashell.service", self.tool_calls())


if __name__ == "__main__":
    unittest.main(verbosity=1)
