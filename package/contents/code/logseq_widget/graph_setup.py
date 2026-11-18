"""First start: finding the CLI, and choosing the graph."""

from .errors import HelperError
from .log import log
from .cli import Cli
from .locate import find_cli
from .safeguards import guard_versions


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
