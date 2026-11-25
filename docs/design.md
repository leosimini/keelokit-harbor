# How Harbor is built

This is the design. **Phases 1 to 5 are implemented** in `lib/harbor.py`.
- *Phase 1* (`tests/test_harbor.py`): logbook init, accounts, workers, seals, `convoy new|add|status`,
  the generated views, the one-time import of a hand-kept board.
- *Phase 2* (`tests/test_phase2.py`): `convoy assemble|verify|sail|abort|defer`, the ok,
  `harbormaster takeover|control`, `harbor/main.toml`.
- *Phase 3* (`tests/test_phase3.py`): messages, session requests, the watcher, the gatekeeper's list and the
  dispatcher ("Phase 3: orchestration from the cloud").
- *Phase 4* (`tests/test_phase4.py`): session titles that read role, account and project, the account's
  mailbox, and the project's requirements with `doctor` ("Phase 4: names, mailboxes and requirements").
- *Phase 5* (`tests/test_phase5.py`): the fleet layer in a project without Keelokit, and `push-guard`
  ("Phase 5: the fleet layer without Keelokit").
Marks *(2)* name what phase 2 added. Designed and **not written yet**: reassigning a skipper
(`convoy skipper N WORKER`), the early hotspot warning from stories' `touches`, the warning for
vessels that share commits, everything marked *(3)*, and phase 3's "Designed, not built". Phase 6, how Harbor fits Keelokit's ledger, is designed in
[ledger-phase6.md](ledger-phase6.md); HRB-1, `Convoy:` on the merge, `NO_STORY` in `convoy add` and the story from
the ledger (`tests/test_phase6.py`, "Phase 6: Keelokit's ledger"), is written, HRB-2 and HRB-3 are not. Phase 7, the lessons of the JOUNA fleet (the ok
straight to `all`, a sail preflight, a seam report, cutoffs, a 30-minute round), is designed in
[lessons-phase7.md](lessons-phase7.md); HRB-4, the ok straight to `all`, HRB-5, the sail preflight, HRB-6,
the seam report at assemble, HRB-7, a convoy's cutoff, and HRB-8, the 30-minute round (`tests/test_phase7.py`),
are written. The evidence is the survey of a week of convoys run by hand on
the fleet Harbor was learned on (see the appendix; its finding ids, `n.m`, are cited as `§n.m`, its
candidate rules as `R1`…`R26`). For how to use Harbor, see the [README](../README.md).

## Thesis

Keelokit lands one story per session directly on `main`; with many sessions, several accounts and
several machines, that means one `pnpm verify` per landing and nobody seeing the combination before
it is on `main` (§1.2, §4.11). That fleet replaced it with convoys: branches from several sessions merged
into one integration branch, verified once and pushed once. Its failures were not in the idea but in
the hand-kept parts: a board that drifted from reality (§5.8), a piece's "green" that no longer
matched its hash (§6.2), handoff files invisible from `main` (§5.4), migration timestamps renamed at
integration (§6.5), a loose push that orphaned a convoy branch (§6.9), budget cuts that left work
half pushed (§6.8). Harbor keeps the process and takes the hand work away: the shared state is a
git branch only `harbor.py` writes, with a fixed schema and generated views; a branch enters a
convoy only with a verify result recorded for its exact hash; the guard of the process (the
harbormaster) has a heartbeat that expires and is taken by the first commit. Harbor adds no
server and no events: every session reads the state with `git fetch`, so the logbook's schema is
the contract a future API would serve.

## Vocabulary

| Harbor | What it is |
|---|---|
| convoy | a batch of branches integrated in `convoy/<n>`, verified once, landed with one push |
| vessel | one piece's branch, built by one session (`/keelokit:build-story`) |
| skipper | the session that carries a convoy: takes deliveries, assembles, fixes the combination |
| harbormaster | the session that gives the ok to sail and keeps the watch |
| dispatcher | the one session per account that turns the logbook's messages and requests into actions in its account |
| logbook | the orphan branch `harbor/log`: TOML state plus generated views |
| gatekeeper | the person who decides what Harbor does not: budgets, accounts, critical oks |
| sail | the harbormaster's ok, then the integrator's one push to `main` |
| pilot | an account designated to integrate; optional, `integrator = "any"` by default |
| worker | `<account>/<host>/<session>`: one session of one account on one machine |

## What Harbor takes from Keelokit

Harbor depends on Keelokit and copies none of its code. It uses these as interfaces:

| Keelokit | Harbor uses it for |
|---|---|
| `.keelokit/` present | SessionStart: without it Harbor says so and does nothing |
| `[landing] policy = "convoy"` in `.keelokit/state.toml` | the switch (`doctor.py` `landing_policy()`); under it `build-story` pushes only its branch and reports branch, full hash, tier and verify result |
| `pnpm verify --since REF` | the vessel's own verify (its part only, routed by `verify-routing.toml`) |
| `pnpm verify --keep-going`, `--all`, `--preflight` | the convoy's one verify, scoped by its diff (`--all` by exception), after a preflight that fails in minutes on missing tools or a busy machine (VER-1) |
| `keelokit-verify.history` | one JSON line per run: `head`, `base`, `level`, `result`, `rc`, `partial`, `clean`, `scope`, `planned`, `passed`, `failed_steps`, `packages`, `step_packages`, steps with seconds, causes. Harbor copies it into the seal, and reuses a whole green run instead of repeating it |
| `[verify] shared_seals = "origin/harbor/log:harbor/seals/{head}.toml"` | Keelokit's `--use-seal` (the pre-push hook) accepts a Harbor seal when its `head` is the commit, its `base` is `origin/main` now, `exit = 0`, its `level` (`changed` or `all`) covers the request and the tree is clean. A push from any machine skips the verify another machine already ran. Trusting it is trusting whoever can push to `harbor/log` |
| `--steps`, `--rerun-failed`, `--packages`, `--filter` | narrower runs. All of them are *partial*: Keelokit never seals them, and Harbor never gives them a `level` |
| the local seal (`keelokit-verify.seal`) | per clone, never from `--since` or a partial run; the shared seal is what crosses machines |
| `doctor.py --scope ID`, `--brief` | the vessel session's own check before it delivers; Harbor does not rerun it *(phase 2: record its exit in the seal)* |
| `status.py`, `ci.py health` | the harbormaster's round: machine state, CI of `main` (Keelokit's `main`, whatever `[harbor] trunk` says) |
| tiers trivial / light / full | the first agent of a vessel and its model |
| `touches`, `critical.toml` | an early hotspot warning, before any code *(phase 2)* |
| the `Story:` trailer | which story a vessel carries, read from its commits (without the ledger, below) |
| `ledger.py --json` answering `"schema": 1` *(6)* | the switch for every phase-6 behaviour; any other answer, a timeout, an exit other than 0 or 1, or no `ledger.py`: Harbor behaves as 0.5 |
| `ledger.py attribution <seal_base>..<head> --json` *(6)* | `convoy add`: `NO_STORY` for a vessel's unattributed commit, and the vessel's story. The contract is in "Phase 6: Keelokit's ledger"; Keelokit builds it in LEDGER-013 (in its docs/ledger.md, not in its 0.16.0 code): until it answers, `convoy add` notes it and reads the `Story:` trailers |
| `ledger.py show <ID> --json`, else the story's `state` in `ledger.py --json` *(6)* | `story take`, `worker register --story`, `wanted take`: `STORY_ON_TRUNK` from `on-trunk` on (HRB-2). Keelokit 0.16.0 has `show <ID> [--full]` only, so the facts of `--json` answer; a ledger that can't say is a note, never a refusal |
| `ledger.py check --json` and the stories' `commit` and `state` in `ledger.py --json` *(6)* | HRB-3: the round's `ledger:` lines and a loose move's stories and unattributed commits; the ok's `LEDGER_DIFF`. Keelokit 0.16.0 answers `{"schema": 1, "diffs": [{"level", "code", "detail"}]}` with no story field, and `--json` counts unattributed commits without listing them, so Harbor reads the story of a `DONE_TWICE` from its detail and a loose move's unattributed commits from `check`'s `UNATTRIBUTED` details. At the ok a schema-1 ledger that can't answer is `LEDGER_UNAVAILABLE` (it fails closed) |
| `ledger.py take <ID>` *(6)* | the first line of a vessel's prompt (`wanted prompt`); with LEDGER-013 it calls `harbor.py story take` |
| the `Convoy: <n>` trailer *(6)* | ends each vessel's merge into `convoy/<n>`; the ledger reads from it which convoy sailed a commit (Keelokit 0.15 already reads it) |

Harbor needs **Keelokit 0.12.0** or later: the landing policy, shared seals, the pre-push that lets the
logbook through, and session titles are all there.

## Configuration

Project-wide, committed, in `.keelokit/state.toml` (read from the working tree of the session):

```toml
[landing]
policy = "convoy"                  # Keelokit's key; Harbor runs only with this value

[verify]                           # Keelokit's key; /harbor:adopt writes it
shared_seals = "origin/harbor/log:harbor/seals/{head}.toml"

[harbor]
integrator = "any"                 # "any": a convoy's skipper integrates on its own machine; or a pilot account name
trunk = "main"                     # the branch convoys are measured against, merge and sail to; "develop" where main is production
vessel_verify = "pnpm verify --since {base} --keep-going"   # {base} = origin/main when the seal runs; also {head}, {branch}
convoy_preflight = "pnpm verify --preflight"        # (2) before every convoy verify; "" turns it off
convoy_verify = "pnpm verify --keep-going"          # (2) level "changed": scoped by the convoy's diff against main
convoy_verify_all = "pnpm verify --all --keep-going" # (2) level "all": only what the routing can't bound
convoy_rerun = "pnpm verify --rerun-failed --keep-going"   # (2) after a red; Keelokit seals it when it completes the plan
convoy_rerun_all = "pnpm verify --all --rerun-failed --keep-going"   # (7) after a red at level "all"; keeps level all
own_verify = false                 # true: the verify commands are the project's own, not Keelokit's ("A level without Keelokit's record")
all_when_covered = 0.9             # (7) the ok's level is `all` when the scoped plan has every step of --all and this share of its packages
ci_check = "python3 .keelokit/bin/ci.py health"     # (2) the ok needs it green (exit 1 = red); default when ci.py exists
person_ok = "critical"             # (2) a person's yes too: "critical" (full tier or a critical area), "areas" (a critical area only), "always", "never"
control_every_minutes = 30         # (7) every 30 minutes, as JOUNA's rounds (was 90, from the first fleet, §5.3)
watch_expiry_minutes = 180         # a value from the first fleet (§5.3): relief after 3 hours without a control

[harbor.models]                    # Harbor's own roles; `harbor.py models` prints what applies (§3.3)
skipper = "sonnet"
harbormaster = "sonnet"            # the ok: judgment
control = "haiku"                  # the round: reads the logbook, git and the CI, and reports
# The story roles (verifier, builder, reviewer, breaker) follow Keelokit's table by role and tier in
# .keelokit/harness/agent-brief.md (Opus for tests and review in the full tier); no second table here.

[harbor.hotspots]                  # name = path globs; a trailing "/" is a prefix
schema = ["apps/api/prisma/schema.prisma", "apps/api/prisma/migrations/"]
shared-types = ["packages/shared-types/"]
locales = ["apps/mobile/src/i18n/locales/"]

[harbor.generated]                 # path glob = command that regenerates it at assembly (phase 2)
"6-Manual/site/pagefind/*" = "pnpm docs:build"

[harbor.migrations]                # (phase 2) default: Keelokit doctor's globs
paths = ["apps/*/prisma/migrations", "*/migrations", "db/migrations"]
```

The example hotspots are the first fleet's measured bottlenecks (§2.12); a project declares its own.
Harbor ships no default hotspot list: that §2.12's contention generalises is **EVIDENCE** at best.

**The trunk.** This document says `main` for the branch convoys land on. It is `[harbor] trunk`:
`main` unless the project names another, as one does whose `main` is production and deploys on every
push, and which integrates on `develop`. Harbor fetches the trunk, takes a convoy's base from it,
measures hotspots and migrations against it, merges it into `convoy/<n>`, and `sail` pushes to it;
the PreToolUse note goes to a push that moves it. With another trunk Harbor never pushes `main`.
- The name is read from the session's working tree, like the rest of the block, once per command
  (`keelokit()`), and every hook that acts on the trunk reads it the same way. Without a state file
  or without the convoy policy it is `main`.
- It must be a branch name (letters, digits, `. _ -` and `/`) and can't be `harbor/log`, `convoy/<n>`
  or a name git can't keep beside them (`convoy`, `harbor`): `BAD_CONFIG`, exit 2. In a hook that is
  one line at SessionStart and silence elsewhere, exit 0.
- The logbook's schema keeps its names: `harbor/main.toml`, `main_before`, `main_after`, the event
  `main-moved`, the codes `NO_MAIN`, `MAIN_MOVED`, `MAIN_RED`. They hold the trunk, and `schema`
  stays 1. Messages and the generated views name the real branch (the logbook's `Main` heading
  becomes `Trunk`, with the branch).
- **Assumption:** every checkout reads the same `trunk`. The logbook doesn't record it, so a session
  whose checkout has another value measures against, and would sail to, another branch. So it is
  written in the commit that sets the policy: a checkout from before has no convoy policy and
  Harbor does nothing there, and none has the policy without the trunk.
