"""The TODO list: listing, filtering, adding and updating tasks."""

import json

from .errors import HelperError
from .log import log
from .entities import ident_of, PRIORITY_PREFIX
from .journal import target_args, task_target_args
from .choices import choice_edn, choice_fields, CLOSED_STATUSES, load_choices, PRIORITY_SORT, set_choices, STATUS_SORT
from .request import require_id, require_text
from .blocks import create_block_with_tags


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
