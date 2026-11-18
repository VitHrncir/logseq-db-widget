#!/usr/bin/env python3
"""
logseq_helper.py: bridge between the Logseq DB Plasma widget and the official
`logseq` CLI that ships with Logseq Desktop (DB version).

The widget runs:   python3 logseq_helper.py <percent-encoded JSON request>
and always receives exactly one JSON object on stdout:

    {"ok": true,  "reqId": <request id>, "data": ...}
    {"ok": false, "reqId": <request id>, "error": "human readable message"}

The CLI is always called with an argument list (never through a shell), so
text typed into the widget cannot be interpreted as shell syntax.

For manual testing you can pass plain JSON:

    python3 logseq_helper.py '{"op": "tasks"}'
    python3 logseq_helper.py '{"op": "journal"}'
    python3 logseq_helper.py '{"op": "page", "name": "Projects"}'
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

CLI_TIMEOUT_SECONDS = 120  # the first call may have to start db-worker-node and load the graph

UUID_REF_RE = re.compile(
    r"\[\[[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\]\]"
)

STATUS_PREFIX = "logseq.property/status."
PRIORITY_PREFIX = "logseq.property/priority."

# Used if the graph's status choices cannot be read. Mirrors the built-in
# closed values in deps/db/src/logseq/db/frontend/property.cljs.
FALLBACK_STATUSES = [
    {"ident": STATUS_PREFIX + "backlog", "title": "Backlog", "checkbox": None},
    {"ident": STATUS_PREFIX + "todo", "title": "Todo", "checkbox": False},
    {"ident": STATUS_PREFIX + "doing", "title": "Doing", "checkbox": None},
    {"ident": STATUS_PREFIX + "in-review", "title": "In Review", "checkbox": None},
    {"ident": STATUS_PREFIX + "done", "title": "Done", "checkbox": True},
    {"ident": STATUS_PREFIX + "canceled", "title": "Canceled", "checkbox": None},
]
CLOSED_STATUSES = {STATUS_PREFIX + "done", STATUS_PREFIX + "canceled"}
STATUS_SORT = {
    STATUS_PREFIX + "doing": 0,
    STATUS_PREFIX + "in-review": 1,
    STATUS_PREFIX + "todo": 2,
    STATUS_PREFIX + "backlog": 3,
    STATUS_PREFIX + "done": 8,
    STATUS_PREFIX + "canceled": 9,
}
PRIORITY_SORT = {
    PRIORITY_PREFIX + "urgent": 0,
    PRIORITY_PREFIX + "high": 1,
    PRIORITY_PREFIX + "medium": 2,
    PRIORITY_PREFIX + "low": 3,
}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}

DEFAULT_JOURNAL_FORMAT = "MMM do, yyyy"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday"]


LOG_MAX_BYTES = 512 * 1024
_log_op = "-"


def log(message):
    """Append a line to ~/.cache/logseq-db-widget/helper.log. Never logs note text."""
    try:
        root = ensure_private_dir(cache_root())
        path = os.path.join(root, "helper.log")
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Readable by you only.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s [%d] %s: %s\n" % (stamp, os.getpid(), _log_op, message))
    except Exception:
        pass


# CLI arguments that carry user text; their values are not logged.
PRIVATE_ARGS = {"--content", "--query", "--inputs", "--page", "--target-page", "--blocks",
                "--update-tags"}

# Options that take a value. The CLI treats any value starting with "-" as a
# new option, so a page named "--root-dir=/x" would otherwise inject an
# option. In the "--flag=value" form everything after the first "=" is the
# value, whatever it starts with.
VALUE_FLAGS = {"--output", "--graph", "--timeout-ms", "--content", "--page", "--target-page", "--target-id",
               "--id", "--status", "--priority", "--update-tags", "--query", "--inputs",
               "--linked-references"}


def join_value_flags(args):
    out, i = [], 0
    args = [str(a) for a in args]
    while i < len(args):
        if args[i] in VALUE_FLAGS and i + 1 < len(args):
            out.append(args[i] + "=" + args[i + 1])
            i += 2
        else:
            if args[i] in VALUE_FLAGS:
                raise HelperError("Internal error: %s has no value." % args[i])
            out.append(args[i])
            i += 1
    return out


def describe_args(args):
    out = []
    for a in args:
        a = str(a)
        flag = a.split("=", 1)[0]
        out.append(flag + "=<...>" if "=" in a and flag in PRIVATE_ARGS else a)
    return " ".join(out)


class HelperError(Exception):
    """An error whose message is shown to the user as-is."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# CLI plumbing
# --------------------------------------------------------------------------

class CliCommand:
    """How to start the logseq CLI: an argv prefix plus extra environment."""

    def __init__(self, argv, env=None, source=""):
        self.argv = list(argv)
        self.env = dict(env or {})
        self.source = source


LAUNCHER_EXEC_RE = re.compile(r'exec\s+"([^"]+)"\s+"([^"]+)"')
APPIMAGE_MOUNT_RE = re.compile(r"^/tmp/\.mount_[^/]+/")
DEFAULT_CLI_SCRIPT = "resources/app.asar/js/logseq-cli.js"
APPIMAGE_SEARCH_DIRS = ["~/AppImages", "~/Applications", "~/.local/bin", "~/bin",
                        "~/Downloads", "/opt", "/opt/appimages"]
EXTRACT_TIMEOUT_SECONDS = 600


def default_launcher():
    for candidate in (os.path.expanduser("~/.local/bin/logseq"), shutil.which("logseq")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def parse_launcher(path):
    """Return (exe, script) from the launcher Logseq Desktop writes, if it is one."""
    try:
        with open(path, "r", errors="replace") as f:
            text = f.read(4096)
    except OSError:
        return None, None
    if "logseq-cli-managed" not in text:
        return None, None
    match = LAUNCHER_EXEC_RE.search(text)
    if not match:
        return None, None
    return os.path.expanduser(match.group(1)), match.group(2)


def is_appimage(path):
    if not path or not os.path.isfile(path):
        return False
    if path.lower().endswith(".appimage"):
        return True
    try:
        with open(path, "rb") as f:
            header = f.read(11)
        return header[8:11] in (b"AI\x01", b"AI\x02")
    except OSError:
        return False


def find_appimage():
    found = []
    for directory in APPIMAGE_SEARCH_DIRS:
        directory = os.path.expanduser(directory)
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            lower = name.lower()
            if "logseq" in lower and lower.endswith(".appimage"):
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    found.append(path)
    if not found:
        return None
    return max(found, key=lambda p: os.stat(p).st_mtime)


def ensure_private_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def cache_root():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "logseq-db-widget")


