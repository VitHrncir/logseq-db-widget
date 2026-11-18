#!/usr/bin/env python3
"""Remove the Logseq widget and everything it created, for a clean test.

    python3 purge-logseq-widget.py --dry-run   # show what would be removed
    python3 purge-logseq-widget.py             # remove (asks first)
    python3 purge-logseq-widget.py --yes       # remove without asking

Covers the widget (io.github.logseqdbwidget):

  1. closes database processes and sync sessions the CLI started
     (runs logseq-sync-sessions.py, which must sit next to this script)
  2. stops widget helper processes that are still running
  3. removes every widget instance, and its settings, from Plasma's
     configuration (backed up first; Plasma is stopped briefly for this)
  4. uninstalls the widget packages
  5. deletes the widgets' caches, including unpacked AppImages and logs,
     and Plasma's compiled-QML cache, so the next install starts fresh
  6. starts Plasma again

Never touched: your graphs (~/logseq), Logseq Desktop and its launcher
(~/.local/bin/logseq), the CLI's settings, your sign-in (~/logseq/auth.json,
shared with Logseq Desktop) and saved encryption passwords.
"""
import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time

WIDGET_IDS = ["io.github.logseqdbwidget"]
HOME = os.path.expanduser("~")
CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
CACHE = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
DATA = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")

# Plasma keeps every widget instance, and its settings, in these files.
APPLET_CONFIGS = ["plasma-org.kde.plasma.desktop-appletsrc", "plasmoidviewer-appletsrc"]
CACHE_DIRS = ["logseq-db-widget", os.path.join("plasmashell", "qmlcache")]
HERE = os.path.dirname(os.path.abspath(__file__))


def say(dry, text):
    print(("[dry run] " if dry else "") + text)


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


# --------------------------------------------------------------------------
# Plasma's applet configuration
# --------------------------------------------------------------------------

HEADER_RE = re.compile(r"^(\[[^\]\n]*\])+\s*$")


def widget_groups(text):
    """Group prefixes such as "[Containments][1][Applets][7]" of our widgets."""
    prefixes, header = [], None
    for line in text.splitlines():
        if HEADER_RE.match(line):
            header = line.strip()
        elif header and line.strip() in ("plugin=" + w for w in WIDGET_IDS):
            prefixes.append(header)
    return prefixes


