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
| `/harbor:adopt` | Sets the convoy policy, this clone's account and host, the logbook, the account's cap and the hotspots. Imports a hand-kept board once if there is one |
| `/harbor:convoy new\|add\|status` | Opens a convoy, adds a sealed vessel, shows what moved |
| `/harbor:convoy assemble\|verify\|sail` | Merges `main` and the vessels into `convoy/<n>`; the ok and its level; one verify on the exact head; one push to `main` |
| `/harbor:convoy abort\|defer` | Gives a convoy up, or takes a late story out so the rest don't wait |
| `/harbor:log` | The logbook: watch, convoys, workers, accounts |
| `/harbor:harbormaster takeover\|control` | Takes the watch; the round that renews it, records every move of `main` and says what each convoy waits for |
| `/harbor:dispatch` | Runs an account's dispatcher: delivers the account's messages, starts the sessions it was asked for, keeps the watcher armed |
| `harbor.py msg send\|list\|ack\|done\|status\|watch` | Messages between sessions of any account, and to the gatekeeper; acks, late and escalated ones; the watcher |
| `harbor.py wanted add\|take\|prompt\|started\|drop\|list` | Requests for new sessions, asked by the harbormaster and taken by a dispatcher with room |
| `harbor.py title --role R [--convoy N] [--story ID] [--account A]` | The title a session carries: role, account, project and scope |
| `harbor.py account set A --mailbox-pr N` | Records the account's mailbox, the draft pull request `harbor/mailbox/A` |
| `harbor.py push-guard LOCAL_REF LOCAL_SHA REMOTE_REF REMOTE_SHA` | For a project's own pre-push hook: exit 0 for a sound push of the logbook or a mailbox, 1 for an unsound one, 3 for any other ref |
| `harbor.py doctor [--account A]` | Checks this machine against the project's `[harbor.requirements]`: one line per item, exit 1 if one is missing, 2 if the check could not run |