def appimage_key(path):
    st = os.stat(path)
    import hashlib
    raw = "%s|%d|%d" % (os.path.realpath(path), st.st_size, int(st.st_mtime))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def extract_appimage(appimage):
    """Unpack the AppImage once per version and return the unpacked root.

    Running the CLI through the AppImage itself is fragile: its files live in
    a temporary mount that disappears when the command exits, but the CLI
    starts a long-running database process from those same files. An
    unpacked copy has permanent paths and is the identical Logseq build.
    """
    root = cache_root()
    key = appimage_key(appimage)
    target = os.path.join(root, "appimage-" + key)
    unpacked = os.path.join(target, "squashfs-root")
    marker = os.path.join(target, ".complete")
    if os.path.exists(marker):
        return unpacked

    ensure_private_dir(root)
    import fcntl
    with open(os.path.join(root, ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if os.path.exists(marker):  # another helper finished it meanwhile
            return unpacked
        work = target + ".partial"
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        if not os.access(appimage, os.X_OK):
            raise HelperError("The Logseq AppImage is not executable: " + appimage)
        env = dict(os.environ)
        env.pop("ELECTRON_RUN_AS_NODE", None)
        log("unpacking %s into %s" % (appimage, target))
        started = time.time()
        try:
            proc = subprocess.run([appimage, "--appimage-extract"], cwd=work, env=env,
                                  capture_output=True, text=True,
                                  timeout=EXTRACT_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            log("unpack timed out after %ds" % EXTRACT_TIMEOUT_SECONDS)
            shutil.rmtree(work, ignore_errors=True)
            raise HelperError("Unpacking the Logseq AppImage timed out.")
        except OSError as exc:
            shutil.rmtree(work, ignore_errors=True)
            raise HelperError("Could not unpack the Logseq AppImage: %s" % exc)
        if proc.returncode != 0 or not os.path.isdir(os.path.join(work, "squashfs-root")):
            log("unpack failed after %.1fs: exit %d" % (time.time() - started, proc.returncode))
            shutil.rmtree(work, ignore_errors=True)
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise HelperError("Could not unpack the Logseq AppImage%s"
                              % (": " + detail[-1] if detail else "."))
        log("unpacked in %.1fs (exit %d)" % (time.time() - started, proc.returncode))
        shutil.rmtree(target, ignore_errors=True)
        os.rename(work, target)
        with open(marker, "w") as f:
            f.write(appimage + "\n")
        # Drop copies unpacked from older Logseq versions, unless a process
        # (a database process started before the update) still runs from one:
        # deleting its files underneath it could crash it mid-work.
        for name in os.listdir(root):
            old = os.path.join(root, name)
            if name.startswith("appimage-") and name != "appimage-" + key \
                    and not name.endswith(".partial"):
                if folder_in_use(old):
                    log("keeping %s: still in use" % name)
                else:
                    shutil.rmtree(old, ignore_errors=True)
    return unpacked


def my_processes(proc=None):
    """(argv, environ) of every process of this user; argv and environ as bytes lists."""
    proc = proc or os.environ.get("LOGSEQ_WIDGET_PROC", "/proc")
    uid = os.getuid()
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return
    for pid in pids:
        base = os.path.join(proc, pid)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "cmdline"), "rb") as f:
                argv = [a for a in f.read().split(b"\0") if a]
            with open(os.path.join(base, "environ"), "rb") as f:
                environ = f.read().split(b"\0")
        except OSError:
            continue
        if argv:
            yield argv, environ


def folder_in_use(folder, proc=None):
    """True if one of this user's processes was started from inside folder."""
    prefix = os.path.join(folder, "").encode()
    for argv, _environ in my_processes(proc):
        if any(a.startswith(prefix) for a in argv[:3]):
            return True
    return False


def appimage_command(appimage, launcher_script=None):
    unpacked = extract_appimage(appimage)
    rel = DEFAULT_CLI_SCRIPT
    if launcher_script and APPIMAGE_MOUNT_RE.match(launcher_script):
        rel = APPIMAGE_MOUNT_RE.sub("", launcher_script)
    script = os.path.join(unpacked, rel)
    asar = script.split(".asar", 1)[0] + ".asar" if ".asar" in script else script
    if not os.path.exists(asar):
        raise HelperError("This Logseq AppImage does not contain the command line tool "
                          "(%s). Is it the DB version of Logseq?" % rel)
    exe = electron_binary(unpacked)
    lib = os.path.join(unpacked, "usr", "lib")
    env = {"ELECTRON_RUN_AS_NODE": "1", "APPDIR": unpacked}
    if os.path.isdir(lib):
        env["LD_LIBRARY_PATH"] = lib + (":" + os.environ["LD_LIBRARY_PATH"]
                                        if os.environ.get("LD_LIBRARY_PATH") else "")
    return CliCommand([exe, script], env, source="appimage:" + appimage)


APPRUN_BIN_RE = re.compile(r'BIN="\$APPDIR/([^"/]+)"')


def electron_binary(unpacked):
    """The Electron executable inside an unpacked AppImage.

    AppRun is skipped on purpose: on systems without unprivileged user
    namespaces it adds --no-sandbox, a Chromium flag that has no place on a
    Node-mode command line.
    """
    apprun = os.path.join(unpacked, "AppRun")
    try:
        with open(apprun, "r", errors="replace") as f:
            match = APPRUN_BIN_RE.search(f.read(65536))
    except OSError:
        match = None
    if match:
        exe = os.path.join(unpacked, match.group(1))
        if os.access(exe, os.X_OK):
            return exe
    if os.access(apprun, os.X_OK):
        log("no Electron binary named in AppRun; falling back to AppRun")
        return apprun
    raise HelperError("Could not find Logseq's program inside the unpacked AppImage.")


def find_cli(configured, configured_appimage=None):
    """Work out how to run the logseq CLI on this machine."""
    if configured:
        path = os.path.expanduser(configured)
        if is_appimage(path):
            return appimage_command(path)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return CliCommand([path], source=path)
        raise HelperError("The configured logseq CLI path is not an executable file: " + path)

    launcher = default_launcher()
    exe, script = parse_launcher(launcher) if launcher else (None, None)

    if configured_appimage:
        path = os.path.expanduser(configured_appimage)
        if not is_appimage(path):
            raise HelperError("The configured Logseq AppImage was not found: " + path)
        # Logseq Desktop rewrites its launcher at every start, naming the
        # AppImage it runs from. If that is a different file, the widget
        # would run another Logseq version against the same graph whenever
        # the app is closed: two versions taking turns on one database and
        # one search index, each expecting its own format.
        if is_appimage(exe) and os.path.realpath(exe) != os.path.realpath(path):
            raise HelperError(
                "The widget is set to use %s, but Logseq Desktop last ran from %s. Using "
                "two copies of Logseq on one graph can break its search index and sync. "
                "Clear the AppImage path in the widget settings to follow Logseq Desktop "
                "automatically, or set it to the file you actually run."
                % (path, exe), "appimage-conflict")
        return appimage_command(path)

    if is_appimage(exe):
        return appimage_command(exe, script)
    if launcher and (script is None or os.path.exists(script)):
        # Package installs (deb, rpm, tarball) have stable paths.
        return CliCommand([launcher], source=launcher)

    # A found AppImage is only suggested, never run: unpacking an AppImage
    # executes it, and a file can land in ~/Downloads without your intent.
    found = find_appimage()
    hint = (" Found %s; to use it, set it as the Logseq AppImage in the widget settings." % found
            if found else "")
    raise HelperError(
        "Could not find Logseq. Start Logseq Desktop (DB version) once so it installs "
        "~/.local/bin/logseq, or set the path to your Logseq AppImage in the widget "
        "settings." + hint
    )


class Cli:
    def __init__(self, command, graph):
        self.command = command
        self.graph = graph or None

    def run(self, args):
        opts = ["--output", "json"]
        if self.graph:
            opts += ["--graph", self.graph]
        cmd = self.command.argv + join_value_flags(opts + [str(a) for a in args])
        try:
            env = dict(os.environ)
            env.update(self.command.env)
            log("run: %s" % describe_args(cmd))
            started = time.time()
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL, env=env,
            )
        except subprocess.TimeoutExpired:
            log("timed out after %ds" % CLI_TIMEOUT_SECONDS)
            raise HelperError("The logseq CLI did not answer within %d seconds. If you were "
                              "making a change, it may still have been saved: refresh before "
                              "trying again. Details are in "
                              "~/.cache/logseq-db-widget/helper.log." % CLI_TIMEOUT_SECONDS)
        except OSError as exc:
            log("could not start: %s" % exc)
            raise HelperError("Could not run the logseq CLI: %s" % exc)
        # CLI output can contain note text, so only the exit code is logged.
        log("exit %d after %.1fs" % (proc.returncode, time.time() - started))

        payload = parse_json_output(proc.stdout)
        if payload is None:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            detail = detail[-1] if detail else "no output"
            raise HelperError("The logseq CLI returned unexpected output (exit %d): %s"
                              % (proc.returncode, detail))
        if payload.get("status") != "ok":
            code, message = extract_error(payload)
            err = HelperError(message, code)
            raw = payload.get("error")
            err.raw = raw.get("message") if isinstance(raw, dict) else None
            raise err
        return payload.get("data")

    def query(self, query, inputs=None):
        args = ["query", "--query", query]
        if inputs is not None:
            args += ["--inputs", inputs]
        data = self.run(args)
        if isinstance(data, dict):
            return data.get("result")
        return data


