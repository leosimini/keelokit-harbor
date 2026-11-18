---
name: adopt
description: Set Harbor up on a project, with or without Keelokit — on Keelokit the convoy landing policy, this clone's account and host, the logbook branch harbor/log, the account's session cap, the hotspots, and a one-time import of a hand-kept BOARD.md if there is one. Use when the user says "adopt harbor", "set up convoys", "sumá harbor", "configurá harbor", "adoptá harbor", or when the SessionStart line says the logbook is missing.
---

# Adopt — Harbor on top of Keelokit

`H="${CLAUDE_PLUGIN_ROOT}/lib/harbor.py"`. Every write to the logbook goes through `python3 "$H"`;
never edit `harbor/log` by hand. Design: `${CLAUDE_PLUGIN_ROOT}/docs/design.md`.

0. **Which path.** Keelokit is optional. `.keelokit/` present: **with Keelokit**, steps 1 to 8 below. Absent:
   **without Keelokit — fleet layer only**, the section at the end; do not stop. No remote `origin` → stop: the
   logbook lives there.
1. **Keelokit 0.12.0 or later** (`version` in its `plugin.json`; `.keelokit/bin/status.py title`
   exists). Older: say Harbor needs 0.12 (its pre-push lets the logbook through, and it titles
   sessions) and point to `/keelokit:harness-upgrade`.
2. **The policy and the config.** Show the block you will add to `.keelokit/state.toml` and ask for
   a yes:
   ```toml
   [landing]
   policy = "convoy"

   [verify]
   shared_seals = "origin/harbor/log:harbor/seals/{head}.toml"

   [harbor]
   integrator = "any"     # or a pilot account that integrates every convoy
   # trunk = "develop"    # optional: the branch convoys land on, when it isn't main
   # own_verify = true    # optional: the verify commands are the project's own, not Keelokit's

   [harbor.models]
   skipper = "sonnet"
   harbormaster = "sonnet"
   ```
   Explain in one sentence: from now on stories land through convoys, not one push per session.
   And one more: with `shared_seals`, a commit verified on one machine isn't verified again when
   another machine pushes it, as long as nobody can push to `harbor/log` who couldn't push to `main`.
   If `doctor.py` rejects `[landing]` or `[verify] shared_seals`, this Keelokit predates them: say
   which version is needed and stop.
   Ask which branch convoys land on. It is `main` unless the project integrates elsewhere (`main`
   is production, work lands on `develop`): then write `trunk` with that branch, in this same
   change (a checkout with the policy and without the trunk would land on `main`), and Harbor never
   pushes `main`.
   If the project has no Keelokit verify (harness mode: no `scripts/verify.sh`, no `pnpm verify`),
   ask for its own commands and write `own_verify = true` with `vessel_verify`, `convoy_verify`,
   `convoy_verify_all` and `convoy_preflight = ""`. Say what it means: Harbor takes a green run of
   those commands as the convoy's verify, and writes no shared seal for it.
   Land this change on the trunk the way the project lands today; it is the last direct landing.
3. **This clone.** Ask the account name (the Claude account these sessions run on) and a short
   host name. Write `.keelokit/local.toml` (`[harbor] account = …, host = …`) and add
   `.keelokit/local.toml` to `.gitignore` in the same change as step 2. Each clone has its own.
4. **The logbook.** `python3 "$H" init`. Then ask how many sessions this account may run at once
   (no default: it's the gatekeeper's budget) and `python3 "$H" account set <account> --max-sessions N`.
5. **Hotspots.** Propose `[harbor.hotspots]` from evidence, each with its reason: the areas in
   `.keelokit/critical.toml`, migration folders, shared packages, locale files, generated files,
   and the paths with most commits lately (`git log --since=30.days --name-only --format= | sort |
   uniq -c | sort -rn | head -20`). Write only what the person confirms. Generated files go in
   `[harbor.generated]` with the command that rebuilds them.
6. **A hand-kept board.** Ask whether the project keeps one (a markdown file with a table of convoys, in
   the tree or on a branch) and where. If so, show what it holds in five lines and, with a yes, save it to a
   temporary file and run `python3 "$H" import-board <file>`. The import knows English column and state
   words only: if the board uses others, add them first in `state.toml` (`[harbor.import] columns = {
   number = ["…"] }`, `states`, `coordinator`; `docs/design.md`, `harbor/imported/board.toml`). It runs once.
   Report the convoys imported, the rows left out and that the watch is not imported (the first
   `/harbor:harbormaster takeover` takes it).
7. **Dispatchers.** Each account that should receive work (messages from other accounts, sessions started for
   it) runs one dispatcher: a session that runs `/harbor:dispatch`. Say so, and that the gatekeeper (for this
   project) is the person who gives the yes for critical convoys and answers what sessions can't settle.
   **Requirements.** Offer to write `[harbor.requirements]` (tools, hosts, secret names, plugins, skills the
   work needs; see `docs/design.md`, "Phase 4") from what the repository already shows: its lockfiles,
   `.claude/skills`, its verify's tools. Only what the person confirms. `harbor.py doctor` checks it. A key
   a cloud session injects at the proxy is never an environment variable: list it under `network_secrets`
   (reported `can't check`), not `secrets` (a `missing` env secret there is a false alarm).
8. **Report** in ten lines: the policy commit's hash on the trunk (`origin/main`), the logbook's tip
   (`git rev-parse origin/harbor/log`), the cap, the hotspots, the import. Then: start convoys with
   `/harbor:convoy new`.

## Without Keelokit — fleet layer only

Messages between accounts, session requests for dispatchers, titles, `doctor`, the watch and the hooks. No
convoys, seals or board import. Steps:

1. **Config.** Ask the project's name and write `.harbor/config.toml` (committed):
   ```toml
   [harbor]
   project = "<name>"
   # trunk = "develop"   # only when the main branch is not `main`

   [harbor.requirements]  # fill with the gatekeeper: tools, hosts, secrets, plugins, skills
   ```
2. **This clone.** Ask the account name and a short host name; write `.harbor/local.toml` (`[harbor] account = …,
   host = …`) and add `.harbor/local.toml` to `.gitignore`. Each clone has its own.
3. **The hooks** come with the plugin; check that `python3 "$H" check` prints this session's line.
4. **The logbook.** `python3 "$H" init`, then ask how many sessions this account may run at once (the gatekeeper's
   budget, no default) and `python3 "$H" account set <account> --max-sessions N`. Without it `worker register`
   says `ACCOUNT_UNKNOWN`.
5. **A pre-push hook of the project's own?** Add this to it so Harbor's writes (the logbook, the mailboxes) go
   through (`H` is the path of `lib/harbor.py`); exit 3 means the ref is not Harbor's and the project's own rules
   go on:
   ```bash
   while read l ls r rs; do
     python3 "$H" push-guard "$l" "$ls" "$r" "$rs"; c=$?
     [ $c = 0 ] && continue; [ $c = 1 ] && exit 1
     # own rules for the other refs
   done
   ```
6. **Dispatchers** as in step 7 above.
7. **Report**: the logbook's tip, the cap, and what is not available (convoys, seals, `wanted add --role
   vessel|skipper`, the board import) and that `/keelokit:project-adopt` followed by this skill's Keelokit path
   adds them later.