Its hooks keep a session's view of the logbook fresh, so it doesn't decide on stale state. A
session starts with a fetch, sees what changed in the logbook at each prompt and after tools, and
gets the open convoys before it pushes to `main`. Details are in
[`docs/design.md`](docs/design.md#fresh-reads).

## Orchestration from the cloud

Sessions of one Claude account can start and message each other; sessions of different accounts can't.
Harbor 0.3 closes that gap without a server: the logbook carries the messages and the requests for new
sessions, and each account runs one **dispatcher** session (`/harbor:dispatch`) that turns what the
logbook holds for its account into actions inside that account.

- **Messages between any sessions, on any account.** `harbor.py msg send --to <target> TEXT`, where the
  target is an account, a worker, the `harbormaster`, a convoy's `skipper:<n>` or the `gatekeeper`. A
  message stays queued until the receiving account acks it, so a dead container never loses one.
- **Sessions on request.** The harbormaster asks for a vessel, a skipper or a dispatcher with
  `harbor.py wanted add`; the dispatcher of an account with room takes it (the first commit wins) and
  starts it with a prompt Harbor builds from the request, never from free text.
- **A wake that costs nothing.** The dispatcher keeps `harbor.py msg watch` running in the background:
  plain shell, no model, a fetch of the logbook every 30 s. It exits when there is work, and the exit wakes
  the session. Measured: 13 s from another account's message to the dispatcher acting on it.
- **Layers for when that fails.** Nothing guarantees a cloud container stays alive while its session is
  idle. A message is *late* after 15 minutes unacked or when its account has no live watcher; a scheduled
  heartbeat per account resumes the dispatcher every few hours; late questions, and anything late for 30
  minutes, go to the gatekeeper's list. Details: [`docs/design.md`](docs/design.md#wakes-and-what-happens-when-one-fails).

To set it up, run `/harbor:dispatch` once in one session of each account that should receive work, and
follow what it says about the heartbeat.

## Session titles

An account can hold many sessions, and a list of them has to say which is which. Every session Harbor knows
has a title from `harbor.py title`, never typed by hand, and it reads role first, then account, then project
and scope: `harbormaster · acme-a · Acme`, `dispatcher · acme-a · Acme`, `skipper C8 · acme-a · Acme`,
`vessel C8 · acme-a · Acme · wave 1 · STORY-001`, `worker · acme-a · Acme`. When the watch changes hands, the
previous holder is told to carry `ex-harbormaster · …` until it ends. The logbook lists the sessions account
by account, with their titles.

## What an account needs to work here

What the repository carries (`.claude/`, lockfiles) reaches every account through `main`. What belongs to an
account (its cloud environment, connectors, plugins, secret names) never travels through git. A project
declares what its work needs:

```toml
[harbor.requirements]
tools = ["docker", "pnpm"]
hosts = ["registry.example.com"]
secrets = ["EXAMPLE_API_TOKEN"]       # names only, never values; environment variables
network_secrets = ["api.example.com"] # keys a cloud session injects at the proxy: reported "can't check"
plugins = ["design"]
skills = ["code-review"]
note = "one line for the gatekeeper"
```

`harbor.py doctor` checks the machine against it and records the result per account; each dispatcher runs it
when it arms and whenever the list changes, and sends what is missing to the gatekeeper, who decides what to
configure. A running session is told, in the hook's summary, when `main` changed the list, `.claude/` or a
lockfile: reinstall after the next merge of `main` (a skipper takes it at `convoy assemble`; a delivered
vessel does not move its branch), said again only when the set of changes differs. The account's mailbox, a draft pull request named
`harbor/mailbox/<account>` that its dispatcher subscribes to, is recorded with `account set --mailbox-pr N` (`0` forgets it).

## The gatekeeper

Harbor is run by people, and in every project one of them has the last word: the **gatekeeper**, the human
operating the fleet. Harbor knows them only as a role and never assumes who they are. The gatekeeper gives
the yes a convoy waits for (`convoy approve`, in their own terminal; `[harbor] gatekeeper_ok` says when),
answers the questions sessions send to `gatekeeper`, and is told when a message is late enough that a
person should step in. Agents decide within what the gatekeeper already decided, and ask about the rest.

## Try it

You need Python 3.11+, git and a remote `origin`; the convoy layer also needs Keelokit 0.12.0 or later in the
project (`.keelokit/`).

```bash
claude plugin marketplace add leosimini/keelokit-harbor
claude plugin install harbor@keelokit-harbor
```

Or [download `harbor-plugin.zip`](https://github.com/leosimini/keelokit-harbor/releases/latest/download/harbor-plugin.zip)
and upload it in Claude (*Customize → Plugins → Upload*). All versions are in the
[releases](https://github.com/leosimini/keelokit-harbor/releases). To load it from a clone:
`claude --plugin-dir /path/to/keelokit-harbor`.

Then run `/harbor:adopt` in a project (with or without Keelokit). Tests: `python3 -m unittest discover -s tests`. What is
designed but not written is listed at the top of [`docs/design.md`](docs/design.md).

## Harbor without Keelokit

Keelokit is not required for the fleet layer: messages between accounts, session requests, the
dispatcher, titles, `doctor`, the watch and the hooks work in any git repository with a remote. Write the
project's settings in `.harbor/config.toml` (committed) and each clone's account and host in
`.harbor/local.toml` (git-ignored); `/harbor:adopt` does both. Convoys, seals and the board import need
Keelokit's convoy policy (`/keelokit:project-adopt`) and say so when asked without it. A project with its own
pre-push hook lets Harbor's writes through with `push-guard`:

```bash
H=$(git config harbor.py)  # each session records the plugin's current harbor.py here
while read l ls r rs; do
  python3 "$H" push-guard "$l" "$ls" "$r" "$rs"; c=$?
  case $c in 0) continue;; 3) ;; *) exit 1;; esac  # 3: not Harbor's ref, the project's own rules go here
done
```

## Good to know

- Harbor copies none of Keelokit's code. With Keelokit it runs its `pnpm verify`, reads its `state.toml`, and
  uses its tiers and its `Story:` trailer. When Keelokit's ledger answers `ledger.py --json` with schema 1, each
  vessel's merge into a convoy carries `Convoy: <n>`, and `convoy add` asks `ledger.py attribution` for the
  vessel's commits: it refuses one with an unattributed commit (`NO_STORY`) and takes the vessel's story from the
  ledger. Keelokit 0.16.0 doesn't answer `attribution` yet: until it does, `convoy add` says so and reads the
  `Story:` trailers, as 0.5. Taking a story is a lock in the logbook (`story take`, `worker register --story`):
  a second worker gets `STORY_TAKEN` with the holder, a story the ledger puts on the trunk `STORY_ON_TRUNK`, and
  a vessel's prompt starts with `ledger.py take <ID>`. Without such a ledger, Harbor behaves as 0.5. Without `.keelokit/`, the fleet layer runs from `.harbor/` (see
  "Harbor without Keelokit") and a repository with neither directory is left alone, silently.
- The hooks run `lib/harbor.py sync --hook` from the plugin and read the project's settings and identity
  (`.keelokit/state.toml` and `.keelokit/local.toml`, or `.harbor/config.toml` and `.harbor/local.toml`). A
  session starts with a fresh fetch (4 s cap), sees what changed in the logbook at each prompt (at most every
  60 s) and after tools (every 2 min), and, with Keelokit, gets the open convoys before a push to `main`. They
  work offline and never block a session.
- `harbor.py seal` runs the command in `[harbor] vessel_verify` from the project's `state.toml`. That
  is project code, just like the project's tests.
- A convoy with a full-tier story or one that touches a critical area also waits for the gatekeeper's yes
  before it sails: the gatekeeper runs `convoy approve <n>` in their own terminal. A PreToolUse hook stops an
  agent from running it; like Keelokit's guard, it's a speed bump, not a sandbox
  (`[harbor] gatekeeper_ok`, formerly `person_ok`, = `critical`, `areas`, `always` or `never`; `areas` waits only for a critical area,
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
