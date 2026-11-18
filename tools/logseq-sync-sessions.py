#!/usr/bin/env python3
"""Find, and close, Logseq CLI database processes and their sync sessions.

    python3 logseq-sync-sessions.py            # list, then close the CLI's sessions
    python3 logseq-sync-sessions.py --list     # only list; change nothing
    python3 logseq-sync-sessions.py --force    # also act while Logseq Desktop is open,
                                               # and end unregistered database processes
    python3 logseq-sync-sessions.py --set-e2ee-password [GRAPH]
                                               # save an encrypted graph's password for
                                               # background sync, and start sync

About --set-e2ee-password: Logseq saves the password in your keyring, locked
with the current sign-in (the refresh token in ~/logseq/auth.json, which
Logseq Desktop and the CLI share). After signing in again anywhere, the old
saved password can't be unlocked and background sync fails with
"decrypt-text-by-text-password"; save it again with this option. The password
is asked for without echo and never stored by this script, but the CLI only
accepts it on its command line, so other user accounts on this computer could
glimpse it in the process list for the second or two the command runs.

What it touches: database processes the Logseq CLI started (owner "cli"),
whether the widget or you in a terminal started them. It stops their sync first, then the process, using the CLI's own
commands so shutdown is clean.

What it never touches: Logseq Desktop's own database processes (owner
"electron"; closing the app stops those), your graphs, and your CLI login.

Exit status: 0 when no CLI-started process is left running, 1 otherwise.
"""
import argparse
import getpass
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time

CACHES = ["~/.cache/logseq-db-widget/appimage-*/squashfs-root"]
LAUNCHER = "~/.local/bin/logseq"
NO_SYNC_STATES = {"stopped", "inactive"}


# --------------------------------------------------------------------------
# Finding a CLI to talk to
# --------------------------------------------------------------------------

def cli_from_unpacked(root):
    """Command for the CLI inside an unpacked AppImage (as the widget runs it)."""
    try:
        with open(os.path.join(root, "AppRun")) as f:
            program = re.search(r'BIN="\$APPDIR/([^"]+)"', f.read()).group(1)
    except (OSError, AttributeError):
        return None
    script = os.path.join(root, "resources/app.asar/js/logseq-cli.js")
    exe = os.path.join(root, program)
    if os.access(exe, os.X_OK) and os.path.exists(os.path.join(root, "resources/app.asar")):
        return [exe, script]
    return None


def find_cli(explicit):
    if explicit:
        return [os.path.expanduser(explicit)], explicit
    # 1. A copy the widgets unpacked: works whether or not Logseq is open.
    roots = []
    for pattern in CACHES:
        roots += glob.glob(os.path.expanduser(pattern))
    for root in sorted(roots, key=os.path.getmtime, reverse=True):
        command = cli_from_unpacked(root)
        if command:
            return command, root
    # 2. Logseq's launcher: works for package installs, and for the AppImage
    #    only while Logseq Desktop is open (it points into the AppImage's mount).
    launcher = os.path.expanduser(LAUNCHER)
    if os.access(launcher, os.X_OK):
        with open(launcher, errors="replace") as f:
            match = re.search(r'exec "[^"]+" "([^"]+)"', f.read())
        if not match or os.path.exists(match.group(1)):
            return [launcher], launcher
    return None, None


def cli_revision(command):
    """This CLI's build revision. Asking for it never touches a database."""
    env = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
    try:
        done = subprocess.run(command + ["--version"], env=env, capture_output=True,
                              text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"^Revision:\s*(\S+)", done.stdout or "", re.M)
    return match.group(1) if match else None


