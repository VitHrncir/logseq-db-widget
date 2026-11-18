# WARNING - AI SLOP
I am not proud of it, but this codebase is based on a lot of AI generated code. I needed this widget for work reasons and, in a moment of weakness, I used a frontier LLM to generate the code. I *have* contributed to the codebase in some ways. Additionally, I have spent (and continue to spend) a lot of time on testing and auditing the code to ensure that the widget is safe. I still recommend backing up your DB frequently to ensure that you do not lose any data (though I have not lost any data personally).

# Logseq DB widget for KDE Plasma 6

A Plasma 6 widget for **Logseq DB graphs** (the database version, not Markdown graphs). It has three sections:

- **Journal** shows today's journal page and lets you add blocks and tasks to it.
- **TODO** lists every task in the graph. You can add tasks, tick them off, change status and priority, edit or delete them, and filter by status and by tag.
- **Pages** has up to six pinned pages plus an "Open page…" field for any other page. Clicking a `[[link]]` anywhere in the widget opens that page here.

On the desktop the widget shows everything directly. In a panel it shows as an icon with a popup.

## Requirements

- KDE Plasma 6.
- Python 3 (installed by default on practically every distribution).
- Logseq Desktop, DB version, with at least one DB graph. Both the AppImage and package installs work (see below).

Logseq does not have to be running. If it is, your changes appear in it live.

## AppImage installs

Logseq Desktop installs a small launcher for its command line tool at `~/.local/bin/logseq`. For the AppImage, that launcher points into the AppImage's temporary mount (`/tmp/.mount_logseq...`), which exists only while that Logseq window is open. Even with a correct path, running the CLI through the AppImage is fragile. The CLI starts a long-running database process from its own files, and the AppImage removes those files when the command ends.

So for AppImages, the widget unpacks your Logseq AppImage once into `~/.cache/logseq-db-widget` and runs the CLI from there. It is the identical Logseq build, so its database process matches the one the app uses, and it works whether or not Logseq is open. The first start takes a minute or so, and the copy uses a few hundred MB of disk. When the AppImage file changes (an update), the widget unpacks the new version and deletes the old copy.

The widget finds the AppImage from the launcher Logseq installs. If there's no launcher, it looks for `*logseq*.AppImage` in `~/AppImages`, `~/Applications`, `~/.local/bin`, `~/bin`, `~/Downloads` and `/opt`, but only *suggests* what it finds: unpacking an AppImage runs it, so the widget never runs one you haven't pointed it at. Set **Logseq AppImage** in the settings to use it.

## Logseq Sync graphs

The widget never logs in to Logseq Sync, and it doesn't need to. When Logseq Desktop opens a synced graph, it keeps a full copy in `~/logseq/graphs` and syncs that copy with the cloud. The widget reads and writes the same local copy, through the same database process the app uses.

That means a synced graph has to have been opened in Logseq Desktop on this computer at least once. If you have only used it in a browser or on another device, the widget shows "No Logseq graphs on this computer yet". Open Logseq Desktop, sign in to Logseq Sync, open the graph so it downloads, then press **Try again**.

When Logseq Desktop is running, your edits from the widget sync right away, because the app's sync is running. When the app is closed, nothing syncs unless you turn on **Keep syncing while Logseq Desktop is closed** in the settings.

### Signing in for background sync

Background sync uses Logseq Desktop's sign-in. The app writes its login to `~/logseq/auth.json`, which the CLI reads, and both use the same login client. So if you're signed in to Logseq Desktop, there's nothing more to do for an unencrypted graph.

Avoid `logseq login` in the CLI. It starts a *separate* sign-in that replaces the app's in that file, and the app swaps its own back the next time it renews its login. The two then keep overwriting each other.

### Encrypted graphs

For an end-to-end encrypted graph, background sync also needs the graph's encryption password, saved once:

1. Open Logseq Desktop, make sure you're signed in, and leave it open for a few minutes. This makes sure `auth.json` holds the app's sign-in, which is the one that lasts.
2. Close Logseq Desktop.
3. Run:

```sh
python3 tools/logseq-sync-sessions.py --set-e2ee-password
```

It asks for the password without showing it, saves it in your keyring, and starts sync. Name the graph after the option if you have more than one.

Logseq locks the saved password with the sign-in that was current when you saved it. After you sign in again, in Logseq Desktop or with `logseq login`, background sync can no longer unlock it, and the widget reports "Logseq can't unlock your saved encryption password". Run the command above again to fix it. Logseq Desktop isn't affected the same way, because it can ask you for the password.

