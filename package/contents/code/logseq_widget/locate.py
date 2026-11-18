"""Choosing which Logseq CLI to run: Logseq's launcher, or an unpacked AppImage."""

import os

from .errors import HelperError
from .appimage import appimage_command, default_launcher, find_appimage, is_appimage, parse_launcher
from .cli import CliCommand


def find_cli(configured, configured_appimage=None):
    """Work out how to run the logseq CLI on this machine."""
    if configured:
        path = os.path.expanduser(configured)
        if is_appimage(path):
            return appimage_command(path)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return CliCommand([path], source=path)
        raise HelperError("The configured logseq CLI path is not an executable file: " + path)

    launcher = default_launcher()
    exe, script = parse_launcher(launcher) if launcher else (None, None)

    if configured_appimage:
        path = os.path.expanduser(configured_appimage)
        if not is_appimage(path):
            raise HelperError("The configured Logseq AppImage was not found: " + path)
        # Logseq Desktop rewrites its launcher at every start, naming the
        # AppImage it runs from. If that is a different file, the widget
        # would run another Logseq version against the same graph whenever
        # the app is closed: two versions taking turns on one database and
        # one search index, each expecting its own format.
        if is_appimage(exe) and os.path.realpath(exe) != os.path.realpath(path):
            raise HelperError(
                "The widget is set to use %s, but Logseq Desktop last ran from %s. Using "
                "two copies of Logseq on one graph can break its search index and sync. "
                "Clear the AppImage path in the widget settings to follow Logseq Desktop "
                "automatically, or set it to the file you actually run."
                % (path, exe), "appimage-conflict")
        return appimage_command(path)

    if is_appimage(exe):
        return appimage_command(exe, script)
    if launcher and (script is None or os.path.exists(script)):
        # Package installs (deb, rpm, tarball) have stable paths.
        return CliCommand([launcher], source=launcher)

    # A found AppImage is only suggested, never run: unpacking an AppImage
    # executes it, and a file can land in ~/Downloads without your intent.
    found = find_appimage()
    hint = (" Found %s; to use it, set it as the Logseq AppImage in the widget settings." % found
            if found else "")
    raise HelperError(
        "Could not find Logseq. Start Logseq Desktop (DB version) once so it installs "
        "~/.local/bin/logseq, or set the path to your Logseq AppImage in the widget "
        "settings." + hint
    )
