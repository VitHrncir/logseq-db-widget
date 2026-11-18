"""Running one Logseq CLI command, safely, and reading its answer.

Commands are always argument lists (never a shell), with every option in
--flag=value form so text can't be mistaken for an option."""

import json
import os
import subprocess
import time

from .errors import HelperError
from .log import log


CLI_TIMEOUT_SECONDS = 120  # the first call may have to start db-worker-node and load the graph


# CLI arguments that carry user text; their values are not logged.
PRIVATE_ARGS = {"--content", "--query", "--inputs", "--page", "--target-page", "--blocks",
                "--update-tags"}


# Options that take a value. The CLI treats any value starting with "-" as a
# new option, so a page named "--root-dir=/x" would otherwise inject an
# option. In the "--flag=value" form everything after the first "=" is the
# value, whatever it starts with.
VALUE_FLAGS = {"--output", "--graph", "--timeout-ms", "--content", "--page", "--target-page", "--target-id",
               "--id", "--status", "--priority", "--update-tags", "--query", "--inputs",
               "--linked-references"}


def join_value_flags(args):
    out, i = [], 0
    args = [str(a) for a in args]
    while i < len(args):
        if args[i] in VALUE_FLAGS and i + 1 < len(args):
            out.append(args[i] + "=" + args[i + 1])
            i += 2
        else:
            if args[i] in VALUE_FLAGS:
                raise HelperError("Internal error: %s has no value." % args[i])
            out.append(args[i])
            i += 1
    return out


def describe_args(args):
    out = []
    for a in args:
        a = str(a)
        flag = a.split("=", 1)[0]
        out.append(flag + "=<...>" if "=" in a and flag in PRIVATE_ARGS else a)
    return " ".join(out)


class CliCommand:
    """How to start the logseq CLI: an argv prefix plus extra environment."""

    def __init__(self, argv, env=None, source=""):
        self.argv = list(argv)
        self.env = dict(env or {})
        self.source = source


class Cli:
    def __init__(self, command, graph):
        self.command = command
        self.graph = graph or None

    def run(self, args):
        opts = ["--output", "json"]
        if self.graph:
            opts += ["--graph", self.graph]
        cmd = self.command.argv + join_value_flags(opts + [str(a) for a in args])
        try:
            env = dict(os.environ)
            env.update(self.command.env)
            log("run: %s" % describe_args(cmd))
            started = time.time()
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL, env=env,
            )
        except subprocess.TimeoutExpired:
            log("timed out after %ds" % CLI_TIMEOUT_SECONDS)
            raise HelperError("The logseq CLI did not answer within %d seconds. If you were "
                              "making a change, it may still have been saved: refresh before "
                              "trying again. Details are in "
                              "~/.cache/logseq-db-widget/helper.log." % CLI_TIMEOUT_SECONDS)
        except OSError as exc:
            log("could not start: %s" % exc)
            raise HelperError("Could not run the logseq CLI: %s" % exc)
        # CLI output can contain note text, so only the exit code is logged.
        log("exit %d after %.1fs" % (proc.returncode, time.time() - started))

        payload = parse_json_output(proc.stdout)
        if payload is None:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            detail = detail[-1] if detail else "no output"
            raise HelperError("The logseq CLI returned unexpected output (exit %d): %s"
                              % (proc.returncode, detail))
        if payload.get("status") != "ok":
            code, message = extract_error(payload)
            err = HelperError(message, code)
            raw = payload.get("error")
            err.raw = raw.get("message") if isinstance(raw, dict) else None
            raise err
        return payload.get("data")

    def query(self, query, inputs=None):
        args = ["query", "--query", query]
        if inputs is not None:
            args += ["--inputs", inputs]
        data = self.run(args)
        if isinstance(data, dict):
            return data.get("result")
        return data


def parse_json_output(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        pass
    # Be tolerant of stray lines before the JSON document.
    start = text.find("{")
    while start != -1:
        try:
            value = json.loads(text[start:])
            return value if isinstance(value, dict) else None
        except ValueError:
            start = text.find("{", start + 1)
    return None


def extract_error(payload):
    err = payload.get("error")
    code = None
    message = None
    if isinstance(err, dict):
        code = err.get("code")
        message = err.get("message")
        hint = err.get("hint")
        if message and hint:
            message = "%s (%s)" % (message, hint)
    elif isinstance(err, str):
        message = err
    if not message:
        message = payload.get("message") or "The logseq CLI reported an error."
    friendly = FRIENDLY_ERRORS.get(code)
    if friendly:
        message = friendly
    return code, str(message)


FRIENDLY_ERRORS = {
    "missing-repo": "No graph is selected. Choose one in the widget settings.",
    "missing-graph": "No graph is selected. Choose one in the widget settings.",
    "graph-not-exists": "That graph is not on this computer. Open it once in Logseq Desktop "
                        "so it downloads, or choose another graph in the widget settings.",
    "e2ee-password-not-found": "This synced graph is end-to-end encrypted and the CLI does not "
                               "have its password. Open the graph in Logseq Desktop first.",
}


def is_not_found(err):
    text = ("%s %s" % (err.code or "", err)).lower()
    return "not-found" in text or "not found" in text or "not exists" in text