The CLI only accepts the password on its command line. While the command runs (a second or two), other user accounts on this computer could see it in the process list. On a computer only you use, this doesn't matter.

With sign-in and password in place, the setting keeps sync running, and restarts it after a reboot whenever the widget starts. See "Security" below for what this trades off.

## Install

```sh
./install.sh
```

or, by hand:

```sh
kpackagetool6 -t Plasma/Applet -i package      # first install
kpackagetool6 -t Plasma/Applet -u package      # upgrade
```

You can also install the built package in `bin/` the same way: `kpackagetool6 -t Plasma/Applet -i bin/logseq-db.plasmoid` (or `-u` to upgrade).

Then right-click the desktop or a panel, choose **Add or Manage Widgets**, and add **Logseq DB**. If it doesn't appear in the list right away, log out and back in, or restart Plasma with `systemctl --user restart plasma-plasmashell`.

To try it without adding it anywhere: `plasmoidviewer -a io.github.logseqdbwidget` (part of the `plasma-sdk` package).

## Settings

**General**

- **Graph:** the DB graph to use. **Detect** lists the graphs the CLI can see. Left empty, the widget uses the CLI's current graph, or the only graph on this computer. If there are several and none is current, the widget asks you to pick one.
- **Logseq AppImage:** only needed if the widget can't find your AppImage by itself.
- **Other logseq CLI:** for non-AppImage installs whose launcher is not at `~/.local/bin/logseq`.
- **Python command:** defaults to `python3`.
- **Refresh every:** how often the widget reloads in the background. It also reloads after every change it makes and when you reopen the popup.
- **Logseq Sync:** keep syncing while Logseq Desktop is closed (off by default; see "Logseq Sync graphs" and "Security").
- **TODO list:** whether completed and canceled tasks show by default.

**Pages**

- **Page 1 to 6:** the pinned pages. Empty slots are hidden.
- **New tasks go to:** a page name, or empty for today's journal.

## Using it

