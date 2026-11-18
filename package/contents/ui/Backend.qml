import QtQuick
import org.kde.plasma.plasma5support as P5Support

// Runs logseq_helper.py one request at a time and hands the parsed result to
// a callback: callback(ok, data, error).
//
// The request is JSON, percent-encoded so that the shell command string only
// ever contains [A-Za-z0-9-_.%]. User text therefore never reaches the shell
// as anything but inert data; the helper then calls the CLI with an argv list.
//
// A watchdog fails any request that runs past its time limit, so a hung step
// shows an error instead of leaving the widget waiting forever.
Item {
    id: backend
    visible: false

    property string cliPath: ""
    property string appImagePath: ""
    property string graph: ""
    property string pythonCommand: "python3"

    // Keep the CLI's database process syncing while Logseq Desktop is closed.
    // Off: the widget stops that process when idle (never the app's own).
    property bool backgroundSync: false
    // Requests queued while this is true count as background work (the
    // refresh timer), not as you using the widget.
    property bool backgroundMode: false
    // How long after your last use the process is kept for quick responses,
    // and how soon after background-only work it is stopped.
    property int idleSeconds: 120
    property int backgroundIdleSeconds: 5
    property double lastUserActivity: 0
    property bool _needsMaintenance: false

    // Where your changes are, for the sync marker:
    //   "saving"     a change is being written to the local graph
    //   "failed"     a change was not saved (stays until a later one saves)
    //   "local"      saved to the local graph, not (yet) in the cloud
    //   "local-only" saved to the local graph, which doesn't sync
    //   "uploading"  saved locally and being uploaded right now
    //   "cloud"      saved locally and synced to the cloud
    //   "unknown"    not checked yet, or couldn't be read
    property string syncState: "unknown"
    property string syncDetail: ""
    property int syncPending: 0
    property int _writesInFlight: 0
    property double _lastStatusCheck: 0
    property double _lastAutoStart: 0
    // Why background sync couldn't start last time, for the marker's tooltip.
    property string _lastSyncProblem: ""
    // Ops that run quietly in the background: no banners, and they don't
    // count as using the widget or keep Logseq's process alive.
    readonly property var quietOps: ["ping", "prepare", "setup", "maintain", "syncStatus"]
    property string _lastMaintainError: ""

    // Time limits in seconds. "prepare" may unpack the AppImage.
    property var timeouts: ({ ping: 20, prepare: 900, setup: 300, _default: 180 })

    property int pendingCount: 0
    readonly property bool busy: pendingCount > 0
    // Seconds the current request has been running, for progress display.
    property int currentElapsed: 0
    property string currentOp: ""

    readonly property string logPath: "~/.cache/logseq-db-widget/helper.log"

    // A write succeeded; views should reload.
    signal changed()
    // Something the user should see (errors, refusals).
    signal notice(string text)

    readonly property var writeOps: ["append", "taskAdd", "taskSet", "edit", "remove"]

    property int _seq: 0
    property var _queue: []
    property var _current: null      // { reqId, op, cmd, callback, started }
    property var _abandoned: ({})    // commands we gave up on; ignore their late output

    property string helperPath: {
        var url = Qt.resolvedUrl("../code/logseq_helper.py").toString();
        if (url.indexOf("file://") === 0)
            url = url.substring(7);
        return decodeURIComponent(url);
    }

    // Where the helper lives if Plasma reports the package location in a form
    // the path above can't use. Tried in order by the shell.
    readonly property var helperFallbacks: [
        "$HOME/.local/share/plasma/plasmoids/io.github.logseqdbwidget/contents/code/logseq_helper.py",
        "/usr/share/plasma/plasmoids/io.github.logseqdbwidget/contents/code/logseq_helper.py",
        "/usr/local/share/plasma/plasmoids/io.github.logseqdbwidget/contents/code/logseq_helper.py"
    ]

    function _command(arg) {
        // Fallback entries are double-quoted, so the shell still expands $HOME.
        var script = "H=" + _shellQuote(helperPath);
        for (var i = 0; i < helperFallbacks.length; ++i)
            script += "; [ -f \"$H\" ] || H=\"" + helperFallbacks[i] + "\"";
        // The request travels in the environment, which other user accounts
        // can't read, rather than on the helper's command line.
        return script + "; export LOGSEQ_WIDGET_REQUEST=" + arg
            + "; exec " + _shellQuote(pythonCommand || "python3") + " \"$H\"";
    }

    Component.onCompleted: console.log("Logseq widget helper:", helperPath)

    function notify(text) {
        notice(text);
    }

    readonly property string runnerProblem: i18n("Plasma's command runner (the \"executable\" data engine from the plasma5support package) is not available, so the widget can't start its helper.")

    // One line of internal state, shown when setup fails so it can be reported.
    function diagnostics() {
        var job = _current;
        return "runner valid: " + runner.valid
            + "; engine: " + runner.engine
            + "; python: " + (pythonCommand || "python3")
            + "; helper: " + helperPath
            + "; queued: " + _queue.length
            + "; running: " + (job ? job.op + " for " + Math.round((Date.now() - job.started) / 1000) + " s" : "none")
            + "; connected: " + runner.connectedSources.length;
    }

    function _shellQuote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'";
    }

    function _encode(obj) {
        return encodeURIComponent(JSON.stringify(obj)).replace(/[!'()*~]/g, function (c) {
            return "%" + c.charCodeAt(0).toString(16).toUpperCase();
        });
    }

    function call(op, params, callback) {
        try {
            _enqueue(op, params, callback);
        } catch (err) {
            console.warn("Logseq widget: could not queue", op, err);
            var message = i18n("Internal widget error while starting %1: %2", op, String(err));
            if (callback)
                callback(false, null, message);
            notice(message);
        }
    }

    function _enqueue(op, params, callback) {
        _seq += 1;
        var req = {};
        if (params) {
            for (var key in params)
                req[key] = params[key];
        }
        req.op = op;
        req.reqId = _seq;
        req.cli = cliPath;
        req.appImage = appImagePath;
        req.graph = graph;

        // reqId is part of the encoded payload, so every command string is
        // unique and the executable engine never merges two requests.
        var cmd = _command(_encode(req));
        _queue.push({ reqId: _seq, op: op, cmd: cmd, callback: callback || null, started: 0 });
        if (!backgroundMode && quietOps.indexOf(op) === -1)
            lastUserActivity = Date.now();
        if (writeOps.indexOf(op) !== -1) {
            _writesInFlight += 1;
            syncState = "saving";
            syncDetail = i18n("Saving your change to the local graph…");
        }
        pendingCount += 1;
        _next();
    }

    function _next() {
        if (_current === null && _queue.length === 0) {
            _scheduleMaintenance();
            // Look at sync now and then, while there's work anyway.
            if (Date.now() - _lastStatusCheck > 60000 && !statusTimer.running)
                checkSyncSoon(1000);
            return;
        }
        if (_current !== null)
            return;
        var job = _queue.shift();
        if (!runner.valid) {
            console.warn("Logseq widget: executable data engine not available");
            _deliver(job, { ok: false, error: runnerProblem });
            _next();
            return;
        }
        _current = job;
        _current.started = Date.now();
        currentOp = _current.op;
        currentElapsed = 0;
        watchdog.start();
        try {
            runner.connectSource(_current.cmd);
        } catch (err) {
            console.warn("Logseq widget: connectSource failed", err);
            _current = null;
            currentOp = "";
            watchdog.stop();
            _deliver(job, { ok: false, error: i18n("Internal widget error while running %1: %2", job.op, String(err)) });
            _next();
        }
    }

    function _deliver(job, res) {
        pendingCount = Math.max(0, pendingCount - 1);
        if (writeOps.indexOf(job.op) !== -1) {
            _writesInFlight = Math.max(0, _writesInFlight - 1);
            if (!res.ok) {
                syncState = "failed";
                syncDetail = i18n("A change was not saved: %1", res.error || "");
            } else if (_writesInFlight === 0) {
                syncState = "local";
                syncDetail = i18n("Saved to the local graph. Checking sync…");
                // Before the idle stop can end Logseq's process.
                checkSyncSoon(1500);
            }
        }
        // Background ops report through the setup panel or the sync marker.
        if (!res.ok && quietOps.indexOf(job.op) === -1)
            notice(res.error);
        if (job.callback) {
            try {
                job.callback(!!res.ok, res.data, res.error);
            } catch (err) {
                console.warn("Logseq widget callback failed:", err);
            }
        }
        if (res.ok && writeOps.indexOf(job.op) !== -1)
            changed();
        if (job.op !== "maintain" && job.op !== "syncStatus")
            _needsMaintenance = true;
    }

    // Once the queue is idle: stop the CLI's process (or keep it syncing),
    // soon after background work, or a while after you last used the widget.
    function _scheduleMaintenance() {
        if (!_needsMaintenance)
            return;
        _needsMaintenance = false;
        var sinceUse = Date.now() - lastUserActivity;
        // Stopping Logseq's process waits until you've stopped using the
        // widget. Keeping sync running doesn't interrupt anything, so with
        // "Keep syncing" on it happens right away instead.
        var delay = backgroundSync
            ? backgroundIdleSeconds * 1000
            : Math.max(backgroundIdleSeconds * 1000, idleSeconds * 1000 - sinceUse);
        maintainTimer.interval = delay;
        maintainTimer.restart();
    }

    function checkSyncSoon(delayMs) {
        statusTimer.interval = Math.max(1, delayMs);
        statusTimer.restart();
    }

    function checkSyncNow() {
        checkSyncSoon(1);
    }

    function _applySyncStatus(ok, data) {
        _lastStatusCheck = Date.now();
        // A change being written, or one that failed, says more than the cloud.
        if (_writesInFlight > 0 || syncState === "failed")
            return;
        if (!ok || !data) {
            syncState = "unknown";
            syncDetail = i18n("Couldn't read the sync status.");
            return;
        }
        syncState = data.state || "unknown";
        syncDetail = data.detail || "";
        syncPending = data.pending || 0;
        // "Keep syncing" is on but sync isn't running: start it (at most once
        // a minute, so a sync that can't start doesn't loop).
        if (backgroundSync && (data.reason === "no-process" || data.reason === "sync-off")
                && Date.now() - _lastAutoStart > 60000) {
            _lastAutoStart = Date.now();
            syncDetail = data.detail + " " + (_lastSyncProblem || i18n("Starting background sync…"));
            maintainNow();
        } else if (backgroundSync && _lastSyncProblem
                   && (data.reason === "no-process" || data.reason === "sync-off")) {
            syncDetail = data.detail + " " + _lastSyncProblem;
        }
        if (syncState === "uploading")
            checkSyncSoon(5000); // follow the upload until it's done
    }

    Timer {
        id: statusTimer
        onTriggered: backend.call("syncStatus", { backgroundSync: backend.backgroundSync },
                                  backend._applySyncStatus)
    }

    function maintainNow() {
        _needsMaintenance = true;
        _scheduleMaintenance();
    }

    onBackgroundSyncChanged: maintainNow()

    Timer {
        id: maintainTimer
        onTriggered: {
            if (backend._current !== null || backend._queue.length > 0) {
                backend._needsMaintenance = true; // rescheduled when idle
                return;
            }
            backend.call("maintain", { backgroundSync: backend.backgroundSync }, function (ok, data, error) {
                var started = ok && data && (data.action === "sync-started" || data.action === "login-renewed");
                if (started) {
                    // Let it connect (a reconnecting session may wait up to 30 s
                    // for Logseq's next attempt), then update the marker.
                    backend.checkSyncSoon(data.reason === "reconnecting" ? 35000 : 4000);
                    if (!data.syncError)
                        backend._lastSyncProblem = "";
                }
                if (ok && data && data.syncError) {
                    backend._lastSyncProblem = data.syncError;
                    // Sync is running but failing (an expired login, say).
                    error = data.syncError;
                    ok = false;
                }
                if (ok) {
                    backend._lastMaintainError = "";
                    return;
                }
                // Report a failure once, not on every cycle.
                if (error !== backend._lastMaintainError) {
                    backend._lastMaintainError = error;
                    backend.notice(i18n("Background sync: %1", error));
                }
            });
        }
    }

    function _finish(sourceName, stdout, stderr, exitCode) {
        if (_abandoned[sourceName]) {
            delete _abandoned[sourceName];
            return;
        }
        if (!_current || _current.cmd !== sourceName) {
            console.warn("Logseq widget: output for an unknown request ignored");
            return;
        }
        var job = _current;
        _current = null;
        currentOp = "";
        watchdog.stop();

        var res = null;
        try {
            res = JSON.parse(stdout);
        } catch (e) {
            res = null;
        }
        if (!res || typeof res !== "object") {
            var detail = String(stderr || stdout || "").trim();
            if (exitCode === 127)
                detail = i18n("'%1' was not found. Install Python 3 or set the Python command in the settings.", pythonCommand);
            res = { ok: false, error: i18n("The widget helper failed: %1", detail || i18n("no output")) };
        }
        _deliver(job, res);
        _next();
    }

    function _timeoutFor(op) {
        return timeouts[op] !== undefined ? timeouts[op] : timeouts._default;
    }

    Timer {
        id: watchdog
        interval: 1000
        repeat: true
        onTriggered: {
            var job = backend._current;
            if (!job) {
                stop();
                return;
            }
            backend.currentElapsed = Math.round((Date.now() - job.started) / 1000);
            var limit = backend._timeoutFor(job.op);
            if (backend.currentElapsed < limit)
                return;
            // Give up on it; any late output is ignored.
            backend._abandoned[job.cmd] = true;
            runner.disconnectSource(job.cmd);
            backend._current = null;
            backend.currentOp = "";
            stop();
            backend._deliver(job, {
                ok: false,
                error: job.op === "ping"
                    ? i18n("The widget's helper did not answer within %1 seconds.", limit)
                    : writeOps.indexOf(job.op) !== -1
                        ? i18n("Logseq did not answer within %1 seconds. The change may still have been saved: refresh before trying again. Details are in %2.", limit, backend.logPath)
                        : i18n("Logseq did not answer within %1 seconds. Details are in %2.", limit, backend.logPath)
            });
            backend._next();
        }
    }

    P5Support.DataSource {
        id: runner
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            runner.disconnectSource(sourceName);
            backend._finish(sourceName, data["stdout"], data["stderr"], data["exit code"]);
        }
    }
}
