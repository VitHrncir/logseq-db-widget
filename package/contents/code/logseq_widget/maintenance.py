"""Looking after Logseq's database process when the widget is idle.

Either stop the process the widget started (when you're not syncing), or keep
background sync running and its login fresh."""

from .log import log
from .processes import desktop_running
from .cli import Cli
from .graph_setup import setup
from .sync import explain_sync_error, find_server, start_sync, SYNC_ERROR_CODE_RE, sync_state
from .safeguards import activity_lock, graph_recently_written


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
