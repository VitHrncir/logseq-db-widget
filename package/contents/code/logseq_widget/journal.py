"""Journal pages: dates, titles in the graph's own format, and where new blocks go."""

import datetime
import re

from .errors import HelperError


DEFAULT_JOURNAL_FORMAT = "MMM do, yyyy"


MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday"]


def journal_day(date):
    return date.year * 10000 + date.month * 100 + date.day


def ordinal(n):
    if n % 100 in (11, 12, 13):
        return "%dth" % n
    return "%d%s" % (n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


_TOKEN_RE = re.compile(r"yyyy|yy|MMMM|MMM|MM|M|EEEE|EEE|E|do|dd|d|'[^']*'|.", re.S)


def format_journal_title(fmt, date):
    """Format a date with the cljs-time style patterns Logseq uses for journal titles."""
    out = []
    for token in _TOKEN_RE.findall(fmt):
        if token == "yyyy":
            out.append("%04d" % date.year)
        elif token == "yy":
            out.append("%02d" % (date.year % 100))
        elif token == "MMMM":
            out.append(MONTHS[date.month - 1])
        elif token == "MMM":
            out.append(MONTHS[date.month - 1][:3])
        elif token == "MM":
            out.append("%02d" % date.month)
        elif token == "M":
            out.append(str(date.month))
        elif token == "EEEE":
            out.append(WEEKDAYS[date.weekday()])
        elif token in ("EEE", "E"):
            out.append(WEEKDAYS[date.weekday()][:3])
        elif token == "do":
            out.append(ordinal(date.day))
        elif token == "dd":
            out.append("%02d" % date.day)
        elif token == "d":
            out.append(str(date.day))
        elif token.startswith("'") and token.endswith("'") and len(token) >= 2:
            out.append(token[1:-1])
        else:
            out.append(token)
    return "".join(out)


def today():
    return datetime.date.today()


def find_journal_page_id(cli, date):
    result = cli.query("[:find ?p . :in $ ?d :where [?p :block/journal-day ?d]]",
                       "[%d]" % journal_day(date))
    return result if isinstance(result, int) else None


def journal_title_format(cli):
    try:
        result = cli.query(
            "[:find ?f . :where [?j :db/ident :logseq.class/Journal] "
            "[?j :logseq.property.journal/title-format ?f]]")
    except HelperError:
        result = None
    return result if isinstance(result, str) and result.strip() else DEFAULT_JOURNAL_FORMAT


def journal_target_args(cli, date):
    """Insert target for today's journal, creating the page in the graph's own date format."""
    page_id = find_journal_page_id(cli, date)
    if page_id is not None:
        return ["--target-id", page_id]
    title = format_journal_title(journal_title_format(cli), date)
    return ["--target-page", title]


def journal_page_title(cli, date):
    """Title of an existing journal page for date, or None."""
    result = cli.query("[:find [?p ?t] :in $ ?d :where [?p :block/journal-day ?d] "
                       "[?p :block/title ?t]]", "[%d]" % journal_day(date))
    if isinstance(result, list) and len(result) == 2 and isinstance(result[1], str):
        return result[1]
    return None


def task_target_args(cli, target):
    """Insert target for a new task.

    `upsert task` in create mode accepts only --target-page (unlike `upsert
    block`), so today's journal is addressed by its exact title.
    """
    target = (target or "").strip()
    if target:
        return ["--target-page", target]
    date = today()
    title = journal_page_title(cli, date) or format_journal_title(journal_title_format(cli), date)
    return ["--target-page", title]


def target_args(cli, target):
    target = (target or "").strip()
    if not target:
        return journal_target_args(cli, today())
    return ["--target-page", target]