- In the Journal and Pages sections, **Enter** adds a block and **Ctrl+Enter** adds a task. The two buttons next to the field do the same.
- Type `#tag` or `#[[two words]]` in a new block or task to tag it, as in Logseq's editor. A tag that doesn't exist yet is created. If a normal page already has that name, Logseq turns the page into a tag, keeping its content.
- Hover over a block or task to **edit** or **delete** it. Delete asks for a second click, because it also removes the block's children. Deleting works like it does in Logseq: the node moves to Logseq's Recycle, where you can restore it for 30 days. (The CLI's task list still includes recycled tasks, so the widget filters them out itself.)
- In the TODO section, the second dropdown filters by tag: pick one of your tags (each shows how many open tasks it has), "No tag" for untagged tasks, or "All tags". Clicking a tag under a task filters by that tag too. While a tag filter is active, tasks you add get that tag, so adding "milk" while filtered to `#shopping` files it there. The widget remembers the filter. Logseq's built-in tags such as `#Task` are not listed.
- In the TODO section, click a task's status or priority to pick any choice your graph has, including statuses and priorities you added in Logseq (such as "Waiting" or "Idea"). New choices appear at the next refresh. The status filter and the quick-add priority list include them too. Click its priority (or "Set priority" on hover) to change it. Overdue deadlines are shown in red.
- **The sync marker** at the bottom of the widget tells you where your changes are:
  - **Synced to the cloud** (green): saved and uploaded.
  - **Saved locally, uploading** while changes are on their way up.
  - **Saved locally, not synced to the cloud** (amber): on this computer only. Hover for why: sync is offline, isn't running (Logseq Desktop closed and background sync off), or has a problem.
  - **Saved locally (this graph doesn't sync)** for a local-only graph.
  - **Saving…** while a change is being written, and **Not saved** (red) if one failed. That stays until a later change saves.

  Click the marker to check again. Checking only reads: it never starts Logseq's database process.
- **Open in Logseq** (the button next to a page title) opens that page in the desktop app through a `logseq://` link.

## How it works

```
Plasma (QML)  ->  logseq_helper.py  ->  logseq CLI  ->  db-worker-node  <-  Logseq Desktop
```

The CLI and Logseq Desktop share one database process (`db-worker-node`) per graph. The widget therefore never touches `db.sqlite` itself, and there is only ever one writer.

Plasma runs commands through a shell. To keep your text out of the shell, the widget sends each request to the helper as percent-encoded JSON, which contains only letters, digits and `-_.%`. The helper then calls the CLI with an argument list, never a shell string.

## Security

What the widget does to stay safe with notes that other people may have written (shared Sync graphs, pasted or imported text):

- **Nothing is fetched to display a note.** Images in notes are shown as links, not loaded, so a note can't act as a tracking pixel. Raw HTML is shown as text, so it can't disguise where a link goes. Page titles, tag and status names are always shown as plain text.
- **Only web and email links open.** `file:` paths, app handlers (`steam://` and the like) and other schemes are blocked with a message. Hovering a link shows where it really goes.
- **Note text and page names can't inject CLI options.** Values are always passed as `--flag=value`, so a page named `--root-dir=...` stays a page name.
- **No shell is involved in running Logseq**, and the one shell command Plasma runs contains only fixed paths and the encoded request.
- **The widget's log is private** (readable by you only) and never contains note text, page names or error messages, only steps, exit codes and timings.
- **A found AppImage is never run** unless it came from Logseq's own launcher or your settings.

Residual risks you should know about:

- **Logseq's database process accepts unauthenticated local connections.** While it runs, other accounts on this computer, and in principle a malicious website using DNS rebinding, can read and change your notes through it. This is Logseq's design: the process runs whenever Logseq Desktop is open, with or without this widget. The widget stops its *own* copy (the one it starts while Logseq is closed) shortly after you stop using it, unless **Keep syncing while Logseq Desktop is closed** is on, in which case it stays running.

How the widget manages that process:

- **While Logseq Desktop is running, the widget changes nothing.** When the app starts it reuses any running database process, including one the widget started, so the widget can't tell whether the app is using it.
- **It only ever stops processes the CLI started**, never Logseq Desktop's own.
- **It never stops a process that is syncing.** That includes one that is only disconnected for the moment, for example during a network drop.
- **If it can't tell what state sync is in, it changes nothing.**
- **"Keep syncing" runs on a timer that doesn't depend on the widget being opened**, so it also starts after a reboot when the widget sits closed in a panel.
- **It keeps the background session's login fresh.** Logseq doesn't renew the login token of a sync session the CLI started; once the token expires (after about an hour), every reconnect is refused. With "Keep syncing" on, the widget hands the session a freshly renewed login every few minutes, which also rescues a session already stuck that way.
- **On a computer shared with other user accounts**, text you add is briefly visible to them in the process list (for about a second, in the logseq CLI's command line). The CLI offers no other way to pass task text. The widget's own request travels in the environment, which other accounts can't read.

## Data safety

The widget changes your graph only through Logseq's own CLI and database process, never the database file. These are the cases where that could still go wrong, and what the widget does about each:

- **Updating Logseq while it is open.** Every CLI command that reaches the database first makes Logseq shut down database processes from a *different Logseq version*, including the one the open app is using. If you replace the AppImage while Logseq Desktop is running, the widget would otherwise unpack the new version and take the running app's database away. While Logseq Desktop is running, the widget therefore compares versions first (using only commands that don't touch the database) and pauses with a message until you restart Logseq. `tools/logseq-sync-sessions.py` does the same.
- **Stopping Logseq's database process.** The widget only stops a process the CLI started, never while Logseq Desktop is running (checked again right before stopping), never while it is syncing, never while another widget instance is in the middle of a request, and never while the graph's database files were written in the last minute. Logseq's shutdown is orderly: requests in progress finish first.
- **The search index.** Logseq keeps it in a separate file and marks it valid only when a build finishes; a build cut short means a full rebuild at the next start. A build can still be running in the widget's process after you close Logseq Desktop (the app reuses that process), which is what the "written in the last minute" rule protects. Logseq opens its database files with exclusive locks, so two processes can't write them at once.
- **One copy of Logseq per graph.** If the widget's settings name one AppImage but Logseq Desktop last ran from another, the widget stops with a message instead of running a second Logseq version against your graph: two versions taking turns can each find the other's search index (and possibly database) in the wrong format. Leave the AppImage setting empty to follow Logseq Desktop automatically.
- **Editing a block that changed meanwhile.** If a block changes in Logseq or through sync between opening the widget's editor and saving, the save is refused instead of replacing the newer text.
- **Blocks with references** can't be edited in the widget, because saving would turn the references into plain text.
- **Deleting** moves the block to Logseq's Recycle, where it can be restored for 30 days.
- **Updates and old copies.** After a Logseq update, the old unpacked copy is deleted only once no process is still running from it.
- **Sync.** The widget only ever starts, renews and stops sync. It never runs the CLI's upload or download commands, which can replace a whole graph, and Logseq's sync does not reset local data on its own when it detects a mismatch (it logs a warning).

One thing the widget can't fully prevent: **if Logseq takes too long to answer** (2 to 3 minutes), the widget reports that it got no answer, but the change may still have been saved. Refresh before trying again, or you may add it twice.

## Known limitations

- **Tags typed while *editing* an existing block stay plain text.** The CLI only turns `#tag` into a tag when a block is created, so add tags to existing blocks in Logseq itself.
- **Not a full outliner.** You can add, edit, tick and delete blocks, but you can't indent, outdent or reorder them. Use **Open in Logseq** for that.
- **Blocks that reference other blocks can't be edited here.** The widget displays references as readable text, and saving that text would quietly turn them into plain page links. Editing such a block shows a message and leaves it unchanged.
- **Formatting is simplified.** Block text is rendered with Qt's Markdown support. Logseq-specific content (embeds, queries, code blocks, images) does not render as it does in the app.
- **The TODO list only shows tasks tagged `#Task` itself.** That is what `logseq list task` returns. Tasks that use a custom tag extending `#Task` are not listed.
- **Each refresh starts the CLI**, which takes a moment. The busy spinner in the header shows when a request is running.
- **Version coupling.** The DB version and its CLI are still changing. If a Logseq update changes the CLI's output, the widget may need an update too. Always use the launcher Logseq installs. A CLI from a different Logseq version will restart the app's database process when it connects.
- **Sync.** See "Logseq Sync graphs" above: edits made while Logseq Desktop is closed sync the next time it runs, unless you sign the CLI in.
- **Untested environments.** The QML is tested headlessly against stand-in KDE modules (see below), not inside a live Plasma session. Flatpak installs of Logseq are untested and may not provide `~/.local/bin/logseq`.

## Troubleshooting

### Logseq reports a search index problem, or re-indexes at startup

Check whether anything cut an index build short, or whether two Logseq versions were involved:

```sh
grep -hE "index-build-failed|post-commit-handler-failed|fts-rowid-migration-failed|stale search index" ~/logseq/graphs/*/db-worker-node-*.log | tail -20
grep -E "decision: stopped|graph-busy|version guard|appimage" ~/.cache/logseq-db-widget/helper.log | tail -20
grep exec ~/.local/bin/logseq        # the AppImage Logseq Desktop last ran from
```

- **`decision: stopped` shortly before the Logseq start that showed the problem** means the widget stopped its process around then. Since 0.14.1 it waits while the database is busy (`graph-busy`).
- **A different AppImage in the last command than in the widget's settings** means two copies of Logseq were in play. Since 0.14.1 the widget refuses to run in that case.
- **To repair the index**, run "Rebuild search index" from Logseq's command palette. The index is derived from your notes, so rebuilding loses nothing.

### Background sync doesn't start

With Logseq Desktop closed and "Keep syncing" on, three places tell you why:

```sh
grep decision ~/.cache/logseq-db-widget/helper.log | tail -5         # what the widget decided
python3 tools/logseq-sync-sessions.py --list                         # what's running, and sync state
grep -h "start-skipped\|db-sync" ~/logseq/graphs/*/db-worker-node-*.log | tail -20   # Logseq's reason
```

- **`desktop-open` in the widget's decisions** means it thinks Logseq Desktop is still running; `ps -o args= -u $USER | grep -i logseq` shows what it's seeing.
- **`sync-skipped`** means Logseq accepted "start sync" but didn't start it. Its own log (the third command) names the reason, such as `:client-op-not-ready`.
- **Sync running but marked offline** usually means a network or sign-in problem; hover over the marker for details.

The helper logs every step to `~/.cache/logseq-db-widget/helper.log`: which Logseq it found, unpacking, each CLI command with its exit code and duration, and errors. It never logs your note text or page names. Watch it live while the widget starts:

```sh
tail -f ~/.cache/logseq-db-widget/helper.log
```

If there is no log file at all, the helper has never run, which points at Plasma or Python rather than Logseq. Check, in order:

```sh
P=~/.local/share/plasma/plasmoids/io.github.logseqdbwidget
grep '"Version"' $P/metadata.json                                 # is the new version installed?
python3 $P/contents/code/logseq_helper.py '{"op": "ping"}'        # does the helper run? (creates the log)
journalctl --user -b | grep -i logseq                             # QML errors and the widget's own messages
plasmoidviewer -a io.github.logseqdbwidget                        # QML errors, printed to the terminal
```

At startup the widget first does a quick round trip that doesn't involve Logseq. If Plasma's command runner (the "executable" data engine from the `plasma5support` package) isn't available, the widget says so immediately. If the helper never answers for any other reason, the widget gives up after 25 seconds and shows a "Details" line describing its internal state; you can select and copy it. An error inside the widget's own code during setup is shown on screen the same way. If a line starting with `run:` has no `exit ...` line after it, that CLI command is hanging.

Any request that runs too long is stopped and shown as an error (15 minutes for unpacking, 5 for finding graphs, 3 for everything else), so the widget should never wait forever.

If the widget shows a setup message instead of your notes, it says what is missing: the CLI, any graph at all, or the graph named in the settings. To see what the CLI sees:

```sh
ls ~/logseq/graphs
python3 "$H" '{"op": "prepare"}'     # find (and if needed unpack) Logseq
python3 "$H" '{"op": "setup"}'     # $H as defined below
```

Run the helper directly. It prints exactly what the widget receives:

```sh
H=~/.local/share/plasma/plasmoids/io.github.logseqdbwidget/contents/code/logseq_helper.py
python3 "$H" '{"op": "setup"}'
python3 "$H" '{"op": "graphs"}'
python3 "$H" '{"op": "journal", "graph": "my-graph"}'
python3 "$H" '{"op": "tasks", "graph": "my-graph"}'
```

QML errors from the widget appear in the Plasma log: `journalctl --user -f -t plasmashell`.

## Tools for testing

`tools/` has two scripts for testing on real machines, described with a full test plan in `TESTING.md`:

- **`tools/logseq-sync-sessions.py`** lists every Logseq database process and its sync state, then closes the ones the CLI started. `--list` only lists. It leaves Logseq Desktop's processes alone, and does nothing while the app is running unless you pass `--force`. `--set-e2ee-password` saves an encrypted graph's password for background sync (see "Encrypted graphs").
- **`tools/purge-logseq-widget.py`** removes the widget and everything it created, for a clean slate: widget instances and their settings, packages, caches and unpacked AppImages. It never touches your graphs, Logseq itself, your sign-in or saved passwords. Try `--dry-run` first.

## Tests

```sh
python3 tests/test_helper.py                       # helper, against a fake CLI
python3 tests/test_tools.py                        # the two scripts in tools/
pip install PySide6-Essentials
python3 tests/qml/run_ui_test.py                   # the real QML, headless
```

`tests/test_helper.py` runs the helper against a fake `logseq` executable, and against a fake AppImage with a stale launcher like the one Logseq writes. The fake answers with JSON in the shapes the real CLI produces (taken from Logseq's own CLI end-to-end tests). The tests cover argument building, shell metacharacters and Unicode in user text, journal creation in each date format Logseq supports, task sorting, and error handling.

`tests/qml/run_ui_test.py` loads the real widget QML in a headless Qt Quick engine, with small stand-ins for the KDE modules in `tests/qml/stubs`. Its process runner really executes commands, so each check goes through the whole chain to the fake CLI. Any QML warning from the widget's files fails the run. Set `SHOT_DIR=/some/dir` to save a screenshot of each section.

## Layout

```
package/                       the Plasma package
  metadata.json
  contents/config/main.xml     settings schema
  contents/config/config.qml   settings pages
  contents/code/logseq_helper.py   talks to the Logseq CLI
  contents/ui/main.qml         entry point
  contents/ui/FullRepresentation.qml   tabs, setup flow, refreshing
  contents/ui/SetupPanel.qml   shown until the CLI and a graph are found
  contents/ui/JournalView.qml, TodoView.qml, PagesView.qml
  contents/ui/BlockPane.qml, BlockDelegate.qml, TaskDelegate.qml, Composer.qml
  contents/ui/Backend.qml      runs the helper, one request at a time
  contents/ui/SyncKeeper.qml   background-sync maintenance on a schedule
  contents/ui/logic.js         shared display and link rules
  contents/ui/configGeneral.qml, configPages.qml
tests/
  test_helper.py               the helper, against a fake Logseq CLI
  test_tools.py                the scripts in tools/
  qml/run_ui_test.py           the real QML, headless (stand-ins in qml/stubs/)
tools/
  logseq-sync-sessions.py      list and close Logseq CLI sync sessions
  purge-logseq-widget.py       remove the widget and everything it created
  make-release.sh              build bin/logseq-db.plasmoid and the release tarball
bin/
  logseq-db.plasmoid           the built widget, ready to install (in release tarballs)
TESTING.md                     test plan for real machines
install.sh                     install or upgrade for the current user
```

## License

Public domain, under the [Unlicense](https://unlicense.org): use, copy, modify and share it for any purpose, without conditions. See `LICENSE`.
