# Changelog

## Unreleased — a zip claude.ai accepts

- **`harbor.py` moved from `bin/` to `lib/`.** claude.ai's upload (Customize → Plugins → Upload) refuses a plugin
  with a top-level `bin/` directory, so the 0.2.0 zip could not be installed there. The hooks, skills and agents call
  `lib/harbor.py`; nothing else changes. `scripts/package.sh` now fails on a top-level `bin/`.

## 0.2.0 — 2026-11-11 — a trunk other than `main`, and a project's own verify

### The trunk
- **Convoys can land on a branch that isn't `main`.** `[harbor] trunk` in `.keelokit/state.toml` names the branch
  convoys are measured against, merge and sail to (`main` by default). With `trunk = "develop"`, in a project whose
  `main` is production, Harbor never pushes `main`, and its messages, its pages and the note before a push name
  `develop`. The logbook's schema doesn't change: `harbor/main.toml` and its keys keep their names and hold the trunk.
  `harbor/log` and `convoy/<n>` are refused as a trunk (`BAD_CONFIG`).

### The project's own verify
- **A convoy can sail on a verify that isn't Keelokit's.** A project with Keelokit in harness mode has no
  `pnpm verify`, so no run ever got a level and no convoy could sail. With `[harbor] own_verify = true`, a green
  convoy run of the project's own command gets its level from Harbor: `changed` for `convoy_verify`, `all` for
  `convoy_verify_all`. After a red, the same command runs again; `convoy_rerun` is not used.
- **Never a shared seal for it.** Such a run is recorded in `harbor/runs/` with `level_source = "harbor"` and never in
  `harbor/seals/`, so Keelokit's pre-push doesn't skip its own verify because of it. Off by default.

## 0.1.0 — 2026-11-07 — convoys for many sessions at once

The first release. Harbor lands the work of many parallel Claude sessions on `main` in one convoy, instead of one
full verify and one push per branch. It comes from hundreds of hours running many projects in parallel, many sessions
on several accounts, delivering software around the clock with minimal intervention.

### Convoys
- **Open, add, assemble, verify, sail.** `/harbor:convoy` takes the sealed branches of a batch, merges `main` and
  them into `convoy/<n>`, runs one verify on the exact head, and pushes to `main` once. Never with `--force`.
- **Abort or defer.** Give a convoy up, or take a late story out so the rest don't wait.

### Seals
- **A branch enters with its exact hash and a verify result for that hash.** A commit after the seal has no result,
  so the delivery is void until it is verified again.

### The logbook
- **State in one git branch only Harbor writes** (`harbor/log`): TOML files with a fixed schema and generated pages
  nobody edits. It is never on `main`, so writing it doesn't move `main` or start its CI.
- **`/harbor:log`** shows the watch, the convoys, the workers and the accounts.
- **A one-time import of an existing `BOARD.md`** when you adopt Harbor.

### Hotspots
- **Shared hot paths go one at a time.** Two branches that touch the same declared hotspot (schema, migrations,
  shared types, locales) are never in open convoys together.

### The watch
- **One harbormaster at a time, with a heartbeat that expires.** When it lapses, any session can take the watch
  (`/harbor:harbormaster takeover`), and the first commit wins. `control` is the round that renews it, records every
  move of `main` and says what each convoy waits for.

### Account caps
- **Each account has a session cap and a pause.** When an account hits its limit, its sessions hand over what they
  pushed, with hashes, instead of leaving half-done work.

### Your yes
- **A convoy with a full-tier story or one that touches a critical area waits for you** before it sails. You run
  `convoy approve <n>` in your own terminal, and a hook stops an agent from running it
  (`[harbor] person_ok` = `critical`, `always` or `never`).

### Fresh reads
- **Sessions that can't see each other still see the same logbook.** A session starts with a fetch, sees what changed
  at each prompt and after tools, and gets the open convoys before it pushes to `main`. It works across the CLI, the
  Claude desktop app, the cloud and several accounts, works offline and never blocks a session.

Needs Keelokit 0.12.0 or later in the project, Python 3.11+, git and a remote `origin`.
