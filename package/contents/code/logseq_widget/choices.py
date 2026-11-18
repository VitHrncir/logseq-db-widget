"""Task statuses and priorities, including ones you added in Logseq.

Built-in choices have a db/ident; ones you add have only a db/id, so every
choice is handled by its id where possible."""

import re

from .errors import HelperError
from .log import log
from .entities import FALLBACK_STATUSES, ident_of, PRIORITY_PREFIX, STATUS_PREFIX, status_title_guess


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
