"""The Logseq DB widget's helper: the bridge between the Plasma widget and the
official `logseq` CLI that ships with Logseq Desktop (DB version).

The widget runs ../logseq_helper.py, which calls main.main(). Each request is
one operation; the modules, from the bottom up:

    errors, paths, log     the error type, the private cache folder, the log
    processes              this user's running processes (is Logseq Desktop open?)
    cli                    running one CLI command safely and reading its answer
    appimage               finding Logseq's AppImage and unpacking it once
    locate                 choosing which Logseq CLI to run
    entities, journal      Logseq's data shapes; journal dates and titles
    choices                task statuses and priorities, including your own
    safeguards             checks that protect your graph and Logseq Desktop
    graph_setup            first start: finding the CLI and choosing the graph
    request                reading a request and checking its fields
    pages, blocks, tasks   reading pages; writing blocks; the TODO list
    sync                   sync state, sync errors, starting sync
    maintenance            the idle stop, and keeping background sync alive
    main                   running one request and answering with one JSON line

Lower modules never import higher ones.
"""