- **Out of scope, Keelokit's side:** Keelokit's own tools still speak of `main`. `status.py`,
  `ci.py health` and the agent brief say `main`, so with another trunk `ci_check` names a command
  that looks at the trunk's CI. Its `--use-seal` compares a shared seal's base with `origin/main`,
  and its `verify.sh` writes the base it measured against in the history line: Harbor gives a run a
  `level` only when that base is the trunk's tip, so with another trunk Keelokit's verify has to
  measure against that branch too, or its runs get no `level` here (safe: the pre-push runs its
  verify, and a convoy doesn't sail on a run measured against something else). **Assumption:** not
  checked against a Keelokit configured for another branch; the tests use a stand-in. A project
  with its own verify and no Keelokit `verify.sh` uses `own_verify`, which needs no history line.

Per clone, git-ignored, in `.keelokit/local.toml`:

```toml
[harbor]
account = "acct1"    # the Claude account this clone's sessions run on
host = "mbp"       # this machine
```

The session id comes from `--session`, `$HARBOR_SESSION` or `$CLAUDE_SESSION_ID`; the SessionStart
hook prints it (`this session is acct1/mbp/<id>`), read from the hook's JSON.

## The logbook

The orphan branch `harbor/log` on `origin`. It never shares history with `main`, so writing it
never moves `main` or triggers its CI (§2.3).

```
harbor/LOGBOOK.md               generated: watch, convoys, the sessions as a tree, accounts, import
harbor/convoys/<n>.md           generated: one convoy, its vessels and events
harbor/logbook.toml             created, created_by
harbor/harbormaster.toml        the watch
harbor/accounts/<account>.toml  cap and pause of one account
harbor/workers/<account>/<host>/<session>.toml
harbor/convoys/<n>.toml
harbor/runs/<sha>.toml          Harbor's record of one verify of one exact commit: green, red or partial
harbor/seals/<sha>.toml         the shared seal Keelokit's pre-push reads: only for a whole green run Keelokit recorded
harbor/main.toml                (phase 2) the last main (the trunk) Harbor saw, and every move of it
harbor/imported/BOARD.md        (once) the hand-kept board file, verbatim
harbor/imported/board.toml      (once) what the import took and left
```

Everything is under `harbor/`. Keelokit 0.12's pre-push lets a push of this branch through without a
verify only then, and only when every new seal in it is backed by a whole green run on that
machine; logbooks from before keep working, and their root views go on the next write.

**Writes.** Only `harbor.py`, in one transaction per command: fetch `harbor/log`; read the tree;
apply the command's change, which checks its own preconditions against that state; regenerate the
views; build one commit with plumbing (`read-tree`, `hash-object`, `update-index`, `commit-tree` in
a temporary index, so the session's checkout and index are never touched); `git push origin
<commit>:refs/heads/harbor/log`, never `--force`. A rejected push means someone wrote first: the
command starts again from the new tip and its preconditions are checked again, so a convoy cap, a
hotspot or the watch can't be taken twice by two sessions that read the same old state (tested in
`TestRejectedPush`). The decision said "`pull --rebase` on rejection"; this is the same order of
commits (ours on top of theirs, linear history) without the textual rebase, because the views
change on every write and would conflict every time, and because a clean textual rebase can still
break a rule (two adds of the same hotspot in different files). **Needs your ok.** After five
rejections in a row the command stops without writing (a bound chosen for the code, not from the
survey).

**Reads.** Every command fetches first. The hooks keep a session's view fresh between commands
(§"Fresh reads").

**Views.** `LOGBOOK.md` and `convoys/<n>.md` are rendered from the TOML on every write, start with
a do-not-edit comment, and carry no clock of their own, so a write that changes no TOML changes
nothing. They replace a hand-kept board file and a per-convoy handoff file (R1, R2): they live on the state branch, not on
a skipper's branch (§5.4), and can't say anything the data doesn't (§5.8).

## Schemas

Every file has `schema = 1`. Times are UTC, `YYYY-MM-DDTHH:MM:SSZ`. Absent keys are omitted, never
written empty. A field marked *(2)* is written from phase 2.

### `harbor/harbormaster.toml`

```toml
schema = 1
worker = "acct1/mbp/session_01KwSx"
since = "2026-11-01T09:42:00Z"
last_control = "2026-11-01T15:21:00Z"
expires = "2026-11-01T18:21:00Z"        # last_control + watch_expiry_minutes

[[history]]                              # (2) one row per holder
worker = "ana/linux/session_02Ab"
since = "2026-10-31T19:51:00Z"
until = "2026-11-01T09:42:00Z"
reason = "expired"                       # expired | handed over | relieved by the owner
```

Phase 1 writes `schema` only: nobody holds the watch until `/harbor:harbormaster takeover`.

### `harbor/accounts/<account>.toml`

```toml
schema = 1
account = "acct1"
max_sessions = 2                 # active workers of this account at once; chosen by the person, no default
paused_until = "2026-11-02T03:00:00Z"
reason = "weekly limit"
updated = "2026-11-01T16:00:00Z"
updated_by = "acct1/mbp/-"
```

Only a clone of that account changes it. `worker register` refuses beyond `max_sessions` and while
`paused_until` is in the future (R12). Harbor measures sessions, not tokens: the survey has no token
data (§3.16), so the cap is the person's estimate of the budget, not a measurement.

### `harbor/workers/<account>/<host>/<session>.toml`

```toml
schema = 1
id = "acct1/mbp/session_01Abc"
account = "acct1"
host = "mbp"
session = "session_01Abc"
role = "vessel"                  # vessel | skipper | harbormaster
convoy = 8
branch = "claude/carga-001"
model = "sonnet"
registered = "2026-11-01T10:40:00Z"
last_seen = "2026-11-01T15:02:00Z"   # every write by this worker
state = "ended"                  # active | ended | lost (2: set by the harbormaster's control)
ended = "2026-11-01T16:48:00Z"
spawned_by = "acct1/mbp/session_01Sk"   # the session that launched this one, and owns its result
title = "vessel C8 · acme-a · Acme · wave 1 · STORY-001"   # (3) the session title (see "Names")
canonical_branch = "carga-001"   # (3) the story id in lower case; `branch` is the one the session really uses
story = "CARGA-001"              # (6, HRB-2) optional: the story it took (`story take`, `worker register --story`).
                                 # Held while state = "active"; kept after it ends or is lost, as the record, holding nothing
children_at_end = ["acct1/mbp/session_01Ve"]   # sessions it launched that were still running when it ended

[handover]                       # on a budget cut or any early end (R22)
branch = "claude/carga-001"
head = "4d44fdd8…"              # checked equal to origin/<branch>: only pushed work is handed over
verified = "seal of 4d44fdd8 green; doctor --scope STORY-001 green"
pending = "screenshots of S3; reviewer round 2"
worktree = "../app-carga-001"
log = "/tmp/verify-carga-001.log"
```

### `harbor/convoys/<n>.toml`

```toml
schema = 1
number = 8
title = "STORY wave 1"
state = "verifying"              # assembling | waiting | ready | verifying | sailed | aborted
branch = "convoy/8"
skipper = "acct1/mbp/session_01Abc"
integrator = "acct1/mbp/session_01Abc"   # the skipper when integrator = "any"; "account:<pilot>" until a pilot session takes it
base = "a2becf56d…"              # origin/main at new; (2) the main last merged into convoy/<n>
head = "60099ef60…"              # (2) tip of convoy/<n> after the last assembly or fix
created = "2026-10-31T19:51:00Z"
depends_on = [7]                 # convoys that must sail first (R15)
expected = ["STORY-000", "STORY-001", "STORY-003"]   # the mandatory stories
optional = ["STORY-004"]         # (7, HRB-7) taken if delivered by the cutoff; absent with none
cutoff = "2026-11-01T18:00:00Z"  # (7, HRB-7) UTC; after it, assemble defers the optional stories not delivered; absent with none
deferred = ["STORY-002"]         # (2) stories that left for the next convoy (convoy defer, or the cutoff)
fixes = ["b71c0e2a4…"]           # (7) the integrator's fix commits on convoy/<n>, recorded by assemble and verify

[ok]                             # (2) the harbormaster's ok (R19)
by = "ana/linux/session_02Ab"
at = "2026-11-01T13:01:00Z"
level = "all"                    # changed | all
reason = "migrations and verify scripts: the risk table says --all"
base = "a2becf56d…"              # main when the ok was given
head = "60099ef60…"              # the convoy head the ok covers
needs_person = "full-tier vessels claude/carga-001"   # why a person's yes is also needed; absent when it isn't
level_by = "plan"                # (7) "plan" (Keelokit's plans chose it) or "harbormaster" (--level); absent with no plan
plan = "the scoped plan covers --all: every step and 46 of 48 packages (96% ≥ 90%)"   # (7) what the plans said

[ok.person]                      # (2) that yes, from the person's own terminal
by = "acct1/mbp/-"
at = "2026-11-01T13:20:00Z"
head = "60099ef60…"              # bound to this head: a later commit needs another yes
note = "read the diff"

[sail]                           # (2)
by = "acct1/mbp/session_01Abc"
at = "2026-11-01T14:30:00Z"
main_before = "a2becf56d…"
main_after = "60099ef60…"
ci = "green"                     # (2) recorded by the next control from ci.py health

[[seams]]                        # (7, HRB-6) written by assemble from the vessels' diffs; absent with none
id = "s-3fa21c0"                 # bound to the kind, the key and the heads of its vessels: a redelivery is a new seam
kind = "file"                    # file | name | selector | token | route
key = "apps/web/nav.tsx"         # the path, exported name, CSS selector, token or route path
vessels = ["claude/carga-001", "claude/carga-003"]
detail = "added by claude/carga-001, in claude/carga-003's tests (apps/web/nav.test.ts)"   # routes only
note = "fixed in 9d2e41b07"      # convoy seam: fine…, fixed in <commit>, or a question (ends in ?)
read_kind = "fixed"              # fine | fixed | question
read_by = "acct1/mbp/session_01Abc"
read_at = "2026-11-01T12:40:00Z"

[[vessels]]
branch = "claude/carga-001"
head = "4d44fdd8…"               # the delivered commit; the remote tip must still be it
story = "STORY-001"              # --story, else (6) the ledger's attribution of its commits, else their Story: trailers
tier = "full"                    # as the vessel session chose it (Keelokit's tier)
hotspots = ["schema"]            # computed from its diff against main and [harbor.hotspots]
seal_base = "a2becf56d…"         # the main its vessel verify ran against
added = "2026-11-01T11:10:00Z"
added_by = "acct1/mbp/session_01Abc"
merged = "9c1e…"                 # (2) its merge commit on convoy/<n>

[[events]]                       # every step, with time and worker (R23)
at = "2026-11-01T11:10:00Z"
by = "acct1/mbp/session_01Abc"
what = "add"                     # new add redelivered assembled main-moved ok verify-start verify-pass
detail = "claude/carga-001@4d44fdd8"   # verify-fail fix preflight-failed sailing sailed aborted skipper-changed imported
                                       # seams seam-read (7, HRB-6)
```

Imported convoys carry `imported = true`, `imported_skipper` (the board's text) and `handoff`, and no
vessels: nothing entered them through Harbor, so nothing in them is sealed.

### `harbor/runs/<sha>.toml` and `harbor/seals/<sha>.toml`

The run record (`runs/`) is Harbor's; the seal (`seals/`) is the contract with Keelokit, and holds
only what its pre-push reads, written only when the run is whole, green, not `--since`, on a clean
tree, and against the `main` of the moment it is written:

```toml
head = "4d44fdd8…"
base = "a2becf56d…"
exit = 0
level = "changed"
```

The run record:

```toml
schema = 1
kind = "vessel"                  # vessel | convoy (2)
head = "4d44fdd8…"               # the commit; the file name is the full sha
branch = "claude/carga-001"
base = "a2becf56d…"
command = "pnpm verify --since a2becf56d…"
exit = 0
result = "pass"                  # pass | fail
started = "2026-11-01T10:52:00Z"
finished = "2026-11-01T11:06:00Z"
duration_seconds = 840
by = "acct1/mbp/session_01Abc"
level = "changed"                # only for a whole green verify (below): what Keelokit's pre-push reads
level_source = "harbor"          # only when Harbor gave the level itself (own_verify): such a run has no seals/ file
reused = true                    # recorded from Keelokit's own run of this commit instead of running again
composite_of = "9f3c…"           # a composite run: the head of the first red run it builds on (and rerun_of, inherited)
keelokit_level = "changed"       # the rest is copied from keelokit-verify.history when it has a line for this run
partial = false
scope = ""                       # --packages / --filter selectors, if any
planned = ["lint", "unit", "e2e-stack"]
passed = ["lint", "unit", "e2e-stack"]
failed_steps = []
causes = []                      # Keelokit's known causes of a red, by id
packages = ["apps/web"]

[[steps]]                        # one per step of the run, in order
name = "unit"
seconds = 340
```

**`level` and the false green.** Keelokit's pre-push skips its verify for any seal with `level`,
so Harbor writes `level` only when Keelokit's own history line for this run says: this exact
commit, this base, `result = "pass"`, `rc = 0`, `partial = false`, `clean = true`, and a level of
`changed` or `all`. A command that leaves no history line, a partial run (`--steps`, `--packages`,
`--rerun-failed` that narrowed), a dirty start or another base: the seal still lets the vessel into
a convoy (it is green on that hash), but it carries no `level`, and the pre-push runs its verify.
Checked against Keelokit's `verify_tools.py shared-seal` from `landing-policy`.

**A level without Keelokit's record (`own_verify`).** A project adopted in Keelokit's harness mode
has `.keelokit/` and no `scripts/verify.sh`: its verify is its own command, which writes no history
line, so by the rule above no run of it gets a `level` and no convoy sails. `[harbor] own_verify =
true` declares that the verify commands are the project's own. Then a convoy verify that exits 0 on
a clean tree with `HEAD` unchanged (`SEAL_INVALID` otherwise, as always), and that left no Keelokit
history line, gets its level from Harbor: `changed` when it ran `convoy_verify`, `all` when it ran
`convoy_verify_all`, which is the level the ok asked for. The run record says where it came from
(`level_source = "harbor"`), and the convoy's events and view show it (`changed (own verify)`).
- **Never a shared seal.** `harbor/seals/<sha>.toml` is written only for a level Keelokit's own
  record gave. A project's command proves nothing about Keelokit's verify, so a Keelokit pre-push,
  where there is one, runs its verify. `convoy verify` and `sail` read `harbor/runs/`, so the convoy
  sails without the seal.
- **No rerun.** `convoy_rerun` stands for a whole verify only because Keelokit records when it
  completed the plan. A project's own rerun leaves no such record, so with `own_verify` the key is
  not used: after a red, the next `convoy verify` runs the level's command again. **Needs your
  ok:** running `convoy_rerun` and never sealing it would have left a red convoy with no way to a
  seal short of another commit and another ok.
- **No level for a vessel.** `convoy add` asks a vessel's seal for `exit = 0` only; its `level`
  matters to the shared seal and to a one-vessel convoy skipping its verify. So `harbor.py seal` is
  unchanged, and with `own_verify` a one-vessel convoy runs its convoy verify.
- **Keelokit's record decides when there is one.** If the command did run Keelokit's verify (a
  history line for this commit, written during the run), that line gives the level or withholds
  it, as without the key.
- **Assumption:** Harbor trusts the declaration. `changed` and `all` here name the command that
  ran, not a scope anyone measured: that `convoy_verify` is the project's whole verify of what the
  convoy changed, and `convoy_verify_all` of everything, is the project's word, like
  `vessel_verify`. With `own_verify` the project also sets `vessel_verify` and `convoy_preflight`
  (`""` turns it off): their defaults are Keelokit's `pnpm verify`.

With `own_verify = false`, the default, nothing changes: a green run without Keelokit's record is
`verify-unsealed`, and sail refuses it (`NOT_SEALED`).

**No second run.** With the convoy policy, `build-story` pushes the vessel's branch, and its
pre-push runs Keelokit's whole verify on that exact commit. `harbor.py seal` finds that run in the
history (same commit, today's `main`, whole, green, clean) and records it without running anything
(`reused = true`); `--rerun` forces a fresh run. One verify per vessel, not two.

`harbor.py seal`, when it runs, runs the command itself on a clean tree and refuses to record if `HEAD` or the
tree changed during the run: the record speaks for one commit. A red run is recorded too (the
history the survey couldn't reconstruct, §4.9). A later commit has another sha and so no seal:
the delivery is void by construction (R3).

### `harbor/main.toml` *(phase 2)*

The file and its keys are named `main` whatever `[harbor] trunk` is: they record the trunk.

```toml
schema = 1
head = "60099ef60…"              # the last origin/main (origin/<trunk>) Harbor saw

[[moves]]
from = "a2becf56d…"
to = "7baa0a279…"
seen = "2026-10-31T18:31:00Z"
cause = "loose"                  # "convoy 7" when a sail explains it; "loose" otherwise (R18)
```

### `harbor/imported/board.toml`

`source`, `sha256`, `imported`, `by`, `coordinator` (the text after "coordinator:"), `convoys` (numbers
imported), `skipped` (rows left out, with the reason). The parser takes markdown tables whose header
has a convoy number column and a state column, maps *assembling / waiting / ready / verifying / on
main* to the states below, and skips rows without a number. It knows English words only (the columns
`convoy`, `#`, `n`, `number`, `skipper`, `branch`, `state`, `handoff`); a project whose board uses other
words adds them in `state.toml`: `[harbor.import] columns = { number = ["…"], skipper = ["…"] }`, `states =
{ sailed = ["…"] }` and `coordinator = ["…"]`; an empty word is `BAD_CONFIG` (it would match every row). **Assumption:** the column layout of the board is known
only from a description (§5.1); the tests use a board written from that description, not a real file.

## Life of a convoy

| State | Means |
|---|---|
| `assembling` | created; the skipper takes deliveries |
| `waiting` | assembled with what was delivered; an expected vessel, an optional one before the cutoff *(7)*, or a convoy it depends on, is still missing, or a seam is unread *(7)* |
| `ready` | every expected vessel merged in `convoy/<n>` with `main`; migrations in order, generated files regenerated: waiting for the ok |
| `verifying` | the ok is given with its level; the integrator runs the convoy's one verify and fixes the combination |
| `sailed` | pushed to `main`; hotspots released |
| `aborted` | given up; its vessels may join another convoy; `convoy/<n>` stays on the remote for reference |

| From → to | Command | Who | When |
|---|---|---|---|
| — → assembling | `convoy new` | any active worker, who becomes its skipper | account not paused; every `--depends` convoy exists; `--cutoff` a time with its zone *(7)* |
| assembling, waiting → same | `convoy add` | the skipper | the vessel is pushed, sealed green on that exact commit, holds no hotspot another open vessel holds, is in no other open convoy |
| assembling, waiting → waiting | `convoy assemble` *(2)* | the integrator | merged what was delivered; something expected or a dependency is missing |
| assembling, waiting → ready | `convoy assemble` *(2)* | the integrator | every expected vessel merged, every optional one merged or deferred at the cutoff *(7)*, `main` merged in, every dependency sailed, migration check passed, every seam read *(7)* |
| waiting → same | `convoy seam N ID --note` *(7)* | the skipper or the integrator | one seam of the report read: fine, fixed in a commit, or a question |
| ready, verifying → assembling | `convoy assemble` *(2)* | the integrator | `main` moved, a vessel was redelivered, or one was added: the ok is cleared |
| ready → verifying | `convoy sail --ok` *(2)* | the harbormaster, holding an unexpired watch | the ok conditions below |
| verifying → same | `convoy approve` *(2)* | the person, from their own terminal | only a critical convoy (`person_ok`); bound to the head |
| verifying → verifying | `convoy verify` *(2)* | the integrator | a run, green or red; fixes in between |
| verifying → sailed | `convoy sail` *(2)* | the integrator | green convoy seal on the exact head at the ok's level; `main` still the ok's base |
| assembling, waiting → same | `convoy defer N STORY` *(2)* | the skipper | an expected (or optional, *7*) vessel is late: it leaves `expected` and goes to the next convoy, so the rest don't wait for it. **Needs your ok:** not in the agreed command list |
| any open → aborted | `convoy abort` *(2)* | the skipper or the harbormaster | with a reason. **Needs your ok:** `abort` is not in the agreed command list |

"Sail = ok + push" is one verb in two halves: the harbormaster's `sail --ok` and the integrator's
`sail`. When the harbormaster is also the integrator they run back to back. The ok comes before the
verify because the ok chooses the verify (R19, §4.6) and the survey's push hook ran it after the ok
(§4.7). **Needs your ok.**

## Commands

Each slash command is a skill that runs `harbor.py` and does the parts that need judgment. Errors
print `harbor: CODE: why` and exit 1 (refused) or 2 (environment or command line).

### `/harbor:adopt`

- **Before:** `.keelokit/` exists (else: `/keelokit:project-adopt` first, and stop); a remote `origin`.
- **Does:** shows and, with the person's yes, writes `[landing] policy = "convoy"` and a `[harbor]`
  block in `state.toml`, landed on the trunk the current way (it is the last direct landing); writes
  `.keelokit/local.toml` (asks account and host) and adds it to `.gitignore`; `harbor.py init`;
  `harbor.py account set <account> --max-sessions N` with the number the person gives; proposes
  hotspots (critical areas, migration folders, shared packages, locales, generated files, and the
  paths with most commits in `git log` lately) for the person to confirm; asks whether the
  project keeps a hand-kept board (a file in the tree or on a branch, wherever the person says) and, with a yes,
  imports it once.
- **Logbook:** the first commit (`harbormaster.toml`, `logbook.toml`, views); `accounts/<account>`;
  the import.
- **Errors:** `NO_KEELOKIT`, `NO_IDENTITY`, `ALREADY_IMPORTED`; `init` again is a no-op.

### `/harbor:convoy new`

- **Before:** an active worker (`harbor.py worker register`); its account not paused; `--depends`
  convoys exist and aren't aborted.
- **Logbook:** `convoys/<n>.toml` with the next number (after imported ones), base = `origin/main`,
  skipper = this worker, integrator per `[harbor] integrator`; the worker's role becomes skipper.
  Event `new`. *(7, HRB-7)* `--expect` is the mandatory list; `--optional STORY …` the stories taken if
  they come in time (`optional`); `--cutoff <UTC time>` (ISO 8601, like `2026-11-23T18:00Z`; another offset
  is converted) is stored as `cutoff` in UTC and named in the event. Both keys are absent when not given.
- **Errors:** `NOT_REGISTERED`, `ACCOUNT_PAUSED`, `UNKNOWN_CONVOY`, `NO_MAIN`; `USAGE` (exit 2) for a
  cutoff that is not a time with a zone, or a story both expected and optional.

### `/harbor:convoy add N BRANCH`

- **Before:** convoy `N` is assembling or waiting; the caller is its skipper; `origin/BRANCH`
  exists and, with `--head`, is exactly that commit; a green seal for that commit; its hotspots
  (from `git diff` against the merge base with `main`) not held by any vessel of an open convoy;
  the branch in no other open convoy.
- **Logbook:** the vessel row (or replaces it: a redelivery after a fix), event `add` or
  `redelivered`, the skipper's `last_seen`. *(7, HRB-7)* `--optional` marks the vessel `optional = true`
  and moves its story from `expected` to `optional`.
- **The ledger** *(6, HRB-1)*: with Keelokit's ledger, before the vessel is recorded, `ledger.py attribution
  <seal_base>..<head> --json`; an unattributed non-merge commit of the vessel's own refuses the add with
  `NO_STORY` and how to attribute each commit, and the vessel's story is the ledger's ("Phase 6: Keelokit's ledger").
- **Errors:** `BRANCH_NOT_PUSHED`, `HEAD_MISMATCH`, `NO_SEAL`, `SEAL_RED`, `HOTSPOT_HELD`,
  `VESSEL_TAKEN`, `NOT_SKIPPER`, `CONVOY_CLOSED`, `UNKNOWN_CONVOY`, `SAILING` (an abort while the
  sail is pushing the trunk), `NO_STORY` *(6)*.
- `convoy status [N]` (read-only) shows, for open convoys, when `main` moved past the base and when
  a vessel's branch moved after delivery ("the delivery is void").

### `/harbor:convoy assemble N` *(phase 2)*

- **Before:** the integrator (the skipper when `integrator = "any"`; a session of the pilot account
  otherwise, which becomes the convoy's integrator); state assembling, waiting, ready or verifying;
  every vessel's remote tip still its delivered head (`VESSEL_MOVED` otherwise).
- **Does:** creates `convoy/<n>` from the base if absent; merges `origin/main` into it if `main`
  moved (merge, not rebase, §4.3); merges each unmerged vessel in order (`depends_on` among
  stories, then the order given, then the order added, §4.4), `--no-ff`. *(6, HRB-1)* With Keelokit's ledger,
  each vessel's merge is always a merge commit (never a fast-forward, `--no-log`) whose message ends with the
  trailer `Convoy: <n>`; a `CONFLICT` prints the merge command that keeps it, and a vessel whose merge on the
  convoy branch lacks it (a merge by hand) is named in the output. `main`'s merge carries none. A conflict only in
  `[harbor.generated]` paths: run its command and commit the result (R17). A conflict only in
  formatting: Keelokit's FMT-1 (keep the content, `pnpm format`). Any other conflict: stop with
  `CONFLICT` and the files; the skipper resolves it in a combination commit. Then the migration
  check: two vessels adding migrations with the same timestamp, or one that sorts before `main`'s
  last, fail with `MIGRATION_COLLISION` / `MIGRATION_ORDER` and the rename to make (R16). Pushes
  `convoy/<n>` without force; a rejection means another integrator pushed and it stops.
- **Seam report** (HRB-6, phase 7): with two or more vessels, from each vessel's diff against its merge
  base with `main` (`[harbor.generated]` paths left out, since they are rebuilt), mechanically:
  1. *file:* a file changed by two or more vessels;
  2. *name:* an exported name defined or changed by two or more vessels, in any file: TypeScript and
     JavaScript `export [default] [async] const|function|class|type|interface <Name>`, Python `def` /
     `class` at module level. A changed line counts for the definition it is, or for the unindented
     definition it sits under;
  3. *selector* / *token:* a CSS selector (the rule a changed line opens or sits in) or a design token
     (a custom property `--name:` or an SCSS `$name:` defined on a changed line) in `.css`, `.scss`,
     `.sass`, `.less` changed by two or more vessels;
  4. *route:* a route path (a quoted literal starting with `/`, with a letter in it) on a line one
     vessel's code adds that appears in a test file another vessel changed (`tests/`, `__tests__/`,
     `e2e/`, `*.test.*`, `*.spec.*`, `test_*.py`, `*_test.py`).
  Each seam gets an id bound to its kind, key and the heads of its vessels (`s-` and 7 hex), so a
  redelivered vessel makes its seams new seams to read, and the same vessels keep their reads across
  assemblies. The report goes into the event `seams` (when the list changed) and to the output: at most
  20 seams listed, then `(+N more)`; every seam is kept in `[[seams]]`. The convoy reaches `ready` only
  when every seam has a `seam-read`; until then it is `waiting` for "N seam(s) to read". One vessel has
  no seams and no report.
- **Cutoff** (HRB-7, phase 7): an optional story not delivered keeps the convoy `waiting` until the cutoff
  (with no cutoff, until the skipper defers it). At or after the cutoff, assemble defers every optional
  story not delivered, as `convoy defer` does by hand (it leaves `optional` and joins `deferred`), one
  event `deferred-at-cutoff` each, and prints `convoy new --optional <STORY>` for the next convoy. A
  mandatory story missing past the cutoff is never deferred: the convoy stays `waiting` and the round
  names it.
- **Logbook:** `head`, `base`, `vessels[].merged`, `[[seams]]` *(7)*, the state, events `assembled` /
  `main-moved` / `seams` *(7)* / `deferred-at-cutoff` *(7)*; a move of `main` clears `[ok]`.
- **Errors:** `NOT_INTEGRATOR`, `DIRTY_TREE`, `VESSEL_MOVED`, `CONFLICT`, `GENERATED_FAILED`,
  `MIGRATION_COLLISION`, `MIGRATION_ORDER`, `DIVERGED` (local and remote `convoy/<n>` disagree),
  `CONVOY_PUSH_REJECTED`, `ASSEMBLE_STALE` (vessels changed meanwhile). An open dependency is not an
  error: the convoy waits.

### `harbor.py convoy seam N SEAM_ID --note TEXT` *(phase 7, HRB-6)*

- **Before:** the convoy's skipper or integrator, an active worker; the convoy open; `SEAM_ID` in its
  `[[seams]]`. The note is one line (at most 500 characters) and says what the seam is: `fine…` (the two
  vessels meet without trouble), `fixed in <commit>` (a commit on `origin/convoy/<n>`: the fix is pushed
  first), or a question (ends in `?`; it counts as read, and shows in `convoy status` and the convoy page
  for the harbormaster before the ok).
- **Logbook:** the seam's `note`, `read_kind`, `read_by`, `read_at`; event `seam-read` with the seam
  and the note. Reading a seam again replaces the note. When the last one is read, the next `assemble`
  reaches `ready`.
- **Errors:** `USAGE` (a note that is none of the three), `UNKNOWN_SEAM`, `NOT_ON_CONVOY` (the fix
  commit isn't on the convoy branch), `NOT_SKIPPER`, `CONVOY_CLOSED`.

### `/harbor:convoy sail N --ok [--level changed|all] [--reason TEXT]` *(phase 2; the level from the plans, phase 7)*

- **Before:** the harbormaster with an unexpired watch; state ready; the convoy's `base` is
  `origin/main`; `ci.py health` says `main` is green where CI is reachable; nothing expected is
  missing (§4.7).
- **The level** (R19): `changed` by default, `all` only for what Keelokit's routing can't bound;
  the reason names the files that decided it. The rules, and why money or migrations don't force
  `all`, are in "Verifying without a bottleneck". Without `--level`, Keelokit's two plans decide it
  (HRB-4, rule 6 there) and `--reason` is optional; with `--level` the harbormaster's word wins and
  `--reason` is required. With no Keelokit plan to read, `--level` is required, as before (`USAGE`).
- **Logbook:** `[ok]`, state verifying, event `ok`. When the plans were read, `[ok]` also has `plan`
  (what they said) and `level_by` (`plan` or `harbormaster`); a reason Harbor wrote says so.
- **The ledger** *(6, HRB-3)*: with a schema-1 ledger the ok asks it and refuses `LEDGER_DIFF` for a vessel
  whose story has an error difference, or fails closed with `LEDGER_UNAVAILABLE` when it can't answer
  ("HRB-3: the ledger in the round and in the ok"); `[ok]` gets `ledger = "checked"`.
- **Errors:** `NOT_HARBORMASTER` (also for an expired watch), `WRONG_STATE`, `MAIN_MOVED`,
  `CONVOY_MOVED`, `MAIN_RED`, `ALREADY_COVERED` (an ok asked on a verifying convoy whose head already
  has a green run covering that level: it sails, nothing runs again), *(6)* `LEDGER_DIFF`, `LEDGER_UNAVAILABLE`.

### `harbor.py convoy approve N [--note TEXT]` *(phase 2)*

- **Who:** the person, from their own terminal. Harbor's PreToolUse hook (`harbor.py guard
  --claude`) blocks the command when an agent runs it; Bash can reach anything, so it is a speed
  bump, as Keelokit's `allowTamper` is, not a sandbox.
- **When it's needed:** `[harbor] person_ok`. `"critical"` (default): a vessel of the full tier or one
  whose diff touches an area of `.keelokit/critical.toml`; `"areas"`: only that second case, so a full-tier
  story outside the critical areas sails on the harbormaster's ok; `"always"`; `"never"`. The ok records why
  (`needs_person`).
- **Before:** state verifying; the ok says a person is needed; `convoy/<n>` is at the head the
  logbook has. The yes is bound to that head: a later commit needs another.
- **Logbook:** `[ok.person]` (`by`, `at`, `head`, `note`), event `approved`. The verify doesn't wait for
  it; only `sail` does (`NEEDS_PERSON`).
- This follows Anthropic's AI-native SDLC playbook: layered agent review for routine work, people
  for critical code, and the agent acts up to the gate and doesn't cross it.

### `/harbor:convoy verify N` *(phase 2)*

- **Before:** the integrator; state verifying; `origin/main` is still the ok's base (else
  `MAIN_MOVED`: back to assemble); `convoy/<n>` still contains the head the ok covered (fixes are
  commits on top, never a rewrite). After a red, the next run is `pnpm verify --rerun-failed`: it
  runs the fix's own routed steps plus the failed ones, which is what R7 asked of a separate fix
  seal (§6.3), so there is no fix seal. With `own_verify`, the next run is the level's command again.
- **Does:** nothing, when the convoy is one vessel sealed against today's `main` and its head is
  that vessel's head: the seal already is the convoy verify. Otherwise `pnpm verify --preflight`,
  then the level's command on the convoy head, in the background with a log (Keelokit's agent
  brief), event `verify-start` with the host first, because the verify lock and its state are
  local to one machine (§5.6). After a red and its fixes, the rerun is as narrow as Keelokit allows
  (see "Verifying without a bottleneck").
- **Logbook:** a `kind = "convoy"` seal; `verify-pass` or `verify-fail` with the failed steps.
- **Errors:** `NOT_INTEGRATOR`, `MAIN_MOVED`, `CONVOY_REWRITTEN`, `DIRTY_TREE`, `SEAL_INVALID`
  (HEAD or the tree changed during the run). A red preflight is a red run (`verify-fail`). A green
  run Keelokit didn't record as whole at the ok's level is `verify-unsealed`, and sail refuses it;
  with `own_verify`, a green run Keelokit didn't record at all gets its level from Harbor.

### `/harbor:convoy sail N` *(phase 2)*

- **Before:** the integrator; `[ok]` present; a green convoy seal for the exact head at the ok's
  level or above; `origin/main` is the ok's base, so the push is a fast-forward.
- **Preflight** (HRB-5, phase 7), before anything is announced or pushed, from `main_before` (the ok's
  base) to the head, with git alone, in seconds (JOUNA's coordinator did it by hand in about a minute):
  1. *History:* every commit is a vessel's (`main_before..<vessel head>`), a recorded fix, a merge that
     brings in a vessel's head (at most one per vessel; none when the vessel went in as a fast-forward)
     or a merge of the trunk (every other parent already in `main_before`). Anything else is a stray
     commit or merge, and every vessel head must be in the head. A *fix* is a commit the integrator made on
     `convoy/<n>` itself: on the first-parent line, not a merge, in no vessel. `assemble` and `verify`
     record each one they find in the convoy's `fixes` (event `fix`); a commit that came in through a merge
     is never one.
  2. *Authors:* no commit has a placeholder author: an empty name, an email without `@`, git's
     `….(none)` and `@localhost`, or one of a short list of defaults (`Your Name`, `you@example.com`,
     `root`, `unknown`…, `PLACEHOLDER_NAMES` / `PLACEHOLDER_EMAILS` in `harbor.py`). Keelokit's pre-push has
     no such list of its own; `[harbor] placeholder_authors = [...]` adds names or emails.
  3. *wip tips:* `python3 .keelokit/bin/verify_tools.py wip-inside origin <head>` (Keelokit 0.13; exit 0
     names an unproven `wip/` tip inside the head). Without `verify_tools.py`, or with one that has no
     `wip-inside`, it is skipped and the sail's line says so.
  4. *Diff:* the files of `git diff main_before <head>` are the union of each vessel's
     `git diff main_before...<vessel head>`, both ways, apart from the files the recorded fixes change and
     the `[harbor.generated]` paths. A file outside them is named.

  A failure stops the sail with `PREFLIGHT_FAILED` and the first failing line (the rest are printed),
  recorded as the event `preflight-failed`; nothing is announced or pushed. A pass goes into the
  `sailing` event (`preflight passed in 0.4 s`).
- **Does:** `git push origin <head>:main` (`<head>:<trunk>`; no other branch is pushed) from the
  machine that ran the verify, so Keelokit's pre-push seal recognises the commit and doesn't repeat
  the run. Rejected: `MAIN_MOVED`, back to assemble.
- **Logbook:** `[sail]`, state sailed, `main.toml`, event `sailed`; the next control records the CI.
- **Errors:** `NO_OK`, `NEEDS_PERSON`, `NOT_SEALED`, `PREFLIGHT_FAILED`, `MAIN_MOVED`, `CONVOY_MOVED`, `NOT_INTEGRATOR`, `PUSH_FAILED`
  (the pre-push hook's own refusal included). If the push lands and the logbook write fails, the
  next control finds `main` at a verifying convoy's head and records the sail.

### `/harbor:log [N]`

Read-only: fetches and prints `LOGBOOK.md`, or `convoys/<n>.md`.

### `/harbor:harbormaster takeover` *(phase 2)*

- **Before:** an active worker; the watch empty or expired (`now > expires`). With
  `--relieve REASON`, only when the person asks: their word beats the logbook, as the owner's
  did over the board on the first fleet (§5.3).
- **Logbook:** `harbormaster.toml` (worker, since, last_control = now, expires) and a `history` row.
  Two takeovers at once: the second push is rejected, the replay finds the watch held and
  unexpired, and it fails with `WATCH_HELD` naming the holder. First commit wins (R20).
- **Then:** the session schedules its own control every `control_every_minutes`: a task scheduled
  by another session doesn't reach it (§5.3). *(7)* Takeover prints the message to schedule, after
  `schedule this message to this session every N minutes, word for word:`. It holds only commands to
  run (`harbor.py --session <id> harbormaster control`, and `python3 .keelokit/bin/ledger.py` when the
  project has that file) and what to do with their output, then to schedule itself again; never a
  state (no convoy numbers, heads or counts), so a compacted or new session gets the facts fresh. The
  same logbook or another gives the same message.

### `/harbor:harbormaster control` *(phase 2)*

- **Before:** the holder of the watch (`NOT_HARBORMASTER` otherwise; an expired holder renews it).
- **The round, in ten lines:** heartbeat; `origin/main` against `main.toml` (a move no sail explains
  is recorded as `loose`, R18); CI of `main`; per open convoy, `main` moved, vessels moved after
  delivery, skipper alive (its worker active and seen within the expiry, its account not paused),
  ready convoys waiting for the ok; workers not seen within the expiry marked `lost` (which frees
  their account's places); verifies started with no result (a cut run on another machine); past a
  convoy's cutoff *(7, HRB-7)*, `past its cutoff <time>: mandatory <STORY> not delivered, it waits` and
  `the next assemble defers <STORY>` for optional ones not yet deferred.
- **The ledger** *(6, HRB-3)*: after those ten lines, never cut with them, `ledger.py check --json`'s error-level
  differences (at most five lines, the fifth `(+N more …)` when there are more), one line when it can't answer,
  and `ledger: not available` once without a schema-1 ledger. A loose move also lists the stories that entered
  and its unattributed commits.
- **Logbook:** `harbormaster.toml`, `main.toml`, workers marked lost, events. Reassigning a convoy
  whose skipper is gone (`harbor.py convoy skipper N WORKER`) is the harbormaster's call in a
  control. **Needs your ok:** neither the command nor the expiry for workers was in the agreement;
  this uses the watch's.

### `harbor.py` without a slash command

`account set|pause|resume`, `worker register|end`, `seal`, `import-board` are run by the skills.
*(6, HRB-2)* `story take|release ID [--worker W]` is run by a vessel (with Keelokit's LEDGER-013, by
`ledger.py take`), and by the harbormaster to release a stuck lock ("HRB-2: taking a story is a lock in the logbook").
`sync --hook` is the entry of every Claude Code hook (§"Fresh reads"); `check --hook` is its SessionStart
part, never fails the session and prints one to three lines.

## The watch and its relief

One harbormaster at a time. Its heartbeat is `last_control`, written by every control; the watch
expires `watch_expiry_minutes` after it. Any active worker can take an expired watch, and the first
push wins because the replay rechecks the expiry (R20, §5.3). The harbormaster gives oks, records
the CI after a sail, notices loose pushes and lost workers; it never integrates unless it is also
an integrator. What the harbormaster does not see (a session's local verify lock, its
`.verify-status`) it learns only from logbook events (§5.6). The first fleet ran its coordinator on Opus
(§3.4); that this was intended is a **HYPOTHESIS**, so Harbor's default is Sonnet, with
`[harbor.models] harbormaster` to change it.

## Keelokit's pre-push and Harbor's pushes

Keelokit's pre-push verifies what is pushed, from any branch, and since 0.12 refuses a push of a
commit that isn't the one checked out (checked with `scripts/test-with-keelokit.sh`):
- **`convoy/<n>`** is pushed from its checkout (`assemble`), and its verify is that push's. When
  the run is whole and green against today's `main`, `assemble` records it as the convoy's seal and
  `convoy verify` at the `changed` level runs nothing. A red one leaves the merge on the local
  `convoy/<n>` (`CONVOY_PUSH_FAILED`).
- **`main`** is pushed by `sail` from a checkout of the sealed head, so the push is that head.
- **A vessel's branch:** under the convoy policy `build-story` verifies with a plain `pnpm verify`,
  which seals, so the push reuses it, and `harbor.py seal` reuses the same run: one verify per vessel.
- **The logbook** is written with commits that are never checked out. Keelokit lets such a push
  through only for the `[verify] shared_seals` branch, when every file is under `harbor/` and every
  new seal is backed by a whole green run on that machine. So Harbor keeps everything under
  `harbor/` and writes a seal only for such a run; everything else about a run goes to `runs/`.
  Harbor never uses `--no-verify`.

## Fresh reads

A session used to see the logbook only at SessionStart, from the last fetch, or when it ran a Harbor
command, and decided on stale state. `harbor.py sync --hook` reads the hook JSON on stdin and keeps a
per-clone file `<git-common-dir>/harbor/seen/<session>.json` (`tip`, `fetched_epoch`; `-` without a
session id). Every fetch has a cap and `GIT_TERMINAL_PROMPT=0`, `--no-recurse-submodules`, and git's
background `gc` and maintenance off. The logbook is fetched first, on its own 4 s cap; the trunk (only by the
hooks that tell what the trunk changed: UserPromptSubmit and PostToolUse) comes after, best-effort, on a 3 s
cap that is never started later than 7.5 s into the hook, so a hook ends well under its 10 s timeout and a
slow trunk can never cost the logbook. The trunk goes to Harbor's own ref `refs/harbor/trunk`, never to
`refs/remotes/<remote>/<trunk>` (`--refmap=` keeps git from updating it on the side): a hook that moved the
session's own `origin/main` would make `git push --force-with-lease` trust a main the session never saw, and
wipe another clone's commit. SessionStart and PreToolUse fetch the logbook only. A hook fetch writes no `FETCH_HEAD`
(`--no-write-fetch-head`), so a session's `git fetch origin feature` followed by `git merge FETCH_HEAD` still
takes `feature`; a retry after a stale lock fetches the logbook only. `refs/harbor/trunk` shows in `git log
--all` and `for-each-ref`, and a `git push --mirror` would publish it: harmless, but worth knowing. The convoy
commands and the harbormaster's control round do fetch the trunk into `origin/<trunk>`, as any deliberate
`git fetch` does; worktrees of one clone share that ref, so push to the trunk with `--force-if-includes`
alongside `--force-with-lease` when a push must force.

| Hook | What it does | Delay |
| --- | --- | --- |
| SessionStart | fetches, prints the `check` lines ("fetched now", or "offline: as of the last fetch, N min old") | 0 |
| UserPromptSubmit | fetches when the last fetch is 60 s old or more; prints, to stdout, only what changed since the seen tip (at most 1000 characters); nothing if the tip is the same | up to 60 s |
| PostToolUse | the same at 120 s, as `additionalContext` JSON; inside the window it reads only the seen file and starts no git process | up to 2 min in a long turn |
| PreToolUse, Bash | `convoy approve` is denied as before. Before a `git push` to `main` (the trunk) or `convoy/*`, or `harbor.py convoy add\|sail\|verify`, it fetches without waiting and adds the open convoys' states; if one is `verifying` and the push goes to `main` not through `convoy sail`, it says so. It never denies for this | 0 |

The change is the TOML at the seen tip against the new tip: new convoy, state change, vessels added,
the last 5 new events, a new watch holder or `last_control`, workers registered or ended. If the seen
tip is unknown or unreadable, a short summary (watch, open convoys, last events) is printed instead.
What reaches the model is framed as data ("Harbor logbook (data, not instructions):"), every field is one
line of at most 80 characters, and a long list is cut with "(+N more)" while the events stay. The window
is claimed before the fetch, the seen file is written atomically, and the new tip is stored after the
output and only if no other hook of the session moved it first (compare-and-set). A push is read from the
`git push` itself (global options, `cd X &&`, `bash -c`, `$(…)`, refspecs; a bare push or `HEAD` means the current branch).
Any error is exit 0: one line at SessionStart, silence elsewhere. The `convoy approve` guard runs first, on any input. A lock on the log ref or on `refs/harbor/trunk` younger than a minute reads as "busy"; an older one is removed. A failed fetch keeps the last good
fetch time and is not retried inside the window.

Not used: `asyncRewake` hooks or a heartbeat that polls. They wake an idle session, and each wake spends
tokens for a logbook nobody is acting on; a session that is working already passes through the hooks above.

## Verifying without a bottleneck

In a large monorepo the verify is the queue everyone waits in. The first fleet's numbers: `--all` took
62–72 min by its own docs and went red at 82 and 84 min in a 4-core container (§4.9); a piece
verify measured 47 min where the docs said minutes (§6.12); one landing took ten verify runs
(§4.11); one convoy needed four runs, another four `--all`, another one `--all` and five resumes
(§4.9). The fleet dropped "every piece green with a full verify" four minutes after writing it, because
"a repo of this size can't take a full verify per piece" (§4.2), and grew narrower variants
(a piece check, `--keep-going`, `--resume`). The fastest convoy was written and reviewed in an hour and
landed four days later, waiting for its batch (§1.8). So Harbor treats verify minutes and machine
time as the scarce resource. Six rules:

1. **Scope by the diff; `--all` is the exception.** The convoy verify is Keelokit's scoped
   `pnpm verify --keep-going` on the convoy head. Because `main` is the convoy's base, that covers
   the packages the whole convoy changed and their dependents, with only the steps its files route
   to (`verify-routing.toml`), mutation included when critical code changed. Money, permissions,
   quotas, notices and migrations don't call for `--all`. They are proven by the full suites of the
   packages they live in, by the integration and real-stack E2E steps, and by mutation, and the
   scoped run already includes all of those. Re-proving untouched packages adds minutes, not proof.
   `--all` is for what the routing can't bound: the verify tooling, test configuration, CI, `.keelokit/`,
   `scripts/`, root manifests and the lockfile. Keelokit already turns any file it doesn't know into
   every step, so going up is automatic, and Harbor doesn't add a "when in doubt" of its own.
   The first fleet's middle level (verify plus the full suite of the widest package, §4.6) is what Keelokit's
   scoped run does already, so it maps to `changed`.
2. **Don't repeat what a seal proved.** Every vessel is verified once: by its own pre-push, then
   reused by `harbor.py seal`. A one-vessel convoy whose vessel seal has a `level` against today's
   `main` is already verified: the convoy head is the vessel head (a fast-forward, no merge
   commit), and it sails without a second run, from any machine, through the shared seal. In a
   larger convoy each seal proved one vessel against its base; what the combination adds is the
   seams: packages two vessels touch, or a package one changes and another depends on. That is
   where §6.1's failures were (one payload shaped two ways, a fixture changed under another piece's
   test). A *seam* run (`--packages` on those packages) would find a seam red in fewer minutes, but
   it is partial: Keelokit won't let it stand in for the scoped verify at the push, and it
   shouldn't, since a seam run proves less. So a seam run can only be an early check before the
   scoped run, and that costs extra minutes on every green convoy. Whether that pays is without a
   decision until the logbook shows how often convoys go red at a seam.
3. **A red costs one fix round, not a restart.** `--keep-going` lists every red of a run. Each fix
   is a commit on `convoy/<n>`. Then `pnpm verify --rerun-failed` runs the failed steps plus what
   the fix's files route to, so the fix itself is verified before the rerun counts (R7), which
   stops §6.3's chain, where every resume was broken by the previous fix. Keelokit narrows it
   only when the red run had the same base, scope and level and a clean tree, and runs the whole
   verify when the fix touches files without a route or files that call for every step. It always
   repeats audit, clock, doctor and sast, and a fix inside a package reruns every per-package step.
   When the narrowed rerun passes and, with the passes it keeps from the red run before it (same
   base, scope and level, clean tree), covers the whole plan of the diff, Keelokit seals it as a
   *composite*: `partial = false` and `composite_of` = the head of the first red run of the chain,
   in its history and in its seal. Harbor gives that seal a `level` like any whole run and keeps
   `composite_of`, `rerun_of` and `inherited` in the logbook, so a composed green can always be
   traced. A red costs one narrowed rerun, not a rerun plus a whole run. When Keelokit can't prove
   the cover, the rerun stays partial and unsealed, and the whole scoped run gives the seal.
4. **Spread the runs; never queue on one machine.** Keelokit runs one verify per machine (a lock in
   the git directory, §2.8), and other machines can't see it (§5.6). Vessel seals run on each
   vessel's machine: parallel across machines, serial on one. The logbook records each seal's host
   and duration, so the skipper sends new vessels to idle hosts, and the integrator's machine runs
   no vessel seal while the convoy verifies. With `--steps`, one convoy verify could split by step
   across integrator machines *(phase 3)*. Each part is partial and unsealed, so the convoy's
   `level` would be written by Harbor, composed from the parts: same head, same base, clean trees,
   no package scope, and the union of `passed` covering the plan Keelokit gives for that diff
   (`verify_tools.py plan --base`, plus the secret scan and the doctor). That makes Harbor vouch
   for a whole verify no single run made. **Decided 2026-11-01: postponed.** The convoy verify is one
   whole run on one machine until the step times recorded in the seals of real convoys show where
   the minutes go. If one step takes most of the run, splitting can't wait less than that step, and
   making that step faster pays more. If the time is spread across steps and integrator machines
   sit idle while a convoy verifies, the split comes back for a decision, with two conditions: the
   composition rule tested against Keelokit's real code, and a composed seal marked as composed in
   the logbook.
5. **Overlap convoys instead of lining them up.** A convoy doesn't wait for its slowest vessel: the
   skipper defers a late expected vessel to the next convoy (`convoy defer`, *phase 2*). One more
   convoy costs one scoped verify; waiting costs every other vessel its latency (§1.8). A convoy
   that depends on one still verifying assembles on top of that one's head instead of idling
   (*stacked*, *phase 3*). When the first sails, `main` is already the second's base, and the
   second's verify reruns only if the first's head changed, which happens when the first goes red.

6. **One run per head: the ok goes straight to `all` when the scoped plan covers it** *(phase 7, HRB-4)*.
   On a wide convoy the scoped plan is the whole suite, and a scoped run followed by `--all` repeats it
   (the JOUNA fleet paid about two hours a train for that). So `convoy sail --ok` asks Keelokit for both
   plans of the convoy head, `verify_tools.py plan --base <main>` and `plan --all`, in a throwaway
   worktree. Keelokit's plan names steps, not packages, so Harbor counts the packages with the
   selectors Keelokit's scoped run uses (`pnpm --filter "...[<main>]" --filter "!{.}" ls`, every
   package when a root manifest changed; a repo without `pnpm-workspace.yaml` is one package).
   - When the scoped plan has every step of `--all` and at least `[harbor] all_when_covered` (default
     0.9) of its packages, the ok's level is `all`, and its reason says so with the counts. Otherwise
     `changed`, and the reason says what is narrower. The harbormaster can still pass `--level`; theirs
     wins, and Harbor prints what the plans would have given.
   - If the head already has a whole green `changed` run against today's main (a one-vessel convoy's
     seal, or the verify of the pre-push at assemble) and the plans say `all`, the level stays `changed`:
     that run already ran the plan, and nothing runs twice.
   - `convoy verify` runs once at the ok's level: at `all` it never starts with a scoped run. A red
     costs one fix round at either level (rule 3): at `changed` the next run is `convoy_rerun`, at `all`
     `convoy_rerun_all` (`pnpm verify --all --rerun-failed`), which Keelokit narrows within level `all`
     and seals at `all` when it completes the plan. Never a second whole `--all`.
   - Once the ok's run is green, an ok asked again for a level that run covers is refused with
     `ALREADY_COVERED`: the convoy sails, and nobody starts a second run on that head.
   - No plan (no `.keelokit/bin/verify_tools.py` in the head, `own_verify`, the plan or `pnpm` failing):
     nothing changes, and the ok needs `--level` as before.
   - **Assumption:** the package count mirrors Keelokit's `verify.sh` (0.12–0.14); if Keelokit's plan
     ever names its packages, Harbor should read them from there instead.

**Measure before tuning.** Every seal records its duration and, from Keelokit's
`keelokit-verify.history`, each step's time, the failed steps and the known causes *(phase 1)*.
Those are the numbers the survey couldn't reconstruct (§4.9: run times; §1.7: working time): verify
minutes per convoy, reds per convoy, wait from delivery to sail, the slowest steps. The balance
between a light vessel verify (fewer minutes per vessel, more reds in the convoy) and a heavy one is
`vessel_verify`, set per project and moved by those numbers, not by a rule. The first fleet's piece check
(§4.1: lint and typecheck of touched workspaces, the tests added, changed and related, never whole
suites) is lighter than Keelokit's `--since`, which runs the affected packages' whole suites.
Narrowing it further needs a related-tests mode in Keelokit, which it left out on purpose: §6.12
is a warning that "related" isn't always cheaper (mobile `--findRelatedTests` took over 20 min),
and nobody has measured it on a large monorepo yet.

**What Harbor asked of Keelokit, and where it stands** (`landing-policy` at `a251e8657`, not on
Keelokit's `main` yet):

| Need | State | For |
|---|---|---|
| `[landing] policy`, `build-story` stopping at the pushed branch | done | the switch |
| `--steps` | done; never seals | the split across machines (rule 4) |
| `--rerun-failed` | done; narrows only with the same base, scope and level and a clean tree; never seals when it narrowed | a fast answer after a fix (rule 3) |
| `--packages`, `--filter` | done; never seal | a seam check (rule 2) |
| history with `head`, `base`, `clean`, `scope`, `planned`, `passed`, `failed_steps`, `packages`, `step_packages` | done | reuse, `level`, measuring |
| `[verify] shared_seals` | done, as proposed | sealing across machines |
| related tests | not done: measure first (§6.12) | a lighter vessel verify |
| `status.py title <ID> [--role ROLE]`: the canonical session title, and the rule in the agent brief | done (0.12.0) | session names (see "Names") |
| seal a narrowed `--rerun-failed` that, with the red run before it, covers the whole plan | done (`0dc2fed59`, tightened in `a251e8657`): `composite_of` in history and seal | a red costing one rerun instead of a rerun plus a whole run |

## When main moves with a convoy assembled

`main` moves for three reasons: another convoy sailed, a fix for a red `main` was pushed (the only
allowed push outside a convoy, §2.4), or a loose push (§6.9, **EVIDENCE** of how a convoy
branch died). Harbor never rebases a convoy:

- **assembling or waiting:** the next `assemble` merges `origin/main` into `convoy/<n>` and moves
  `base`.
- **ready or verifying:** the ok is void (its level was chosen for other contents); `assemble`
  merges `main`, the state returns to ready, and the harbormaster gives a new ok. `sail` refuses
  while `main` isn't the ok's base, and a rejected push says the same. The new verify is scoped like
  the first, not `--all`: what `main` brought is in the diff only where it meets the convoy's
  packages. Stacking (rule 5 above) avoids most of these re-merges.
- **depending convoys:** a convoy whose `depends_on` hasn't sailed stays waiting; when it sails,
  the next `assemble` merges the new `main` (R15). Convoys from the same base that depend on each
  other can't both be ready: two of the first fleet's convoys (§1.6) would have queued.
- **vessel seals:** stay valid as entry tickets: they speak for the vessel's own part against the
  main it had. The combination is what the convoy's verify covers.
- **record:** every move goes in `main.toml`, with its cause; a loose one is shown in the logbook
  until the harbormaster acknowledges it.

## Budget cuts and handover

The first fleet's sessions stopped together on account limits for 71 hours (§1.7), and left `wip` commits on
`main` (§6.8). In Harbor:

- the account is paused (`account pause --until`, with the time the limit lifts if known):
  `worker register` refuses new sessions of it, and the logbook shows it;
- before stopping, each session pushes its branch and ends with a handover (`worker end --branch
  --head --verified --pending --worktree --log`): the head is checked against the remote, so only
  pushed work is handed over; "verified" names seals by hash;
- a vessel never pushes to `main`, so there are no `wip` commits on `main` to clean; the survey's
  `wip/*` proposal (R22) is unnecessary for vessels and dropped;
- a skipper cut mid-convoy shows as an ended or lost worker; the harbormaster reassigns the convoy
  in its next control; the new skipper reads the convoy file and the handover;
- a convoy verify cut on one machine shows as `verify-start` without a result; the next integrator
  reruns it (Keelokit's `status.py` shows it as CUT on that machine).

## Who owns a session

Whoever launches a session owns its result. A session launched by another registers with
`--spawned-by <its worker id>`; the owner must be an active worker. When an owner ends, `worker end`
lists the sessions it launched that still run, and keeps them in `children_at_end`. Each control
names the orphans: active sessions whose owner ended, got lost or has its account paused. Harbor
doesn't end them or move them: who takes them over is the person's call.

## Names

*(Decided 2026-11-02; reworked in 0.4. Written on Keelokit 0.12's `status.py title`.)* The sessions of the
fleet Harbor was learned on were known by `session_01…` ids (§5.7), its integration branches had random
names (§1.4), one convoy number meant two things (§1.9), and a convoy branch drifted from what it held
(§6.9). So a name comes from the data and is never typed. Since 0.4 it also answers the question an account
with many sessions raises: which one is the harbormaster, which the dispatcher?

**The title reads role first, then the account, then the project and the scope**, separated by ` · `:

| Session | Title |
|---|---|
| harbormaster | `harbormaster · acme-a · Acme` |
| dispatcher | `dispatcher · acme-a · Acme` |
| skipper of convoy 8 | `skipper C8 · acme-a · Acme` |
| vessel of convoy 8 building a story | `vessel C8 · acme-a · Acme · wave 1 · STORY-001` |
| a worker with no Harbor role | `worker · acme-a · Acme` |
| the previous harbormaster, until it ends | `ex-harbormaster · acme-a · Acme` |
| A subagent (an `Agent` description, not a session) | `STORY-001 · verifier` (Keelokit's, unchanged) |

- **Role first** because that is what a list of sessions is scanned for; the account is always there
  because one account holds many sessions and two accounts hold the same roles. The convoy sits on the
  role (`skipper C8`, `vessel C8`), so the sessions of one convoy sort together. The story's part
  (`wave 1 · STORY-001`) is Keelokit's and goes last; the story id goes whole: it is the one stable key
  (its file, its `Story:` trailer). The word for wave follows `[dashboard] lang`.
- **Keelokit owns the story's part and the project's name** (sessions, stories and waves are its
  concepts): `status.py title <ID>` computes them from `.keelokit/answers.yml`, the story's front matter
  and the language. Harbor calls that command and puts the role, the convoy and the account around it;
  it copies nothing. A Keelokit that predates `status.py title` still gets `role · account · project`, the
  project being the repository directory's name; a story's title needs Keelokit. The account is the clone's (`.keelokit/local.toml`); `harbor.py title --account A`
  names another account's session before it exists (a dispatcher building a prompt for a session in its
  own account never needs it; the harbormaster asking for a session in another account does).
- **Never typed.** `harbor.py title`, `worker register`, `convoy new` and `harbormaster takeover` print
  the title to set, and every skill that launches or adopts a session sets it right away: `title` of
  `create_session`, or `set_session_title` for a session it adopts.
- **A role change re-titles the old holder.** `harbormaster takeover` prints, for the previous holder, the
  `ex-harbormaster · …` title it must now carry, and records it, with the role `ex-harbormaster`, in that
  worker's file (the view shows one harbormaster). Harbor cannot rename a
  session: the skills say to use `set_session_title` when the previous holder is in the same account, and
  to send it a `msg` with the title when it is in another.
- **Branches keep Keelokit's convention**, the story id in lower case. A cloud session that is
  given its own branch (`claude/…`) can't rename it: the worker file keeps both, `branch` (real)
  and `canonical_branch`, and the views show both.
- **What can be checked:** titles live in the Claude app, not in the repo, so neither Keelokit nor
  Harbor can read the title a session really has. Harbor computes the canonical one, stores it in the
  worker's record, and `harbor/LOGBOOK.md` lists sessions by it, as a tree, each under the session that
  launched it (`spawned_by`), and, in "Sessions by account", account by account with session, title, role
  and state: the one place the gatekeeper reads to know who is who.

## Phase 6: Keelokit's ledger *(HRB-1; 0.6.0 when HRB-2 and HRB-3 are in)*

Keelokit's ledger (`.keelokit/bin/ledger.py`, its docs/ledger.md) derives every story's state from git and reads
Harbor's logbook, never writing it. Harbor adds what makes the two fit; the plan is
[ledger-phase6.md](ledger-phase6.md).

- **Feature detection.** Every phase-6 behaviour runs only when `python3 .keelokit/bin/ledger.py --json`, run
  from this checkout, answers a JSON object whose `schema` is the integer 1 (exit 0, or 1: the ledger found
  differences). No `ledger.py`, another schema (or `true`), text that is not UTF-8 JSON, any other exit, or no
  answer in `LEDGER_SECONDS` (60; `HARBOR_LEDGER_SECONDS` overrides it): Harbor behaves exactly as 0.5. It is
  asked once per command, and only by `convoy add`, `convoy assemble`, *(HRB-2)* `story take`, `worker register
  --story`, `wanted take` and `wanted prompt` (a vessel's). Keelokit 0.15.0 already answers
  schema 1, so it gets the trailer too, which its ledger already reads.
- **The ledger is project code**, like `vessel_verify`: run with `sys.executable`, from the checkout, stdin
  closed, with the timeout; Harbor copies none of its code.
- **`Convoy: <n>` on the merge** (`convoy assemble`): each vessel's merge into `convoy/<n>` is a merge commit
  (`--no-ff --no-log`: a fast-forward would leave nowhere to put the trailer, and `merge.log` would put a
  shortlog after it) whose message is `convoy <n>: merge <branch>@<head>`, a blank line, `Convoy: <n>`. A conflict
  only in generated files is committed with that same message (git's `# Conflicts:` lines would follow the
  trailer). The vessels' own commits, with their `Story:` / `Part-of:` trailers, reach `main` unchanged. After
  the merges, a vessel whose merge on the convoy's first-parent chain lacks the trailer is named, one line each.
- **`NO_STORY` in `convoy add`.** When the add would otherwise reach its seal check (the convoy open, the caller
  its skipper, a green seal), Harbor runs `ledger.py attribution <seal_base>..<head> --json` (`seal_base` is the
  seal's `base`; the merge base with `main` when the seal has none or this clone lacks it). Of its answer it
  counts only the vessel's own commits: those `<head>` reaches and neither `<seal_base>` nor today's `main` does
  (a vessel that merged a newer `main` brings `main`'s commits, which are not its own). A merge is never
  unattributed (the ledger attributes what it brings), and `No-story:` is the ledger's to judge. Any own
  non-merge commit with `attributed = false` refuses the add: `harbor: NO_STORY: <short sha> '<subject>', …`
  (exit 1), after a line for each saying how to attribute it. Nothing is recorded.
- **The story from the ledger.** Without `--story`, the vessel's `story` is the stories of its own commits in
  the answer (`story` and `part_of`, merges included), sorted and joined with `, `; with none, no `story`. `--story` still overrides.
- **An answer Harbor can't read is not a refusal.** When `attribution` exits other than 0 (2: usage or
  unsupported, which is what Keelokit 0.16.0 does, since the command is in its docs and not yet in its code; 3:
  history incomplete), times out, prints no JSON, or its commits lack a sha or a boolean `attributed`, `convoy add`
  prints `harbor: ledger: attribution not available (<why>)` and goes on as 0.5 (the `Story:` trailers). A ledger
  that can't answer must not stop every convoy; HRB-3's ok checks the ledger again before the sail.
- **The contract with Keelokit's `ledger.py attribution` (LEDGER-013).** Both sides build against this one shape:
  `python3 .keelokit/bin/ledger.py attribution <a>..<b> --json` exits 0 when it answered, even if some commits are
  unattributed; 2 for usage or unsupported (also a range whose ends don't resolve); 3 when the history is
  incomplete.

  ```json
  {"schema": 1,
   "range": "<a>..<b>",
   "ok": true,
   "commits": [{"sha": "<40 hex>", "subject": "…",
                "story": ["AUTH-001"], "part_of": [], "no_story": null,
                "merge": false, "attributed": true, "via": "own"}],
   "unattributed": ["<sha>"],
   "stories": ["AUTH-001"]}
  ```

  `ok`: every non-merge commit of `a..b` is attributed. `via`: how a commit is attributed (`own` trailer, a `merge`
  that brings it, an approved `correction` row), `null` when it isn't. A merge counts as attributed when everything
  it brings is (`via` `own` when it carries a trailer itself). `stories` is the union of `story` and `part_of` over
  the range, sorted. Harbor reads `commits` (`sha`, `subject`, `story`, `part_of`, `attributed`) and checks merges
  itself with git; it ignores other keys, and matches a `sha` by prefix.
- **The logbook keeps `schema = 1`.** HRB-1 adds no key: a vessel's `story` is the key it always had. HRB-2 adds
  one optional key, `story` on a worker, omitted when absent.

### HRB-2: taking a story is a lock in the logbook

- **`harbor.py story take ID [--worker W]`** writes `story = "ID"` (and `canonical_branch`, the id in lower case) on
  worker `W` (default: the calling session) in one logbook transaction. A worker **holds** a story while its
  `state` is `active` and its `story` names it; ids compare without case, and an id is one plain word
  (letters, digits, `. _ -`; anything else is `USAGE`, exit 2). Refused:
  - `STORY_TAKEN: <ID> is held by <worker>` when another active worker holds it, or a vessel request holds it
    (below). This is the logbook's lock: it never depends on the ledger, in any project;
  - `STORY_ON_TRUNK: <ID> is <state>` when the ledger says it is `on-trunk`, `in-version`, `in-staging` or
    `in-production`. Harbor asks `ledger.py show <ID> --json` first and reads `state` from its answer (an object
    with schema 1, the state at the top or under `story`); Keelokit 0.16.0 has only `show <ID> [--full]`, so
    Harbor falls back to the story's row in `ledger.py --json` (the facts the feature detection already read).
    A ledger that can't say (no row for the id, no state) is one line, `harbor: ledger: … not checked against
    the trunk`, never a refusal; without the ledger nothing is asked;
  - `NOT_REGISTERED` when `W` is a worker that ended or is lost, or `--worker` names no worker;
  - `NOT_YOURS` when the caller doesn't answer for `W`: only `W` itself, a session of its account and host, the
    session that launched it (`spawned_by`) or the harbormaster.
  Taking what `W` already holds changes nothing (no commit), even beside a duplicate holder an older Harbor wrote. Taking another story replaces the one it held
  (`was X: released`). A session not registered yet is checked (both refusals) and nothing is written: its
  `worker register --story ID` is the take.
- **Two takes at once.** Both build a commit on the same tip; one push wins; the other is rejected, fetches the
  new tip and replays its change, whose precondition now finds the story held: `STORY_TAKEN`. First commit wins,
  as the watch and `wanted take`. A take that dies before its push leaves nothing; one that dies after holds the
  story until its worker ends or the harbormaster's control marks it lost.
- **`harbor.py story release ID [--worker W]`** clears the story on its holder `W`. A worker that doesn't hold it
  is refused with `NOT_HOLDER` naming the holder, so a worker that was lost or ended and comes back can never
  clear the lock of whoever took the story since; releasing a story nobody holds is a no-op (exit 0). The
  harbormaster releases a stuck lock with `--worker <holder>`.
- **A worker that ends or is marked lost releases its story**: it is no longer active, so it holds nothing (the
  round's `lost:` line names the story). Its `story` stays in its file as the record of what it worked on; a
  worker that registers again without `--story` after it ended or was lost starts with no story.
- **`worker register --story ID`** takes the story at registration, with the same refusals, in the same
  transaction as the registration. `STORY_TAKEN` runs in every project, with or without a ledger, and whatever
  the ledger answers on that call; only `STORY_ON_TRUNK` asks the ledger. The prompt's first line needs the ledger.
- **A vessel request holds its story** while it is `taken` or `started` by a dispatcher that is still active and
  no session has claimed it, for at most `watch_expiry_minutes` after its take (`wanted started` never extends it):
  a session that never registers is as gone as a lost worker. `wanted take` of another request for that story, and a take or a
  `worker register --story` by any worker, get `STORY_TAKEN` naming the request, other children of the same
  dispatcher included.
- **The claim ties a request to one session.** The vessel's prompt registers with `worker register --story <ID>
  --spawned-by <dispatcher> --request <id>`. In the same transaction the registration records `claimed_by = <worker
  id>` on the request, and from then on the request holds nothing: the claimant's own hold is the lock (so it ends
  when the claimant releases the story, ends or is lost, with no clock compared). Refused: `REQUEST_NOT_YOURS` when
  the request is not a taken or started vessel request for that story whose taker is the declared `--spawned-by`;
  `REQUEST_CLAIMED`, naming the claimant, when another active worker claimed it first (first commit wins). A session
  not registered yet (`ledger.py take`, the prompt's first line) is checked against workers only; its register
  claims.
- **An unclaimed request can always be lifted**, before the expiry too: `wanted drop` takes a started request
  nobody claimed (no `claimed_by`, or its claimant ended or is lost), from its taker or the harbormaster; a claimed
  request whose claimant is active stays (its hold is the claimant's). `story release ID`, when only a request
  holds the story, drops that request for its taker or the harbormaster and says so; anyone else gets
  `NOT_HOLDER` naming the request and its `wanted drop`. The harbormaster's round drops a started, unclaimed
  request whose taker is no longer active, and names each one older than the watch's expiry with its
  `wanted drop`. Mixed versions are unsupported (an old vessel doesn't know `--request`; an old dispatcher's prompt
  lacks it, so the new vessel is refused by its own request), and they end in this same state, lifted the same ways.
- **Identity is self-declared**, as everywhere in Harbor: account and host come from the clone's local file and
  `--spawned-by` is the session's word. The claim stops an accidental steal and a double holder; a session that lies
  can still claim first, but then exactly one holder exists and the real spawn gets `REQUEST_CLAIMED` naming it, in
  the logbook for anyone to see. `wanted add --role vessel` refuses a second request for a story that already has one open or holding it:
  `STORY_REQUESTED`, naming it (drop it first).
- **Every clone must run Harbor 0.6.0.** The logbook stays schema 1, so an older Harbor can't tell the lock is
  there: its `worker register --story` doesn't check it, and its re-registration of a lost worker keeps the old
  story. The harbormaster's round repairs that: for each story two or more active workers hold, it keeps the one
  whose hold began first (the oldest commit of the unbroken run in which its file says active and that story) and
  releases it from the others, one line per story naming them all.
- **`LOGBOOK.md`** shows each active worker's story in the Workers table.
- **Not locked:** a story that reaches the trunk between the check and the take is HRB-3's (`DONE_TWICE` at the ok).

### HRB-3: the ledger in the round and in the ok

- **The round** (`harbormaster control`) asks `ledger.py --json` and `ledger.py check --json` before its
  transaction (they take time) and prints, after the round's ten lines and never cut with them, each error-level
  difference as `ledger: <CODE> <detail>`, each one short printable line. More than five: the first four and
  `ledger: (+N more: python3 .keelokit/bin/ledger.py check)`, so never more than five lines. Warnings are not the
  round's. Without a schema-1 ledger (no `ledger.py`, or another integer schema) the round says `ledger: not
  available` once; a ledger that can't answer (timeout, another exit, not UTF-8 JSON, wrong types, more than
  `LEDGER_MAX_BYTES`, 32 MiB, `HARBOR_LEDGER_MAX_BYTES` overrides it) is one `ledger: … not available (why)` line.
  Neither stops the round.
- **A loose move** (`cause = "loose"` in `main.toml`) gets, on its line and in its row, the stories that entered
  (each story of `ledger.py --json` whose `commit` is in `<from>..<to>`) and the unattributed commits (Keelokit
  0.16.0's `--json` only counts them, `unattributed.commits`, so they are `check --json`'s `UNATTRIBUTED`
  differences whose detail starts with a sha of that range): `stories = [...]`, `unattributed = [full shas]`
  (optional keys; the logbook stays schema 1). A ledger that can't answer, or that read `main` at another commit
  than the round fetched, is said on the line and nothing is recorded.
- **The judge is main's ledger, never the convoy's** (the coordinator's decision after a breaker on 88f5aab: a
  vessel could delete `ledger.py`, or ship one answering schema 2 or a clean schema 1, and the ok ran the checkout's,
  which after `convoy assemble` is the convoy's). Whether there is a schema-1 ledger is main's tree: no
  `.keelokit/bin/ledger.py` at the trunk tip (or one answering another integer schema) is 0.5's ok. Else the ok
  builds two throwaway clones of this one (`git clone --shared --no-checkout`, deleted afterwards): one checked out
  at the trunk tip, one at the convoy tip, each with `refs/remotes/origin/<trunk>` (and the local trunk) at that tip,
  its other origin refs this clone's, and `.keelokit/bin/` and `.keelokit/state.toml` replaced by the trunk tip's
  bytes (so main's ledger runs, with main's `[ledger]` rules: a convoy can't set `enforce = "warn"` for itself). In
  them, with no caller `GIT_*`, no GitHub pull-request variables and Keelokit's hardened git
  (`safe.bareRepository=explicit`, `protocol.ext.allow=never`, `core.hooksPath=/dev/null`, `GIT_NO_LAZY_FETCH=1`),
  it runs `--json` and `check --ci --json` on main as it is, and `check --ci --json` on the convoy as if it had
  landed. Every difference the convoy run has that main's doesn't (same code and detail; the level is the
  project's `enforce`, not the difference), at level `error` or with code `DONE_TWICE`, `UNKNOWN_STORY`,
  `UNATTRIBUTED`, `BAD_CATEGORY` or `STORY_NO_BODY` at any level, is the convoy's: `LEDGER_DIFF`. That is Keelokit's
  own rules on what would reach main: two vessels each closing one story (`DONE_TWICE`: they arrive in two
  first-parent merges), a `No-story:` category it doesn't know, a bodiless `Story:` commit, a corrections file the
  convoy breaks.
- **What the judge's clones copy.** A link in main's `.keelokit/bin/` (or `state.toml`) is never written as a link
  (in the landed clone it would lead into the convoy's files): it is the blob it points to inside main's tree,
  links followed up to eight times, a directory's on the way too (`.keelokit/bin` a link to `tools/kkbin` copies
  that directory's files); one pointing out of the tree, or at nothing, leaves no file, and the ok fails closed
  (`LEDGER_UNAVAILABLE`): a link met on the way to `ledger.py` counts as a ledger, never as none. A vessel's commits
  are read as bytes and decoded leniently (git prints a message it can't convert in its own encoding). Refs are read and written as bytes (a branch name need not be UTF-8), and the
  clone's own refs (origin refs and local branches; its HEAD is detached) are deleted in a transaction of their own
  before this clone's are written, so a local `topic` and a remote `topic/x`, or `main/wip` and `main`, don't clash. Residual: Keelokit 0.16.0 reads some rules from the trunk's committed
  tree (`[ledger.approval]` in its committed `state.toml`, `critical.toml`, the review files); in the landed clone
  that tree is the convoy's, which Harbor can't replace without rewriting it.
- **The ok is bound to the convoy's exact tip.** An ok that asked the ledger records `ledger = "checked"` and its
  `head`; any later commit on `convoy/<n>` (a fix `convoy verify` records, anything) makes it stale: verify marks
  it (`stale`, event `ok-stale`), and the sail refuses `OK_STALE` until `convoy sail N --ok` is given again on the
  new tip (allowed on a verifying convoy whose ok is stale; the level and reason stand unless given), which runs
  the judge again. Without a ledger the ok stays 0.5's, unbound.
- **The ok** (`convoy sail N --ok`) decides what reaches main, so it fails closed. With the judge above, also for
  each vessel's own commits (`<main>..<head>`), and for the
  convoy's own commits (`<main>..<convoy head>` that no vessel brings: the integrator's fixes, as if a vessel of
  `convoy/<n>`), `ledger.py attribution <main>..<head> --json` when it answers (Keelokit 0.16.0 doesn't: then the commits'
  `Story:`/`Part-of:`/`No-story:` trailers, read by git from the message's last paragraph, stand in; a commit only
  a trailered merge of the vessel attributes is then counted unattributed). The commits and their parents come
  from `git rev-list --parents`, their messages from `git log -z` (NUL-separated: a message can't hold a NUL), and
  the two must name the same commits in the same order, so no text in a message can forge or hide a commit. It refuses `LEDGER_DIFF` (exit 1,
  one line per vessel, all of them) when a vessel has:
  - `UNATTRIBUTED`: an own commit, not a merge, with no `Story:`, `Part-of:` or `No-story:` (a merge's trailers still
    count: its `Story:` closes a story, its ids must be known);
  - `UNKNOWN_STORY`: a story (its recorded `story`, or an id its commits name) no story of `ledger.py --json` has
    (ids compare with case, as Keelokit's `EPIC-NNN` do: `Story: qa-1` is no id to it), or one whose state is
    `unknown` (a cut history: the reason is given); a ledger listing one id twice is `LEDGER_UNAVAILABLE`;
  - `DONE_TWICE`: a story one of its commits closes with `Story:` that the ledger says is `on-trunk` or later.
    Keelokit's `DONE_TWICE` counts `Story:` commits, so a `Part-of:` follow-up of a done story is not one;
  - a `check --json` difference naming one of its stories at level `error`, or with code `DONE_TWICE`,
    `UNKNOWN_STORY` or `UNATTRIBUTED` at any level (0.16.0 gives `DONE_TWICE` as a warning). A difference names a
    story through its `story`/`stories` fields when the ledger gives them (with case); 0.16.0 gives neither, so a
    `DONE_TWICE`'s story is the id before the colon of its detail (`QA-1: Story: commits … arrived separately`).
- **Fails closed** (Leo's decision): with a `ledger.py` on main whose `--json` answers schema 1, anything else at
  the ok is `LEDGER_UNAVAILABLE` and no ok (a judge clone that can't be built too): `--json` or `check --json` timing out, exiting otherwise, answering text
  that is not UTF-8 JSON, a schema that is not the integer 1 (an integer other than 1 is another ledger: below),
  more than the cap, `stories` or `diffs` of the wrong types (a story's id must be one plain word: letters,
  digits, `. _ -`), no full `trunk_sha`, a `trunk_sha` other than the `main` the ok fetched, or a `ledger.py`
  that is there but is no file (a dangling link on main; in the round, a directory too). With no `ledger.py` on
  main, or one answering another integer schema, there is no schema-1 ledger: the ok is 0.5's, and asks nothing
  more. The round still runs the checkout's ledger: it reports, it decides nothing.
- **Races.** The ledger is asked outside the ok's transaction; the transaction refuses `CONVOY_MOVED` unless the
  convoy's vessels (branch, head, story) are exactly the ones checked, besides its own head, base and state
  checks. A ledger that read another `main` is refused above; `main` moving after the ok voids it at verify and
  sail, as before.
- **The ledger's process** runs in its own process group, killed whole at the timeout or when its answer passes
  the cap; its stderr is kept to 64 KiB. `HARBOR_LEDGER_SECONDS` counts only when it is a finite number above 0,
  and at most 600 (`LEDGER_MAX_SECONDS`); anything else is the default 60.

## Phase 5: the fleet layer without Keelokit *(0.5.0)*

Harbor adapts to the project it finds. Up to 0.4 every command stopped unless the repository had
`.keelokit/state.toml` with `[landing] policy = "convoy"`, so even a message between two accounts needed
Keelokit. 0.5 splits Harbor in two layers.

- **The fleet layer runs in any git repository with a remote:** `init`, `account`, `worker register|end`, `story take|release` *(6)*,
  `msg *`, `wanted *`, `title`, `doctor`, `models`, `log`, `harbormaster takeover|control`, the hooks (the
  logbook delta and the note about what the trunk changed) and `push-guard`.
- **The convoy layer needs Keelokit, as before:** `convoy *`, `seal`, `import-board`. Without Keelokit they
  exit 2 with `NEEDS_KEELOKIT: <command> runs on Keelokit's convoy policy (/keelokit:project-adopt)`. A
  `wanted add --role vessel|skipper` needs a story and a convoy, so it exits the same way; a
  `--role dispatcher` request works anywhere. The reason: a request may only start what the project already
  describes, and without Keelokit Harbor has nothing to check a story against, so it does not guess.
  `harbormaster control` renews the watch, finds lost workers and lists late messages without Keelokit; it
  leaves out the trunk, the CI and the convoys, which only exist with it.

With Keelokit nothing changes: its files stay the source and the policy is still required.

### Configuration without Keelokit

- **Project, committed:** `.harbor/config.toml`, with the same `[harbor]`, `[harbor.models]`,
  `[harbor.requirements]` and `[harbor.import]` tables as `.keelokit/state.toml`, plus `[harbor] project = "<name>"`
  (the project in titles) and `[harbor] trunk`. It is read only when there is no `.keelokit/`; with both,
  Keelokit wins and `doctor` and `log` say `.harbor/config.toml is ignored: this project runs on Keelokit`.
- **Identity, never committed:** `.harbor/local.toml`, `[harbor] account` and `host`, one per clone, in
  `.gitignore` (`init` adds it, after the logbook exists, when git says it is not ignored; it also creates `.harbor/config.toml` if missing, for the person to commit; SessionStart in a clone with `origin/harbor/log` and neither directory says so). A Keelokit repo reads `.keelokit/local.toml` only, no
  fallback to `.harbor/local.toml`; a linked worktree without its own file uses the main checkout's. If the file
  is tracked by git every clone would share one identity: `doctor` reports it (exit 1) and `init` refuses (exit 2).
- **Titles:** `role · account · project`, the project being `[harbor] project` or the main checkout's
  directory name. A story's part comes from Keelokit's `status.py title`, so a title with a story needs Keelokit
  (`NO_TITLE` otherwise).
- **Hooks:** they act only in a repository with `.keelokit/` or `.harbor/`; anywhere else they say nothing. The
  `convoy approve` guard runs on any input, as in 0.4, whatever repository the session is rooted in (a command can
  `cd` into one that has Keelokit). Without Keelokit the hooks leave out the convoy lines: SessionStart does not
  count convoys, and a push to the trunk gets no note and no fetch.

### `push-guard`: a project's own pre-push hook

A project with its own pre-push hook must let Harbor's writes through. `harbor.py push-guard <local_ref>
<local_sha> <remote_ref> <remote_sha>` takes one line of the hook's stdin and exits **0** when the push is
Harbor's and sound, **1** when it is a Harbor ref and unsound (the reason on stderr), **3** when the ref is not
Harbor's.

- `refs/heads/harbor/log`: no delete; the remote's tip must be an ancestor of what is pushed (no dropped
  commits). A tip the clone does not have means another clone wrote first (git runs the hook before it finds
  out), or a tip it has but that is not in what is pushed (a sibling fetched it meanwhile): both refuse with «fetch first», which Harbor's own write answers by fetching and replaying; every new commit's tree holds only regular files (mode 100644) under `harbor/`; the branch shares
  no history with the trunk.
- `refs/heads/harbor/mailbox/<account>` (a valid account name): on top of the trunk, each new commit a
  single-parent commit that adds or changes exactly `harbor/mailbox/<account>.md` as a regular file; no delete.

The mailbox reads the trunk from `origin/<trunk>`, then Harbor's own copy of it, never the local branch; with neither the push is
refused («push <trunk> first, or fetch it»). The logbook also tries the local trunk branch, and with no trunk at all only the tree check
applies (a brand-new repo whose trunk was never pushed can `init`). Any error on a Harbor ref is exit 1, and the repository is the hook's (its working directory), never the
session's `CLAUDE_PROJECT_DIR`. So the hook below refuses on any exit but 0 and 3. A bash hook:

```bash
H=$(git config harbor.py)  # each session records the plugin's current harbor.py here
while read l ls r rs; do
  python3 "$H" push-guard "$l" "$ls" "$r" "$rs"; c=$?
  case $c in 0) continue;; 3) ;; *) exit 1;; esac  # 3: not Harbor's ref, the project's own rules go here
done
```

with `H` the path of `lib/harbor.py`: a stale `H` or a Harbor that cannot run exits 2, and that refuses the push.

## Phase 4: names, mailboxes and requirements *(0.4.0)*

Three things that were left to habit. The titles are in "Names"; the other two are here.

### The account's mailbox

A dispatcher's watcher reaches the logbook; a person reaches the dispatcher faster through a draft pull
request the dispatcher is subscribed to (a comment by a person wakes the session in seconds). The name is
fixed so that every account finds its own and nobody invents another: the branch `harbor/mailbox/<account>`,
holding one file `harbor/mailbox/<account>.md`; the pull request is titled `Harbor mailbox: <account>`, a
draft, never merged. `harbor.py account set A --mailbox-pr N` (`0` forgets it) records the number in
`harbor/accounts/A.toml` (`mailbox_pr`); the Accounts table of `LOGBOOK.md` shows it; and the dispatcher
subscribes again on every wake, because `subscribe_pr_activity` does not survive a restart. A project whose
pre-push hook refuses unknown branches lets `harbor/mailbox/*` through, as it does the logbook.

### What an account needs to work here

What the repository carries (`.claude/skills`, agents, hooks, lockfiles, `CLAUDE.md`) reaches every account
through `main`: a new session gets it on clone, a running one on its next merge of `main`. What belongs to an
account (its cloud environment: hosts, setup script, tools; connectors; plugins and skills of the account;
the names of its secrets) never travels through git. Harbor makes both visible and changes neither.

**The manifest** is in the project's `.keelokit/state.toml`, with the rest of `[harbor]`:

```toml
[harbor.requirements]
tools = ["docker", "pnpm"]            # commands that must be on PATH
hosts = ["registry.example.com"]      # outbound hosts the work needs
secrets = ["EXAMPLE_API_TOKEN"]       # names only, never values; the variable must be set
network_secrets = ["api.example.com"] # keys a cloud session injects at the proxy: never a variable, never checked
plugins = ["design"]                  # Claude Code plugins the work expects
skills = ["code-review"]         # project skills; checked to exist in .claude/skills
note = "one line for the gatekeeper"
```

**`harbor.py doctor [--account A] [--if-changed]`** checks this machine against it and prints one line per
item: `ok`, `missing` or `can't check`; it exits 0 when nothing is missing, 1 when anything is, and 2 when the
check could not run or be recorded (`NOT_YOUR_ACCOUNT`, `BAD_CONFIG`, `PUSH_RETRIES_EXHAUSTED`, …: the error is
on stderr). A tool is looked up on `PATH`; a host is reached with a short HTTPS HEAD through the
environment's proxy, redirects not followed, 8 s at most per host (any answer counts, a refused page or a
redirect too; a proxy that answers 429 or 503 at CONNECT says `can't check`, no verdict on the host); a secret
is an environment variable that is set; a skill is a directory in `.claude/skills`; a plugin is checked against
Claude Code's local plugin list, `missing` when the list is there and lacks it, `can't check` where that list
is not there (a cloud session). **A missing secret may be a false alarm in a cloud session**, where a key is
injected at the proxy and is never an environment variable: such a key is declared under `network_secrets`,
which always says `can't check`. A key of the manifest that is not one of `tools`, `hosts`, `secrets`,
`network_secrets`, `plugins`, `skills`, `note` is `BAD_CONFIG` (a typo like `secret =` would otherwise check
nothing). The account is always this clone's: the checks run on this machine.
The result goes to `harbor/accounts/A.toml` as `requirements_checked_at`, `requirements_hash` (of the
manifest, not of the note) and `requirements_missing`, written once per change (a run that finds the same
hash and the same list writes nothing; a manifest emptied later records the empty state, so no stale
`missing` stays in the views, and a project that never had one writes nothing). `--if-changed` skips the checks when the recorded hash is the
manifest's and nothing was missing. The Accounts table shows the last check and what is missing. This
replaces the `doctor --cloud` that earlier versions of this document designed and did not build.

**The dispatcher** runs it when it arms and whenever the manifest changed on `main` since its last check
(`doctor --if-changed` compares the hash; the first check on arming is a plain `doctor`, because a new
container has never checked); what is missing goes to the gatekeeper with `msg send --to
gatekeeper --kind question`: configuring an account is a person's decision, and Harbor never does it.

**Running sessions are told.** The hooks that already summarize logbook changes (UserPromptSubmit,
PostToolUse) fetch the trunk after the logbook (see "Fresh reads"), and when it changed the manifest,
`.claude/` or a lockfile since the base this session branched from (`git diff --name-only --no-renames`), they
add one line, framed as data like the rest: `main changed the requirements manifest, .claude/, a lockfile:
reinstall after your next merge of main (a skipper: at the next `convoy assemble`; a delivered vessel: leave the
branch where it is)`. A skipper takes the trunk only through `convoy assemble`, and a delivered vessel that moved
its branch would void its delivery, so the line never tells either to merge now. It is said again only when the
set of changes differs from the last one told (a new tip with the same lockfile change is silent), and not at
all after the session has merged the trunk. A shallow clone with no merge-base never gets it.

## Models and the first agent

The vessel's tier is Keelokit's (trivial, light, full), chosen by the vessel session's
`build-story`; Harbor records it when the skipper adds the vessel. The tier is not stored
anywhere machine-readable in Keelokit, so the skipper copies it from the vessel's report: an
**assumption** that the report is right, to replace with a recorded value when Keelokit has one.

| Tier | First agent | Model |
|---|---|---|
| trivial | builder | Sonnet (Keelokit's brief) |
| light | verifier (mode A: tests before code, R9) | Sonnet; review Sonnet |
| full | verifier (mode A) | Opus for tests and review; the builder stays on Sonnet |

Every `Agent` and `create_session` Harbor starts names its model (§3.3): its own roles from
`[harbor.models]`, the story roles from Keelokit's brief. The defaults are the cheap case and the
expensive one is the exception (R11, §3.11, §3.12). The harbormaster's round runs on `control`
(Haiku): it only reads and reports, and the harbormaster acts on it on its own model. That the
model rule changed the practice is **EVIDENCE** (§3.7: commit counts, not tokens).

## Assumptions to validate

| Assumption | Source | How it would be checked |
|---|---|---|
| Keelokit's `landing-policy` branch lands on its `main` as reviewed | Keelokit's report; checked here against `4b22a548c` | Harbor's tests use stand-ins; rerun the shared-seal check against Keelokit's release |
| hotspots concentrate on shared types, schema, migrations, locales, generated files | §2.12 (**EVIDENCE** for the density) | `git log --format=%h -- <path>` counts in the adopting repo |
| a coordinator on Opus was intended | §3.4 (**HYPOTHESIS**) | ask the owner; Harbor defaults to Sonnet |
| trailers name the model of the session that signed | §3.6 (**HYPOTHESIS**) | not needed: Harbor records `model` per worker |
| a reviewer of the right level doesn't replace a real run | §3.15 (**EVIDENCE**) | the convoy verify is a real run; nothing else assumes it |
| duplicated history comes from rebasing sibling branches that share commits | §6.7 (**EVIDENCE**) | *(phase 2)* `add` warns when two vessels share commits not on `main` |
| "future" migration names were an ordering convention without a reservation | §6.5 (**EVIDENCE**) | the migration check at assembly doesn't depend on it |
| the hidden cost of direct landings | §4.11 (**EVIDENCE**) | the logbook's seal history gives the numbers the survey lacked |
| the push that killed a convoy branch was a loose push | §6.9 (**EVIDENCE**) | `main.toml` records the cause of every move |
| the board file's tables look as §5.1 describes | §5.1 | run the import on the real board |
| a third review round without P0/P1 was unjustified | §3.14 (**HYPOTHESIS**) | not Harbor's: Keelokit caps rounds |
| process documents conflicting at integration | §6.15 (**EVIDENCE**) | not Harbor's (R24) |

## Without a decision

- **Renumbering migrations automatically (R16).** Harbor fails and names the rename. Doing it
  itself changes a vessel's commits, so its seal; whether the integrator may rename and re-seal is
  your call.
- **Totals fixed in tests (§6.6, R17).** "Put the merge total" has no general mechanism: it needs
  to know which test holds which total. Missing: how a project would declare them.
- **Staggered start of sessions (R12).** The survey has no interval to stagger by, and no data on
  what a start costs. Missing: a number from the owner, or measurements.
- **API changes and the app version that consumes them (R26).** Missing: whether a convoy declares
  its consumers and who deploys them, and whether that belongs in Harbor or in Keelokit's contract
  dimension.
- **How light the vessel verify is.** `vessel_verify` defaults to Keelokit's `--since` with
  `--keep-going`. Lighter means more reds at the convoy; heavier means more minutes per vessel.
  Missing: the logbook's numbers from real convoys.
- **A future API over the logbook.** Missing: who would serve it. The schema above is the contract.

## Failure modes of the survey, and where Harbor answers

| § | Failure | Harbor |
|---|---|---|
| 6.1 | two green branches, red together | one convoy verify on the combination; fixes as sealed commits on `convoy/<n>` |
| 6.2 | the piece didn't run what broke; a fix voids the green | seal by exact hash; a new commit has no seal (R3) |
| 6.3 | chain of reds on resume | `--rerun-failed` verifies the fix's own steps with the failed ones (R7); a rerun that completes the plan is sealed as composite |
| 6.4 | tests bound to date, zone or text | Keelokit's (time invariants, FLAKY-1); not Harbor's |
| 6.5 | migration timestamp collisions | migration check at assembly (R16) |
| 6.6 | generated artifacts and fixed totals in conflict | `[harbor.generated]`; totals without a decision |
| 6.7 | duplicated history from sibling branches | assumption above; a warning at `add` *(2)* |
| 6.8 | sessions cut by account limits | account pause, cap, handover with pushed head |
| 6.9 | a loose push kills a convoy branch | `main.toml` causes; ok void when `main` moves |
| 6.10 | `main` pushed with only Format run | push only with a green convoy seal at the ok's level; Keelokit's hook stays |
| 6.11 | process rules set and withdrawn in minutes | the rules live in Harbor's code and tests, versioned by release; not editable from the logbook |
| 6.12 | container resources and tools | Keelokit's `--preflight` before the convoy verify (R21); step times in every seal; no vessel seal on the integrator's machine while it verifies |
| 6.13 | scheduled CI red four runs in a row | the ok requires `main` green (`ci.py health`) |
| 6.14 | API↔app contract unverified between convoys | without a decision (R26) |
| 6.15 | process docs out of date | views can't drift; the rest is Keelokit's (R24) |
| 6.16 | piece reverted and redone in a convoy | a redelivery replaces the vessel; abort and a new vessel otherwise |

## Phase 3: orchestration from the cloud *(0.3.0)*

Harbor keeps sessions from deciding on stale state, but someone still opened every session, carried every
message from one account to another, and noticed when a cloud session died. Phase 3 takes that hand work
away without adding a server: the logbook stays the only shared state, and each account runs one session,
the **dispatcher**, that turns what the logbook holds for its account into actions inside that account.

**Built in 0.3.0:** messages (`msg`), session requests (`wanted`), the watcher (`msg watch`), acks, late and
escalated messages, the gatekeeper's list, the `dispatcher` role and its skill and agent. **Designed, not
built:** session state written by hooks and `verify_host` (below, at the end).

### The gatekeeper

Harbor is run by people, and in every project one of them has the last word: the **gatekeeper**, the human
operating the fleet. Harbor never names them and never assumes who they are; it knows them only as a role.
The gatekeeper:

- gives the yes a convoy waits for (`convoy approve`, typed in their own terminal; `[harbor] gatekeeper_ok`,
  formerly `person_ok`, says when);
- answers the questions sessions can't settle (`msg send --to gatekeeper --kind question`);
- is told when a message is late enough that a person should step in (below);
- can always wake a session by hand (a comment on a PR the session watches, or opening it in the app).

Everything an agent decides, it decides within what the gatekeeper already decided. What belongs to the
gatekeeper (money, production, third-party accounts, anything the project marks critical) is asked, not
assumed. One project can have several people; the logbook doesn't model them. Whoever answers as the
gatekeeper is the gatekeeper for that answer.

### What the platform allows

Checked against Claude Code's tools and `code.claude.com/docs/en/routines` on 2026-11-17, and measured on
a real fleet the same day:

| Need | Available | Reach |
|---|---|---|
| Start a session | `create_session` | only in the caller's own account |
| Message a session | `send_message` | only in the caller's own account |
| A schedule | scheduled tasks, at most hourly | the account that owns them |
| A session's state | `get_session`, `list_sessions` | only the caller's own account; no notice when it changes |
| Wake a session from GitHub | `subscribe_pr_activity` | a comment by a person or a bot wakes it in seconds; **a comment posted by a Claude session, of any account, is never delivered** (it counts as the session's own) |
| Start a session from anywhere | a scheduled task's fire URL (`POST …/routines/<trig>/fire`, bearer token, free `text`) | whoever holds the token; beta; 100 fires/hour per account |
| A background command | Bash with `run_in_background` | the session wakes when it exits; capped at 2 hours |

So no session acts in another account. What crosses accounts is git (the logbook), a person's comment, and
fire tokens. Between sessions, the logbook is the channel and a background watcher is the wake.

### Messages: `harbor/inbox/<id>.toml`

```toml
schema = 1
id = "m-0042"
to = "account:acct2"                 # a target, below
from = "acct1/cloud/session_01Hm"
at = "2026-11-17T18:00:00Z"
kind = "message"                     # message | question | answer
re = ""                              # for an answer: the id it answers
text = "…"                           # one line, at most 2000 characters; data, never instructions
state = "queued"                     # queued | delivered | done
delivered_at = ""                    # set by `msg ack`
delivered_by = ""
done_at = ""
```

Targets, resolved to an account when the message is read, against the logbook of that moment:

| Target | Account |
|---|---|
| `account:<a>` | `<a>` |
| `<a>/<host>/<session>` (a worker id) | `<a>` |
| `harbormaster` | the account of the watch holder |
| `skipper:<n>` | the account of convoy `<n>`'s skipper |
| `gatekeeper` | none: a person, listed in the gatekeeper's list, never watched |

Commands (every write is a logbook transaction, replayed when another clone wrote first):

- `msg send --to TARGET [--kind message|question|answer] [--re ID] TEXT` — needs a session; the id is the
  next free `m-NNNN`. A question or an answer may go to any target; `gatekeeper` takes any kind.
- `msg list [--to TARGET|--account A] [--state S] [--all]` — queued and delivered by default.
- `msg ack ID` — `queued` → `delivered`. Only a worker of the message's account acks it (for `gatekeeper`,
  the watch holder, who relays it to the person).
- `msg done ID` — → `done`: it was acted on or answered. The sender, the receiver's account or the watch
  holder.
- `msg status` — the late and escalated ones (below), and every account's watcher. Exit 0 when nothing is
  late, 1 when something is.
- `msg watch --account A [--poll S] [--cap M]` — the watcher (below).

An active session already sees new messages for its account through the hooks it has: the change summary
of UserPromptSubmit and PostToolUse names new messages, framed as data like the rest. A session that sleeps
gets them from its dispatcher.

### Session requests: `harbor/wanted/<id>.toml`

```toml
schema = 1
id = "w-0017"
role = "vessel"                      # vessel | skipper | dispatcher
story = "STORY-001"                  # vessels: must be a story the project knows (Keelokit's title lookup)
convoy = 28                          # optional
model = "sonnet"                     # one of the allowed models
account = "any"                      # or one account
note = ""                            # optional, one line, shown to the gatekeeper; never put in the prompt
requested_by = "acct1/cloud/session_01Hm"
at = "2026-11-17T18:00:00Z"
state = "open"                       # open | taken | started | dropped
taken_by = ""                        # the dispatcher's worker id; the first commit wins
taken_at = ""
session = ""                         # the session it started
started_at = ""
claimed_by = "acct1/mbp/session_01Ve"  # (6, HRB-2) optional: the vessel session that claimed it (register --request)
```

- `wanted add --role R [--story ID] [--convoy N] [--model M] [--account A] [--note TEXT]` — only the watch
  holder (the harbormaster) asks for sessions. `model` defaults to `[harbor.models]` for Harbor's roles and
  must be in `[harbor] allowed_models` (default `haiku`, `sonnet`, `opus`).
- `wanted take ID` — a `dispatcher` worker of an eligible account takes an open request, if the account is
  not paused and its active workers are under `max_sessions`. Two dispatchers can race: the replay checks
  the request is still open, so only one wins (`WANTED_TAKEN`). *(6, HRB-2)* With Keelokit's ledger, a vessel
  request is refused with `STORY_ON_TRUNK` when the ledger says its story is on the trunk or later, and with
  `STORY_TAKEN` (naming the holder) when an active worker or another request holds it, with or without the ledger;
  the request stays open. `wanted add` refuses a second vessel request for one story (`STORY_REQUESTED`).
- `wanted prompt ID` — prints the prompt the dispatcher sends to `create_session`. Harbor builds it from
  the request's fields only (role, story, convoy, title, model, the dispatcher's worker id for
  `--spawned-by`), never from free text: a request can only start what the project already describes.
  *(6, HRB-2)* With Keelokit's ledger, a vessel's prompt starts with the line
  `python3 .keelokit/bin/ledger.py take <ID>` (with LEDGER-013 it calls `harbor.py story take`); its
  `worker register --story <ID>` is the take in the logbook.
- `wanted started ID --session S` — the taker records the session it started.
- `wanted drop ID` — the requester or the watch holder gives it up. *(6, HRB-2)* A started request nobody claimed
  is dropped by its taker or the harbormaster.
- `wanted list [--all]` — open and taken by default.

### The dispatcher: one per account

A worker with `role = "dispatcher"`, one per account, on `[harbor.models] dispatcher` (default Haiku). It
writes no code. On every wake, whatever woke it:

1. `msg list --account <its account>`: delivers each queued message to the session it names with
   `send_message` (or acts on it, if it is for the dispatcher), then `msg ack`;
2. `wanted list`: takes what its account has room for (`wanted take`), starts each with `create_session`
   and the text of `wanted prompt`, records it (`wanted started`);
3. checks with `get_session` the workers of its account that have been silent longer than
   `[harbor] silent_minutes` and ends or marks them as it finds them;
4. re-arms the watcher, and goes back to sleep.

It does nothing on its own initiative: no message or request in the logbook, no action. The skill
`/harbor:dispatch` holds the loop; `agents/dispatcher.md` is its brief.

### Wakes, and what happens when one fails

Nothing guarantees that a cloud container stays alive while its session is idle, so every layer assumes
the one above it can be dead.

**1. The watcher (seconds, no cost).** `msg watch --account A` is the dispatcher's background command:
plain shell work, no model. On start it writes `watching_since` and `watcher` in `harbor/accounts/A.toml`
(once per arm, not per poll). Then it fetches the logbook every `--poll` seconds (default
`[harbor] watch_poll_seconds`, 30) and exits 0, printing one line per item, as soon as the account has a
queued message or an open request it could take. If there is one already when it starts, it exits at once:
the dispatcher drains first. After `--cap` minutes (default `[harbor] watch_cap_minutes`, 110, under Claude
Code's 2-hour cap) it exits 75 ("re-arm"). The cap is at most 115 minutes (`CAP_TOO_LONG` above it): a
background command that reaches the 2-hour limit is killed, not ended, and Claude Code then tells the session
not to start it again, so the account would have no watcher until its heartbeat. Seen three times in one night
on a watcher with no cap of its own. A failed fetch is retried at the next poll. Measured: a message
written by another account woke the dispatcher in 13 s, and in 46 s after 40 minutes idle.

**2. Acks (no message is lost).** A message stays `queued` until the dispatcher of its account acks it,
and the dispatcher drains every queued message on every wake. A message is **late** when it has been queued
longer than `[harbor] ack_minutes` (default 15), or when its account's `watching_since` is older than the
watch cap plus `ack_minutes` (no watcher alive there).

**3. The heartbeat (hours, small cost).** A scheduled task of the account bound to the dispatcher's own
session, every `[harbor] heartbeat_hours` (default 3). It resumes the session, which gets a container
again, and runs the loop. If the dispatcher session is gone, the task starts a fresh dispatcher instead.
Harbor can't create it (it is the account's setting); the skill says how, and the logbook records it
(`harbor.py account set A --heartbeat-hours N`) so the views can tell an account with no heartbeat.

**4. The gatekeeper (minutes, when it matters).** A late message is **escalated** when it is a question,
when it is to `gatekeeper`, or when it has been queued longer than `[harbor] escalate_minutes` (default 30).
Escalated messages go on the gatekeeper's list (the logbook view and `msg status`), and the harbormaster's
control tells the person once (a push notification where the harbormaster has one). The person can wake a
dispatcher by hand: a comment on a PR it watches (a draft PR per account that is never merged works as a
mailbox) or opening the session.

**5. Optional: a fire URL per account.** A scheduled task with no schedule whose prompt starts a fresh
dispatcher. Its token is a secret, kept outside the logbook; its prompt accepts nothing from the request
text. It replaces waiting for the heartbeat when the dispatcher session is gone.

Worst cases: watcher alive, `--poll` seconds; container dead, the heartbeat period; and the gatekeeper is
told after `escalate_minutes`.

### Configuration added

```toml
[harbor]
gatekeeper_ok = "critical"         # was person_ok (still read); "critical", "areas", "always", "never"
ack_minutes = 15
escalate_minutes = 30
heartbeat_hours = 3
watch_poll_seconds = 30
watch_cap_minutes = 110
silent_minutes = 120
allowed_models = ["haiku", "sonnet", "opus"]

[harbor.models]
dispatcher = "haiku"
```

### Trust

Whoever can push to the logbook could already forge a seal; now they can also queue messages and ask for
sessions. What still holds: a request starts only a role and story the project knows, with an allowed model,
within the account's cap, from a prompt Harbor builds; messages are framed as data at every reader; the
dispatcher's tools have no Write or Edit; fire tokens never live in the logbook; the gatekeeper's yes is
still typed by a person.

### Designed, not built

- **Session state from hooks.** The `Stop` hook writes `state = "idle"` and `last_turn_end`, the next
  turn's first hook writes `working`; only a change, at most every 5 minutes per session.
- **The heavy verify.** A whole verify of an hour or more is fragile in a cloud container (no Docker
  daemon, background commands capped, the container reclaimed when idle). `[harbor] verify_host` would name
  the machine that runs convoy verifies. (`doctor --cloud`, once designed here to say what a cloud
  environment lacks, is replaced by 0.4's `doctor`: "Phase 4".)

## Appendix: the fleet Harbor was learned on

Harbor is a generic product; this appendix is the one place that names where it came from. Its evidence is a
survey of a week of convoys run by hand on JOUNA, a monorepo whose sessions worked in trains on a hand-kept
board, in Spanish. The survey's finding ids (`§n.m`) and candidate rules (`R1`…`R26`) are cited through this
document; what follows maps that fleet's words to Harbor's, and the rules to what Harbor does about them.
In the fleet's words a convoy is a *train*, its board file is `BOARD.md` and its handoff file is one per train (`tren-<n>.md`, under `3-Tasks/`).

### Vocabulary of the fleet

| Harbor | The fleet's word | What it is |
|---|---|---|
| convoy | tren | a batch of branches integrated in `convoy/<n>`, verified once, landed with one push |
| vessel | pieza | one piece's branch, built by one session (`/keelokit:build-story`) |
| skipper | jefe de tren | the session that carries a convoy: takes deliveries, assembles, fixes the combination |
| harbormaster | coordinador | the session that gives the ok to sail and keeps the watch |
| logbook | tablero (`coord/board`) | the orphan branch `harbor/log`: TOML state plus generated views |
| sail | ok + push | the harbormaster's ok, then the integrator's one push to `main` |
| pilot | integrador | an account designated to integrate; optional, `integrator = "any"` by default |
| worker | sesión | `<account>/<host>/<session>`: one session of one account on one machine |

### The 26 candidate rules

| Rule | Harbor | Phase |
|---|---|---|
| R1 one versioned state outside the protected branch, fixed schema, generated | the logbook: `harbor/log`, TOML schemas, only `harbor.py` writes | 1 |
| R2 generate the per-convoy handoff file from data, on the state branch | `convoys/<n>.md`, rendered on every write | 1 |
| R3 a piece enters with branch, hash and checks on that hash; a later commit voids it | `seal` + `convoy add` (`HEAD_MISMATCH`, `NO_SEAL`); status shows a void delivery | 1 |
| R4 piece verify derived from the diff and its consumers | Keelokit's `verify --since` routing (`verify-routing.toml`); Harbor runs it, doesn't reimplement it. Whether the routing covers consumers (a change in shared types running every consumer) is Keelokit's to check | delegated |
| R5 after a review fix, rerun what cites the change | falls out of R3: a fix is a new commit, which needs a new seal; selecting the tests that cite a string is Keelokit's routing | 1 + delegated |
| R6 the gate on every delivered branch, green seal per hash | the gate is entry to a convoy, not the push of a branch: an unsealed branch can be pushed and can't enter. A pre-push hook on every branch would be Keelokit's | 1 |
| R7 validate the fix commit before each verify resume | `convoy verify` after a red runs Keelokit's `--rerun-failed`, which runs what the fix's files route to plus what failed | 2 |
| R8 risk level from the diff; unknown goes up; the agent can't lower it | Keelokit's `build-story` tier rules (escalate only); Harbor records the tier | delegated |
| R9 the first agent of N1/N2 is the test writer | tier → first agent (verifier mode A for light and full) | 2 (skills) |
| R10 roles enforced by tools | Harbor's agents have `tools:` lists (skipper without Write, harbormaster read-only). Keelokit's reviewer and breaker are read-only by tools; its verifier needs Write for tests, and weakened tests are caught by `doctor --scope` (VERIFY-2), not by tools. Bash in any list is not a sandbox | 1 (agents) |
| R11 model per role and level in project config, coordinator included; cheap defaults | `[harbor.models]` for skipper, harbormaster and the control round (Haiku); story roles by Keelokit's table per tier; `harbor.py models` | 2 |
| R12 concurrency cap tied to budget, staggered starts | per-account `max_sessions` and `paused_until`; staggering without a decision | 1 |
| R13 counter of review rounds, a third only with P0/P1 | dropped: Keelokit's `build-story` already stops after two rounds, and the case behind it is a **HYPOTHESIS** (§3.14) | — |
| R14 hotspots in config, branches serialized, warn on shared declarations | `[harbor.hotspots]`, `HOTSPOT_HELD` at `add`; the early warning from `touches` | 1, 2 (warning) |
| R15 no parallel convoys that depend on each other from one base; order and re-base | `depends_on`, waiting until the dependency sails, then merge `main` | 1 (field), 2 |
| R16 reserve or renumber migration timestamps; fail on a shared one | the check at assembly fails and names the rename; renumbering without a decision | 2 |
| R17 generated artifacts and fixed totals as known conflicts | `[harbor.generated]` regenerated at assembly; totals without a decision | 2 |
| R18 detect `main` moving under an assembled convoy; record a loose push | `status` shows it (1); `main.toml`, ok void, re-assembly (2) | 1, 2 |
| R19 choose the convoy verify by a risk table; the reason with the ok | `[ok] level` and `reason`: `changed` by default, `all` only for what the routing can't bound ("Verifying without a bottleneck") | 2 |
| R20 heartbeat with expiry, first commit wins | the watch: `last_control`, `expires`, replay on rejection | 2 (the write rule is in 1) |
| R21 a preflight that fails on missing tools or an unfit machine | Keelokit's `verify --preflight` (VER-1) before the convoy verify | delegated |
| R22 structured handover on a budget cut; `wip/*` outside convoys | `worker end` with `[handover]`, head checked pushed; `wip/*` dropped (vessels never touch `main`) | 1 |
| R23 structured timestamps for every step | `events` per convoy, seals with start, end and duration | 1 |
| R24 coherence of process docs with the tools | dropped for Harbor: its state is generated, so it can't describe a tool that changed; prose docs are Keelokit's doctor's (vague phrases) | — |
| R25 the CI trigger as a project policy (`landing: convoy \| direct`) | Keelokit's `[landing] policy`; Harbor runs only under `convoy` | 1 (read) |
| R26 convoys that change the API declare the consuming app version and who deploys | without a decision (see above) | — |

### Proposals from the fleet's process (2026-11-02, not built)

A reading of the fleet's process documents alongside Keelokit 0.13. Three of
its five coordination ideas are already here: a board off `main` (the logbook, `harbor/log`), relief of
a lost coordinator after 3 hours with the first commit winning (`watch_expiry_minutes = 180`), and a
verification level chosen by risk (`convoy sail --level --reason`). Two are not:

- **A vessel never asks the person directly.** The fleet lost a train for 2 hours to a session blocked on
  AskUserQuestion that nobody saw. A worker in a convoy sends its question to the harbormaster with
  `send_message` and goes on with what doesn't depend on the answer; the harbormaster asks the person.
  Where: the worker's brief, and `worker` refusing to start a vessel's prompt without that line.
- **A red convoy leaves a cause.** Each red of a convoy's verify adds a row to the project's
  `.keelokit/red-causes.toml` (pattern, where to look) or to `docs/escapes.md` when it was a bug, in
  the commit that fixes it, so the next red with the same signature names itself. Where: `convoy
  verify` refusing a re-verify of a red convoy whose fix commit adds neither.

What Keelokit 0.13 changes for Harbor:

- `[verify] wip_branches = "wip/"` (opt-in, WIP-1): unfinished work moves on `wip/<topic>`, unverified,
  and Keelokit's pre-push refuses any other push holding an unproven wip tip. `convoy add` should refuse
  a branch whose head holds one before the hook does (`verify_tools.py wip-inside origin <sha>`).
- The pre-push lets a commit that isn't checked out reach a non-main branch when it already passed a
  clean, full verify here against `origin/main` (`verify_tools.py proven`): a worker can deliver a
  verified head from another worktree.
- `--rerun-failed` reruns only the failed integration specs and what the fix reaches, and a narrowed
  green still completes the red run into a composite seal: §"Verifying without a bottleneck" can count
  on it for a convoy's red integration step.
- A new verify step, `zones`, runs a change's unit tests at awkward clocks; it is a full step for
  `level`, like `unit`.

Fresh reads (§"Fresh reads") came from the fleet's board incident of 2026-11-07: a convoy started verifying
while another session kept adding pieces, because the second session read the board as of its last fetch.
