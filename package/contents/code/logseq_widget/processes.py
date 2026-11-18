"""Looking at this user's running processes.

Used to tell whether Logseq Desktop is open, and whether a folder is still in
use by a running program."""

import os


def my_processes(proc=None):
    """(argv, environ) of every process of this user; argv and environ as bytes lists."""
    proc = proc or os.environ.get("LOGSEQ_WIDGET_PROC", "/proc")
    uid = os.getuid()
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return
    for pid in pids:
        base = os.path.join(proc, pid)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "cmdline"), "rb") as f:
                argv = [a for a in f.read().split(b"\0") if a]
            with open(os.path.join(base, "environ"), "rb") as f:
                environ = f.read().split(b"\0")
        except OSError:
            continue
        if argv:
            yield argv, environ


def folder_in_use(folder, proc=None):
    """True if one of this user's processes was started from inside folder."""
    prefix = os.path.join(folder, "").encode()
    for argv, _environ in my_processes(proc):
        if any(a.startswith(prefix) for a in argv[:3]):
            return True
    return False


def desktop_running(proc=None):
    """True if Logseq Desktop's app (not a CLI or database process) is running.

    When it starts, Logseq Desktop reuses any live database process for the
    graph, including one the CLI started, which keeps its "cli" label. So the
    process can't tell us whether the app is using it, and the widget must
    leave it alone whenever the app is running.
    """
    for argv, environ in my_processes(proc):
        name = os.path.basename(argv[0].decode("utf-8", "replace")).lower()
        # Usually Logseq's own binary; some distributions (Arch's AUR, for
        # one) run it with the system Electron and Logseq's app.asar instead.
        via_electron = name.startswith("electron") and any(
            b"logseq" in a.lower() for a in argv[1:] if not a.startswith(b"-"))
        if not (name.startswith("logseq") or via_electron):
            continue
        if b"ELECTRON_RUN_AS_NODE=1" in environ:
            continue  # the CLI, or a database process
        if any(a.startswith(b"--type=") for a in argv) or b"--appimage-extract" in argv:
            continue  # an Electron helper process, or an unpacking AppImage
        return True
    return False
