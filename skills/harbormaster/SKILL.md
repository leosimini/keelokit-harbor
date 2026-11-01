---
name: harbormaster
description: Keep Harbor's watch — take it when nobody holds it or it expired (takeover), and run the periodic control (control) that renews the heartbeat, checks main, the convoys, the workers and the accounts, and gives the ok to sail. Use when the user says "take the watch", "you are the harbormaster", "control round", "tomá la guardia", "sos el harbormaster", "ronda de control", or when the SessionStart line says nobody holds the watch.
---

# Harbormaster — one watch, an expiry, the first commit wins

`H="${CLAUDE_PLUGIN_ROOT}/bin/harbor.py"`. The role, its expiry and its relief are in
`${CLAUDE_PLUGIN_ROOT}/docs/design.md` ("The watch and its relief"). Run on the model in
`[harbor.models] harbormaster`. The harbormaster reads code and git, and writes only through
`harbor.py`.

## takeover, control — not yet

Phase 2: `harbor.py` has neither. Say so, and show the watch as the logbook has it
(`python3 "$H" log`). Don't write `harbor/harbormaster.toml` by hand and don't keep the watch in
prose: a watch with no heartbeat in the logbook can't expire, so nobody can relieve it.

What exists today and helps a person coordinating by hand: `python3 "$H" convoy status`, and
Keelokit's `python3 .keelokit/bin/status.py` for this machine.