def run_cli(command, *args):
    """Run one CLI command; return (data, error message)."""
    env = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
    try:
        done = subprocess.run(command + ["--output=json", *args], env=env,
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        return None, lines[-1] if lines else "no output"
    if answer.get("status") != "ok":
        error = answer.get("error") or {}
        return None, error.get("message") if isinstance(error, dict) else str(error)
    return answer.get("data"), None


# --------------------------------------------------------------------------
# Looking at processes
# --------------------------------------------------------------------------

def my_processes(proc="/proc"):
    """(pid, argv, environ) for every process of this user."""
    uid = os.getuid()
    for pid in os.listdir(proc):
        if not pid.isdigit():
            continue
        base = os.path.join(proc, pid)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "cmdline"), "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
            with open(os.path.join(base, "environ"), "rb") as f:
                environ = f.read().split(b"\0")
        except OSError:
            continue
        if argv:
            yield int(pid), argv, environ


def desktop_running(proc):
    """Same check the widget uses: is Logseq Desktop's app running?"""
    for _pid, argv, environ in my_processes(proc):
        name = os.path.basename(argv[0]).lower()
        via_electron = name.startswith("electron") and any(
            "logseq" in a.lower() for a in argv[1:] if not a.startswith("-"))
        if not (name.startswith("logseq") or via_electron):
            continue
        if b"ELECTRON_RUN_AS_NODE=1" in environ:
            continue
        if any(a.startswith("--type=") for a in argv) or "--appimage-extract" in argv:
            continue
        return True
    return False


def option(argv, name):
    if name in argv and argv.index(name) + 1 < len(argv):
        return argv[argv.index(name) + 1]
    return None


def database_processes(proc):
    """Logseq database processes (db-worker-node) running as this user."""
    found = []
    for pid, argv, environ in my_processes(proc):
        if any("db-worker-node" in a for a in argv) and option(argv, "--repo"):
            found.append({"pid": pid,
                          "repo": option(argv, "--repo"),
                          "owner": option(argv, "--owner-source") or "unknown"})
    return found


def helper_processes(proc):
    found = []
    for pid, argv, _env in my_processes(proc):
        if any(a.endswith("logseq_helper.py") for a in argv):
            found.append(pid)
    return found


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def graph_of(server):
    graph = server.get("graph")
    repo = server.get("repo") or ""
    return graph or (repo[len("logseq_db_"):] if repo.startswith("logseq_db_") else repo)


