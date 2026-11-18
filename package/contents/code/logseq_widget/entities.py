"""Logseq's data as the CLI returns it, turned into plain values for the widget."""

import re

from .errors import HelperError


UUID_REF_RE = re.compile(
    r"\[\[[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\]\]"
)


STATUS_PREFIX = "logseq.property/status."


PRIORITY_PREFIX = "logseq.property/priority."


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
