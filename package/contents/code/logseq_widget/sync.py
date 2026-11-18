"""Logseq Sync: reading its state, explaining its errors, and starting it.

Sync itself runs inside Logseq's database process; the widget only starts it,
renews its login, and reports where your changes are."""

import re

from .errors import HelperError
from .log import log
from .processes import desktop_running
from .cli import Cli
from .graph_setup import setup


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
