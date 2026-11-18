#!/usr/bin/env python3
"""
logseq_helper.py: bridge between the Logseq DB Plasma widget and the official
`logseq` CLI that ships with Logseq Desktop (DB version).

The widget runs:   python3 logseq_helper.py <percent-encoded JSON request>
and always receives exactly one JSON object on stdout:

    {"ok": true,  "reqId": <request id>, "data": ...}
    {"ok": false, "reqId": <request id>, "error": "human readable message"}

The CLI is always called with an argument list (never through a shell), so
text typed into the widget cannot be interpreted as shell syntax.

For manual testing you can pass plain JSON:

    python3 logseq_helper.py '{"op": "tasks"}'
    python3 logseq_helper.py '{"op": "journal"}'
    python3 logseq_helper.py '{"op": "page", "name": "Projects"}'

The code itself is in the logseq_widget folder next to this file; its
__init__.py lists what each module does.
"""
import os
import sys

# Don't leave compiled-code caches in the installed widget's folder.
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logseq_widget.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv))