def parse_json_output(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        pass
    # Be tolerant of stray lines before the JSON document.
    start = text.find("{")
    while start != -1:
        try:
            value = json.loads(text[start:])
            return value if isinstance(value, dict) else None
        except ValueError:
            start = text.find("{", start + 1)
    return None


def extract_error(payload):
    err = payload.get("error")
    code = None
    message = None
    if isinstance(err, dict):
        code = err.get("code")
        message = err.get("message")
        hint = err.get("hint")
        if message and hint:
            message = "%s (%s)" % (message, hint)
    elif isinstance(err, str):
        message = err
    if not message:
        message = payload.get("message") or "The logseq CLI reported an error."
    friendly = FRIENDLY_ERRORS.get(code)
    if friendly:
        message = friendly
    return code, str(message)


FRIENDLY_ERRORS = {
    "missing-repo": "No graph is selected. Choose one in the widget settings.",
    "missing-graph": "No graph is selected. Choose one in the widget settings.",
    "graph-not-exists": "That graph is not on this computer. Open it once in Logseq Desktop "
                        "so it downloads, or choose another graph in the widget settings.",
    "e2ee-password-not-found": "This synced graph is end-to-end encrypted and the CLI does not "
                               "have its password. Open the graph in Logseq Desktop first.",
}


def is_not_found(err):
    text = ("%s %s" % (err.code or "", err)).lower()
    return "not-found" in text or "not found" in text or "not exists" in text


# --------------------------------------------------------------------------
# Data normalization
# --------------------------------------------------------------------------

def ident_of(value):
    if isinstance(value, dict):
        return value.get("db/ident")
    if isinstance(value, str):
        return value.lstrip(":")
    return None


def title_of_ref(value):
    if isinstance(value, dict):
        return value.get("block/title")
    return None


def flatten_children(node, depth, out):
    for child in node.get("block/children") or []:
        if not isinstance(child, dict):
            continue
        # Property value blocks are not part of the outline.
        if child.get("logseq.property/created-from-property"):
            continue
        status_value = child.get("logseq.property/status")
        status = ident_of(status_value)
        out.append({
            "id": child.get("db/id"),
            "uuid": child.get("block/uuid"),
            "title": child.get("block/title") or "",
            "depth": depth,
            "status": status,
            "statusTitle": title_of_ref(child.get("logseq.property/status"))
                           or status_title_guess(status),
            "priority": ident_of(child.get("logseq.property/priority")),
            # A status you added has a title but no ident; it's still a task.
            "isTask": bool(status or title_of_ref(status_value)),
        })
        flatten_children(child, depth + 1, out)
    return out


def status_title_guess(ident):
    if not ident:
        return None
    for s in FALLBACK_STATUSES:
        if s["ident"] == ident:
            return s["title"]
    return ident.rsplit(".", 1)[-1].replace("-", " ").title()


def tree_result(data):
    root = data.get("root") if isinstance(data, dict) else None
    if not isinstance(root, dict):
        raise HelperError("Unexpected response from `logseq show`.")
    return {
        "pageId": root.get("db/id"),
        "title": root.get("block/title") or "",
        "blocks": flatten_children(root, 0, []),
    }


def flatten_query_rows(result):
    """`:find (pull ...)` results arrive as a list of 1-tuples."""
    rows = []
    for row in result or []:
        if isinstance(row, list):
            rows.extend(r for r in row if isinstance(r, dict))
        elif isinstance(row, dict):
            rows.append(row)
    return rows


# --------------------------------------------------------------------------
# Journal helpers
# --------------------------------------------------------------------------

def journal_day(date):
    return date.year * 10000 + date.month * 100 + date.day


def ordinal(n):
    if n % 100 in (11, 12, 13):
        return "%dth" % n
    return "%d%s" % (n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


_TOKEN_RE = re.compile(r"yyyy|yy|MMMM|MMM|MM|M|EEEE|EEE|E|do|dd|d|'[^']*'|.", re.S)


def format_journal_title(fmt, date):
    """Format a date with the cljs-time style patterns Logseq uses for journal titles."""
    out = []
    for token in _TOKEN_RE.findall(fmt):
        if token == "yyyy":
            out.append("%04d" % date.year)
        elif token == "yy":
            out.append("%02d" % (date.year % 100))
        elif token == "MMMM":
            out.append(MONTHS[date.month - 1])
        elif token == "MMM":
            out.append(MONTHS[date.month - 1][:3])
        elif token == "MM":
            out.append("%02d" % date.month)
        elif token == "M":
            out.append(str(date.month))
        elif token == "EEEE":
            out.append(WEEKDAYS[date.weekday()])
        elif token in ("EEE", "E"):
            out.append(WEEKDAYS[date.weekday()][:3])
        elif token == "do":
            out.append(ordinal(date.day))
        elif token == "dd":
            out.append("%02d" % date.day)
        elif token == "d":
            out.append(str(date.day))
        elif token.startswith("'") and token.endswith("'") and len(token) >= 2:
            out.append(token[1:-1])
        else:
            out.append(token)
    return "".join(out)


def today():
    return datetime.date.today()


def find_journal_page_id(cli, date):
    result = cli.query("[:find ?p . :in $ ?d :where [?p :block/journal-day ?d]]",
                       "[%d]" % journal_day(date))
    return result if isinstance(result, int) else None


def journal_title_format(cli):
    try:
        result = cli.query(
            "[:find ?f . :where [?j :db/ident :logseq.class/Journal] "
            "[?j :logseq.property.journal/title-format ?f]]")
    except HelperError:
        result = None
    return result if isinstance(result, str) and result.strip() else DEFAULT_JOURNAL_FORMAT


def journal_target_args(cli, date):
    """Insert target for today's journal, creating the page in the graph's own date format."""
    page_id = find_journal_page_id(cli, date)
    if page_id is not None:
        return ["--target-id", page_id]
    title = format_journal_title(journal_title_format(cli), date)
    return ["--target-page", title]


def journal_page_title(cli, date):
    """Title of an existing journal page for date, or None."""
    result = cli.query("[:find [?p ?t] :in $ ?d :where [?p :block/journal-day ?d] "
                       "[?p :block/title ?t]]", "[%d]" % journal_day(date))
    if isinstance(result, list) and len(result) == 2 and isinstance(result[1], str):
        return result[1]
    return None


def task_target_args(cli, target):
    """Insert target for a new task.

    `upsert task` in create mode accepts only --target-page (unlike `upsert
    block`), so today's journal is addressed by its exact title.
    """
    target = (target or "").strip()
    if target:
        return ["--target-page", target]
    date = today()
    title = journal_page_title(cli, date) or format_journal_title(journal_title_format(cli), date)
    return ["--target-page", title]


def target_args(cli, target):
    target = (target or "").strip()
    if not target:
        return journal_target_args(cli, today())
    return ["--target-page", target]


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------

def prepare(req):
    """Find the CLI, unpacking the AppImage if needed (slow only the first time)."""
    try:
        command = find_cli(req.get("cli"), req.get("appImage"))
    except HelperError as exc:
        return {"problem": "no-cli", "message": str(exc), "cliPath": None}
    log("cli: %s" % command.source)
    return {"problem": None, "message": None, "cliPath": command.source}


def setup(req):
    """Work out whether the widget can run, and which graph it should use.

    Runs before anything else and never raises: problems are reported in
    the result so the widget can show what to do about them.
    """
    out = {"problem": None, "message": None, "cliPath": None,
           "graphs": [], "current": None}
    try:
        command = find_cli(req.get("cli"), req.get("appImage"))
    except HelperError as exc:
        out.update(problem="no-cli", message=str(exc))
        return out
    out["cliPath"] = command.source
    plain = Cli(command, None)
    try:
        guard_versions(command, (req.get("graph") or "").strip() or None)
    except HelperError as exc:
        out.update(problem="error", message=str(exc))
        return out

    try:
        data = plain.run(["graph", "list"])
    except HelperError as exc:
        out.update(problem="error", message=str(exc))
        return out
    graphs = data.get("graphs") if isinstance(data, dict) else None
    graphs = [g for g in (graphs or []) if isinstance(g, str)]
    out["graphs"] = graphs
    if not graphs:
        out["problem"] = "no-graphs"
        return out

    configured = (req.get("graph") or "").strip()
    if configured:
        if configured in graphs:
            out["current"] = configured
        else:
            out.update(problem="graph-missing", message=configured)
        return out

    # No graph configured: use the CLI's current graph, or the only one.
    try:
        info = plain.run(["graph", "info"])
        current = info.get("graph") if isinstance(info, dict) else None
    except HelperError:
        current = None
    if current not in graphs:
        current = graphs[0] if len(graphs) == 1 else None
    if current is None:
        out["problem"] = "choose-graph"
    out["current"] = current
    return out


def op_info(cli, req):
    data = cli.run(["graph", "info"])
    graph = data.get("graph") if isinstance(data, dict) else None
    return {"graph": graph}


def op_graphs(cli, req):
    # Listing graphs must not depend on a (possibly wrong) configured graph.
    data = Cli(cli.command, None).run(["graph", "list"])
    graphs = data.get("graphs") if isinstance(data, dict) else None
    return {"graphs": [g for g in (graphs or []) if isinstance(g, str)]}


def op_journal(cli, req):
    date = today()
    page_id = find_journal_page_id(cli, date)
    if page_id is None:
        title = format_journal_title(journal_title_format(cli), date)
        return {"pageId": None, "title": title, "blocks": [], "day": journal_day(date)}
    data = cli.run(["show", "--id", page_id, "--linked-references", "false"])
    result = tree_result(data)
    result["day"] = journal_day(date)
    return result


def op_page(cli, req):
    name = (req.get("name") or "").strip()
    if not name:
        raise HelperError("No page name given.")
    try:
        data = cli.run(["show", "--page", name, "--linked-references", "false"])
    except HelperError as err:
        if is_not_found(err):
            return {"pageId": None, "title": name, "blocks": [], "missing": True}
        raise
    return tree_result(data)


FALLBACK_PRIORITIES = [
    {"ident": PRIORITY_PREFIX + "low", "title": "Low", "checkbox": None},
    {"ident": PRIORITY_PREFIX + "medium", "title": "Medium", "checkbox": None},
    {"ident": PRIORITY_PREFIX + "high", "title": "High", "checkbox": None},
    {"ident": PRIORITY_PREFIX + "urgent", "title": "Urgent", "checkbox": None},
]

# Every choice of the status and priority properties, built-in or yours.
# Choices you add in Logseq have no db/ident (only built-ins do), so each is
# identified by its db/id, which every choice has.
CHOICES_QUERY = (
    "[:find ?pi (pull ?v [:db/id :db/ident :block/title :block/order "
    ":logseq.property/choice-checkbox-state :logseq.property/deleted-at]) "
    ":in $ [?pi ...] :where [?p :db/ident ?pi] [?v :block/closed-value-property ?p]]"
)
CHOICE_PROPERTIES = "[[:logseq.property/status :logseq.property/priority]]"


def with_values(choices):
    """Each choice's "value" is what the widget sends back to set it."""
    for c in choices:
        c.setdefault("id", None)
        c["value"] = c["id"] if c["id"] is not None else c["ident"]
    return choices


def load_choices(cli):
    try:
        rows = cli.query(CHOICES_QUERY, CHOICE_PROPERTIES)
    except HelperError as exc:
        log("choices lookup failed: %s" % (exc.code or "helper"))
        rows = []
    found = {"logseq.property/status": [], "logseq.property/priority": []}
    for row in rows or []:
        if not (isinstance(row, list) and len(row) == 2 and isinstance(row[1], dict)):
            continue
        prop, choice = ident_of(row[0]), row[1]
        if prop not in found or choice.get("logseq.property/deleted-at"):
            continue
        title = choice.get("block/title")
        if not isinstance(title, str) or not title or not isinstance(choice.get("db/id"), int):
            continue
        found[prop].append({
            "id": choice["db/id"],
            "ident": ident_of(choice.get("db/ident")),
            "title": title,
            "checkbox": choice.get("logseq.property/choice-checkbox-state"),
            "order": str(choice.get("block/order") or ""),
        })
    out = {}
    for prop, key, fallback in (("logseq.property/status", "statuses", FALLBACK_STATUSES),
                                ("logseq.property/priority", "priorities", FALLBACK_PRIORITIES)):
        choices = sorted(found[prop], key=lambda c: c.pop("order"))
        out[key] = with_values(choices or [dict(c) for c in fallback])
    return out


def op_statuses(cli, req):
    return load_choices(cli)


# Per task: its tags, and whether it (or the page it's on) is in Logseq's
# Recycle. Deleting in a DB graph is a soft delete: the node moves to a hidden
# Recycle page with logseq.property/deleted-at set, and `list task` still
# returns it, so the widget filters recycled tasks out itself.
TASK_META_QUERY = (
    "[:find ?e (pull ?e [:logseq.property/deleted-at "
    "{:block/tags [:db/id :db/ident :block/title]} "
    "{:logseq.property/status [:db/id :db/ident :block/title]} "
    "{:logseq.property/priority [:db/id :db/ident :block/title]} "
    "{:block/page [:logseq.property/deleted-at]}]) "
    ":where [?task :db/ident :logseq.class/Task] [?e :block/tags ?task]]"
)


def task_meta(cli):
    """Map task id -> {"tags": [...], "recycled": bool}. Built-in tags are left out.

    A failure here only costs tags and recycle filtering, never the task list.
    """
    try:
        rows = cli.query(TASK_META_QUERY)
    except HelperError as exc:
        log("task metadata lookup failed: %s" % (exc.code or "helper"))
        return {}
    out = {}
    for row in rows or []:
        if not (isinstance(row, list) and len(row) == 2):
            continue
        task_id, entity = row
        if not isinstance(task_id, int) or not isinstance(entity, dict):
            continue
        page = entity.get("block/page")
        recycled = bool(entity.get("logseq.property/deleted-at")) or (
            isinstance(page, dict) and bool(page.get("logseq.property/deleted-at")))
        tags = []
        for tag in entity.get("block/tags") or []:
            if not isinstance(tag, dict):
                continue
            ident = ident_of(tag.get("db/ident")) or ""
            title = tag.get("block/title")
            if ident.startswith("logseq.class/") or not isinstance(title, str) or not title:
                continue
            if all(t["id"] != tag.get("db/id") for t in tags):
                tags.append({"id": tag.get("db/id"), "title": title})
        tags.sort(key=lambda t: t["title"].lower())
        out[task_id] = {"tags": tags, "recycled": recycled,
                        "status": entity.get("logseq.property/status"),
                        "priority": entity.get("logseq.property/priority")}
    return out


def choice_fields(entity, listed):
    """A status or priority as {id, ident, title}, from the task query if possible.

    `list task` reports only db/ident, which choices you added don't have,
    so the task query's pulled entity is preferred.
    """
    if isinstance(entity, dict) and (entity.get("db/id") or entity.get("db/ident")):
        ident = ident_of(entity.get("db/ident"))
        title = entity.get("block/title") or status_title_guess(ident)
        return {"id": entity.get("db/id"), "ident": ident, "title": title}
    ident = ident_of(listed)
    return {"id": None, "ident": ident, "title": status_title_guess(ident)}


def tag_summary(tasks):
    """Every tag used by a task, with open and total task counts."""
    summary = {}
    for task in tasks:
        for tag in task["tags"]:
            entry = summary.setdefault(tag["id"], {"id": tag["id"], "title": tag["title"],
                                                   "open": 0, "total": 0})
            entry["total"] += 1
            if task["status"] not in CLOSED_STATUSES:
                entry["open"] += 1
    return sorted(summary.values(), key=lambda t: t["title"].lower())


def op_tasks(cli, req):
    data = cli.run(["list", "task"])
    items = data.get("items") if isinstance(data, dict) else None
    include_closed = bool(req.get("includeClosed"))
    meta = task_meta(cli)
    tasks = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        info = meta.get(item.get("db/id"), {})
        status = choice_fields(info.get("status"), item.get("logseq.property/status"))
        priority = choice_fields(info.get("priority"), item.get("logseq.property/priority"))
        if info.get("recycled"):
            continue  # deleted: sitting in Logseq's Recycle
        if not include_closed and status["ident"] in CLOSED_STATUSES:
            continue
        tasks.append({
            "id": item.get("db/id"),
            "title": item.get("block/title") or "",
            "status": status["ident"],
            "statusId": status["id"],
            "statusTitle": status["title"],
            "priority": priority["ident"],
            "priorityId": priority["id"],
            "priorityTitle": priority["title"],
            "scheduled": item.get("logseq.property/scheduled"),
            "deadline": item.get("logseq.property/deadline"),
            "updatedAt": item.get("block/updated-at") or 0,
            "tags": info.get("tags", []),
        })
    tasks.sort(key=lambda t: (
        STATUS_SORT.get(t["status"], 5),
        PRIORITY_SORT.get(t["priority"], 4 if t["priorityId"] is not None else 5),
        t["deadline"] if isinstance(t["deadline"], (int, float)) else float("inf"),
        -(t["updatedAt"] if isinstance(t["updatedAt"], (int, float)) else 0),
    ))
    result = {"tasks": tasks, "tags": tag_summary(tasks)}
    # Choices are reloaded with every refresh, so new ones show up.
    result.update(load_choices(cli))
    return result


def require_text(req, key="text"):
    text = req.get(key)
    if not isinstance(text, str) or not text.strip():
        raise HelperError("Nothing to add.")
    return text.strip()


def require_id(req):
    value = req.get("id")
    if isinstance(value, bool) or not isinstance(value, int):
        raise HelperError("Missing or invalid block id.")
    return value


TAG_NOT_FOUND_RE = re.compile(r"tag not found: (.+)$")
MAX_NEW_TAGS = 10


def as_markdown_block(text):
    """One Markdown bullet; continuation lines are indented to stay in it."""
    lines = text.split("\n")
    return "- " + lines[0] + "".join("\n  " + line for line in lines[1:])


def create_block_with_tags(cli, text, target):
    """Create a block whose #tags become real tags, as in Logseq's editor.

    `--content` keeps "#tag" as plain text; only Markdown input (`--blocks`)
    turns it into a tag, and only one that already exists. So when the CLI
    reports "tag not found: X", create exactly that tag and try again: the
    CLI's own parser decides what counts as a tag. A tag named like an
    existing page turns that page into a tag, as in Logseq itself.
    Returns the new block's id.
    """
    created = set()
    while True:
        try:
            data = cli.run(["upsert", "block", "--blocks", as_markdown_block(text)] + target)
            break
        except HelperError as exc:
            raw = getattr(exc, "raw", None) or ""
            match = TAG_NOT_FOUND_RE.search(raw) if exc.code == "tag-not-found" else None
            name = match.group(1).strip() if match else None
            if not name or name in created or len(created) >= MAX_NEW_TAGS:
                raise
            cli.run(["upsert", "tag", "--name", name])
            created.add(name)
            log("created a tag for a new entry")
    ids = data.get("result") if isinstance(data, dict) else None
    ids = [i for i in (ids or []) if isinstance(i, int) and not isinstance(i, bool)]
    if not ids:
        raise HelperError("The entry was added, but Logseq didn't report its id.")
    return ids[0]


def op_append(cli, req):
    text = require_text(req)
    if "#" in text:
        create_block_with_tags(cli, text, target_args(cli, req.get("page")))
        return {}
    args = ["upsert", "block", "--content", text]
    args += target_args(cli, req.get("page"))
    cli.run(args)
    return {}


def edn_string_vector(values):
    # JSON string escaping is valid EDN for the characters it produces here.
    return "[" + " ".join(json.dumps(v, ensure_ascii=False) for v in values) + "]"


def op_task_add(cli, req):
    text = require_text(req)
    tags = req.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) and t.strip() for t in tags):
        raise HelperError("Invalid tags.")
    args = ["upsert", "task", "--content", text, "--status", req.get("status") or "todo"]
    priority = req.get("priority")
    if isinstance(priority, str):
        priority = priority.strip()
    if priority not in (None, ""):
        choice_edn(priority, PRIORITY_PREFIX)  # reject a bad value before creating anything
    if "#" in text:
        # `upsert task` only takes plain --content, so create the block from
        # Markdown (tags work there), then make it a task.
        block_id = create_block_with_tags(cli, text, target_args(cli, req.get("page")))
        convert = ["upsert", "task", "--id", block_id, "--status", req.get("status") or "todo"]
        try:
            cli.run(convert)
        except HelperError as exc:
            raise HelperError("The entry was added, but making it a task failed: %s" % exc)
        data = {"result": [block_id]}
    else:
        args += task_target_args(cli, req.get("page"))
        data = cli.run(args)
    new_ids = data.get("result") if isinstance(data, dict) else None
    new_ids = [i for i in (new_ids or []) if isinstance(i, int) and not isinstance(i, bool)]
    if priority not in (None, ""):
        if not new_ids:
            raise HelperError("The task was added, but Logseq didn't report its id, so its "
                              "priority couldn't be set.")
        try:
            set_choices(cli, new_ids[0], priority=priority)
        except HelperError as exc:
            raise HelperError("The task was added, but setting its priority failed: %s" % exc)
    if tags:
        # upsert task can't attach tags, so tag the new block in a second step.
        ids = data.get("result") if isinstance(data, dict) else None
        ids = [i for i in (ids or []) if isinstance(i, int) and not isinstance(i, bool)]
        if not ids:
            raise HelperError("The task was added, but Logseq didn't report its id, so it "
                              "couldn't be tagged.")
        try:
            for block_id in ids:
                cli.run(["upsert", "block", "--id", block_id,
                         "--update-tags", edn_string_vector([t.strip() for t in tags])])
        except HelperError as exc:
            raise HelperError("The task was added, but tagging it failed: %s" % exc)
    return {}


