"""The helper's log file (~/.cache/logseq-db-widget/helper.log).

It records steps, timings and decisions, never note text, page names or the
CLI's error output."""

import datetime
import os

from .paths import cache_root, ensure_private_dir


LOG_MAX_BYTES = 512 * 1024


_log_op = "-"  # the operation being run, shown on every line


def set_operation(op):
    """Name the operation that the following log lines belong to."""
    global _log_op
    _log_op = str(op)


def log(message):
    """Append a line to ~/.cache/logseq-db-widget/helper.log. Never logs note text."""
    try:
        root = ensure_private_dir(cache_root())
        path = os.path.join(root, "helper.log")
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Readable by you only.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s [%d] %s: %s\n" % (stamp, os.getpid(), _log_op, message))
    except Exception:
        pass
