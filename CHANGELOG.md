# Changelog

## Unreleased

### Phase 7: lessons from the JOUNA fleet
- **HRB-4: the ok goes straight to `all` when the scoped plan covers it.** `convoy sail --ok` without
  `--level` asks Keelokit for the convoy head's scoped plan (`verify_tools.py plan --base <main>`) and its
  `--all` plan, and counts the packages each covers the way Keelokit's scoped run does. When the scoped
  plan has every step of `--all` and at least `[harbor] all_when_covered` (default 0.9) of its packages,
  the level is `all` and the reason says so; otherwise `changed`. `--level` from the harbormaster still
  wins (then `--reason` is required, as before); the ok records `plan` and `level_by`. A head that already
  has a whole green `changed` run keeps `changed` (no second run). With no Keelokit plan (no
  `verify_tools.py`, `own_verify`, no `pnpm`), the ok needs `--level` as before.
- **One run per head.** An ok asked again on a verifying convoy whose head already has a green run covering
  that level is refused with `ALREADY_COVERED`. `convoy verify` at `all` no longer follows a red with the
  scoped `convoy_rerun` (which can't seal at `all`): it runs the new `[harbor] convoy_rerun_all`
  (default `pnpm verify --all --rerun-failed --keep-going`), so a red costs one fix round at `all` too.
- **HRB-5: a mechanical preflight before the push to main.** `convoy sail` checks, before it announces or
  pushes anything, that the head's history from `main_before` is exactly the vessels' commits, at most one
  merge per vessel, merges of the trunk and the integrator's recorded fixes; that no commit has a placeholder
  author (a short documented list, plus `[harbor] placeholder_authors`); that no unproven `wip/` tip is inside
  the head (Keelokit's `verify_tools.py wip-inside`, skipped with a note when the project's Keelokit lacks
  it); and that the head changes exactly the vessels' files, apart from the fixes' files and
  `[harbor.generated]`. A failure stops the sail with `PREFLIGHT_FAILED` and the line that failed, recorded
  as the event `preflight-failed`; a pass is in the `sailing` event, with its time (seconds). A fix is a
  commit the integrator makes on `convoy/<n>` itself (first parent, not a merge, in no vessel): `assemble`
  and `verify` record it in the convoy's new optional `fixes` list (event `fix`); the schema stays 1.
- **HRB-6: a seam report at assemble.** With two or more vessels, `convoy assemble` lists, from each vessel's
  diff against its merge base with main, the files two or more vessels changed, the exported names
  (TypeScript `export const|function|class|type|interface`, Python module-level `def`/`class`) two or more
  defined or changed, the CSS selectors and design tokens two or more changed, and the route paths one
  vessel adds that appear in another vessel's tests. `[harbor.generated]` paths are left out. The report
  goes to the output and the new event `seams` (at most 20 listed, then `(+N more)`); every seam is kept in
  the convoy's new optional `[[seams]]`, with an id bound to the vessels' heads. New command
  `harbor.py convoy seam N <seam-id> --note TEXT` (the skipper or the integrator) records `seam-read`: `fine…`,
  `fixed in <commit>` (on `convoy/<n>`) or a question (ends in `?`). `assemble` keeps the convoy `waiting`
  until every seam is read, then reaches `ready`. `convoy status` and the convoy page show the seams. The
  logbook stays schema 1.

## 0.5.1 — 2026-11-18

- **A git hook finds Harbor.** Each session's SessionStart records its own `harbor.py` in `git config --local
  harbor.py` (only when it changed), so a project's pre-push hook runs `push-guard` with `H=$(git config
  harbor.py)` and follows plugin upgrades; `${CLAUDE_PLUGIN_ROOT}` exists only inside the plugin's own hooks. A
  hook with no recorded path refuses Harbor's refs (any exit but 0 and 3).

## 0.5.0 — 2026-11-18

### The fleet layer without Keelokit
- **Harbor runs in any git repository.** `init`, `account`, `worker`, `msg`, `wanted`, `title`, `doctor`,
  `models`, `log`, `harbormaster` and the hooks no longer need `.keelokit/`. `convoy *`, `seal` and
  `import-board` exit 2 with `NEEDS_KEELOKIT`, and so does `wanted add --role vessel|skipper`. With Keelokit
  everything behaves as in 0.4.
- **`.harbor/config.toml`** (committed; `[harbor] project`, `trunk`, models, requirements, import) and
  **`.harbor/local.toml`** (git-ignored; account and host) replace Keelokit's files where there is none.
  Keelokit's win when both exist, and `doctor` and `log` say so.
- **Round-1 review fixes.** The `convoy approve` guard runs on any input again (0.4 behaviour), so a session
  rooted in a repository without Keelokit cannot approve by `cd`-ing into one that has it. `push-guard` asks
  for a fetch when the remote's tip is unknown (a logbook write racing another clone replays instead of
  failing), refuses when it finds no trunk, never reads the local trunk branch, maps every error on a Harbor
  ref to exit 1 and works in the hook's repository; the documented snippet now refuses on any exit but 0 and 3.
  A repository with neither `.keelokit/` nor `.harbor/` hears nothing at SessionStart. `doctor` and `init`
  catch a committed `.harbor/local.toml`, and `init` git-ignores it. Fleet-only repos get no convoy lines in
  the hooks, messages name the config file in use, `[harbor] project` must be one line of at most 60
  characters, `worker register --story` says `NEEDS_KEELOKIT`, a worktree reads the main checkout's identity,
  and a Keelokit repo never falls back to `.harbor/local.toml`.
- **Round-2 review fixes.** `push-guard` also says «fetch first» when the remote's tip is known but not in
  what you push (a sibling fetched it meanwhile), so the write is retried instead of failing. The logbook
  check falls back to the local trunk branch, then Harbor's copy, and with no trunk at all only the tree
  check applies (a repo whose `main` was never pushed can `init`); the mailbox still needs `origin/<trunk>`
  and says to push or fetch it. `init` no longer glues `.harbor/local.toml` onto a `.gitignore` without a
  final newline, edits it only when git says the file is not ignored and only after the logbook was
  created, and creates `.harbor/config.toml` (`[harbor]`) if missing: commit it so other clones see the
  project. SessionStart tells a clone that has `origin/harbor/log` but no `.harbor/` or `.keelokit/`. A
  worktree reads the main checkout's identity only for a plain `.git` checkout. `[harbor] project` is
  trimmed and empty means the directory's name. A write pauses briefly between push attempts and retries a
  fetch that cannot lock the ref. The `convoy approve` guard also catches quoted words (`convoy "approve"`).
  **Behaviour change in Keelokit repos:** the committed-identity check covers `.keelokit/local.toml` too:
  with it tracked, `init` is refused and `doctor` exits 1.
- **`harbor.py push-guard`** lets a project's own pre-push hook accept the logbook and the mailboxes: exit 0
  sound, 1 unsound, 3 not a Harbor ref.

## 0.4.0 — 2026-11-18

### Names and vocabulary
- **Session titles read role first, then account, then project and scope**: `harbormaster · acme-a · Acme`,
  `skipper C8 · acme-a · Acme`, `vessel C8 · acme-a · Acme · wave 1 · STORY-001`, `dispatcher · …`,
  `worker · …`. `harbor.py title` gains `--account` and the roles `worker` and `ex-harbormaster`. On a
  takeover the previous holder is told the `ex-harbormaster · …` title it must carry, and the skills set every
  title right away. The logbook lists sessions by account.
- **No project vocabulary inside Harbor.** `import-board` knows English words only; a project adds its own in
  `[harbor.import]` (`columns`, `states`, `coordinator`). The design document speaks of convoys, and the fleet
  Harbor was learned on is named once, in an appendix.

### The account's mailbox
- **A fixed name**: branch and file `harbor/mailbox/<account>`, pull request `Harbor mailbox: <account>`,
  a draft, never merged. `harbor.py account set A --mailbox-pr N` records it, the views show it, and the
  dispatcher subscribes again on every wake.

### Requirements
- **`[harbor.requirements]`** in `state.toml` declares the tools, hosts, secret names, plugins and skills a
  project's work needs. **`harbor.py doctor`** checks this machine against it, records the result per
  account (once per change), and replaces the never-built `doctor --cloud`. The dispatcher runs it on arm and
  when the list changes and sends what is missing to the gatekeeper.
- **Running sessions are told** when `main` changed the list, `.claude/` or a lockfile since their base:
  reinstall after the next merge of `main` (a skipper takes it at `convoy assemble`, a delivered vessel does
  not move its branch). Said again only when the set of changes differs, not for every new tip.
- **`network_secrets`** declares keys a cloud session injects at the proxy; `doctor` reports them `can't
  check` (a `secrets` entry is an environment variable, so a missing one may be a false alarm there).
- **`doctor` is stricter and clearer**: a host check does not follow redirects and has a deadline, a busy
  proxy (429/503 at CONNECT) says `can't check`; a plugin missing from a local plugin list is `missing`; an
  unknown key in the manifest is `BAD_CONFIG`; a manifest emptied later clears the recorded `missing`; exit
  codes are 0 nothing missing, 1 something missing, 2 the check could not run or be recorded. The dispatcher
  runs a plain `doctor` on arming (a new container never checked).

### Fixed
- **The hooks no longer move `origin/<trunk>`.** The trunk fetch for the note about what it changed wrote the
  session's own remote-tracking ref, which made `git push --force-with-lease` trust a main the session never
  saw (another clone's commit was wiped in a reproduction). It now goes to Harbor's own `refs/harbor/trunk`,
  after the logbook, best-effort, on its own cap; SessionStart and the PreToolUse push note fetch the logbook
  only; no submodules, no background `gc`. A hook stays under its 10 s timeout, and a stale lock on the trunk
  ref is cleared like the logbook's.
- **A hook fetch leaves `FETCH_HEAD` alone** (`--no-write-fetch-head`): a session's `git fetch origin feature`
  then `git merge FETCH_HEAD` took the trunk instead. A retry after a stale lock fetches the logbook only.
- **The note about what the trunk changed is said again after the session merged the trunk** and the same kind of
  thing changes once more (the dedup now looks at the base too).
- **`doctor`**: a host that settles nothing by its deadline, and a plugin absent from the local list when the
  organisation's synced plugins live elsewhere, are "can't check", not "missing"; an unexpected error exits 2.
- The fallback title takes the project from the main checkout, not a worktree's directory.
- **A takeover leaves the previous holder with the role `ex-harbormaster`** (the view showed two
  harbormasters); a Keelokit without `status.py title` still titles a session `role · account · project`;
  `account set --mailbox-pr 0` forgets the mailbox; an empty word in `[harbor.import]` is refused.

## 0.3.1 — 2026-11-18

### Watcher
- **`msg watch` refuses a cap above 115 minutes** (`CAP_TOO_LONG`), from `--cap` or from `[harbor]
  watch_cap_minutes`. Claude Code kills a background command at 2 hours, and a killed command can't be started
  again from that turn: the account was left with no watcher until its heartbeat. Found on a fleet whose
  hand-made watcher had no cap of its own and was killed three times in one night.
- **`/harbor:dispatch`** says why the cap matters, and what to do when the watcher is killed anyway.

## 0.3.0 — 2026-11-17 — orchestration from the cloud

Sessions of different Claude accounts can't start or message each other. Harbor now carries that work in the
logbook, and each account runs one dispatcher session that acts on it inside the account. No server, no paid
CI: the wake is a background watcher that costs no tokens while it waits.

### Messages
- **`harbor.py msg send --to TARGET TEXT`** queues a message in the logbook (`harbor/inbox/`) for an account,
  a worker, the `harbormaster`, a convoy's `skipper:<n>` or the `gatekeeper`. Targets resolve when read, so a
  message to `skipper:28` reaches whoever carries convoy 28 then. Kinds `message`, `question` and `answer`
  (`--re`). Text is one line and is framed as data everywhere it is shown.
- **Acks.** A message stays queued until a worker of its account runs `msg ack`, and `msg done` closes it. A
  dead container loses no message: it waits in the logbook.
- **Late and escalated.** `msg status` lists messages queued longer than `[harbor] ack_minutes` (15) or whose
  account's watcher stopped renewing, and escalates questions, messages to the gatekeeper and anything late
  for `[harbor] escalate_minutes` (30). It exits 1 when something is late.
- **The hooks** name new messages and requests in the change summary each session already gets.

### The watcher and the dispatcher
- **`harbor.py msg watch --account A`**: plain shell, no model. It records `watching_since` once, fetches the
  logbook every `[harbor] watch_poll_seconds` (30) and exits 0 as soon as the account has something to do,
  or 75 after `[harbor] watch_cap_minutes` (110) so it is re-armed. Run as a background command, its exit
  wakes the session. Measured on a real fleet: 13 s from another account's message to the dispatcher, and
  46 s after 40 minutes idle.
- **Role `dispatcher`**, `/harbor:dispatch` and `agents/dispatcher.md` (Haiku by default, no Write or Edit):
  one per account; delivers messages with `send_message`, starts requested sessions with `create_session`,
  checks silent workers, keeps the watcher armed, and sets up a scheduled heartbeat every
  `[harbor] heartbeat_hours` (3) for when its container dies (`account set A --heartbeat-hours N` records it).

### Sessions on request
- **`harbor.py wanted add|take|prompt|started|drop|list`** (`harbor/wanted/`). The harbormaster asks for a
  vessel, a skipper or a dispatcher; a dispatcher of an account that isn't paused and is under its cap takes
  it, and the first commit wins (`WANTED_TAKEN`). `wanted prompt` builds the new session's prompt from the
  request's fields only, never from free text, with the `worker register --spawned-by` line it must run
  first. Models must be in `[harbor] allowed_models` (`haiku`, `sonnet`, `opus`).

### The gatekeeper
- **The human operating the fleet is a role, the gatekeeper**, never a name. `[harbor] gatekeeper_ok` is the
  new name of `person_ok` (still read). Messages, views and skills say "the gatekeeper" where they said "the
  person". `harbor/LOGBOOK.md` gets "For the gatekeeper": escalated messages and unanswered questions, and
  `harbormaster control` prints them, with accounts that have no watcher or no heartbeat.
- Sample accounts in tests and docs are generic (`acct1`, `acct2`).

### Learned and documented
- A pull request comment posted by a Claude session never wakes another Claude session, of any account; a
  person's or a bot's does. A draft PR per account still works as a mailbox for the gatekeeper.

### Convoys
- **`[harbor] gatekeeper_ok = "areas"`.** A convoy waits for the gatekeeper's yes only when a vessel touches an area of
  `.keelokit/critical.toml`. A full-tier story outside those areas sails on the harbormaster's ok and a green verify.
  `"critical"` (the default), `"always"` and `"never"` are unchanged.
- **A sail says it is pushing, and an abort during the push is refused.** `convoy sail` pushes the trunk through the
  project's pre-push hook, which can take minutes. An abort accepted in that window was overwritten when the push
  ended: the convoy sailed after the harbormaster had aborted it. Now the sail writes `sailing` to the logbook before
  the push, checking the convoy's state and ok again in that write, and `convoy abort` answers `SAILING` while the
  push runs (for at most 30 minutes, in case the sail died). A push that fails withdraws the announcement.

## 0.2.1 — 2026-11-11 — a zip claude.ai accepts

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
