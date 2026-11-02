# Harbor

**Convoys for [Keelokit](https://github.com/leosimini/keelokit): many sessions, one push to main.**

*[Leer en español](README.es.md)*

Keelokit builds one story per session and lands it on `main`. When the sessions are many, run on
more than one Claude account or on more than one machine, that becomes one full verify per landing,
and nobody sees the combination before it is on `main`. Harbor batches them: each session finishes
on its own branch (a *vessel*), a *skipper* integrates a batch in `convoy/<n>`, it is verified once,
and after the *harbormaster*'s ok it reaches `main` with one push.

I wrote it after a week of doing this by hand on a real monorepo. The board we kept drifted from
reality, a branch's "green" stopped matching its last commit, and migration timestamps had to be
renamed during integration. Harbor keeps the process and takes the hand work away:

- **The state is a git branch only Harbor writes** (`harbor/log`): TOML files with a fixed schema,
  and pages generated from them that nobody edits. It is never on `main`, so writing it doesn't
  move `main` or start its CI. Sessions on any account or machine read it with `git fetch`.
- **A branch enters a convoy only with its exact hash and a verify result for that hash.** A commit
  after that has no result, so the delivery is void until it is verified again.
- **Shared hot paths go one at a time.** Two branches that touch the same declared hotspot (schema,
  migrations, shared types, locales) are never in open convoys together.
- **One harbormaster at a time, with a heartbeat that expires.** When it lapses, any session can take
  the watch, and the first commit wins.
- **Accounts have a session cap and a pause.** When an account hits its limit, its sessions hand over
  what they pushed, with hashes, instead of leaving half-done work.

## Status

Version 0.1.0, not released. The whole cycle is written and tested against stand-ins for
Keelokit's verify: the logbook, accounts and workers, seals, convoys from `new` to `sail`, the
harbormaster's watch, and a one-time import of an existing `BOARD.md`. It hasn't run on a real
project yet. What is designed but not written is listed at the top of
[`docs/design.md`](docs/design.md).

## Commands

| Command | What happens |
|---|---|
| `/harbor:adopt` | Sets the convoy policy, this clone's account and host, the logbook, the account's cap and the hotspots. Imports a `BOARD.md` once if there is one |
| `/harbor:convoy new\|add\|status` | Opens a convoy, adds a sealed vessel, shows what moved |
| `/harbor:convoy assemble\|verify\|sail` | Merges `main` and the vessels into `convoy/<n>`; the ok and its level; one verify on the exact head; one push to `main` |
| `/harbor:convoy abort\|defer` | Gives a convoy up, or takes a late story out so the rest don't wait |
| `/harbor:log` | The logbook: watch, convoys, workers, accounts |
| `/harbor:harbormaster takeover\|control` | Takes the watch; the round that renews it, records every move of `main` and says what each convoy waits for |

## Try it

It needs Keelokit in the project (`.keelokit/`) with the convoy policy and shared seals (on
Keelokit's `landing-policy` branch, not released yet), Python 3.11+, git, and a remote `origin`.
It isn't published yet. To load it from a clone:

```bash
claude --plugin-dir /path/to/keelokit-harbor
```

Then run `/harbor:adopt` in a Keelokit project. Tests: `python3 -m unittest discover -s tests`.

## Good to know

- Harbor depends on Keelokit and copies none of its code. It runs Keelokit's `pnpm verify`, reads its
  `state.toml`, and uses its tiers and its `Story:` trailer. Without `.keelokit/`, Harbor prints one
  line and does nothing.
- The SessionStart hook runs `bin/harbor.py check` from the plugin and reads the project's
  `.keelokit/state.toml` and `.keelokit/local.toml`. It works offline and never blocks a session.
- `harbor.py seal` runs the command in `[harbor] vessel_verify` from the project's `state.toml`. That
  is project code, just like the project's tests.
- A convoy with a full-tier story or one that touches a critical area also waits for your yes
  before it sails: you run `convoy approve <n>` in your own terminal. A PreToolUse hook stops an
  agent from running it; like Keelokit's guard, it's a speed bump, not a sandbox
  (`[harbor] person_ok` = `critical`, `always` or `never`).
- Harbor pushes to `harbor/log` and `convoy/<n>`, and to `main` only in `convoy sail`: a fast-forward
  to a head with a green seal and the harbormaster's ok. Never with `--force`.

## License

No license file yet: the choice is the author's.
