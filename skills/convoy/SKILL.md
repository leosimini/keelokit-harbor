---
name: convoy
description: Run a convoy — a batch of vessel branches from several sessions, accounts or machines integrated in convoy/N, verified once and landed on main with one push. Subcommands new, add, assemble, verify, sail, status; also how a vessel session delivers its branch. Use when the user says "new convoy", "add this branch to the convoy", "convoy status", "sail", "armá un convoy", "sumá esta rama al convoy", "estado del convoy", "zarpá", or when a vessel finished and must be delivered.
---

# Convoy — a branch enters with its hash and its seal, or not at all

`H="${CLAUDE_PLUGIN_ROOT}/lib/harbor.py"`; pass `--session <id>` (the SessionStart line gives it).
Design and the state table: `${CLAUDE_PLUGIN_ROOT}/docs/design.md`. Keelokit's
`.keelokit/harness/agent-brief.md` still applies to every session. Where this says `main`, it is the
trunk: `[harbor] trunk` in `.keelokit/state.toml` when the project sets it (`harbor.py` names it in
its messages), and then that is the branch nobody pushes by hand, in prompts and commands too.

Register once per session before writing: `python3 "$H" --session <id> worker register --role
skipper|vessel [--convoy N] [--branch B] --model <model>`. `ACCOUNT_AT_CAP` or `ACCOUNT_PAUSED`:
say so and stop; don't start another session to get around it.

## new

`python3 "$H" --session <id> convoy new --title "<what>" --expect <STORY> … [--depends N …]`. The
stories come from one Keelokit wave or from the person; a convoy that needs another to land first
names it in `--depends`. Report the number and the base.

## Launching vessels (skipper)

One session per story, each with the model Keelokit's brief gives its role and tier, named on every
`Agent` or `create_session`, and titled from the data, never by hand:
`python3 "$H" title --role vessel --convoy <n> --story <ID>` prints it (`jouna · C8 · ola 1 ·
CARGA-001`); launch the session with that title. Whoever launches a session owns its result, so the
prompt says who:
`Read .keelokit/harness/agent-brief.md. Register with harbor.py worker register --role vessel
--convoy <n> --story <ID> --spawned-by <your worker id>, then /keelokit:build-story <ID>. You are a
vessel of convoy <n>: land on your pushed branch, never on main, then deliver as /harbor:convoy says.`
`convoy new` prints your own title as skipper; set it on this session. Before this session ends,
every session it launched is delivered, ended or handed over: `worker end` lists the ones still
running.

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

## assemble (integrator)

`python3 "$H" --session <id> convoy assemble <n>` switches this checkout to `convoy/<n>`, merges
`main` and every delivered vessel into it (merge, never rebase), rebuilds conflicts that are only in
`[harbor.generated]` files, checks migration timestamps, and pushes `convoy/<n>`. It ends `ready`, or
`waiting` with what is missing. Refusals:
- `CONFLICT`: you merge that vessel's head by hand on `convoy/<n>`, resolve only what the merge
  needs, commit, and run assemble again (it takes your local branch). A conflict only in formatting
  follows Keelokit's FMT-1: keep the content, `pnpm format`.
- `MIGRATION_COLLISION` / `MIGRATION_ORDER`, `VESSEL_MOVED`: back to the vessel, which fixes, seals
  and is added again.
- A late expected story: `convoy defer <n> <STORY>` takes it out; the next convoy expects it. Don't
  hold the rest for it.

## The ok (harbormaster)

`python3 "$H" --session <id> convoy sail <n> --ok --level changed|all --reason "<files that decided>"`.
`changed` unless the convoy touches what Keelokit's routing can't bound (verify tooling, test config,
CI, `.keelokit/`, `scripts/`, root manifests, the lockfile): then `all`. Money, permissions and
migrations don't force `all`. It refuses if main is red, moved, or the convoy isn't `ready`. When the convoy is critical (a
full-tier vessel or a critical area, per `[harbor] person_ok`; with `"areas"`, only a critical area), the ok says it also needs the
person's yes: the verify runs meanwhile, and only the sail waits.

## verify (integrator)

`python3 "$H" --session <id> convoy verify <n>`, in the background with a log, then one `until` on
its exit. A one-vessel convoy whose seal already covers the ok's level runs nothing. Red: the fix is
a commit on `convoy/<n>` — a failing test first by Keelokit's verifier, then the builder — pushed,
then verify again: it reruns only what failed plus what the fix touches, and Keelokit seals it when
that completes the plan. Don't run vessel seals on this machine while it verifies.

## sail (integrator)

`python3 "$H" --session <id> convoy sail <n>`, from the machine that verified. It pushes the sealed
head to `main` as a fast-forward; `MAIN_MOVED` means assemble again and a new ok. `NEEDS_PERSON`:
tell the person what to review (`git show origin/harbor/log:harbor/convoys/<n>.md`, `git diff
origin/main...origin/convoy/<n>`) and that they approve by running `python3 <harbor.py> convoy approve
<n>` in their own terminal. Never run it yourself: Harbor's hook blocks it, and getting around the
hook is approving in their name. Report the hash on
`origin/main`, never "sailed" alone.

## abort

`convoy abort <n> --reason "<why>"` (skipper or harbormaster): its vessels and hotspots are free. While a sail is pushing the convoy
to the trunk the abort answers `SAILING`: wait for the sail to end and look at the trunk before deciding what to do.
