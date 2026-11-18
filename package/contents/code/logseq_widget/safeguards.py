"""Checks that keep the widget from harming your graph or Logseq Desktop.

- the version guard: never let a different Logseq version take over the
  database Logseq Desktop is using;
- never stop the database while it is busy (an index build, say);
- never stop it while another widget instance is in the middle of a request."""

import os
import re
import subprocess
import time

from .errors import HelperError
from .paths import cache_root, ensure_private_dir
from .log import log
from .processes import desktop_running
from .cli import Cli


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
