# Testing the widget on real machines

The automated tests (`tests/`) run the real code against a fake Logseq CLI and a stand-in for Plasma. They can't cover real Plasma versions, real Logseq builds, systemd, networks or other distributions. This list is for that.

## Before every round

```sh
python3 tools/purge-logseq-widget.py --dry-run   # see what would go
python3 tools/purge-logseq-widget.py             # clean slate (asks first)
kpackagetool6 -t Plasma/Applet -i bin/logseq-db.plasmoid   # or: -i package
systemctl --user restart plasma-plasmashell
```

While testing, keep two terminals open:

```sh
tail -f ~/.cache/logseq-db-widget/helper.log
watch -n 10 python3 tools/logseq-sync-sessions.py --list
```

The sessions list shows each Logseq database process, who started it (`cli` or `electron`) and its sync state. Each `decision:` line in the log says what the widget decided and why, for example `maintain: decision: none, desktop-open (background sync on)`.

## The machine matrix

Record for each machine: distribution and version, `plasmashell --version`, Logseq version, how Logseq is installed (AppImage, distribution package, AUR, Flatpak), and whether the graph is local, synced, or synced with end-to-end encryption.

- **Fedora** (current release), **Arch**, **Kubuntu 25.04 or later**, **openSUSE Tumbleweed**. Kubuntu 24.04 LTS ships Plasma 5, which the widget doesn't support.
- At least one non-AppImage install. On Arch, an AUR package that runs Logseq with the system Electron is the most useful, because it exercises a different desktop-detection path.
- Flatpak Logseq is untested territory; note what happens.

## Background sync (highest priority)

Sync state words used below: `open` means connected; `closed` means a sync client exists but is disconnected or reconnecting; `stopped` and `inactive` mean no sync is running.

1. **Logseq Desktop is never interrupted.** With "Keep syncing" off, open Logseq Desktop, use the widget, then keep working in Logseq for 5 minutes. The log should show `maintain` with reason `desktop-open`, and Logseq should never show a database or connection error.
2. **The case that used to break.** Close Logseq Desktop. Use the widget so it starts its own database process (owner `cli` in the sessions list). Open Logseq Desktop again, which reuses that process. Work in Logseq for 5 minutes, especially with a *local-only* graph. Expected: nothing stops; the log shows `desktop-open`. Previously the widget could stop the database under the app here.
3. **Idle stop.** Logseq Desktop closed, "Keep syncing" off: use the widget, then leave it. The CLI's process should disappear about 2 minutes later (log: `stopped idle process`). A background refresh alone should stop it again a few seconds after it finishes.
4. **Keep syncing after a reboot, panel placement.** Put the widget in a panel, turn "Keep syncing" on, reboot, and *don't* open the widget. Within about a minute of logging in, the sessions list should show a `cli` process with sync `open`. Edit something on another device; it should reach this machine's graph without Logseq Desktop running.
5. **Same on the desktop**, with the widget placed on the desktop instead.
   Also with the widget in active use: with Logseq Desktop closed and "Keep syncing" on, add a few blocks in a row. Sync should start within seconds of the first one (log: `maintain: decision: sync-started`), and the marker should reach "Synced to the cloud" without opening Logseq.
6. **Hours of background sync.** With Logseq Desktop closed and "Keep syncing" on, leave the machine for more than 2 hours, including at least one suspend and resume or network drop. Afterwards the marker should still reach "Synced to the cloud" after a change, and Logseq's log should show no long run of failing reconnects:

   ```sh
   grep -h "ws-reconnect-scheduled" ~/logseq/graphs/*/db-worker-node-*.log | tail -3   # attempt numbers should stay small
   grep decision ~/.cache/logseq-db-widget/helper.log | tail -5                        # "login-renewed" every few minutes
   ```