CHOICE_IDENT_RE = re.compile(r"^:?[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")


def choice_edn(value, prefix):
    """EDN for a choice: its db/id, or :ident for built-ins. Never free text."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        value = value.strip()
        if value.lower() in VALID_PRIORITIES and prefix == PRIORITY_PREFIX:
            value = prefix + value.lower()
        if CHOICE_IDENT_RE.match(value):
            return ":" + value.lstrip(":")
    raise HelperError("Invalid choice.")


def set_choices(cli, block_id, status=None, priority=None):
    """Set status and/or priority to any choice, including ones you added.

    The CLI's --status/--priority only know choices with a db/ident, so the
    property is set directly; Logseq accepts a choice's db/id as its value.
    """
    parts = []
    if status not in (None, ""):
        parts.append(":logseq.property/status " + choice_edn(status, STATUS_PREFIX))
    if priority not in (None, ""):
        parts.append(":logseq.property/priority " + choice_edn(priority, PRIORITY_PREFIX))
    if parts:
        cli.run(["upsert", "block", "--id", block_id,
                 "--update-properties", "{" + " ".join(parts) + "}"])


def op_task_set(cli, req):
    block_id = require_id(req)
    if "status" not in req and "priority" not in req:
        raise HelperError("Nothing to change.")
    status, priority = req.get("status"), req.get("priority")
    if "status" in req and status in (None, ""):
        cli.run(["upsert", "task", "--id", block_id, "--no-status"])
    if "priority" in req and priority in (None, ""):
        cli.run(["upsert", "task", "--id", block_id, "--no-priority"])
    set_choices(cli, block_id,
                status=status if "status" in req else None,
                priority=priority if "priority" in req else None)
    return {}


def op_raw(cli, req):
    """Raw (unresolved) title of a block, used to decide whether inline editing is safe."""
    block_id = require_id(req)
    data = cli.run(["debug", "pull", "--id", block_id])
    entity = find_entity(data)
    title = entity.get("block/title") if entity else None
    if not isinstance(title, str):
        raise HelperError("Could not read that block.")
    return {"title": title, "hasRefs": bool(UUID_REF_RE.search(title))}


def find_entity(data):
    if isinstance(data, dict):
        if "block/title" in data:
            return data
        for key in ("entity", "result", "item"):
            found = find_entity(data.get(key))
            if found:
                return found
    return None


def op_edit(cli, req):
    block_id = require_id(req)
    text = require_text(req)
    # Never overwrite a title that holds [[uuid]] references: the widget only
    # sees the resolved text, and saving it would turn references into plain
    # page links.
    raw = op_raw(cli, {"id": block_id})
    if raw["hasRefs"]:
        raise HelperError("This block contains references. Edit it in Logseq instead.")
    # The text the editor started from. If the block has changed since (in
    # Logseq, or on another device through sync), saving would silently
    # replace the newer text.
    expected = req.get("expected")
    if isinstance(expected, str) and raw["title"] != expected:
        raise HelperError("This block changed while you were editing it (in Logseq, or on "
                          "another device). Your edit was not saved; refresh and edit it again.",
                          "changed")
    cli.run(["upsert", "block", "--id", block_id, "--content", text])
    return {}


def op_remove(cli, req):
    # Bare `remove` is a command group (its docs say otherwise); deleting a
    # block is `remove block`. In a DB graph this moves it to the Recycle.
    cli.run(["remove", "block", "--id", require_id(req)])
    return {}


# Sync states as the CLI reports them. The worker only ever sets "open" or
# "closed" on a live sync client, and a client starts out "closed" and returns
# to it while reconnecting after a network drop. With no client at all the
# status reads "stopped" (sync configured) or "inactive" (not configured).
NO_SYNC_STATES = {"stopped", "inactive"}


def find_server(cli):
    """The running database process for this graph, or None. Never starts one."""
    data = Cli(cli.command, None).run(["server", "list"])
    servers = data.get("servers") if isinstance(data, dict) else None
    graph = cli.graph
    for server in servers or []:
        if not isinstance(server, dict):
            continue
        if server.get("graph") == graph or server.get("repo") in (graph, "logseq_db_" + str(graph)):
            return server
    return None


def sync_state(cli):
    """(syncing, last_error) for a running process; syncing is None if unknown."""
    try:
        data = cli.run(["sync", "status"])
    except HelperError as exc:
        log("sync status failed: %s" % (exc.code or "helper"))
        return None, None
    state = data.get("ws-state") if isinstance(data, dict) else None
    if not state:
        return None, None
    state = str(state).lstrip(":")
    last_error = data.get("last-error") if isinstance(data, dict) else None
    return state not in NO_SYNC_STATES, (str(last_error) if last_error else None)


SET_PASSWORD_HINT = ("Save it again with the widget's tools/logseq-sync-sessions.py "
                     "--set-e2ee-password.")

# Logseq's sync errors arrive as raw EDN such as
# {:code :decrypt-text-by-text-password :message "..."}; these are the ones
# background sync can actually run into, in plain words.
SYNC_ERROR_TEXT = {
    "decrypt-text-by-text-password":
        "Logseq can't unlock your saved encryption password. It was saved under an "
        "earlier sign-in, and you have signed in again since (in the CLI or in Logseq "
        "Desktop). " + SET_PASSWORD_HINT,
    "db-sync/missing-e2ee-password":
        "This graph is end-to-end encrypted, and no encryption password is saved for "
        "background sync. " + SET_PASSWORD_HINT,
    "e2ee-password-not-found":
        "This graph is end-to-end encrypted, and no encryption password is saved for "
        "background sync. " + SET_PASSWORD_HINT,
    "db-sync/invalid-e2ee-password":
        "The saved encryption password is not this graph's password. " + SET_PASSWORD_HINT,
    "db-sync/invalid-e2ee-password-payload":
        "The saved encryption password is damaged. " + SET_PASSWORD_HINT,
}
SYNC_ERROR_CODE_RE = re.compile(r":code\s+:?([\w./-]+)")


def explain_sync_error(raw):
    """Plain-language text for a sync error, with Logseq's code for reference."""
    raw = str(raw).strip()
    match = SYNC_ERROR_CODE_RE.search(raw)
    code = match.group(1) if match else None
    if code in SYNC_ERROR_TEXT:
        return "%s (Logseq: %s)" % (SYNC_ERROR_TEXT[code], code)
    if code:
        return "Logseq reported %s." % code
    return raw[:300]