def without_groups(text, prefixes):
    """The file with those groups and all their subgroups removed."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if HEADER_RE.match(line):
            header = line.strip()
            skipping = any(header == p or header.startswith(p + "[") for p in prefixes)
        if not skipping:
            out.append(line)
    return "".join(out)


def plasma_running():
    if run(["systemctl", "--user", "is-active", "--quiet", "plasma-plasmashell.service"]).returncode == 0:
        return "systemd"
    if run(["pgrep", "-u", str(os.getuid()), "-x", "plasmashell"]).returncode == 0:
        return "process"
    return None


def stop_plasma(how):
    if how == "systemd":
        run(["systemctl", "--user", "stop", "plasma-plasmashell.service"])
    else:
        if run(["kquitapp6", "plasmashell"]).returncode != 0:
            run(["pkill", "-u", str(os.getuid()), "-x", "plasmashell"])
    for _ in range(20):
        if not plasma_running():
            return True
        time.sleep(0.5)
    return False


def start_plasma(how):
    if how == "systemd":
        run(["systemctl", "--user", "start", "plasma-plasmashell.service"])
    else:
        subprocess.Popen(["plasmashell"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="show what would be removed")
    parser.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args()
    dry = args.dry_run

    # Survey first, so the confirmation can say exactly what will happen.
    configs = {}
    for name in APPLET_CONFIGS:
        path = os.path.join(CONFIG, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="surrogateescape") as f:
                text = f.read()
            groups = widget_groups(text)
            if groups:
                configs[path] = (text, groups)
    packages = [w for w in WIDGET_IDS if os.path.isdir(os.path.join(DATA, "plasma", "plasmoids", w))]
    system_packages = [d for w in WIDGET_IDS for d in
                       (os.path.join("/usr/share/plasma/plasmoids", w),
                        os.path.join("/usr/local/share/plasma/plasmoids", w)) if os.path.isdir(d)]
    caches = [os.path.join(CACHE, d) for d in CACHE_DIRS if os.path.exists(os.path.join(CACHE, d))]

    print("This will:")
    print("  - close database processes and sync sessions the Logseq CLI started")
    print("  - stop running widget helper processes")
    for path, (_text, groups) in configs.items():
        print("  - remove %d widget instance(s) from %s (backup kept)" % (len(groups), path))
    for w in packages:
        print("  - uninstall %s" % w)
    for c in caches:
        print("  - delete %s" % c)
    if configs:
        print("  - stop Plasma for a moment while its configuration is edited")
    if not (configs or packages or caches):
        print("  (no widget packages, instances or caches found)")
    if system_packages:
        print("\nAlso installed system-wide (remove these yourself, with sudo):")
        for d in system_packages:
            print("  " + d)
    print("\nNot touched: your graphs, Logseq Desktop and its launcher, CLI settings, "
          "your sign-in and saved encryption passwords.")

    if not dry and not args.yes:
        if input("\nContinue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing changed.")
            return 1
    print()

    # 1. Database processes and sync sessions. The CLI lives in the caches
    #    deleted below, so this has to happen first.
    sessions = os.path.join(HERE, "logseq-sync-sessions.py")
    if os.path.exists(sessions):
        say(dry, "Closing CLI database processes and sync sessions:")
        result = run([sys.executable, sessions] + (["--list"] if dry else []))
        print("    " + result.stdout.strip().replace("\n", "\n    "))
    else:
        print("logseq-sync-sessions.py not found next to this script; skipping step 1.")

    # 2. Helper processes still running.
    found = run(["pgrep", "-u", str(os.getuid()), "-f", r"logseq_helper\.py"])
    pids = [int(p) for p in found.stdout.split() if p.strip().isdigit()]
    if pids:
        say(dry, "Stopping helper processes: %s" % ", ".join(map(str, pids)))
        if not dry:
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass

    # 3. Widget instances in Plasma's configuration. Plasma writes this file
    #    when it exits, so it must not be running while we edit it.
    plasma = None
    if configs:
        plasma = plasma_running() if not dry else None
        if plasma:
            print("Stopping Plasma...")
            if not stop_plasma(plasma):
                print("Plasma did not stop; leaving its configuration alone.")
                configs = {}
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for path, (text, groups) in configs.items():
            say(dry, "Removing %s from %s" % (", ".join(groups), path))
            if not dry:
                shutil.copy2(path, path + ".bak-logseq-" + stamp)
                # Write a new file and swap it in, so a crash can't leave
                # Plasma's configuration half-written.
                with open(path + ".new", "w", encoding="utf-8", errors="surrogateescape") as f:
                    f.write(without_groups(text, groups))
                    f.flush()
                    os.fsync(f.fileno())
                shutil.copymode(path, path + ".new")
                os.replace(path + ".new", path)
                print("    backup: %s" % (path + ".bak-logseq-" + stamp))

    # 4. Packages.
    for w in packages:
        say(dry, "Uninstalling %s" % w)
        if not dry:
            result = run(["kpackagetool6", "-t", "Plasma/Applet", "-r", w])
            folder = os.path.join(DATA, "plasma", "plasmoids", w)
            if os.path.isdir(folder):  # kpackagetool6 missing or failed
                shutil.rmtree(folder, ignore_errors=True)
            if result.returncode != 0 and os.path.isdir(folder):
                print("    could not remove %s: %s" % (folder, result.stderr.strip()))

    # 5. Caches.
    for c in caches:
        say(dry, "Deleting %s" % c)
        if not dry:
            shutil.rmtree(c, ignore_errors=True)

    # 6. Plasma back.
    if plasma:
        print("Starting Plasma again...")
        start_plasma(plasma)

    print("\nDone." if not dry else "\nDry run finished; nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
