"""Running one request: pick the operation, run it, answer with one JSON line."""

import json
import os
import sys

from .errors import HelperError
from .log import log, set_operation
from .cli import Cli
from .locate import find_cli
from .choices import op_statuses
from .graph_setup import op_graphs, op_info, prepare, setup
from .request import decode_request, REQUEST_ENV
from .pages import op_journal, op_page, op_raw
from .blocks import op_append, op_edit, op_remove
from .tasks import op_task_add, op_task_set, op_tasks
from .sync import op_sync_status
from .safeguards import activity_lock, guard_versions
from .maintenance import op_maintain


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


def op_ping(req):
    """Answers without touching Logseq: proves Plasma can run the helper."""
    return {"python": sys.version.split()[0], "helper": os.path.abspath(sys.argv[0])}


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
        set_operation(req.get("op"))
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
        try:
            out = {"ok": True, "reqId": req_id, "data": op(cli, req)}
        finally:
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