def desktop_running(proc=None):
    """True if Logseq Desktop's app (not a CLI or database process) is running.

    When it starts, Logseq Desktop reuses any live database process for the
    graph, including one the CLI started, which keeps its "cli" label. So the
    process can't tell us whether the app is using it, and the widget must
    leave it alone whenever the app is running.
    """
    for argv, environ in my_processes(proc):
        name = os.path.basename(argv[0].decode("utf-8", "replace")).lower()
        # Usually Logseq's own binary; some distributions (Arch's AUR, for
        # one) run it with the system Electron and Logseq's app.asar instead.
        via_electron = name.startswith("electron") and any(
            b"logseq" in a.lower() for a in argv[1:] if not a.startswith(b"-"))
        if not (name.startswith("logseq") or via_electron):
            continue
        if b"ELECTRON_RUN_AS_NODE=1" in environ:
            continue  # the CLI, or a database process
        if any(a.startswith(b"--type=") for a in argv) or b"--appimage-extract" in argv:
            continue  # an Electron helper process, or an unpacking AppImage
        return True
    return False


# ---- Version guard --------------------------------------------------------
#
# Every CLI command that needs the database first runs Logseq's
# stopOutdatedWorkers for that graph: it shuts down any database process whose
# build differs from the CLI's, whoever owns it, including the one Logseq
# Desktop is using. That can happen when the AppImage file is replaced while
# Logseq is still open: the widget would unpack the new version and its CLI
# would take the running (old) app's database away, possibly upgrading the
# graph's database under it. So while Logseq Desktop runs, the builds are
# compared first, using only `--version` and `server list`, which are safe.

