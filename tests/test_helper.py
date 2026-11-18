#!/usr/bin/env python3
"""
Tests for the widget's helper (logseq_helper.py and its logseq_widget package). A fake `logseq` executable records every argument
list it receives and answers with JSON in the shapes the real CLI produces
(taken from logseq/cli-e2e/spec/non_sync_cases.edn and cli/lib/*.ml).

Run:  python3 tests/test_helper.py
"""
import datetime
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "..", "package", "contents", "code", "logseq_helper.py")
sys.path.insert(0, os.path.dirname(HELPER))
sys.dont_write_bytecode = True  # no cache files inside the widget's folder
from logseq_widget import cli as cli_module  # noqa: E402
from logseq_widget import journal, processes, safeguards  # noqa: E402
from logseq_widget import sync as sync_module  # noqa: E402

FAKE_CLI = r'''#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]

def is_option(t):
    return len(t) > 0 and t[0] == "-" and not (len(t) > 1 and t[1] in " \t\n\r")

def real_parse(argv):
    """Port of logseq cli_parse.ml parse_tokens: what the real CLI would see."""
    opts, pos, i = {}, [], 0
    while i < len(argv):
        t = argv[i]
        if t == "--":
            pos += argv[i + 1:]
            break
        if t.startswith("--") and len(t) > 2 and "=" in t:
            k, v = t[2:].split("=", 1)
            opts.setdefault(k, v)
            i += 1
        elif t.startswith("--") and len(t) > 2:
            k = t[2:]
            if i + 1 < len(argv) and not is_option(argv[i + 1]):
                opts.setdefault(k, argv[i + 1])
                i += 2
            else:
                opts.setdefault(k, None)
                i += 1
        else:
            pos.append(t)
            i += 1
    return opts, pos

def expand(argv):
    """--flag=value -> --flag value, so tests can index arguments simply."""
    out = []
    for t in argv:
        if t.startswith("--") and "=" in t:
            out += t.split("=", 1)
        else:
            out.append(t)
    return out

real_opts, real_pos = real_parse(args)

# Commands and options the real CLI accepts (from cli/lib/cli_parse.ml,
# allowed_options_for_path), so a wrong command fails here as it would there.
GLOBAL = {"graph", "root-dir", "config", "timeout-ms", "output", "verbose", "profile",
          "help", "version"}
LIST = {"fields", "limit", "offset", "sort", "order"}
ALLOWED = {
    ("query",): {"query", "name", "inputs"},
    ("show",): {"id", "uuid", "page", "page-hierarchy", "linked-references",
                "ref-id-footer", "level"},
    ("list", "task"): LIST | {"status", "priority", "content"},
    ("remove", "block"): {"id", "uuid"},
    ("remove", "page"): {"id", "page", "force"},
    ("upsert", "block"): {"id", "uuid", "target-id", "target-uuid", "target-page", "pos",
                          "content", "blocks", "blocks-file", "dry-run", "update-tags",
                          "update-properties", "remove-tags", "remove-properties"},
    ("upsert", "task"): {"id", "uuid", "page", "content", "target-id", "target-uuid",
                         "target-page", "pos", "status", "priority", "scheduled", "deadline",
                         "no-status", "no-priority", "no-scheduled", "no-deadline"},
    ("debug", "pull"): {"id", "uuid", "ident"},
    ("upsert", "tag"): {"id", "name", "add-properties", "remove-properties"},
    ("graph", "list"): set(), ("graph", "info"): set(),
    ("server", "list"): set(), ("server", "stop"): set(),
    ("sync", "status"): set(), ("sync", "start"): {"e2ee-password"}, ("sync", "stop"): set(),
    ("logout",): set(),
}
if "version" in real_opts and not real_pos:
    # Plain text, like the real CLI; never touches a database.
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps({"argv": args, "norm": args, "opts": real_opts, "pos": []}) + "\n")
    print("Build time: test\nRevision: " + os.environ.get("FAKE_CLI_REV", "rev-1"))
    sys.exit(0)
path = tuple(real_pos)
if path not in ALLOWED:
    if any(len(p) > len(path) and p[:len(path)] == path for p in ALLOWED):
        # A bare group like `remove` prints help text, not JSON, and fails.
        print("Usage: logseq %s <command> [options]" % " ".join(path))
        sys.exit(1)
    print(json.dumps({"status": "error", "error": {"code": "unknown-command",
                                                    "message": "unknown command: " + " ".join(path)}}))
    sys.exit(1)
unknown = set(real_opts) - GLOBAL - ALLOWED[path]
if unknown:
    print(json.dumps({"status": "error", "error": {"code": "invalid-options",
                                                    "message": "unknown options: " + ", ".join(sorted(unknown))}}))
    sys.exit(1)
norm = expand(args)
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": args, "norm": norm, "opts": real_opts, "pos": real_pos}) + "\n")
mode = os.environ.get("FAKE_MODE", "normal")
args = norm
PX = os.environ.get("FAKE_PIXEL", "http://127.0.0.1:9")
def evil(name):
    return '<img src="%s/%s.png">' % (PX, name)

def ok(data):
    print(json.dumps({"status": "ok", "data": data})); sys.exit(0)
def err(code, msg):
    print(json.dumps({"status": "error", "error": {"code": code, "message": msg}})); sys.exit(1)

# strip globals
i = 0
rest = []
while i < len(args):
    if args[i] in ("--output", "--graph", "--timeout-ms", "--root-dir", "--config"):
        i += 2; continue
    rest.append(args[i]); i += 1
cmd = rest[:2]

if mode == "garbage":
    print("Segmentation fault"); sys.exit(139)
if mode == "hang":
    import time; time.sleep(6)
if mode == "nocurrent" and "--graph" not in args and cmd != ["graph", "list"]:
    err("missing-repo", "repo is required")

if rest[0] == "query":
    q = rest[rest.index("--query") + 1]
    if "[:find [?p ?t]" in q:
        ok({"result": None if mode == "nojournal" else [500, "Oct 7th, 2026"]})
    if ":block/journal-day" in q:
        ok({"result": None if mode == "nojournal" else 500})
    if "title-format" in q:
        ok({"result": "yyyy-MM-dd EEEE"})
    if ":block/tags ?task]" in q and "deleted-at" in q:
        if mode == "notags":
            err("invalid-query", "task metadata query failed")
        task = {"db/id": 9, "db/ident": "logseq.class/Task", "block/title": "Task"}
        work = {"db/id": 50, "db/ident": "user.class/work-AbC", "block/title": "work"}
        shop = {"db/id": 51, "db/ident": "user.class/shopping-XyZ", "block/title": "shopping"}
        card = {"db/id": 52, "db/ident": "logseq.class/Card", "block/title": "Card"}
        if mode == "evil":
            hostile = {"db/id": 60, "db/ident": "user.class/x", "block/title": evil("tag")}
            ok({"result": [[1, {"block/tags": [task, hostile]}]]})
        rows = {1: {"block/tags": [task, work], "block/page": {}},
                4: {"block/tags": [task, work, shop]},
                2: {"block/tags": [task, shop]},
                3: {"block/tags": [task, card]}}
        if mode == "custom":
            ok({"result": [[5, {"block/tags": [task],
                                "logseq.property/status": {"db/id": 75, "block/title": "Waiting"},
                                "logseq.property/priority": {"db/id": 85, "block/title": "Idea"}}]]})
        if mode == "recycled":
            rows[3]["logseq.property/deleted-at"] = 1770000000000           # deleted itself
            rows[1]["block/page"] = {"logseq.property/deleted-at": 1770000000000}  # its page deleted
        ok({"result": [[k, v] for k, v in rows.items()]})
    if "[?pi ...]" in q:
        S, P = "logseq.property/status", "logseq.property/priority"
        def c(i, title, order, ident=None, box=None):
            d = {"db/id": i, "block/title": title, "block/order": order}
            if ident: d["db/ident"] = ident
            if box is not None: d["logseq.property/choice-checkbox-state"] = box
            return d
        if mode == "evil":
            ok({"result": [[S, c(71, evil("status"), "a1", S + ".todo")]]})
        ok({"result": [
            [S, c(74, "Done", "a4", S + ".done", True)],
            [S, c(71, "Todo", "a1", S + ".todo", False)],
            [S, c(75, "Waiting", "a3")],                      # yours: no ident
            [S, c(72, "Doing", "a2", S + ".doing")],
            [S, c(76, "Old", "a5") | {"logseq.property/deleted-at": 1}],
            [P, c(83, "High", "a3", P + ".high")],
            [P, c(81, "Low", "a1", P + ".low")],
            [P, c(85, "Idea", "a5")],                         # yours: no ident
        ]})
if cmd == ["show", "--id"] or cmd == ["show", "--page"]:
    if "Missing" in rest:
        err("page-not-found", "page not found")
    if mode == "custom":
        ok({"root": {"db/id": 500, "block/title": "Oct 7th, 2026", "block/children": [
            {"db/id": 510, "block/title": "waiting on Bob",
             "logseq.property/status": {"block/title": "Waiting"}}]}})
    if mode == "evil":
        ok({"root": {"db/id": 500, "block/title": evil("heading"), "block/children": [
            {"db/id": 501, "block/title": "md image ![x](%s/md.png) and ref ![y][r]\n\n[r]: %s/ref.png" % (PX, PX)},
            {"db/id": 502, "block/title": evil("html") + ' <a href="file:///etc/passwd">harmless</a>'},
        ]}})
    ok({"root": {"db/id": 500, "block/title": "Oct 7th, 2026", "block/children": [
        {"db/id": 501, "block/title": "Plain [[Page A]]", "block/children": [
            {"db/id": 502, "block/title": "Child task",
             "logseq.property/status": {"db/ident": "logseq.property/status.todo", "block/title": "Todo"}}]},
        {"db/id": 503, "block/title": "prop value", "logseq.property/created-from-property": {"db/id": 9}},
    ]}})
if cmd == ["list", "task"] and mode == "evil":
    ok({"items": [{"db/id": 1, "block/title": "task " + evil("task") + " ![t](%s/taskmd.png)" % PX,
                   "logseq.property/status": "logseq.property/status.todo"}]})
if cmd == ["list", "task"] and mode == "custom":
    ok({"items": [{"db/id": 5, "block/title": "custom one", "logseq.property/status": None,
                   "logseq.property/priority": None}]})
if cmd == ["list", "task"]:
    ok({"items": [
        {"db/id": 1, "block/title": "low todo", "logseq.property/status": "logseq.property/status.todo",
         "logseq.property/priority": "logseq.property/priority.low", "block/updated-at": 5},
        {"db/id": 2, "block/title": "done one", "logseq.property/status": "logseq.property/status.done"},
        {"db/id": 3, "block/title": "doing", "logseq.property/status": "logseq.property/status.doing"},
        {"db/id": 4, "block/title": "urgent todo", "logseq.property/status": "logseq.property/status.todo",
         "logseq.property/priority": "logseq.property/priority.urgent"},
    ]})
if cmd == ["debug", "pull"]:
    bid = rest[rest.index("--id") + 1]
    title = "has ref [[11111111-1111-1111-1111-111111111111]]" if bid == "7" else "plain text"
    ok({"block/title": title, "db/id": int(bid)})
# Tags: Markdown --blocks input turns #tag into a tag, but only an existing
# one; `upsert tag --name` creates tags (kept in a state file between calls).
TAG_STATE = os.environ["FAKE_LOG"] + ".tags"
def known_tags():
    known = {"work", "shopping"}
    if os.path.exists(TAG_STATE):
        known |= {l.strip().lower() for l in open(TAG_STATE) if l.strip()}
    return known
if cmd == ["upsert", "tag"]:
    with open(TAG_STATE, "a") as f:
        f.write(real_opts["name"] + "\n")
    ok({"result": [777]})
if cmd == ["upsert", "block"] and "--blocks" in rest:
    md = rest[rest.index("--blocks") + 1]
    for link, word in re.findall(r"(?<!\S)#(?:\[\[([^\]]+)\]\]|([^\s#\[\]]+))", md):
        name = link or word
        if name.lower() not in known_tags() or mode == "tagloop":
            print(json.dumps({"status": "error", "error": {"code": "tag-not-found",
                  "message": "tag not found: " + name, "hint": "create it with upsert tag"}}))
            sys.exit(1)
    ok({"result": [999, 1000]})
if cmd == ["upsert", "task"] and "--id" in rest and mode == "taskfail":
    err("invalid-options", "cannot convert")
STOPPED = os.environ["FAKE_LOG"] + ".stopped"
if cmd == ["sync", "stop"]:
    open(STOPPED + "-sync", "w").close()
    ok({})
if rest[:1] == ["logout"]:
    ok({"logged-out": True})
if cmd == ["server", "list"] and os.path.exists(STOPPED):
    ok({"servers": []})
SYNCED = STOPPED.replace(".stopped", ".synced")
if cmd == ["server", "list"] and os.path.exists(SYNCED):
    ok({"servers": [{"repo": "logseq_db_" + g, "graph": g, "owner-source": "cli",
                     "status": "running", "pid": 4242,
                     "revision": os.environ.get("FAKE_SERVER_REV", "rev-1")}
                    for g in ("work", "personal")]})
if cmd == ["server", "list"]:
    owner = os.environ.get("FAKE_SERVER", "none")
    servers = [] if owner == "none" else [
        {"repo": "logseq_db_" + g, "graph": g, "owner-source": owner, "status": "running",
         "pid": 4242, "revision": os.environ.get("FAKE_SERVER_REV", "rev-1")}
        for g in ("work", "personal")]
    ok({"servers": servers})
if cmd == ["server", "stop"]:
    if os.environ.get("FAKE_SERVER") == "electron":
        err("server-owned-by-other", "owned by electron")
    open(STOPPED, "w").close()
    ok({"repo": "logseq_db_work"})
if cmd == ["sync", "status"]:
    state = ("stopped" if os.path.exists(STOPPED + "-sync")
             else "open" if os.path.exists(STOPPED.replace(".stopped", ".synced"))
             else os.environ.get("FAKE_SYNC", "stopped"))
    if state == "error":
        err("timeout", "sync status timed out")
    gid = os.environ.get("FAKE_GRAPH_ID", "g-1")
    ok({"ws-state": state, "last-error": os.environ.get("FAKE_SYNC_ERROR"),
        "graph-id": None if gid == "none" else gid,
        "pending-local": int(os.environ.get("FAKE_PENDING", "0")),
        "pending-asset": int(os.environ.get("FAKE_PENDING_ASSET", "0"))})
if cmd == ["sync", "start"] and os.environ.get("FAKE_SYNC_START") == "timeout":
    # Like the real CLI when the connection doesn't open within --timeout-ms.
    err("sync-start-timeout", "sync start timed out before websocket reached open state")
if cmd == ["sync", "start"]:
    # Like the real CLI: starts the graph's database process if needed, with sync.
    open(STOPPED.replace(".stopped", ".synced"), "w").close()
    for f in (STOPPED, STOPPED + "-sync"):
        if os.path.exists(f):
            os.remove(f)
    ok({"ws-state": "open"})
if cmd == ["graph", "list"]:
    if mode == "nographs":
        ok({"graphs": [], "graph-items": []})
    if mode == "onegraph":
        ok({"graphs": ["solo"], "graph-items": []})
    ok({"graphs": ["work", "personal"], "graph-items": []})
if cmd == ["graph", "info"]:
    if mode in ("nocurrent", "onegraph"):
        err("missing-repo", "repo is required")
    ok({"graph": "work", "kv": {}})
# Like the real CLI: creating a task accepts only --target-page.
if rest[:2] == ["upsert", "task"] and "--content" in rest and \
        any(a in rest for a in ("--target-id", "--target-uuid", "--pos")):
    err("spec-blocker", "upsert task create currently supports only --target-page")
if rest[0] in ("upsert", "remove"):
    ok({"result": [999]})
err("unknown", "fake cli does not know " + " ".join(rest))
'''


