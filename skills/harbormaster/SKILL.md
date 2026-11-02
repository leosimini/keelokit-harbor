---
name: harbormaster
description: Keep Harbor's watch — take it when nobody holds it or it expired (takeover), and run the periodic control (control) that renews the heartbeat, checks main, the convoys, the workers and the accounts, and gives the ok to sail. Use when the user says "take the watch", "you are the harbormaster", "control round", "tomá la guardia", "sos el harbormaster", "ronda de control", or when the SessionStart line says nobody holds the watch.
---

# Harbormaster — one watch, an expiry, the first commit wins

`H="${CLAUDE_PLUGIN_ROOT}/bin/harbor.py"`. The role, its expiry and its relief are in
`${CLAUDE_PLUGIN_ROOT}/docs/design.md` ("The watch and its relief"). Run on the model in
`[harbor.models] harbormaster`. The harbormaster reads code and git, and writes only through
`harbor.py`.

## takeover

`python3 "$H" --session <id> harbormaster takeover`. Refused with `WATCH_HELD` while another
session's watch hasn't expired; `--relieve "<reason>"` only when the person says so in this
conversation. Then schedule this session's own control every `[harbor] control_every_minutes`
(a task another session scheduled doesn't reach this one): one scheduled message to itself that
runs `/harbor:harbormaster control` and schedules the next.

## control

The round only reads and reports, so it runs on the cheap model: `python3 "$H" models` says which
(`control`, Haiku by default). Launch one `Agent` on that model with this prompt, and act on what it
returns yourself:
`Run python3 "<H>" --session <this session's id> harbormaster control and return its output exactly,
nothing else. Don't run anything else.`
The ok, and anything else that needs judgment, stays in this session, on `harbormaster`'s model.

`harbormaster control` renews the heartbeat, records any move of `main`
(a convoy's sail, or a loose push), marks workers not seen within the expiry as lost, and prints one
line per open convoy with what it waits for. Act on each line:
- `waiting for the person's yes`: remind the person once, with what to review; don't approve.
- `waiting for the ok`: read the convoy (`git show origin/harbor/log:convoys/<n>.md`, its diff
  against main) and give the ok with its level and reason (`/harbor:convoy`, "The ok"), or say why not.
- `main moved`: tell the convoy's integrator to assemble again.
- `skipper … is lost/ended`: tell the person; reassigning is theirs to approve.
- `verify started … with no result`: the run was cut on that machine; the integrator runs it again.
- a loose push: tell the person what landed outside a convoy.
- `orphan: …`: a session still running whose owner ended, got lost or is paused. Tell the person;
  its result is either taken over by its owner's replacement or ended.

Report in ten lines at most, as control prints them, plus what needs the person.