VERSION_OK_SECONDS = 20
REVISION_RE = re.compile(r"^Revision:\s*(\S+)", re.M)


def cli_revision(command):
    """The build revision of this CLI, as `--version` prints it."""
    env = dict(os.environ)
    env.update(command.env)
    try:
        proc = subprocess.run(command.argv + ["--version"], capture_output=True, text=True,
                              timeout=60, stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = REVISION_RE.search(proc.stdout or "")
    return match.group(1) if match else None


def guard_versions(command, graph):
    """Refuse to touch the graph while Logseq Desktop runs a different build."""
    if not desktop_running():
        return
    stamp = os.path.join(ensure_private_dir(cache_root()), "version-ok")
    key = "|".join(command.argv) + "|" + str(graph or "")
    try:
        with open(stamp) as f:
            saved_key, saved_at = f.read().rsplit("\n", 1)
        if saved_key == key and 0 <= time.time() - float(saved_at) < VERSION_OK_SECONDS:
            return
    except (OSError, ValueError):
        pass
    mine = cli_revision(command)
    data = Cli(command, None).run(["server", "list"])
    servers = data.get("servers") if isinstance(data, dict) else None
    for server in servers or []:
        if not isinstance(server, dict):
            continue
        ours = (not graph or server.get("graph") == graph
                or server.get("repo") in (graph, "logseq_db_" + str(graph)))
        if not (ours or server.get("owner-source") == "electron"):
            continue
        theirs = server.get("revision")
        if not mine or theirs != mine:
            log("version guard: running %s, CLI %s" % (theirs, mine))
            raise HelperError(
                "Logseq Desktop is running a different Logseq version (%s) than the Logseq "
                "file on disk (%s), probably because Logseq was updated while it was open. "
                "The widget is paused so it doesn't shut down the app's database. Restart "
                "Logseq Desktop to continue." % (theirs or "unknown", mine or "unknown"),
                "version-mismatch")
    try:
        with open(stamp, "w") as f:
            f.write(key + "\n" + str(time.time()))
    except OSError:
        pass


# ---- Don't stop the database while it is working --------------------------

BUSY_SECONDS = 60


def graph_recently_written(graph, now=None):
    """True if the graph's database files were written in the last minute.

    A database process can be busy with no request in progress: building the
    search index (Logseq empties the index, refills it in batches, and only
    marks it valid at the end, so a build cut short means a full rebuild at
    the next start), applying changes from sync, or checkpointing. All of
    that shows as recent writes to the graph's SQLite files.
    """
    root = os.path.expanduser(os.environ.get("LOGSEQ_WIDGET_GRAPHS", "~/logseq/graphs"))
    folder = os.path.join(root, str(graph))
    # A graph name with unusual characters is stored under an encoded folder
    # name; if ours isn't found as is, look at every graph to stay safe.
    folders = [folder] if os.path.isdir(folder) else [root]
    now = now or time.time()
    for top in folders:
        for dirpath, _dirs, files in os.walk(top):
            for name in files:
                if ".sqlite" not in name:
                    continue
                try:
                    if now - os.stat(os.path.join(dirpath, name)).st_mtime < BUSY_SECONDS:
                        return True
                except OSError:
                    continue
    return False


# ---- One widget instance must not stop the database under another ---------

def activity_lock(exclusive):
    """Lock shared by every request that uses the graph; exclusive to stop it.

    Returns the open lock file (keep it referenced), or None if an exclusive
    lock isn't available because another request is in progress.
    """
    import fcntl
    path = os.path.join(ensure_private_dir(cache_root()), "activity.lock")
    handle = open(path, "w")
    try:
        fcntl.flock(handle, (fcntl.LOCK_EX | fcntl.LOCK_NB) if exclusive else fcntl.LOCK_SH)
    except OSError:
        handle.close()
        return None
    return handle


# How long `sync start` may wait for the connection to open. The CLI's own
# default is 10 seconds, shorter than Logseq's reconnect delay (up to 30 s).
SYNC_START_TIMEOUT_MS = 45000


def start_sync(cli, renewing=False):
    """Start sync, or renew the login of a session that is already running.

    Logseq never renews the login token of a sync session the CLI started: it
    reuses the expired token on every reconnect, and the server refuses it,
    forever. `sync start` renews the token first and hands it to Logseq's
    database process; on a running session it changes nothing else.

    Starting can also quietly not happen: Logseq skips it when no sync server
    is configured, when the graph's cloud ID can't be found, or when the
    graph's local sync records aren't ready.
    """
    action = "login-renewed" if renewing else "sync-started"
    try:
        data = cli.run(["--timeout-ms", SYNC_START_TIMEOUT_MS, "sync", "start"])
        state = str(data.get("ws-state") or "").lstrip(":") if isinstance(data, dict) else ""
    except HelperError as exc:
        if exc.code != "sync-start-timeout":
            raise
        # The connection didn't open in time. A session that exists is just
        # reconnecting (now with a fresh login); none means Logseq skipped it.
        try:
            status = cli.run(["sync", "status"])
        except HelperError:
            raise exc
        state = str(status.get("ws-state") or "").lstrip(":") if isinstance(status, dict) else ""
        if not state:
            raise exc
        if state not in NO_SYNC_STATES:
            log("maintain: login handed over; sync is still reconnecting")
            return {"action": action, "reason": "reconnecting"}
    if state not in NO_SYNC_STATES:
        log("maintain: %s (%s)" % (action.replace("-", " "), state or "state not reported"))
        return {"action": action}
    log("maintain: Logseq skipped starting sync (state %s)" % state)
    graph_log = "~/logseq/graphs/%s/db-worker-node-<date>.log" % cli.graph
    if state == "inactive":
        why = "no sync server is configured for Logseq's database process"
    else:
        why = ("in Logseq's code this happens when it can't find the graph's cloud ID, or "
               "when the graph's local sync records aren't ready")
    return {"action": "sync-skipped", "reason": "state-" + state,
            "syncError": "Logseq skipped starting sync for this graph without reporting an "
                         "error (%s). Logseq's own log says why: look for \"start-skipped\" in %s."
                         % (why, graph_log)}


def op_maintain(cli, req):
    """Stop the widget's idle database process, or keep it syncing.

    Only processes the CLI started are touched, and nothing at all while
    Logseq Desktop is running (it may be using that process).
    """
    if not cli.graph:
        # Maintenance may run before the widget was ever opened (a panel
        # widget), so find the graph the same way setup does.
        found = setup({"cli": req.get("cli"), "appImage": req.get("appImage"), "graph": ""})
        if found["problem"] or not found["current"]:
            return {"action": "none", "reason": "no-graph"}
        cli = Cli(cli.command, found["current"])
    if desktop_running():
        return {"action": "none", "reason": "desktop-open"}
    keep_syncing = bool(req.get("backgroundSync"))
    server = find_server(cli)
    if server is None:
        if keep_syncing:
            return start_sync(cli)
        return {"action": "none", "reason": "not-running"}
    owner = server.get("owner-source")
    if owner != "cli":
        return {"action": "none", "reason": "owner-%s" % owner}
    syncing, last_error = sync_state(cli)
    if syncing is None:
        return {"action": "none", "reason": "state-unknown"}  # never act on a guess
    if keep_syncing:
        if syncing:
            # Keep the session's login fresh: Logseq won't renew it itself.
            result = start_sync(cli, renewing=True)
            _still, last_error = sync_state(cli)
            if last_error:
                result["syncError"] = explain_sync_error(last_error)
                log("background sync error: %s" % (SYNC_ERROR_CODE_RE.search(last_error).group(1)
                                                    if SYNC_ERROR_CODE_RE.search(last_error) else "unknown"))
            return result
        return start_sync(cli)
    if syncing:
        # Someone started sync on purpose; don't cut it off.
        return {"action": "none", "reason": "syncing"}
    if graph_recently_written(cli.graph):
        return {"action": "none", "reason": "graph-busy"}  # e.g. a search index build
    lock = activity_lock(exclusive=True)
    if lock is None:
        return {"action": "none", "reason": "busy"}  # another instance is using the graph
    try:
        # Logseq Desktop may have started since the check above.
        if desktop_running():
            return {"action": "none", "reason": "desktop-open"}
        cli.run(["server", "stop"])
    finally:
        lock.close()
    log("maintain: stopped idle process")
    return {"action": "stopped"}


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def op_sync_status(cli, req):
    """Where your changes are: in the cloud, only in the local graph, or unknown.

    Reads only: if no database process is running, none is started, and the
    answer comes from what is known without one.
    Returns {"state": "cloud" | "uploading" | "local" | "local-only" | "unknown",
             "detail": text, "pending": changes not yet uploaded}.
    """
    if not cli.graph:
        found = setup({"cli": req.get("cli"), "appImage": req.get("appImage"), "graph": ""})
        if found["problem"] or not found["current"]:
            return {"state": "unknown", "reason": "no-graph", "detail": "No graph selected.",
                    "pending": 0}
        cli = Cli(cli.command, found["current"])
    if find_server(cli) is None:
        # Nothing is running, so nothing can be uploading right now.
        if desktop_running():
            detail = "Saved to the local graph. Logseq Desktop hasn't opened this graph."
        else:
            detail = ("Saved to the local graph. Not synced while Logseq Desktop is closed, "
                      "unless background sync is on.")
        return {"state": "local", "reason": "no-process", "detail": detail, "pending": 0}
    try:
        status = cli.run(["sync", "status"])
    except HelperError as exc:
        log("sync status failed: %s" % (exc.code or "helper"))
        return {"state": "unknown", "reason": "status-error",
                "detail": "Couldn't read the sync status.", "pending": 0}
    if not isinstance(status, dict):
        return {"state": "unknown", "reason": "status-error",
                "detail": "Couldn't read the sync status.", "pending": 0}

    state = str(status.get("ws-state") or "").lstrip(":")
    pending = count(status.get("pending-local")) + count(status.get("pending-asset"))
    waiting = (" %d change%s waiting to upload." % (pending, "" if pending == 1 else "s")
               if pending else "")
    last_error = status.get("last-error")

    if not status.get("graph-id"):
        return {"state": "local-only", "reason": "graph-not-synced", "pending": 0,
                "detail": "Saved to the local graph. This graph doesn't sync to the cloud."}
    if last_error:
        return {"state": "local", "reason": "sync-error", "pending": pending,
                "detail": "Saved to the local graph, but sync has a problem: "
                          + explain_sync_error(last_error) + waiting}
    if state in NO_SYNC_STATES:
        return {"state": "local", "reason": "sync-off", "pending": pending,
                "detail": "Saved to the local graph. Sync isn't running." + waiting}
    if state == "closed":
        return {"state": "local", "reason": "offline", "pending": pending,
                "detail": "Saved to the local graph. Sync is offline and uploads when it "
                          "reconnects." + waiting}
    if state == "open" and pending:
        return {"state": "uploading", "reason": "uploading", "pending": pending,
                "detail": "Saved to the local graph and uploading:" + waiting}
    if state == "open":
        return {"state": "cloud", "reason": "synced", "pending": 0,
                "detail": "All changes are synced to the cloud."}
    return {"state": "unknown", "reason": "state-" + (state or "none"), "pending": pending,
            "detail": "Sync is in an unknown state."}


OPS = {
    "syncStatus": op_sync_status,
    "maintain": op_maintain,
    "info": op_info,
    "graphs": op_graphs,
    "journal": op_journal,
    "page": op_page,
    "statuses": op_statuses,
    "tasks": op_tasks,
    "append": op_append,
    "taskAdd": op_task_add,
    "taskSet": op_task_set,
    "raw": op_raw,
    "edit": op_edit,
    "remove": op_remove,
}


def decode_request(arg):
    text = arg if arg.lstrip().startswith("{") else urllib.parse.unquote(arg)
    req = json.loads(text)
    if not isinstance(req, dict):
        raise ValueError("request must be a JSON object")
    return req


REQUEST_ENV = "LOGSEQ_WIDGET_REQUEST"


def op_ping(req):
    """Answers without touching Logseq: proves Plasma can run the helper."""
    return {"python": sys.version.split()[0], "helper": os.path.abspath(__file__)}


def main(argv):
    req_id = None
    # First thing, so any invocation at all leaves a trace in the log.
    log("invoked (python %s, %d args)" % (sys.version.split()[0], len(argv) - 1))
    try:
        # The widget passes the request in the environment, which other user
        # accounts can't read (unlike a command line). An argument still
        # works for manual testing.
        raw = os.environ.pop(REQUEST_ENV, None) or (argv[1] if len(argv) > 1 else None)
        if not raw:
            raise HelperError("usage: logseq_helper.py <json-request>")
        try:
            req = decode_request(raw)
        except ValueError as exc:
            raise HelperError("Malformed request: %s" % exc)
        req_id = req.get("reqId")
        global _log_op
        _log_op = str(req.get("op"))
        log("start")
        if req.get("op") == "ping":
            out = {"ok": True, "reqId": req_id, "data": op_ping(req)}
            log("done")
            sys.stdout.write(json.dumps(out) + "\n")
            return 0
        if req.get("op") == "prepare":
            out = {"ok": True, "reqId": req_id, "data": prepare(req)}
            log("done: %s" % (out["data"]["problem"] or "ok"))
            sys.stdout.write(json.dumps(out) + "\n")
            return 0
        if req.get("op") == "setup":
            out = {"ok": True, "reqId": req_id, "data": setup(req)}
            log("done: %s" % (out["data"]["problem"] or "ok"))
            sys.stdout.write(json.dumps(out) + "\n")
            return 0
        op = OPS.get(req.get("op"))
        if op is None:
            raise HelperError("Unknown operation: %r" % req.get("op"))
        cli = Cli(find_cli(req.get("cli"), req.get("appImage")), req.get("graph"))
        guard_versions(cli.command, cli.graph)
        # Held while this request uses the graph, so that another widget
        # instance's idle stop waits its turn. (Maintenance takes it itself.)
        in_use = activity_lock(exclusive=False) if req.get("op") != "maintain" else None
        out = {"ok": True, "reqId": req_id, "data": op(cli, req)}
        if in_use is not None:
            in_use.close()
        if req.get("op") in ("maintain", "syncStatus"):
            d = out["data"]
            log("decision: %s%s (background sync %s)" % (
                d.get("action") or d.get("state"),
                (", " + d["reason"]) if d.get("reason") else "",
                "on" if req.get("backgroundSync") else "off"))
    except HelperError as exc:
        # Messages can quote page names, so only the code is logged.
        log("error: %s" % (exc.code or "helper"))
        out = {"ok": False, "reqId": req_id, "error": str(exc), "code": exc.code}
    except Exception as exc:  # report, never crash silently
        log("internal error: %r" % exc)
        out = {"ok": False, "reqId": req_id, "error": "Internal helper error: %r" % exc}
    else:
        log("done")
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
