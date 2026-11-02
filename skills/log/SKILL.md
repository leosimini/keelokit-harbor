---
name: log
description: Show Harbor's logbook — who holds the watch, open convoys with their state and vessels, active workers, paused accounts — fetched from the harbor/log branch. Read-only. Use when the user says "logbook", "harbor status", "show the convoys", "bitácora", "¿cómo van los convoys?", "estado de harbor".
---

# Log — read the logbook, never write it

`python3 "${CLAUDE_PLUGIN_ROOT}/bin/harbor.py" log` fetches `harbor/log` and prints `harbor/LOGBOOK.md`;
`convoy status [n]` adds what moved on the remote (main, vessel branches). For one convoy's full
page: `git show origin/harbor/log:harbor/convoys/<n>.md`.

Show it as it is, in the user's language, ten lines at most, and link nothing that isn't in it.
The views are generated: if something in them is wrong, the fix is a `harbor.py` command (or a bug
in `harbor.py`), never an edit of the branch.
