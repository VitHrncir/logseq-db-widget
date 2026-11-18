"""Writing blocks: adding, editing and deleting.

Text containing #tags is sent as Markdown so the tags become real tags,
creating missing ones first."""

import re

from .errors import HelperError
from .log import log
from .journal import target_args
from .request import require_id, require_text
from .pages import op_raw


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