7. **Network drop.** With sync running (either way), disconnect the network for 2 minutes, then reconnect. While offline the state should read `closed`, and the widget must neither stop the process nor start a second sync. After reconnecting it should return to `open` by itself. Also try suspend and resume.
8. **Login problems surface.** With "Keep syncing" on, sign out in Logseq Desktop, which also signs the CLI out. The widget should show one "Background sync:" error, not one every few minutes. Sign back in; the error should not return.
9. **Encrypted graph.** Open Logseq Desktop signed in for a few minutes, close it, then save the password with `python3 tools/logseq-sync-sessions.py --set-e2ee-password`. "Keep syncing" should then start sync without asking. Check that the password is not echoed while you type.
10. **A new sign-in invalidates the saved password.** After step 8, sign out and back in to Logseq Desktop, then close it. Background sync should report "Logseq can't unlock your saved encryption password" (Logseq's code `decrypt-text-by-text-password`), once. Running `--set-e2ee-password` again should fix it. Note whether Logseq Desktop asked for the password when you signed back in.
11. **Plasma restarts.** Run `systemctl --user restart plasma-plasmashell` with "Keep syncing" on. Processes the widget started live in Plasma's service and are expected to be stopped with it. Sync should be running again within about a minute.
12. **A session you started yourself.** Start sync from a terminal (`sync start`), with "Keep syncing" *off*. The widget must leave it alone (reason `syncing`). Then close that terminal: does the process survive? Record the answer; it depends on how your desktop runs terminal sessions.
13. **Two instances, different settings.** One instance with "Keep syncing" on and one with it off, same graph. Sync should stay up; the "off" instance must not stop it.
14. **How long `sync start` takes** the first time on a large graph. If it takes longer than 3 minutes, the widget reports a timeout even though sync may still start; note it.
15. **Desktop detection on each install type.** With Logseq Desktop open, run:

    ```sh
    python3 ~/.local/share/plasma/plasmoids/io.github.logseqdbwidget/contents/code/logseq_helper.py '{"op": "maintain"}'
    ```

    The answer must contain `"reason": "desktop-open"`. With Logseq closed it must not. If it's wrong for an install type, `ps -o args= -u $USER | grep -i logseq` shows what the process looks like.

## Data safety

1. **Updating Logseq while it is open.** With Logseq Desktop running, replace the AppImage file with a different Logseq version (keep the same file name). The widget should show "Logseq Desktop is running a different Logseq version..." and do nothing else; Logseq Desktop must keep working, and `python3 tools/logseq-sync-sessions.py --list` should say the process "runs a different Logseq version" without querying it. After restarting Logseq Desktop, the widget should work again. Check `~/logseq/graphs/*/db-worker-node-*.log` for unexpected shutdowns around that time.
2. **Edit conflict.** Open a block's editor in the widget, change the same block in Logseq Desktop, then save in the widget: the save should be refused with "This block changed while you were editing it", and Logseq's version should be intact.
3. **Two instances.** With two widget instances on the same graph, add blocks quickly in one while the other sits idle with "Keep syncing" off. No change should report "Not saved".
4. **Search index build.** With a large graph, close Logseq Desktop, use the widget (so it starts its own process), open Logseq Desktop, run "Rebuild search index" from the command palette and close Logseq while it shows "Indexing". The widget's log should show `graph-busy` instead of `stopped` until the build is done, and the next Logseq start should not re-index.
5. **Two AppImages.** Set the widget's AppImage path to a different Logseq file than the one you run. The widget should show "The widget is set to use ... but Logseq Desktop last ran from ..." and do nothing else.
6. **Old copies.** After an update with Logseq Desktop closed, `ls ~/.cache/logseq-db-widget` should show the old `appimage-...` folder only while a process started from it is still running.

## Everything else

- **First start:** the setup screen, unpacking time, and that the widget works with Logseq Desktop closed.
- **Graph choice:** one graph (picked automatically) and several (chooser appears).
- **Journal:** your date format; adding blocks and tasks; `#tags` (new, existing, `#[[two words]]`); a tag named like an existing page.
- **TODO:** tag filter; your own statuses and priorities appear in the menus within one refresh; deleting a task.
- **Pages:** pinned pages; a page that doesn't exist yet; clicking `[[links]]`.
- **Sync marker:** with Logseq Desktop open and a synced graph, add a block: "Saving…", then "Synced to the cloud". Disconnect the network and add another: "Saved locally, not synced" (hover says offline), then "Synced" again after reconnecting (click to check sooner). With Logseq closed and background sync off: "Saved locally, not synced", with the reason on hover. A local-only graph: "this graph doesn't sync".
- **Safety:** a note with an image link must not load the image; a `file://` link must be blocked with a message.
- **Updating Logseq:** replace the AppImage; the next start should unpack the new version and delete the old copy in `~/.cache/logseq-db-widget`.

## When reporting a problem

Include the machine details above, the relevant part of `~/.cache/logseq-db-widget/helper.log` (it never contains note text), the output of `python3 tools/logseq-sync-sessions.py --list`, and anything from `journalctl --user -b | grep -i logseq`.
