---
name: harbormaster
description: Keep Harbor's watch — take it when nobody holds it or it expired (takeover), and run the periodic control (control) that renews the heartbeat, checks main, the convoys, the workers and the accounts, and gives the ok to sail. Use when the user says "take the watch", "you are the harbormaster", "control round", "tomá la guardia", "sos el harbormaster", "ronda de control", or when the SessionStart line says nobody holds the watch.
---

# Harbormaster — one watch, an expiry, the first commit wins

`H="${CLAUDE_PLUGIN_ROOT}/lib/harbor.py"`. The role, its expiry and its relief are in
`${CLAUDE_PLUGIN_ROOT}/docs/design.md` ("The watch and its relief"). Run on the model in
`[harbor.models] harbormaster`. The harbormaster reads code and git, and writes only through
`harbor.py`. Where this says `main`, it is the trunk (`[harbor] trunk` in `.keelokit/state.toml`
or `.harbor/config.toml` when the project sets it). Without Keelokit the watch and the control run, but the
convoy parts (main, CI, convoys, sailing) do not exist.

## takeover

`python3 "$H" --session <id> harbormaster takeover`; set this session's title to the one it prints
(`set_session_title`, right away). If it also prints a previous holder, that session must now carry the
`ex-harbormaster · …` title it names (it is the one place its role is told until it ends): set it with
`set_session_title` when the holder is in this account (the session id is the last part of the printed worker
id), otherwise send it a `msg` with that title.
Refused with `WATCH_HELD` while another
session's watch hasn't expired; `--relieve "<reason>"` only when the person says so in this
conversation (the gatekeeper's word). Then schedule this session's own control every `[harbor] control_every_minutes`
(30 by default; a task another session scheduled doesn't reach this one): one scheduled message to itself, the
one takeover prints after `schedule this message to this session …`, word for word. It holds only the commands
to run (`harbor.py … harbormaster control`, and `python3 .keelokit/bin/ledger.py` when the project has it) and
what to do with their output, never a state: no convoy numbers, heads, counts or "where we were", so a compacted
or new session reads the facts fresh each round. Each round ends by scheduling the same message again.

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
- `waiting for the gatekeeper's yes`: remind the gatekeeper once, with what to review; don't approve.
- `waiting for the ok`: read the convoy (`git show origin/harbor/log:harbor/convoys/<n>.md`, its diff
  against main) and give the ok (`/harbor:convoy`, "The ok"), or say why not. Keelokit's plans pick the
  level (`all` when the scoped plan already covers `--all`); pass `--level` only to overrule them, with the
  reason. `ALREADY_COVERED` means the head already has a green run at that level: it sails, nothing reruns.
- `main moved`: tell the convoy's integrator to assemble again.
- `skipper … is lost/ended`: tell the gatekeeper; reassigning is theirs to approve.
- `verify started … with no result`: the run was cut on that machine; the integrator runs it again.
- `past its cutoff …: mandatory <STORY> not delivered, it waits`: ask the story's vessel (or the skipper)
  when it lands; deferring a mandatory story is the gatekeeper's call (`convoy defer`), never automatic.
  `the next assemble defers <STORY>`: tell the integrator to assemble; the optional ones go by themselves.
- a loose push: tell the gatekeeper what landed outside a convoy. With Keelokit's ledger the line lists the
  stories that entered and the unattributed commits: name those commits to the gatekeeper (attributing them on main
  is `ledger.py correct`, a person's `backfill --accept`).
- `orphan: …`: a session still running whose owner ended, got lost or is paused. Tell the gatekeeper;
  its result is either taken over by its owner's replacement or ended.

Then, with Keelokit's ledger, `ledger: <CODE> <detail>` lines: the error-level differences of `ledger.py check`
(five lines at most; `(+N more …)` means run `python3 .keelokit/bin/ledger.py check` for the rest). Tell the
gatekeeper each one once; fixing history is theirs (`ledger.py correct`). `ledger: not available` (no ledger) or
`ledger: … not available (why)` (a ledger that can't answer) is one line and the round goes on; but while the
ledger can't answer, the ok fails closed (`LEDGER_UNAVAILABLE`): say so to the gatekeeper.

The ok asks the ledger too: `LEDGER_DIFF` names each vessel the ledger holds back (`UNATTRIBUTED` commit,
`UNKNOWN_STORY`, `DONE_TWICE`: its story already on the trunk). Never work around it: tell the vessel's owner to fix
its commits, or the skipper to take it out of the convoy, then assemble and give the ok again.

After those lines, control prints what is late: `escalated: …` (a late question, a message for the gatekeeper, or one
queued past `escalate_minutes`), `late: …`, `account A: no watcher` and `account A: no heartbeat recorded`. Tell the
gatekeeper about each escalated one, once (a push notification, if this session has one), and wake an account's
dispatcher when its watcher is down. Relay an answer with `msg send --to <the asker> --kind answer --re <id>`, then
`msg done <id>`. `python3 "$H" msg status` lists every late message and every watcher (exit 1 when something is late):
run it in each control.

## Asking for sessions

The harbormaster is the one that asks for sessions: `python3 "$H" --session <id> wanted add --role vessel --story <ID>
[--convoy N] [--model M] [--account A]` (`--role skipper` or `dispatcher` too). A dispatcher takes it, starts the
session and records it; `wanted list` shows where each request is, `wanted drop <id>` gives one up. A request starts
only a role and story the project knows, on an allowed model, within the account's cap. `/harbor:dispatch` is the
other side. One vessel request per story at a time: `STORY_REQUESTED` names the one already open or
taken (drop it first). The round repairs a story two active workers hold (a clone on a Harbor older than 0.6.0 can
leave one): `double hold: …` names them and the one kept; tell the released one's owner. A started
request nobody claimed holds its story: the round drops it when its taker is gone and names it once it is older
than the watch's expiry; `wanted drop <id>` (or `story release <ID>`) lifts it earlier.

Report in ten lines at most, as control prints them, plus what needs the gatekeeper.
