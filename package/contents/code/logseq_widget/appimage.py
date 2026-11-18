"""Logseq's AppImage: finding it, and unpacking it once into the cache.

Logseq's own launcher points into a temporary folder that only exists while
Logseq Desktop runs, so the widget runs the CLI from its own unpacked copy."""

import os
import re
import shutil
import subprocess
import time

from .errors import HelperError
from .paths import cache_root, ensure_private_dir
from .log import log
from .processes import folder_in_use
from .cli import CliCommand


LAUNCHER_EXEC_RE = re.compile(r'exec\s+"([^"]+)"\s+"([^"]+)"')


APPIMAGE_MOUNT_RE = re.compile(r"^/tmp/\.mount_[^/]+/")


DEFAULT_CLI_SCRIPT = "resources/app.asar/js/logseq-cli.js"


APPIMAGE_SEARCH_DIRS = ["~/AppImages", "~/Applications", "~/.local/bin", "~/bin",
                        "~/Downloads", "/opt", "/opt/appimages"]


EXTRACT_TIMEOUT_SECONDS = 600


def default_launcher():
    for candidate in (os.path.expanduser("~/.local/bin/logseq"), shutil.which("logseq")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def parse_launcher(path):
    """Return (exe, script) from the launcher Logseq Desktop writes, if it is one."""
    try:
        with open(path, "r", errors="replace") as f:
            text = f.read(4096)
    except OSError:
        return None, None
    if "logseq-cli-managed" not in text:
        return None, None
    match = LAUNCHER_EXEC_RE.search(text)
    if not match:
        return None, None
    return os.path.expanduser(match.group(1)), match.group(2)


def is_appimage(path):
    if not path or not os.path.isfile(path):
        return False
    if path.lower().endswith(".appimage"):
        return True
    try:
        with open(path, "rb") as f:
            header = f.read(11)
        return header[8:11] in (b"AI\x01", b"AI\x02")
    except OSError:
        return False


def find_appimage():
    found = []
    for directory in APPIMAGE_SEARCH_DIRS:
        directory = os.path.expanduser(directory)
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            lower = name.lower()
            if "logseq" in lower and lower.endswith(".appimage"):
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    found.append(path)
    if not found:
        return None
    return max(found, key=lambda p: os.stat(p).st_mtime)


def appimage_key(path):
    st = os.stat(path)
    import hashlib
    raw = "%s|%d|%d" % (os.path.realpath(path), st.st_size, int(st.st_mtime))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def extract_appimage(appimage):
    """Unpack the AppImage once per version and return the unpacked root.

    Running the CLI through the AppImage itself is fragile: its files live in
    a temporary mount that disappears when the command exits, but the CLI
    starts a long-running database process from those same files. An
    unpacked copy has permanent paths and is the identical Logseq build.
    """
    root = cache_root()
    key = appimage_key(appimage)
    target = os.path.join(root, "appimage-" + key)
    unpacked = os.path.join(target, "squashfs-root")
    marker = os.path.join(target, ".complete")
    if os.path.exists(marker):
        return unpacked

    ensure_private_dir(root)
    import fcntl
    with open(os.path.join(root, ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if os.path.exists(marker):  # another helper finished it meanwhile
            return unpacked
        work = target + ".partial"
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        if not os.access(appimage, os.X_OK):
            raise HelperError("The Logseq AppImage is not executable: " + appimage)
        env = dict(os.environ)
        env.pop("ELECTRON_RUN_AS_NODE", None)
        log("unpacking %s into %s" % (appimage, target))
        started = time.time()
        try:
            proc = subprocess.run([appimage, "--appimage-extract"], cwd=work, env=env,
                                  capture_output=True, text=True,
                                  timeout=EXTRACT_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            log("unpack timed out after %ds" % EXTRACT_TIMEOUT_SECONDS)
            shutil.rmtree(work, ignore_errors=True)
            raise HelperError("Unpacking the Logseq AppImage timed out.")
        except OSError as exc:
            shutil.rmtree(work, ignore_errors=True)
            raise HelperError("Could not unpack the Logseq AppImage: %s" % exc)
        if proc.returncode != 0 or not os.path.isdir(os.path.join(work, "squashfs-root")):
            log("unpack failed after %.1fs: exit %d" % (time.time() - started, proc.returncode))
            shutil.rmtree(work, ignore_errors=True)
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise HelperError("Could not unpack the Logseq AppImage%s"
                              % (": " + detail[-1] if detail else "."))
        log("unpacked in %.1fs (exit %d)" % (time.time() - started, proc.returncode))
        shutil.rmtree(target, ignore_errors=True)
        os.rename(work, target)
        with open(marker, "w") as f:
            f.write(appimage + "\n")
        # Drop copies unpacked from older Logseq versions, unless a process
        # (a database process started before the update) still runs from one:
        # deleting its files underneath it could crash it mid-work.
        for name in os.listdir(root):
            old = os.path.join(root, name)
            if name.startswith("appimage-") and name != "appimage-" + key \
                    and not name.endswith(".partial"):
                if folder_in_use(old):
                    log("keeping %s: still in use" % name)
                else:
                    shutil.rmtree(old, ignore_errors=True)
    return unpacked


def appimage_command(appimage, launcher_script=None):
    unpacked = extract_appimage(appimage)
    rel = DEFAULT_CLI_SCRIPT
    if launcher_script and APPIMAGE_MOUNT_RE.match(launcher_script):
        rel = APPIMAGE_MOUNT_RE.sub("", launcher_script)
    script = os.path.join(unpacked, rel)
    asar = script.split(".asar", 1)[0] + ".asar" if ".asar" in script else script
    if not os.path.exists(asar):
        raise HelperError("This Logseq AppImage does not contain the command line tool "
                          "(%s). Is it the DB version of Logseq?" % rel)
    exe = electron_binary(unpacked)
    lib = os.path.join(unpacked, "usr", "lib")
    env = {"ELECTRON_RUN_AS_NODE": "1", "APPDIR": unpacked}
    if os.path.isdir(lib):
        env["LD_LIBRARY_PATH"] = lib + (":" + os.environ["LD_LIBRARY_PATH"]
                                        if os.environ.get("LD_LIBRARY_PATH") else "")
    return CliCommand([exe, script], env, source="appimage:" + appimage)


APPRUN_BIN_RE = re.compile(r'BIN="\$APPDIR/([^"/]+)"')


def electron_binary(unpacked):
    """The Electron executable inside an unpacked AppImage.

    AppRun is skipped on purpose: on systems without unprivileged user
    namespaces it adds --no-sandbox, a Chromium flag that has no place on a
    Node-mode command line.
    """
    apprun = os.path.join(unpacked, "AppRun")
    try:
        with open(apprun, "r", errors="replace") as f:
            match = APPRUN_BIN_RE.search(f.read(65536))
    except OSError:
        match = None
    if match:
        exe = os.path.join(unpacked, match.group(1))
        if os.access(exe, os.X_OK):
            return exe
    if os.access(apprun, os.X_OK):
        log("no Electron binary named in AppRun; falling back to AppRun")
        return apprun
    raise HelperError("Could not find Logseq's program inside the unpacked AppImage.")