def set_e2ee_password(command, graph, desktop, force):
    """Save the encryption password under the current sign-in and start sync."""
    if not command:
        print("No Logseq CLI found. Open the widget once so it unpacks Logseq, or pass --cli.")
        return 1
    if desktop and not force:
        print("Close Logseq Desktop first, so the password is saved for the sign-in the "
              "background sync will use (or use --force).")
        return 1
    if not graph:
        data, error = run_cli(command, "graph", "list")
        graphs = (data or {}).get("graphs") or []
        if error or len(graphs) != 1:
            print("Name the graph: --set-e2ee-password GRAPH (graphs: %s)"
                  % (", ".join(graphs) if graphs else error))
            return 1
        graph = graphs[0]
    password = getpass.getpass("Encryption password for %s: " % graph)
    if not password:
        print("No password entered; nothing changed.")
        return 1
    # --flag=value, so a password starting with "-" is still a value.
    _data, error = run_cli(command, "--graph=" + graph, "sync", "start",
                           "--e2ee-password=" + password)
    password = None
    if error:
        print("Logseq rejected it: %s" % error)
        return 1
    print("Saved for the current sign-in, and sync started for %s." % graph)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--list", action="store_true", help="only list; change nothing")
    parser.add_argument("--force", action="store_true",
                        help="act even while Logseq Desktop is open, and end unregistered "
                             "CLI database processes")
    parser.add_argument("--cli", help="path of a logseq CLI to use")
    parser.add_argument("--set-e2ee-password", nargs="?", const="", metavar="GRAPH",
                        help="save an encrypted graph's password for background sync "
                             "(asks for it), then start sync")
    parser.add_argument("--proc", default="/proc", help=argparse.SUPPRESS)  # for tests
    args = parser.parse_args()

    command, source = find_cli(args.cli)
    desktop = desktop_running(args.proc)
    if args.set_e2ee_password is not None:
        return set_e2ee_password(command, args.set_e2ee_password, desktop, args.force)
    print("Logseq Desktop:", "running" if desktop else "not running")
    print("CLI used:", source or "none found (process list only)")

    servers = []
    revision = cli_revision(command) if command else None
    if command:
        data, error = run_cli(command, "server", "list")
        if error:
            print("Could not list database processes through the CLI:", error)
        else:
            servers = [s for s in (data or {}).get("servers", []) if isinstance(s, dict)]

    print("\nDatabase processes registered with Logseq:")
    if not servers:
        print("  none")
    for server in servers:
        graph = graph_of(server)
        state = "-"
        # Any command that reaches a database process first makes Logseq shut
        # down processes from a different Logseq version, the app's included.
        # So a process from another version is listed, but never queried.
        server["_differs"] = bool(revision and server.get("revision")
                                  and server.get("revision") != revision)
        if server["_differs"]:
            state = "not checked (runs a different Logseq version than this CLI)"
        elif command:
            data, error = run_cli(command, "--graph=" + graph, "sync", "status")
            state = (str(data.get("ws-state")).lstrip(":") if data else "unknown (%s)" % error)
        server["_sync"] = state
        print("  graph %-24s owner %-9s pid %-8s sync %s"
              % (graph, server.get("owner-source"), server.get("pid", "?"), state))

    registered = {s.get("pid") for s in servers}
    strays = [p for p in database_processes(args.proc) if p["pid"] not in registered]
    if strays:
        print("\nDatabase processes NOT registered with Logseq (left over, or a different root):")
        for p in strays:
            print("  repo %-26s owner %-9s pid %s" % (p["repo"], p["owner"], p["pid"]))
    helpers = helper_processes(args.proc)
    if helpers:
        print("\nWidget helper processes running right now:", ", ".join(map(str, helpers)))

    cli_servers = [s for s in servers if s.get("owner-source") == "cli"]
    if args.list:
        return 0 if not cli_servers else 1
    if desktop and not args.force:
        if cli_servers:
            print("\nLogseq Desktop is running and may be using these processes, so nothing "
                  "was changed.\nClose Logseq Desktop and run this again, or use --force.")
        return 0 if not cli_servers else 1

    print()
    for server in cli_servers:
        graph = graph_of(server)
        state = server.get("_sync", "")
        if server.get("_differs") and desktop:
            print("Left alone: %s runs a different Logseq version while Logseq Desktop is "
                  "open. Restart Logseq Desktop first." % graph)
            continue
        if not server.get("_differs") and state and state.split(" ")[0] not in NO_SYNC_STATES:
            _data, error = run_cli(command, "--graph=" + graph, "sync", "stop")
            print("Stopping sync for %s: %s" % (graph, "done" if not error else error))
        _data, error = run_cli(command, "--graph=" + graph, "server", "stop")
        print("Stopping database process for %s: %s" % (graph, "done" if not error else error))
    for server in servers:
        if server.get("owner-source") != "cli":
            print("Left alone (owner %s): %s. Closing Logseq Desktop stops it."
                  % (server.get("owner-source"), graph_of(server)))

    for p in strays:
        if p["owner"] == "electron":
            print("Left alone (Logseq Desktop's): pid %s" % p["pid"])
        elif args.force:
            os.kill(p["pid"], signal.SIGTERM)
            print("Asked unregistered process %s (%s) to exit" % (p["pid"], p["repo"]))
        else:
            print("Unregistered process %s (%s) left running; use --force to end it"
                  % (p["pid"], p["repo"]))
    if strays and args.force:
        time.sleep(3)

    # Check what is still running.
    remaining = []
    if command:
        data, error = run_cli(command, "server", "list")
        if not error:
            remaining = [s for s in (data or {}).get("servers", [])
                         if isinstance(s, dict) and s.get("owner-source") == "cli"]
    alive_strays = [p for p in database_processes(args.proc)
                    if p["owner"] == "cli" and p["pid"] not in registered]
    if remaining or alive_strays:
        print("\nStill running:", ", ".join([graph_of(s) for s in remaining]
                                            + ["pid %s" % p["pid"] for p in alive_strays]))
        return 1
    print("\nNo CLI database processes or sync sessions are running.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
