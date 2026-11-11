---
name: adopt
description: Set Harbor up on a Keelokit project — the convoy landing policy, this clone's account and host, the logbook branch harbor/log, the account's session cap, the hotspots, and a one-time import of a hand-kept BOARD.md if there is one. Use when the user says "adopt harbor", "set up convoys", "sumá harbor", "configurá harbor", "adoptá harbor", or when the SessionStart line says the logbook is missing.
---

# Adopt — Harbor on top of Keelokit

`H="${CLAUDE_PLUGIN_ROOT}/bin/harbor.py"`. Every write to the logbook goes through `python3 "$H"`;
never edit `harbor/log` by hand. Design: `${CLAUDE_PLUGIN_ROOT}/docs/design.md`.

1. **Keelokit first, 0.12.0 or later** (`version` in its `plugin.json`; `.keelokit/bin/status.py title`
   exists). Older: say Harbor needs 0.12 (its pre-push lets the logbook through, and it titles
   sessions) and point to `/keelokit:harness-upgrade`. No `.keelokit/` → say Harbor works on top of Keelokit, point to
   `/keelokit:project-adopt`, and stop. No remote `origin` → stop: the logbook lives there.
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
   (no default: it's the person's budget) and `python3 "$H" account set <account> --max-sessions N`.
5. **Hotspots.** Propose `[harbor.hotspots]` from evidence, each with its reason: the areas in
   `.keelokit/critical.toml`, migration folders, shared packages, locale files, generated files,
   and the paths with most commits lately (`git log --since=30.days --name-only --format= | sort |
   uniq -c | sort -rn | head -20`). Write only what the person confirms. Generated files go in
   `[harbor.generated]` with the command that rebuilds them.
6. **A hand-kept board.** Look for one: `git ls-remote origin coord/board` and then
   `git show origin/coord/board:BOARD.md`, or a `BOARD.md` in the tree. If found, show what it
   holds in five lines and, with a yes, save it to a temporary file and run
   `python3 "$H" import-board <file>`. It runs once. Report the convoys imported, the rows left out
   and that the watch is not imported (the first `/harbor:harbormaster takeover` takes it).
7. **Report** in ten lines: the policy commit's hash on the trunk (`origin/main`), the logbook's tip
   (`git rev-parse origin/harbor/log`), the cap, the hotspots, the import. Then: start convoys with
   `/harbor:convoy new`.
