"""Reading: today's journal, pinned pages, and one block's raw text."""

from .errors import HelperError
from .cli import is_not_found
from .entities import tree_result, UUID_REF_RE
from .journal import find_journal_page_id, format_journal_title, journal_day, journal_title_format, today
from .request import require_id


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
