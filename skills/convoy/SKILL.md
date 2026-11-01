---
name: convoy
description: Run a convoy — a batch of vessel branches from several sessions, accounts or machines integrated in convoy/<n>, verified once and landed on main with one push. Subcommands new, add, assemble, verify, sail, status; also how a vessel session delivers its branch. Use when the user says "new convoy", "add this branch to the convoy", "convoy status", "sail", "armá un convoy", "sumá esta rama al convoy", "estado del convoy", "zarpá", or when a vessel finished and must be delivered.
---

# Convoy — a branch enters with its hash and its seal, or not at all

`H="${CLAUDE_PLUGIN_ROOT}/bin/harbor.py"`; pass `--session <id>` (the SessionStart line gives it).
Design and the state table: `${CLAUDE_PLUGIN_ROOT}/docs/design.md`. Keelokit's
`.keelokit/harness/agent-brief.md` still applies to every session.

Register once per session before writing: `python3 "$H" --session <id> worker register --role
skipper|vessel [--convoy N] [--branch B] --model <model>`. `ACCOUNT_AT_CAP` or `ACCOUNT_PAUSED`:
say so and stop; don't start another session to get around it.

## new

`python3 "$H" --session <id> convoy new --title "<what>" --expect <STORY> … [--depends N …]`. The
stories come from one Keelokit wave or from the person; a convoy that needs another to land first
names it in `--depends`. Report the number and the base.

## Launching vessels (skipper)

One session per story, each with its model from `[harbor.models]`, named on every `Agent` or
`create_session`. The prompt is short:
`Read .keelokit/harness/agent-brief.md, then /keelokit:build-story <ID>. You are a vessel of convoy
<n>: land on your pushed branch, never on main, then deliver as /harbor:convoy says.`
The tier is the vessel's `build-story` call; the first agent follows it: trivial → builder;
light and full → the verifier writes the tests first.

## Delivering (vessel)

1. `build-story` done on your branch, every review fix committed, branch pushed. Its pre-push ran
   Keelokit's whole verify on that exact commit.
2. `python3 "$H" --session <id> seal` on the same clean checkout. It finds that run in Keelokit's
   history and records it without running again ("already passed Keelokit's verify"). If it runs
   the verify instead (`main` moved, the run was partial or red), put it in the background with a
   log (`nohup … > seal.log 2>&1 &`, then one `until` on its exit). Red: fix, commit, push, seal
   again. Keelokit runs one verify per machine: a seal on a machine that is already verifying waits
   for it, so a skipper with several hosts spreads vessels across them. The last line says whether
   Keelokit's pre-push will accept the seal from other machines.
3. Hand the skipper three things, nothing else: branch, full hash, tier. Any later commit voids the
   delivery: seal the new tip and hand that.

## add (skipper)

`python3 "$H" --session <id> convoy add <n> <branch> --head <hash> --tier <tier>`. Refusals say
what to do: `NO_SEAL` / `SEAL_RED` / `HEAD_MISMATCH` go back to the vessel; `HOTSPOT_HELD` means
that vessel waits for the holder to sail and then rebases; `VESSEL_TAKEN` means it is in another
convoy.

## status

`python3 "$H" convoy status [n]`: state, vessels, "main moved", deliveries void because the branch
moved after delivery, expected stories not delivered. Report it as it prints; don't summarize away
a void delivery.

## assemble, verify, sail — not yet

Phase 2: `harbor.py` doesn't have them. Say so and stop. Don't integrate, verify or push by hand
in their place: a hand-made sail writes nothing in the logbook and is the loose push the design
is there to stop.