EMPTY_PROC = tempfile.mkdtemp()


def fake_proc(*processes):
    """A fake /proc with (argv list, environ list) processes owned by us."""
    root = tempfile.mkdtemp()
    for pid, (argv, environ) in enumerate(processes, start=100):
        d = os.path.join(root, str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in argv) + b"\0")
        with open(os.path.join(d, "environ"), "wb") as f:
            f.write(b"\0".join(e.encode() for e in environ) + b"\0")
    return root


DESKTOP = (["/tmp/.mount_logseqAb12/logseq", "--no-sandbox"], ["HOME=/home/u"])
DB_WORKER = (["/home/u/.cache/logseq-db-widget/appimage-x/squashfs-root/logseq",
              "/x/db-worker-node.js", "--repo", "logseq_db_work", "--owner-source", "cli"],
             ["ELECTRON_RUN_AS_NODE=1"])
RENDERER = (["/tmp/.mount_logseqAb12/logseq", "--type=renderer"], [])


class HelperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.cli = os.path.join(cls.tmp, "logseq")
        with open(cls.cli, "w") as f:
            f.write(FAKE_CLI)
        os.chmod(cls.cli, os.stat(cls.cli).st_mode | stat.S_IEXEC)
        cls.log = os.path.join(cls.tmp, "log.jsonl")

    def setUp(self):
        # State the fake CLI keeps between calls (created tags, stopped
        # processes and sync) must not leak from one test into the next.
        for suffix in (".tags", ".stopped", ".stopped-sync", ".synced"):
            if os.path.exists(self.log + suffix):
                os.remove(self.log + suffix)

    def call(self, req, mode="normal", encode=True, graph="work", cli=None, env_extra=None):
        open(self.log, "w").close()
        req = dict(req, cli=cli if cli is not None else self.cli, graph=graph, reqId=42)
        arg = json.dumps(req)
        if encode:  # same encoding as Backend.qml
            arg = urllib.parse.quote(arg, safe="-_.")
        # An empty process list, so a real Logseq on this machine can't affect tests.
        env = dict(os.environ, FAKE_LOG=self.log, FAKE_MODE=mode, LOGSEQ_WIDGET_PROC=EMPTY_PROC,
                   LOGSEQ_WIDGET_GRAPHS=EMPTY_PROC)  # no real graph folders
        env.update(env_extra or {})
        out = subprocess.run([sys.executable, HELPER, arg], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        res = json.loads(out.stdout)
        self.assertEqual(res["reqId"], 42)
        with open(self.log) as f:
            self.parsed = [json.loads(line) for line in f if line.strip()]
        return res, [p["norm"] for p in self.parsed]

    def test_journal_existing(self):
        res, calls = self.call({"op": "journal"})
        self.assertTrue(res["ok"], res)
        blocks = res["data"]["blocks"]
        self.assertEqual([b["id"] for b in blocks], [501, 502])  # property block skipped
        self.assertEqual(blocks[1]["depth"], 1)
        self.assertEqual(blocks[1]["status"], "logseq.property/status.todo")
        self.assertEqual(calls[-1][:6], ["--output", "json", "--graph", "work", "show", "--id"])

    def test_journal_missing_uses_graph_format(self):
        res, _ = self.call({"op": "journal"}, mode="nojournal")
        expected = journal.format_journal_title("yyyy-MM-dd EEEE", datetime.date.today())
        self.assertEqual(res["data"]["title"], expected)
        self.assertEqual(res["data"]["blocks"], [])

    def test_append_to_existing_journal_targets_id(self):
        res, calls = self.call({"op": "append", "text": "hello $(rm -rf ~) 'quoted' \"x\" ünïcode"})
        self.assertTrue(res["ok"], res)
        up = calls[-1]
        self.assertIn("hello $(rm -rf ~) 'quoted' \"x\" ünïcode", up)
        self.assertEqual(up[up.index("--target-id") + 1], "500")

    def test_append_creates_journal_with_title(self):
        res, calls = self.call({"op": "append", "text": "x"}, mode="nojournal")
        up = calls[-1]
        title = journal.format_journal_title("yyyy-MM-dd EEEE", datetime.date.today())
        self.assertEqual(up[up.index("--target-page") + 1], title)

    def test_append_to_page(self):
        _, calls = self.call({"op": "append", "text": "x", "page": "Projects"})
        self.assertEqual(calls[-1][-2:], ["--target-page", "Projects"])

    def test_tasks_sorted_and_filtered(self):
        res, _ = self.call({"op": "tasks"})
        self.assertEqual([t["id"] for t in res["data"]["tasks"]], [3, 4, 1])
        res, _ = self.call({"op": "tasks", "includeClosed": True})
        self.assertEqual([t["id"] for t in res["data"]["tasks"]], [3, 4, 1, 2])

    def test_tasks_carry_tags(self):
        res, _ = self.call({"op": "tasks", "includeClosed": True})
        by_id = {t["id"]: t for t in res["data"]["tasks"]}
        self.assertEqual([t["title"] for t in by_id[4]["tags"]], ["shopping", "work"])
        self.assertEqual(by_id[3]["tags"], [], "built-in tags are left out")
        summary = {t["title"]: (t["open"], t["total"]) for t in res["data"]["tags"]}
        # Task 2 is done, so #shopping has 1 open of 2.
        self.assertEqual(summary, {"shopping": (1, 2), "work": (2, 2)})

    def test_recycled_tasks_are_hidden(self):
        res, _ = self.call({"op": "tasks", "includeClosed": True}, mode="recycled")
        ids = [t["id"] for t in res["data"]["tasks"]]
        self.assertNotIn(3, ids, "a deleted task must not come back")
        self.assertNotIn(1, ids, "a task on a deleted page must not come back")
        self.assertEqual(sorted(ids), [2, 4])
        summary = {t["title"]: (t["open"], t["total"]) for t in res["data"]["tags"]}
        self.assertEqual(summary, {"shopping": (1, 2), "work": (1, 1)})

    def test_tasks_survive_tag_lookup_failure(self):
        res, _ = self.call({"op": "tasks"}, mode="notags")
        self.assertTrue(res["ok"], res)
        self.assertEqual(len(res["data"]["tasks"]), 3)
        self.assertEqual(res["data"]["tags"], [])

    def test_task_add_with_tag(self):
        res, calls = self.call({"op": "taskAdd", "text": "Milk", "tags": ['sh"op ping']})
        self.assertTrue(res["ok"], res)
        tag_call = calls[-1]
        self.assertEqual(tag_call[4:8], ["upsert", "block", "--id", "999"])
        self.assertEqual(tag_call[8:], ["--update-tags", '["sh\\"op ping"]'])

    def test_task_add_targets_journal_by_title(self):
        res, calls = self.call({"op": "taskAdd", "text": "Call mum"})
        self.assertTrue(res["ok"], res)
        up = calls[-1]
        self.assertNotIn("--target-id", up)
        self.assertEqual(up[up.index("--target-page") + 1], "Oct 7th, 2026")

    def test_task_add_creates_journal_by_formatted_title(self):
        res, calls = self.call({"op": "taskAdd", "text": "Call mum"}, mode="nojournal")
        self.assertTrue(res["ok"], res)
        up = calls[-1]
        title = journal.format_journal_title("yyyy-MM-dd EEEE", datetime.date.today())
        self.assertEqual(up[up.index("--target-page") + 1], title)

    def test_journal_task_button_works(self):
        # The Journal tab's "add as task" uses the same path.
        res, _ = self.call({"op": "taskAdd", "text": "x", "page": ""})
        self.assertTrue(res["ok"], res)

    def test_task_add_rejects_bad_tags(self):
        res, calls = self.call({"op": "taskAdd", "text": "Milk", "tags": [""]})
        self.assertFalse(res["ok"])
        self.assertEqual(calls, [])

    def test_choices_include_yours_in_order(self):
        res, _ = self.call({"op": "statuses"})
        st = res["data"]["statuses"]
        self.assertEqual([s["title"] for s in st], ["Todo", "Doing", "Waiting", "Done"])
        waiting = st[2]
        self.assertEqual((waiting["id"], waiting["ident"], waiting["value"]), (75, None, 75))
        self.assertEqual([p["title"] for p in res["data"]["priorities"]], ["Low", "High", "Idea"])

    def test_tasks_with_your_status_and_priority(self):
        res, _ = self.call({"op": "tasks"}, mode="custom")
        t = res["data"]["tasks"][0]
        self.assertEqual((t["statusId"], t["statusTitle"], t["status"]), (75, "Waiting", None))
        self.assertEqual((t["priorityId"], t["priorityTitle"]), (85, "Idea"))
        self.assertIn("Waiting", [s["title"] for s in res["data"]["statuses"]],
                      "choices come with every task refresh")

    def test_block_with_your_status_is_a_task(self):
        res, _ = self.call({"op": "journal"}, mode="custom")
        b = res["data"]["blocks"][0]
        self.assertTrue(b["isTask"])
        self.assertEqual(b["statusTitle"], "Waiting")

    def test_set_your_status_and_priority_by_id(self):
        _, calls = self.call({"op": "taskSet", "id": 3, "status": 75, "priority": 85})
        self.assertEqual(calls[-1][4:], ["upsert", "block", "--id", "3", "--update-properties",
                                         "{:logseq.property/status 75 :logseq.property/priority 85}"])

    def test_set_builtin_status_by_ident(self):
        _, calls = self.call({"op": "taskSet", "id": 3, "status": "logseq.property/status.done"})
        self.assertEqual(calls[-1][-1], "{:logseq.property/status :logseq.property/status.done}")

    def test_choice_values_cannot_inject_edn(self):
        for bad in ["Waiting", "} :x 1 {", "[1 2]", 1.5, True]:
            res, calls = self.call({"op": "taskSet", "id": 3, "status": bad})
            self.assertFalse(res["ok"], bad)
            self.assertEqual(calls, [], bad)

    def test_task_add_with_your_priority(self):
        res, calls = self.call({"op": "taskAdd", "text": "Think about it", "priority": 85})
        self.assertTrue(res["ok"], res)
        self.assertNotIn("--priority", calls[-2])
        self.assertEqual(calls[-1][4:], ["upsert", "block", "--id", "999", "--update-properties",
                                         "{:logseq.property/priority 85}"])

    def test_task_add_and_set(self):
        _, calls = self.call({"op": "taskAdd", "text": "Buy milk", "priority": "high"})
        self.assertEqual(calls[-2][4:10], ["upsert", "task", "--content", "Buy milk", "--status", "todo"])
        self.assertEqual(calls[-1][-1], "{:logseq.property/priority :logseq.property/priority.high}")
        _, calls = self.call({"op": "taskSet", "id": 3, "priority": ""})
        self.assertEqual(calls[-1][-1], "--no-priority")
        res, _ = self.call({"op": "taskSet", "id": 3, "priority": "extreme"})
        self.assertFalse(res["ok"])

    def test_edit_refuses_blocks_with_refs(self):
        res, calls = self.call({"op": "edit", "id": 7, "text": "new"})
        self.assertFalse(res["ok"])
        self.assertFalse(any(c[4:6] == ["upsert", "block"] for c in calls))
        res, calls = self.call({"op": "edit", "id": 8, "text": "new"})
        self.assertTrue(res["ok"], res)
        self.assertEqual(calls[-1][4:], ["upsert", "block", "--id", "8", "--content", "new"])

    def test_page_missing(self):
        res, _ = self.call({"op": "page", "name": "Missing"})
        self.assertTrue(res["ok"])
        self.assertTrue(res["data"]["missing"])

    # --- #tags in new entries ---------------------------------------------
    def test_append_with_new_tag_creates_it(self):
        res, calls = self.call({"op": "append", "text": "Lecture notes #University"})
        self.assertTrue(res["ok"], res)
        cmds = [c[4:] for c in calls if c[4:6] in (["upsert", "block"], ["upsert", "tag"])]
        self.assertEqual(cmds[0][:4], ["upsert", "block", "--blocks", "- Lecture notes #University"])
        self.assertEqual(cmds[1], ["upsert", "tag", "--name", "University"],
                         "tag name taken from the CLI's message, without its hint")
        self.assertEqual(cmds[2][:4], ["upsert", "block", "--blocks", "- Lecture notes #University"])
        self.assertEqual(len(cmds), 3)

    def test_append_with_existing_tag(self):
        res, calls = self.call({"op": "append", "text": "Buy #shopping stuff"})
        self.assertTrue(res["ok"], res)
        self.assertFalse(any(c[4:6] == ["upsert", "tag"] for c in calls))
        self.assertEqual(sum(c[4:6] == ["upsert", "block"] for c in calls), 1)

    def test_append_without_tags_keeps_plain_content(self):
        res, calls = self.call({"op": "append", "text": "Just a note"})
        self.assertIn("--content", calls[-1])
        self.assertNotIn("--blocks", calls[-1])

    def test_multi_word_and_several_new_tags(self):
        res, calls = self.call({"op": "append", "text": "Plan #[[Big Project]] for #Q4"})
        self.assertTrue(res["ok"], res)
        made = [c[-1] for c in calls if c[4:6] == ["upsert", "tag"]]
        self.assertEqual(made, ["Big Project", "Q4"])

    def test_multi_line_entry_stays_one_block(self):
        self.call({"op": "append", "text": "first line #work\nsecond line"})
        md = self.parsed[-1]["opts"]["blocks"]
        self.assertEqual(md, "- first line #work\n  second line")

    def test_tag_text_cannot_inject_options(self):
        self.call({"op": "append", "text": "--root-dir=/tmp/x #work"})
        seen = self.parsed[-1]["opts"]
        self.assertEqual(seen["blocks"], "- --root-dir=/tmp/x #work")
        self.assertNotIn("root-dir", seen)

    def test_tag_creation_cannot_loop(self):
        res, calls = self.call({"op": "append", "text": "x #Stubborn"}, mode="tagloop")
        self.assertFalse(res["ok"])
        self.assertEqual(sum(c[4:6] == ["upsert", "tag"] for c in calls), 1)

    def test_task_with_inline_tag(self):
        res, calls = self.call({"op": "taskAdd", "text": "Read chapter 3 #University",
                                "priority": "high"})
        self.assertTrue(res["ok"], res)
        self.assertFalse(any(c[4:6] == ["upsert", "task"] and "--content" in c for c in calls),
                         "the plain-text task path must not be used")
        convert = [c[4:] for c in calls if c[4:6] == ["upsert", "task"]]
        self.assertEqual(convert, [["upsert", "task", "--id", "999", "--status", "todo"]])
        self.assertEqual(calls[-1][-1], "{:logseq.property/priority :logseq.property/priority.high}")

    def test_task_with_inline_tag_and_filter_tag(self):
        res, calls = self.call({"op": "taskAdd", "text": "Milk #shopping", "tags": ["work"]})
        self.assertTrue(res["ok"], res)
        self.assertEqual(calls[-1][4:], ["upsert", "block", "--id", "999", "--update-tags", '["work"]'])

    def test_task_conversion_failure_is_reported(self):
        res, _ = self.call({"op": "taskAdd", "text": "x #work"}, mode="taskfail")
        self.assertFalse(res["ok"])
        self.assertIn("making it a task failed", res["error"])

    def test_remove_uses_block_subcommand(self):
        res, calls = self.call({"op": "remove", "id": 5})
        self.assertTrue(res["ok"], res)
        self.assertEqual(calls[-1][4:], ["remove", "block", "--id", "5"])

    def test_remove_rejects_non_int(self):
        res, calls = self.call({"op": "remove", "id": "5; rm -rf"})
        self.assertFalse(res["ok"])
        self.assertEqual(calls, [])

    def test_graphs_and_info(self):
        res, calls = self.call({"op": "graphs"})
        self.assertEqual(res["data"]["graphs"], ["work", "personal"])
        self.assertNotIn("--graph", calls[-1])
        res, _ = self.call({"op": "info"})
        self.assertEqual(res["data"]["graph"], "work")

    def test_garbage_output(self):
        res, _ = self.call({"op": "tasks"}, mode="garbage")
        self.assertFalse(res["ok"])
        self.assertIn("Segmentation fault", res["error"])

    def test_plain_json_argument(self):
        res, _ = self.call({"op": "graphs"}, encode=False)
        self.assertTrue(res["ok"])

    def test_setup_configured_graph(self):
        res, _ = self.call({"op": "setup"})
        self.assertEqual(res["data"]["problem"], None)
        self.assertEqual(res["data"]["current"], "work")

    def test_setup_uses_cli_current_graph(self):
        res, _ = self.call({"op": "setup"}, graph="")
        self.assertEqual((res["data"]["problem"], res["data"]["current"]), (None, "work"))

    def test_setup_picks_only_graph(self):
        res, _ = self.call({"op": "setup"}, graph="", mode="onegraph")
        self.assertEqual((res["data"]["problem"], res["data"]["current"]), (None, "solo"))

    def test_setup_asks_when_several_graphs(self):
        res, _ = self.call({"op": "setup"}, graph="", mode="nocurrent")
        self.assertEqual(res["data"]["problem"], "choose-graph")
        self.assertEqual(res["data"]["graphs"], ["work", "personal"])

    def test_setup_no_graphs(self):
        res, _ = self.call({"op": "setup"}, mode="nographs")
        self.assertEqual(res["data"]["problem"], "no-graphs")

    def test_setup_configured_graph_missing(self):
        res, _ = self.call({"op": "setup"}, graph="Cloud notes")
        self.assertEqual(res["data"]["problem"], "graph-missing")
        self.assertEqual(res["data"]["message"], "Cloud notes")

    def test_setup_no_cli(self):
        res, _ = self.call({"op": "setup"}, cli="/nonexistent/logseq")
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["problem"], "no-cli")

    def test_missing_repo_message_is_friendly(self):
        res, _ = self.call({"op": "tasks"}, graph="", mode="nocurrent")
        self.assertFalse(res["ok"])
        self.assertIn("No graph is selected", res["error"])

    def test_ping(self):
        res, calls = self.call({"op": "ping"})
        self.assertTrue(res["ok"])
        self.assertTrue(res["data"]["helper"].endswith("logseq_helper.py"))
        self.assertEqual(calls, [], "ping never touches Logseq")

    def test_log_created_even_for_bad_request(self):
        cache = tempfile.mkdtemp()
        env = dict(os.environ, XDG_CACHE_HOME=cache)
        out = subprocess.run([sys.executable, HELPER, "%7Bnot-json"], capture_output=True,
                             text=True, env=env)
        self.assertFalse(json.loads(out.stdout)["ok"])
        with open(os.path.join(cache, "logseq-db-widget", "helper.log")) as f:
            self.assertIn("invoked", f.read())

    # --- security: option injection -------------------------------------
    def test_note_text_cannot_inject_options(self):
        evil = "--root-dir=/tmp/evil"
        res, _ = self.call({"op": "append", "text": evil, "page": "--config=/tmp/evil.edn"})
        self.assertTrue(res["ok"], res)
        seen = self.parsed[-1]["opts"]  # as the real CLI parser sees it
        self.assertEqual(seen.get("content"), evil)
        self.assertEqual(seen.get("target-page"), "--config=/tmp/evil.edn")
        self.assertNotIn("root-dir", seen)
        self.assertNotIn("config", seen)
        self.assertEqual(seen.get("graph"), "work")

    def test_page_name_cannot_inject_options(self):
        self.call({"op": "page", "name": "--graph=someone-else"})
        seen = self.parsed[-1]["opts"]
        self.assertEqual(seen.get("page"), "--graph=someone-else")
        self.assertEqual(seen.get("graph"), "work")

    def test_lone_double_dash_is_a_value(self):
        self.call({"op": "append", "text": "--"})
        self.assertEqual(self.parsed[-1]["opts"].get("content"), "--")

    def test_join_value_flags(self):
        self.assertEqual(cli_module.join_value_flags(["show", "--page", "-x", "--linked-references", "false"]),
                         ["show", "--page=-x", "--linked-references=false"])
        self.assertEqual(cli_module.join_value_flags(["remove", "--id", 5]), ["remove", "--id=5"])

    # --- security: request transport and logging -------------------------
    def test_request_via_environment(self):
        req = json.dumps({"op": "ping", "reqId": 7})
        env = dict(os.environ, LOGSEQ_WIDGET_REQUEST=urllib.parse.quote(req, safe="-_."))
        out = subprocess.run([sys.executable, HELPER], capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(out.stdout)["reqId"], 7)

    def test_log_is_private_and_omits_error_text(self):
        cache = tempfile.mkdtemp()
        self.call({"op": "tasks"}, mode="garbage", env_extra={"XDG_CACHE_HOME": cache})
        self.call({"op": "page", "name": "Secret plans"}, mode="nocurrent",
                  env_extra={"XDG_CACHE_HOME": cache})
        root = os.path.join(cache, "logseq-db-widget")
        log = os.path.join(root, "helper.log")
        self.assertEqual(stat.S_IMODE(os.stat(log).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700)
        with open(log) as f:
            text = f.read()
        self.assertNotIn("Secret plans", text)
        self.assertNotIn("Segmentation", text)

    # --- background process maintenance ----------------------------------
    def maintain(self, server, sync="stopped", keep=False):
        res, calls = self.call({"op": "maintain", "backgroundSync": keep},
                               env_extra={"FAKE_SERVER": server, "FAKE_SYNC": sync})
        self.assertTrue(res["ok"], res)
        return res["data"], [c[-2:] for c in calls]

    def test_maintain_stops_idle_cli_process(self):
        data, cmds = self.maintain("cli", sync="stopped")
        self.assertEqual(data["action"], "stopped")
        self.assertIn(["server", "stop"], cmds)

    def test_reconnecting_sync_is_not_stopped(self):
        # "closed" = a sync client exists but is reconnecting (e.g. network drop).
        data, cmds = self.maintain("cli", sync="closed")
        self.assertEqual(data["reason"], "syncing")
        self.assertNotIn(["server", "stop"], cmds)
        self.setUp()
        data, cmds = self.maintain("cli", sync="closed", keep=True)
        self.assertEqual(data["action"], "login-renewed")
        self.assertEqual(cmds.count(["sync", "start"]), 1,
                         "only a login renewal; Logseq keeps the running session")
        self.assertNotIn(["server", "stop"], cmds)

    def test_unknown_sync_state_changes_nothing(self):
        for keep in (False, True):
            data, cmds = self.maintain("cli", sync="error", keep=keep)
            self.assertEqual(data["reason"], "state-unknown")
            self.assertNotIn(["server", "stop"], cmds)
            self.assertNotIn(["sync", "start"], cmds)

    def test_nothing_happens_while_desktop_is_running(self):
        proc = fake_proc(DESKTOP, DB_WORKER)
        for keep in (False, True):
            res, calls = self.call({"op": "maintain", "backgroundSync": keep},
                                   env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "stopped",
                                              "LOGSEQ_WIDGET_PROC": proc})
            self.assertEqual(res["data"]["reason"], "desktop-open")
            self.assertFalse(any(c[4:6] in (["server", "stop"], ["sync", "start"]) for c in calls))

    def test_desktop_detection(self):
        self.assertTrue(processes.desktop_running(fake_proc(DESKTOP)))
        self.assertTrue(processes.desktop_running(fake_proc((["/home/u/AppImages/Logseq.AppImage"], []))))
        self.assertTrue(processes.desktop_running(fake_proc((["/opt/Logseq/logseq"], []))))
        self.assertFalse(processes.desktop_running(fake_proc(DB_WORKER, RENDERER)))
        self.assertFalse(processes.desktop_running(fake_proc(
            (["/home/u/AppImages/logseq.appimage", "--appimage-extract"], []))))
        self.assertFalse(processes.desktop_running(fake_proc((["/usr/bin/python3", "logseq_helper.py"], []))))
        self.assertFalse(processes.desktop_running(EMPTY_PROC))
        # Arch/AUR style: system Electron running Logseq's app.asar.
        self.assertTrue(processes.desktop_running(fake_proc(
            (["/usr/lib/electron34/electron", "/usr/share/logseq/app.asar"], []))))
        self.assertFalse(processes.desktop_running(fake_proc(
            (["/usr/lib/electron34/electron", "/usr/share/code/app.asar"], []))),
            "another Electron app is not Logseq")
        self.assertFalse(processes.desktop_running(fake_proc(
            (["/usr/lib/electron34/electron", "/usr/share/logseq/app.asar"],
             ["ELECTRON_RUN_AS_NODE=1"]))), "a CLI run through system Electron")

    def test_maintain_finds_the_graph_itself(self):
        res, calls = self.call({"op": "maintain"}, graph="",
                               env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "stopped"})
        self.assertEqual(res["data"]["action"], "stopped", res)
        self.assertIn(["--graph", "work", "server", "stop"], [c[2:6] for c in calls])

    def test_background_sync_reports_its_error(self):
        res, _ = self.call({"op": "maintain", "backgroundSync": True},
                           env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "closed",
                                      "FAKE_SYNC_ERROR": "unauthorized"})
        self.assertEqual(res["data"].get("syncError"), "unauthorized")

    def test_encryption_password_error_is_explained(self):
        raw = ('{:code :decrypt-text-by-text-password :message "decrypt-text-by-text-password" '
               ':at 1793016717364 :data nil}')
        cache = tempfile.mkdtemp()
        res, _ = self.call({"op": "maintain", "backgroundSync": True},
                           env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "closed",
                                      "FAKE_SYNC_ERROR": raw, "XDG_CACHE_HOME": cache})
        text = res["data"]["syncError"]
        self.assertIn("earlier sign-in", text)
        self.assertIn("--set-e2ee-password", text)
        self.assertIn("(Logseq: decrypt-text-by-text-password)", text)
        with open(os.path.join(cache, "logseq-db-widget", "helper.log")) as f:
            log = f.read()
        self.assertIn("background sync error: decrypt-text-by-text-password", log)
        self.assertNotIn("1793016717364", log, "only the code is logged")

    def test_unknown_sync_error_codes_pass_through(self):
        self.assertEqual(sync_module.explain_sync_error('{:code :db-sync/new-thing :message "m"}'),
                         "Logseq reported db-sync/new-thing.")

    # --- data safety -----------------------------------------------------------
    def commands(self):
        """Command words of every CLI call, as the real parser sees them."""
        return [p["pos"] for p in self.parsed]

    def test_version_guard_blocks_before_touching_the_graph(self):
        # Logseq Desktop runs an older build than the CLI (AppImage replaced
        # while it was open). Any command that reaches the database would make
        # Logseq shut the app's process down, so none may run.
        env = {"LOGSEQ_WIDGET_PROC": fake_proc(DESKTOP), "FAKE_SERVER": "electron",
               "FAKE_SERVER_REV": "rev-OLD", "XDG_CACHE_HOME": tempfile.mkdtemp()}
        for op in ({"op": "journal"}, {"op": "append", "text": "x"}, {"op": "syncStatus"},
                   {"op": "tasks"}):
            res, _ = self.call(op, env_extra=env)
            self.assertFalse(res["ok"], op)
            self.assertEqual(res["code"], "version-mismatch", res)
            self.assertIn("Restart Logseq Desktop", res["error"])
            self.assertTrue(all(c in ([], ["server", "list"]) for c in self.commands()),
                            self.commands())
        res, _ = self.call({"op": "setup"}, env_extra=env)
        self.assertEqual(res["data"]["problem"], "error")
        self.assertIn("different Logseq version", res["data"]["message"])
        self.assertNotIn(["graph", "info"], self.commands())

    def test_version_guard_allows_matching_versions(self):
        env = {"LOGSEQ_WIDGET_PROC": fake_proc(DESKTOP), "FAKE_SERVER": "electron",
               "XDG_CACHE_HOME": tempfile.mkdtemp()}
        res, _ = self.call({"op": "journal"}, env_extra=env)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.commands()[:2], [[], ["server", "list"]])
        # ...and the answer is remembered briefly, so requests stay fast.
        res, _ = self.call({"op": "journal"}, env_extra=env)
        self.assertTrue(res["ok"], res)
        self.assertNotIn([], self.commands(), "no second --version within the cache time")

    def test_version_guard_only_matters_while_desktop_runs(self):
        # With the app closed, a mismatched CLI-started process is simply
        # replaced by Logseq, which is the normal upgrade path.
        res, _ = self.call({"op": "journal"},
                           env_extra={"FAKE_SERVER": "cli", "FAKE_SERVER_REV": "rev-OLD"})
        self.assertTrue(res["ok"], res)
        self.assertNotIn([], self.commands())

    def test_edit_refuses_to_overwrite_a_changed_block(self):
        res, calls = self.call({"op": "edit", "id": 8, "text": "mine", "expected": "older text"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "changed")
        self.assertFalse(any(c[4:6] == ["upsert", "block"] for c in calls))
        res, calls = self.call({"op": "edit", "id": 8, "text": "mine", "expected": "plain text"})
        self.assertTrue(res["ok"], res)

    def test_idle_stop_waits_for_other_requests(self):
        import fcntl
        cache = tempfile.mkdtemp()
        os.makedirs(os.path.join(cache, "logseq-db-widget"))
        with open(os.path.join(cache, "logseq-db-widget", "activity.lock"), "w") as held:
            fcntl.flock(held, fcntl.LOCK_SH)  # another widget instance mid-request
            res, calls = self.call({"op": "maintain"},
                                   env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "stopped",
                                              "XDG_CACHE_HOME": cache})
            self.assertEqual(res["data"]["reason"], "busy")
            self.assertFalse(any(c[-2:] == ["server", "stop"] for c in calls))
        res, calls = self.call({"op": "maintain"},
                               env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "stopped",
                                          "XDG_CACHE_HOME": cache})
        self.assertEqual(res["data"]["action"], "stopped")

    def make_graph(self, name, age_seconds):
        root = tempfile.mkdtemp()
        folder = os.path.join(root, name, "search")
        os.makedirs(folder)
        path = os.path.join(folder, "db.sqlite-wal")
        open(path, "w").close()
        then = time.time() - age_seconds
        os.utime(path, (then, then))
        return root

    def test_idle_stop_waits_while_the_database_is_busy(self):
        # Files written seconds ago: a search index build (or sync) is running.
        busy = self.make_graph("work", age_seconds=5)
        res, calls = self.call({"op": "maintain"},
                               env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "stopped",
                                          "LOGSEQ_WIDGET_GRAPHS": busy})
        self.assertEqual(res["data"]["reason"], "graph-busy")
        self.assertFalse(any(c[-2:] == ["server", "stop"] for c in calls))
        quiet = self.make_graph("work", age_seconds=600)
        res, calls = self.call({"op": "maintain"},
                               env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "stopped",
                                          "LOGSEQ_WIDGET_GRAPHS": quiet})
        self.assertEqual(res["data"]["action"], "stopped")

    def test_busy_check_covers_graphs_stored_under_another_name(self):
        # Our graph's folder isn't found by name: every graph is checked.
        os.environ["LOGSEQ_WIDGET_GRAPHS"] = self.make_graph("encoded%20name", age_seconds=5)
        try:
            self.assertTrue(safeguards.graph_recently_written("my graph"))
            os.environ["LOGSEQ_WIDGET_GRAPHS"] = self.make_graph("encoded%20name", age_seconds=600)
            self.assertFalse(safeguards.graph_recently_written("my graph"))
        finally:
            del os.environ["LOGSEQ_WIDGET_GRAPHS"]

    def test_folder_in_use(self):
        folder = "/home/u/.cache/logseq-db-widget/appimage-old"
        running = ([folder + "/squashfs-root/logseq", folder + "/squashfs-root/x/db-worker-node.js"],
                   ["ELECTRON_RUN_AS_NODE=1"])
        self.assertTrue(processes.folder_in_use(folder, fake_proc(running)))
        self.assertFalse(processes.folder_in_use(folder + "-other", fake_proc(running)))
        self.assertFalse(processes.folder_in_use(folder, EMPTY_PROC))

    # --- where your changes are ----------------------------------------------
    def status(self, **env):
        res, calls = self.call({"op": "syncStatus"}, env_extra=env)
        self.assertTrue(res["ok"], res)
        return res["data"], [c[-2:] for c in calls]

    def test_status_synced_to_cloud(self):
        data, _ = self.status(FAKE_SERVER="electron", FAKE_SYNC="open")
        self.assertEqual(data["state"], "cloud")

    def test_status_uploading(self):
        data, _ = self.status(FAKE_SERVER="cli", FAKE_SYNC="open", FAKE_PENDING="2",
                              FAKE_PENDING_ASSET="1")
        self.assertEqual((data["state"], data["pending"]), ("uploading", 3))
        self.assertIn("3 changes waiting to upload", data["detail"])

    def test_status_offline_and_sync_off_are_local(self):
        data, _ = self.status(FAKE_SERVER="cli", FAKE_SYNC="closed", FAKE_PENDING="1")
        self.assertEqual(data["state"], "local")
        self.assertIn("offline", data["detail"])
        self.assertIn("1 change waiting", data["detail"])
        data, _ = self.status(FAKE_SERVER="cli", FAKE_SYNC="stopped")
        self.assertEqual(data["state"], "local")
        self.assertIn("isn't running", data["detail"])

    def test_status_sync_problem_is_local_with_reason(self):
        data, _ = self.status(FAKE_SERVER="cli", FAKE_SYNC="open",
                              FAKE_SYNC_ERROR="{:code :decrypt-text-by-text-password}")
        self.assertEqual(data["state"], "local")
        self.assertIn("can't unlock your saved encryption password", data["detail"])

    def test_status_graph_that_does_not_sync(self):
        data, _ = self.status(FAKE_SERVER="cli", FAKE_SYNC="inactive", FAKE_GRAPH_ID="none")
        self.assertEqual(data["state"], "local-only")

    def test_status_never_starts_a_database_process(self):
        data, cmds = self.status(FAKE_SERVER="none")
        self.assertEqual(data["state"], "local")
        self.assertEqual(cmds, [["server", "list"]], "only looks; no sync status, no start")

    def test_status_reasons(self):
        for env, reason in (({"FAKE_SERVER": "none"}, "no-process"),
                            ({"FAKE_SERVER": "cli", "FAKE_SYNC": "stopped"}, "sync-off"),
                            ({"FAKE_SERVER": "cli", "FAKE_SYNC": "closed"}, "offline"),
                            ({"FAKE_SERVER": "cli", "FAKE_SYNC": "open"}, "synced")):
            self.setUp()
            data, _ = self.status(**env)
            self.assertEqual(data["reason"], reason, env)

    def test_running_session_gets_a_fresh_login(self):
        # Logseq never renews the token of a CLI-started session; the widget
        # hands it a fresh one on every check, with time for a reconnect.
        res, calls = self.call({"op": "maintain", "backgroundSync": True},
                               env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "open"})
        self.assertEqual(res["data"]["action"], "login-renewed")
        start = [p for p in self.parsed if p["pos"] == ["sync", "start"]]
        self.assertEqual(len(start), 1)
        self.assertEqual(start[0]["opts"].get("timeout-ms"), "45000")

    def test_stuck_session_recovers(self):
        # A session stuck reconnecting with an expired login (state "closed").
        res, _ = self.call({"op": "maintain", "backgroundSync": True},
                           env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "closed"})
        self.assertEqual(res["data"]["action"], "login-renewed")
        status, _ = self.status(FAKE_SERVER="cli", FAKE_SYNC="closed")
        self.assertEqual(status["state"], "cloud", "reconnected with the fresh login")

    def test_timeout_while_reconnecting_is_not_an_error(self):
        res, _ = self.call({"op": "maintain", "backgroundSync": True},
                           env_extra={"FAKE_SERVER": "cli", "FAKE_SYNC": "closed",
                                      "FAKE_SYNC_START": "timeout"})
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["data"]["action"], res["data"]["reason"]),
                         ("login-renewed", "reconnecting"))
        self.assertNotIn("syncError", res["data"])

    def test_skipped_sync_start_is_reported(self):
        res, _ = self.call({"op": "maintain", "backgroundSync": True},
                           env_extra={"FAKE_SERVER": "none", "FAKE_SYNC_START": "timeout",
                                      "FAKE_SYNC": "stopped"})
        data = res["data"]
        self.assertEqual(data["action"], "sync-skipped")
        self.assertIn("start-skipped", data["syncError"])
        self.assertIn("~/logseq/graphs/work/db-worker-node-", data["syncError"])
        self.setUp()
        res, _ = self.call({"op": "maintain", "backgroundSync": True},
                           env_extra={"FAKE_SERVER": "none", "FAKE_SYNC_START": "timeout",
                                      "FAKE_SYNC": "inactive"})
        self.assertIn("no sync server is configured", res["data"]["syncError"])

    def test_decisions_are_logged(self):
        cache = tempfile.mkdtemp()
        self.call({"op": "maintain", "backgroundSync": True},
                  env_extra={"FAKE_SERVER": "none", "XDG_CACHE_HOME": cache})
        self.call({"op": "syncStatus"}, env_extra={"XDG_CACHE_HOME": cache})
        with open(os.path.join(cache, "logseq-db-widget", "helper.log")) as f:
            log = f.read()
        self.assertIn("maintain: decision: sync-started (background sync on)", log)
        self.assertIn("syncStatus: decision: cloud, synced", log,
                      "the sync started by maintain is seen by the next status check")

    def test_status_unknown_when_unreadable(self):
        data, _ = self.status(FAKE_SERVER="cli", FAKE_SYNC="error")
        self.assertEqual(data["state"], "unknown")

    def test_maintain_never_touches_desktop_process(self):
        data, cmds = self.maintain("electron")
        self.assertEqual(data["action"], "none")
        self.assertNotIn(["server", "stop"], cmds)
        data, cmds = self.maintain("electron", keep=True)
        self.assertNotIn(["sync", "start"], cmds)

    def test_maintain_keeps_manual_sync(self):
        data, cmds = self.maintain("cli", sync="open")
        self.assertEqual(data["reason"], "syncing")
        self.assertNotIn(["server", "stop"], cmds)

    def test_maintain_nothing_running(self):
        data, cmds = self.maintain("none")
        self.assertEqual(data["reason"], "not-running")
        self.assertEqual(cmds, [["server", "list"]], "must not start a process just to check")

    def test_background_sync_starts_and_restarts(self):
        data, cmds = self.maintain("none", keep=True)
        self.assertEqual(data["action"], "sync-started")
        self.setUp()  # each step starts from a clean fake
        data, cmds = self.maintain("cli", sync="stopped", keep=True)
        self.assertEqual(data["action"], "sync-started")
        self.assertNotIn(["server", "stop"], cmds)
        self.setUp()
        data, cmds = self.maintain("cli", sync="open", keep=True)
        self.assertEqual(data["action"], "login-renewed")

    def test_date_formats(self):
        d = datetime.date(2026, 10, 7)  # a Wednesday
        cases = {
            "MMM do, yyyy": "Oct 7th, 2026",
            "MMMM do, yyyy": "October 7th, 2026",
            "do MMM yyyy": "7th Oct 2026",
            "E, dd-MM-yyyy": "Wed, 07-10-2026",
            "EEEE, dd.MM.yyyy": "Wednesday, 07.10.2026",
            "yyyy-MM-dd EEE": "2026-10-07 Wed",
            "yyyyMMdd": "20261007",
            "yyyy年MM月dd日": "2026年10月07日",
            "MM_dd_yyyy": "10_07_2026",
        }
        for fmt, want in cases.items():
            self.assertEqual(journal.format_journal_title(fmt, d), want, fmt)
        self.assertEqual(journal.ordinal(11), "11th")
        self.assertEqual(journal.ordinal(22), "22nd")
        self.assertEqual(journal.ordinal(103), "103rd")


