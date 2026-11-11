# Harbor

**A Claude Code plugin for landing many parallel sessions on `main` in one convoy.**

*[Keelokit](https://github.com/leosimini/keelokit) · [Leer en español](README.es.md)*

I wrote Harbor after a week of landing parallel sessions by hand on a real monorepo built with
[Keelokit](https://github.com/leosimini/keelokit). The board we kept drifted from reality, a
branch's "green" stopped matching its last commit, and migration timestamps had to be renamed
during integration. Harbor keeps that process and takes the hand work away. It comes from hundreds of hours running many projects in parallel, many sessions on several
accounts, delivering software around the clock with minimal intervention. I maintain it as a
hobby, next to Keelokit, and it is opinionated and built around how I work, so take what's useful.

## The idea

Keelokit builds one story per session and lands it on `main`. When the sessions are many, on more
than one Claude account or more than one machine, that becomes one full verify per landing, and
nobody sees the combination before it is on `main`. Harbor batches them: each session finishes on
its own branch (a *vessel*), a *skipper* integrates a batch in `convoy/<n>`, it is verified once,
and after the *harbormaster*'s ok it reaches `main` with one push. The rules that matter are
written as checks, not left to memory:

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

## What it does

| Command | What happens |
|---|---|
| `/harbor:adopt` | Sets the convoy policy, this clone's account and host, the logbook, the account's cap and the hotspots. Imports a `BOARD.md` once if there is one |
| `/harbor:convoy new\|add\|status` | Opens a convoy, adds a sealed vessel, shows what moved |
| `/harbor:convoy assemble\|verify\|sail` | Merges `main` and the vessels into `convoy/<n>`; the ok and its level; one verify on the exact head; one push to `main` |
| `/harbor:convoy abort\|defer` | Gives a convoy up, or takes a late story out so the rest don't wait |
| `/harbor:log` | The logbook: watch, convoys, workers, accounts |
| `/harbor:harbormaster takeover\|control` | Takes the watch; the round that renews it, records every move of `main` and says what each convoy waits for |

Its hooks keep a session's view of the logbook fresh, so it doesn't decide on stale state. A
session starts with a fetch, sees what changed in the logbook at each prompt and after tools, and
gets the open convoys before it pushes to `main`. Details are in
[`docs/design.md`](docs/design.md#fresh-reads).

## Try it

You need Keelokit 0.12.0 or later in the project (`.keelokit/`), Python 3.11+, git, and a remote
`origin`.

```bash
claude plugin marketplace add leosimini/keelokit-harbor
claude plugin install harbor@keelokit-harbor
```

Or [download `harbor-plugin.zip`](https://github.com/leosimini/keelokit-harbor/releases/latest/download/harbor-plugin.zip)
and upload it in Claude (*Customize → Plugins → Upload*). All versions are in the
[releases](https://github.com/leosimini/keelokit-harbor/releases). To load it from a clone:
`claude --plugin-dir /path/to/keelokit-harbor`.

Then run `/harbor:adopt` in a Keelokit project. Tests: `python3 -m unittest discover -s tests`. What is
designed but not written is listed at the top of [`docs/design.md`](docs/design.md).

## Good to know

- Harbor depends on Keelokit and copies none of its code. It runs Keelokit's `pnpm verify`, reads its
  `state.toml`, and uses its tiers and its `Story:` trailer. Without `.keelokit/`, Harbor prints one
  line and does nothing.
- The hooks run `lib/harbor.py sync --hook` from the plugin and read the project's
  `.keelokit/state.toml` and `.keelokit/local.toml`. A session starts with a fresh fetch (5 s cap), sees
  what changed in the logbook at each prompt (at most every 60 s) and after tools (every 2 min), and
  gets the open convoys before a push to `main`. They work offline and never block a session.
- `harbor.py seal` runs the command in `[harbor] vessel_verify` from the project's `state.toml`. That
  is project code, just like the project's tests.
- A convoy with a full-tier story or one that touches a critical area also waits for your yes
  before it sails: you run `convoy approve <n>` in your own terminal. A PreToolUse hook stops an
  agent from running it; like Keelokit's guard, it's a speed bump, not a sandbox
  (`[harbor] person_ok` = `critical`, `areas`, `always` or `never`; `areas` waits only for a critical area,
  not for the full tier).
- Harbor pushes to `harbor/log` and `convoy/<n>`, and to `main` only in `convoy sail`: a fast-forward
  to a head with a green seal and the harbormaster's ok. Never with `--force`.
- If the project's verify is its own command and not Keelokit's `pnpm verify` (Keelokit adopted in
  harness mode), set `[harbor] own_verify = true` and put your commands in `vessel_verify`,
  `convoy_verify` and `convoy_verify_all`. Harbor then gives a green convoy run its level itself, so
  the convoy can sail, and never writes a shared seal for it: Keelokit's pre-push, where there is
  one, still runs its own verify.
- Where this page says `main`, it means the trunk: `[harbor] trunk` in `.keelokit/state.toml`, `main`
  by default. If your `main` is production and you integrate on `develop`, set `trunk = "develop"`:
  convoys are measured against it, merge it and sail to it, and Harbor never pushes `main`.

## How it's built

[`docs/design.md`](docs/design.md) explains the pieces and the reasons behind them. Harbor tests
itself with `python3 -m unittest discover -s tests`.

## License

MIT — see [LICENSE](LICENSE). Made by [Leopoldo Simini](https://leopoldosimini.com).