# Shaped like electron-builder 26's AppRun, which can inject --no-sandbox.
FAKE_APPRUN = """#!/usr/bin/env bash
BIN="$APPDIR/logseq"
exec "$BIN" --no-sandbox "$@"
"""

# Stands in for Electron: in node mode it runs the script it is given, and
# like Node it rejects Chromium flags such as --no-sandbox.
FAKE_ELECTRON = """#!/bin/sh
[ "$ELECTRON_RUN_AS_NODE" = "1" ] || { echo "ELECTRON_RUN_AS_NODE not set" >&2; exit 3; }
[ "$1" = "--no-sandbox" ] && { echo "bad option: --no-sandbox" >&2; exit 9; }
exec python3 "$@"
"""

# An AppRun without a BIN= line, to exercise the fallback.
FAKE_APPRUN_PLAIN = """#!/bin/sh
exec "$(dirname "$0")/logseq" "$@"
"""

FAKE_APPIMAGE = """#!/bin/sh
if [ "$1" = "--appimage-extract" ]; then
  echo extract >> "$FAKE_EXTRACT_LOG"
  mkdir -p squashfs-root/resources/app.asar/js
  cp "$FAKE_SRC/AppRun" squashfs-root/AppRun
  cp "$FAKE_SRC/electron" squashfs-root/logseq
  chmod +x squashfs-root/AppRun squashfs-root/logseq
  cp "$FAKE_SRC/cli.py" squashfs-root/resources/app.asar/js/logseq-cli.js
  exit 0
fi
echo "this fake AppImage only supports --appimage-extract" >&2
exit 1
"""


class AppImageTest(unittest.TestCase):
    """The AppImage install: launcher points into a mount that no longer exists."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.src = os.path.join(self.home, "src")
        os.makedirs(self.src)
        for name, body in (("AppRun", FAKE_APPRUN), ("cli.py", FAKE_CLI),
                           ("electron", FAKE_ELECTRON)):
            with open(os.path.join(self.src, name), "w") as f:
                f.write(body)
        self.appimages = os.path.join(self.home, "AppImages")
        os.makedirs(self.appimages)
        self.appimage = os.path.join(self.appimages, "logseq.appimage")
        self.write_appimage(self.appimage)
        self.log = os.path.join(self.home, "cli.log")
        self.extract_log = os.path.join(self.home, "extract.log")
        open(self.extract_log, "w").close()
        # Like a real install: Logseq writes a launcher with a stale mount path.
        self.write_launcher(self.appimage,
                            "/tmp/.mount_logseqAkifll/resources/app.asar/js/logseq-cli.js")

    def write_appimage(self, path):
        with open(path, "w") as f:
            f.write(FAKE_APPIMAGE)
        os.chmod(path, 0o755)

    def write_launcher(self, exe, script):
        bindir = os.path.join(self.home, ".local", "bin")
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, "logseq")
        with open(path, "w") as f:
            f.write('#!/usr/bin/env sh\n# logseq-cli-managed\nset -eu\n'
                    'ELECTRON_RUN_AS_NODE=1 exec "%s" "%s" "$@"\n' % (exe, script))
        os.chmod(path, 0o755)
        return path

    def call(self, req, proc=None):
        open(self.log, "w").close()
        env = {
            "LOGSEQ_WIDGET_PROC": proc or EMPTY_PROC,
            "HOME": self.home, "PATH": "/usr/bin:/bin",
            "XDG_CACHE_HOME": os.path.join(self.home, ".cache"),
            "FAKE_LOG": self.log, "FAKE_MODE": "normal",
            "FAKE_EXTRACT_LOG": self.extract_log, "FAKE_SRC": self.src,
        }
        req = dict({"cli": "", "graph": "", "reqId": 1}, **req)
        out = subprocess.run([sys.executable, HELPER, json.dumps(req)],
                             capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def extractions(self):
        with open(self.extract_log) as f:
            return len(f.read().split())

    def cache_dirs(self):
        root = os.path.join(self.home, ".cache", "logseq-db-widget")
        return sorted(n for n in os.listdir(root) if n.startswith("appimage-"))

    def test_stale_launcher_uses_unpacked_appimage(self):
        self.write_launcher(self.appimage,
                            "/tmp/.mount_logseqAkifll/resources/app.asar/js/logseq-cli.js")
        res = self.call({"op": "setup"})
        self.assertTrue(res["ok"], res)
        self.assertIsNone(res["data"]["problem"], res["data"])
        self.assertEqual(res["data"]["current"], "work")
        self.assertTrue(res["data"]["cliPath"].startswith("appimage:"))
        res = self.call({"op": "tasks", "graph": "work"})
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.extractions(), 1, "unpacks once, then reuses")

    def test_launcher_with_tilde_path(self):
        self.write_launcher("~/AppImages/logseq.appimage",
                            "/tmp/.mount_logseqXYZ/resources/app.asar/js/logseq-cli.js")
        res = self.call({"op": "setup"})
        self.assertIsNone(res["data"]["problem"], res["data"])

    def test_found_appimage_is_suggested_not_run(self):
        os.remove(os.path.join(self.home, ".local", "bin", "logseq"))
        res = self.call({"op": "setup"})
        self.assertEqual(res["data"]["problem"], "no-cli")
        self.assertIn(self.appimage, res["data"]["message"])
        self.assertEqual(self.extractions(), 0, "a merely found AppImage must not be executed")

    def test_configured_appimage(self):
        # No launcher (Logseq Desktop never started here): the setting decides.
        os.remove(os.path.join(self.home, ".local", "bin", "logseq"))
        other = os.path.join(self.home, "elsewhere", "Logseq-DB.AppImage")
        os.makedirs(os.path.dirname(other))
        self.write_appimage(other)
        res = self.call({"op": "setup", "appImage": other})
        self.assertIsNone(res["data"]["problem"], res["data"])
        self.assertIn("Logseq-DB.AppImage", res["data"]["cliPath"])

    def test_configured_appimage_must_match_the_one_desktop_runs(self):
        # The settings name one file; Logseq Desktop's launcher names another.
        # Two Logseq versions would take turns on the graph, so: refuse, and
        # never run the configured file.
        other = os.path.join(self.home, "elsewhere", "Logseq-old.AppImage")
        os.makedirs(os.path.dirname(other))
        self.write_appimage(other)
        res = self.call({"op": "setup", "appImage": other})
        self.assertIsNotNone(res["data"]["problem"])
        self.assertIn("two copies of Logseq", res["data"]["message"])
        self.assertEqual(self.extractions(), 0, "the other copy must not be run")
        res = self.call({"op": "journal", "appImage": other, "graph": "work"})
        self.assertEqual(res["code"], "appimage-conflict")
        # The same file under another name (a symlink) is not a conflict.
        link = os.path.join(self.home, "elsewhere", "logseq-link.AppImage")
        os.symlink(self.appimage, link)
        res = self.call({"op": "setup", "appImage": link})
        self.assertIsNone(res["data"]["problem"], res["data"])

    def test_updated_appimage_is_unpacked_again(self):
        self.call({"op": "setup"})
        first = self.cache_dirs()
        st = os.stat(self.appimage)
        os.utime(self.appimage, (st.st_atime, st.st_mtime + 100))
        res = self.call({"op": "setup"})
        self.assertIsNone(res["data"]["problem"], res["data"])
        self.assertEqual(self.extractions(), 2)
        second = self.cache_dirs()
        self.assertEqual(len(second), 1, "old version removed")
        self.assertNotEqual(first, second)

    def test_old_copy_still_in_use_is_kept(self):
        self.call({"op": "setup"})
        (first,) = self.cache_dirs()
        old = os.path.join(self.home, ".cache", "logseq-db-widget", first)
        st = os.stat(self.appimage)
        os.utime(self.appimage, (st.st_atime, st.st_mtime + 100))  # Logseq was updated
        # A database process started before the update still runs from the old copy.
        running = fake_proc(([old + "/squashfs-root/logseq", old + "/squashfs-root/db-worker-node.js"],
                             ["ELECTRON_RUN_AS_NODE=1"]))
        self.call({"op": "setup"}, proc=running)
        self.assertEqual(len(self.cache_dirs()), 2, "the copy in use must not be deleted")
        self.assertTrue(os.path.isdir(old))
        os.utime(self.appimage, (st.st_atime, st.st_mtime + 200))
        self.call({"op": "setup"})                               # nothing uses them now
        self.assertEqual(len(self.cache_dirs()), 1)

    def test_package_install_launcher_used_directly(self):
        cli = os.path.join(self.home, "opt", "logseq-cli.js")
        os.makedirs(os.path.dirname(cli))
        with open(cli, "w") as f:
            f.write(FAKE_CLI)
        os.chmod(cli, 0o755)
        # Simulate a deb install: the exe is a normal binary and the script exists.
        exe = os.path.join(self.home, "opt", "fake-electron")
        with open(exe, "w") as f:
            f.write('#!/bin/sh\nexec python3 "$@"\n')
        os.chmod(exe, 0o755)
        os.remove(self.appimage)
        self.write_launcher(exe, cli)
        res = self.call({"op": "setup"})
        self.assertIsNone(res["data"]["problem"], res["data"])
        self.assertTrue(res["data"]["cliPath"].endswith("/.local/bin/logseq"))
        self.assertEqual(self.extractions(), 0)

    def test_nothing_found(self):
        os.remove(self.appimage)
        res = self.call({"op": "setup"})
        self.assertEqual(res["data"]["problem"], "no-cli")
        self.assertIn("AppImage", res["data"]["message"])

    def test_runs_electron_directly_not_apprun(self):
        # The fake AppRun adds --no-sandbox, which the fake Electron rejects.
        res = self.call({"op": "tasks", "graph": "work"})
        self.assertTrue(res["ok"], res)

    def test_apprun_fallback(self):
        with open(os.path.join(self.src, "AppRun"), "w") as f:
            f.write(FAKE_APPRUN_PLAIN)
        res = self.call({"op": "tasks", "graph": "work"})
        self.assertTrue(res["ok"], res)

    def test_prepare_step(self):
        res = self.call({"op": "prepare"})
        self.assertIsNone(res["data"]["problem"], res["data"])
        self.assertEqual(self.extractions(), 1)
        os.remove(self.appimage)
        res = self.call({"op": "prepare"})
        self.assertEqual(res["data"]["problem"], "no-cli")

    def test_log_records_steps_but_not_note_text(self):
        self.call({"op": "prepare"})
        self.call({"op": "append", "graph": "work", "text": "my secret diary entry",
                   "page": "Private page"})
        with open(os.path.join(self.home, ".cache", "logseq-db-widget", "helper.log")) as f:
            text = f.read()
        self.assertIn("unpacking", text)
        self.assertIn("unpacked in", text)
        self.assertIn("run: ", text)
        self.assertIn("exit 0 after", text)
        self.assertIn("append: done", text)
        self.assertNotIn("secret diary", text)
        self.assertNotIn("Private page", text)

    def test_broken_appimage(self):
        with open(self.appimage, "w") as f:
            f.write("#!/bin/sh\necho 'not an appimage' >&2\nexit 2\n")
        res = self.call({"op": "setup"})
        self.assertEqual(res["data"]["problem"], "no-cli")
        self.assertIn("not an appimage", res["data"]["message"])
        self.assertEqual(self.cache_dirs(), [], "no half-unpacked copy left behind")


if __name__ == "__main__":
    unittest.main(verbosity=2)
