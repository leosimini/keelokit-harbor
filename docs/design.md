# How Harbor is built

This is the design. **Phases 1 and 2 are implemented** in `bin/harbor.py`.
- *Phase 1* (`tests/test_harbor.py`): logbook init, accounts, workers, seals, `convoy new|add|status`,
  the generated views, the one-time `BOARD.md` import.
- *Phase 2* (`tests/test_phase2.py`): `convoy assemble|verify|sail|abort|defer`, the ok,
  `harbormaster takeover|control`, `harbor/main.toml`.
Marks *(2)* name what phase 2 added. Designed and **not written yet**: reassigning a skipper
(`convoy skipper N WORKER`), the early hotspot warning from stories' `touches`, the warning for
vessels that share commits, and everything marked *(3)*. The evidence is the survey of a week of convoys run by hand in JOUNA
(`multi-train-orchestration.md`; its finding ids, `n.m`, are cited as `§n.m`, its candidate
rules as `R1`…`R26`). For how to use Harbor, see the [README](../README.md).

## Thesis

Keelokit lands one story per session directly on `main`; with many sessions, several accounts and
several machines, that means one `pnpm verify` per landing and nobody seeing the combination before
it is on `main` (§1.2, §4.11). JOUNA replaced it with trains: branches from several sessions merged
into one integration branch, verified once and pushed once. Its failures were not in the idea but in
the hand-kept parts: a board that drifted from reality (§5.8), a piece's "green" that no longer
matched its hash (§6.2), train files invisible from `main` (§5.4), migration timestamps renamed at
integration (§6.5), a loose push that orphaned a train branch (§6.9), budget cuts that left work
half pushed (§6.8). Harbor keeps the process and takes the hand work away: the shared state is a
git branch only `harbor.py` writes, with a fixed schema and generated views; a branch enters a
convoy only with a verify result recorded for its exact hash; the guard of the process (the
harbormaster) has a heartbeat that expires and is taken by the first commit. Harbor adds no
server and no events: every session reads the state with `git fetch`, so the logbook's schema is
the contract a future API would serve.

## Vocabulary

| Harbor | JOUNA (survey) | What it is |
|---|---|---|
| convoy | tren | a batch of branches integrated in `convoy/<n>`, verified once, landed with one push |
| vessel | pieza | one piece's branch, built by one session (`/keelokit:build-story`) |
| skipper | jefe de tren | the session that carries a convoy: takes deliveries, assembles, fixes the combination |
| harbormaster | coordinador | the session that gives the ok to sail and keeps the watch |
| logbook | tablero (`coord/board`) | the orphan branch `harbor/log`: TOML state plus generated views |
| sail | ok + push | the harbormaster's ok, then the integrator's one push to `main` |
| pilot | integrador | an account designated to integrate; optional, `integrator = "any"` by default |
| worker | sesión | `<account>/<host>/<session>`: one session of one account on one machine |

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
| `status.py`, `ci.py health` | the harbormaster's round: machine state, CI of `main` |
| tiers trivial / light / full | the first agent of a vessel and its model |
| `touches`, `critical.toml` | an early hotspot warning, before any code *(phase 2)* |
| the `Story:` trailer | which story a vessel carries, read from its commits |

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
vessel_verify = "pnpm verify --since {base} --keep-going"   # {base} = origin/main when the seal runs; also {head}, {branch}
convoy_preflight = "pnpm verify --preflight"        # (2) before every convoy verify; "" turns it off
convoy_verify = "pnpm verify --keep-going"          # (2) level "changed": scoped by the convoy's diff against main
convoy_verify_all = "pnpm verify --all --keep-going" # (2) level "all": only what the routing can't bound
convoy_rerun = "pnpm verify --rerun-failed --keep-going"   # (2) after a red; Keelokit seals it when it completes the plan
ci_check = "python3 .keelokit/bin/ci.py health"     # (2) the ok needs it green (exit 1 = red); default when ci.py exists
person_ok = "critical"             # (2) a person's yes too: "critical" (full tier or a critical area), "always", "never"
control_every_minutes = 90         # JOUNA's value (§5.3)
watch_expiry_minutes = 180         # JOUNA's value (§5.3): relief after 3 hours without a control

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

The example hotspots are JOUNA's measured bottlenecks (§2.12); a project declares its own.
Harbor ships no default hotspot list: that §2.12's contention generalises is an **INDICIO** at best.

Per clone, git-ignored, in `.keelokit/local.toml`:

```toml
[harbor]
account = "leo"    # the Claude account this clone's sessions run on
host = "mbp"       # this machine
```

The session id comes from `--session`, `$HARBOR_SESSION` or `$CLAUDE_SESSION_ID`; the SessionStart
hook prints it (`this session is leo/mbp/<id>`), read from the hook's JSON.

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
harbor/seals/<sha>.toml         the shared seal Keelokit's pre-push reads: only for a whole green run
harbor/main.toml                (phase 2) the last main Harbor saw, and every move of it
harbor/imported/BOARD.md        (once) the hand-kept board, verbatim
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
nothing. They replace `BOARD.md` and `tren-<n>.md` (R1, R2): they live on the state branch, not on
a skipper's branch (§5.4), and can't say anything the data doesn't (§5.8).

## Schemas

Every file has `schema = 1`. Times are UTC, `YYYY-MM-DDTHH:MM:SSZ`. Absent keys are omitted, never
written empty. A field marked *(2)* is written from phase 2.

### `harbor/harbormaster.toml`

```toml
schema = 1
worker = "leo/mbp/session_01KwSx"
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
account = "leo"
max_sessions = 2                 # active workers of this account at once; chosen by the person, no default
paused_until = "2026-11-02T03:00:00Z"
reason = "weekly limit"
updated = "2026-11-01T16:00:00Z"
updated_by = "leo/mbp/-"
```

Only a clone of that account changes it. `worker register` refuses beyond `max_sessions` and while
`paused_until` is in the future (R12). Harbor measures sessions, not tokens: the survey has no token
data (§3.16), so the cap is the person's estimate of the budget, not a measurement.

### `harbor/workers/<account>/<host>/<session>.toml`

```toml
schema = 1
id = "leo/mbp/session_01Abc"
account = "leo"
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
spawned_by = "leo/mbp/session_01Sk"   # the session that launched this one, and owns its result
title = "jouna · C8 · ola 1 · CARGA-001"   # (3) the canonical session title (see "Names")
canonical_branch = "carga-001"   # (3) the story id in lower case; `branch` is the one the session really uses
children_at_end = ["leo/mbp/session_01Ve"]   # sessions it launched that were still running when it ended

[handover]                       # on a budget cut or any early end (R22)
branch = "claude/carga-001"
head = "4d44fdd8…"              # checked equal to origin/<branch>: only pushed work is handed over
verified = "seal of 4d44fdd8 green; doctor --scope CARGA-001 green"
pending = "screenshots of S3; reviewer round 2"
worktree = "../app-carga-001"
log = "/tmp/verify-carga-001.log"
```

### `harbor/convoys/<n>.toml`

```toml
schema = 1
number = 8
title = "CARGA wave 1"
state = "verifying"              # assembling | waiting | ready | verifying | sailed | aborted
branch = "convoy/8"
skipper = "leo/mbp/session_01Abc"
integrator = "leo/mbp/session_01Abc"   # the skipper when integrator = "any"; "account:<pilot>" until a pilot session takes it
base = "a2becf56d…"              # origin/main at new; (2) the main last merged into convoy/<n>
head = "60099ef60…"              # (2) tip of convoy/<n> after the last assembly or fix
created = "2026-10-31T19:51:00Z"
depends_on = [7]                 # convoys that must sail first (R15)
expected = ["CARGA-000", "CARGA-001", "CARGA-003"]

[ok]                             # (2) the harbormaster's ok (R19)
by = "ana/linux/session_02Ab"
at = "2026-11-01T13:01:00Z"
level = "all"                    # changed | all
reason = "migrations and verify scripts: the risk table says --all"
base = "a2becf56d…"              # main when the ok was given
head = "60099ef60…"              # the convoy head the ok covers
needs_person = "full-tier vessels claude/carga-001"   # why a person's yes is also needed; absent when it isn't

[ok.person]                      # (2) that yes, from the person's own terminal
by = "leo/mbp/-"
at = "2026-11-01T13:20:00Z"
head = "60099ef60…"              # bound to this head: a later commit needs another yes
note = "read the diff"

[sail]                           # (2)
by = "leo/mbp/session_01Abc"
at = "2026-11-01T14:30:00Z"
main_before = "a2becf56d…"
main_after = "60099ef60…"
ci = "green"                     # (2) recorded by the next control from ci.py health

[[vessels]]
branch = "claude/carga-001"
head = "4d44fdd8…"               # the delivered commit; the remote tip must still be it
story = "CARGA-001"              # --story, else the Story: trailers of its commits
tier = "full"                    # as the vessel session chose it (Keelokit's tier)
hotspots = ["schema"]            # computed from its diff against main and [harbor.hotspots]
seal_base = "a2becf56d…"         # the main its vessel verify ran against
added = "2026-11-01T11:10:00Z"
added_by = "leo/mbp/session_01Abc"
merged = "9c1e…"                 # (2) its merge commit on convoy/<n>

[[events]]                       # every step, with time and worker (R23)
at = "2026-11-01T11:10:00Z"
by = "leo/mbp/session_01Abc"
what = "add"                     # new add redelivered assembled main-moved ok verify-start verify-pass
detail = "claude/carga-001@4d44fdd8"   # verify-fail fix sailed aborted skipper-changed imported
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
by = "leo/mbp/session_01Abc"
level = "changed"                # only for a whole green verify (below): what Keelokit's pre-push reads
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

**No second run.** With the convoy policy, `build-story` pushes the vessel's branch, and its
pre-push runs Keelokit's whole verify on that exact commit. `harbor.py seal` finds that run in the
history (same commit, today's `main`, whole, green, clean) and records it without running anything
(`reused = true`); `--rerun` forces a fresh run. One verify per vessel, not two.

`harbor.py seal`, when it runs, runs the command itself on a clean tree and refuses to record if `HEAD` or the
tree changed during the run: the record speaks for one commit. A red run is recorded too (the
history the survey couldn't reconstruct, §4.9). A later commit has another sha and so no seal:
the delivery is void by construction (R3).

### `harbor/main.toml` *(phase 2)*

```toml
schema = 1
head = "60099ef60…"              # the last origin/main Harbor saw

[[moves]]
from = "a2becf56d…"
to = "7baa0a279…"
seen = "2026-10-31T18:31:00Z"
cause = "loose"                  # "convoy 7" when a sail explains it; "loose" otherwise (R18)
```

### `harbor/imported/board.toml`

`source`, `sha256`, `imported`, `by`, `coordinator` (the text after "coordina:"), `convoys` (numbers
imported), `skipped` (rows left out, with the reason). The parser takes markdown tables whose header
has a train number column and a state column, maps *armando / esperando / listo / verificando / en
main* to the states below, and skips rows without a number (such as «Tren de Eventos»). **Assumption:**
the column layout of JOUNA's `BOARD.md` is known only from its description (§5.1); the tests use a
board written from that description, not the real file.

## Life of a convoy

| State | Means |
|---|---|
| `assembling` | created; the skipper takes deliveries |
| `waiting` | assembled with what was delivered; an expected vessel, or a convoy it depends on, is still missing |
| `ready` | every expected vessel merged in `convoy/<n>` with `main`; migrations in order, generated files regenerated: waiting for the ok |
| `verifying` | the ok is given with its level; the integrator runs the convoy's one verify and fixes the combination |
| `sailed` | pushed to `main`; hotspots released |
| `aborted` | given up; its vessels may join another convoy; `convoy/<n>` stays on the remote for reference |

| From → to | Command | Who | When |
|---|---|---|---|
| — → assembling | `convoy new` | any active worker, who becomes its skipper | account not paused; every `--depends` convoy exists |
| assembling, waiting → same | `convoy add` | the skipper | the vessel is pushed, sealed green on that exact commit, holds no hotspot another open vessel holds, is in no other open convoy |
| assembling, waiting → waiting | `convoy assemble` *(2)* | the integrator | merged what was delivered; something expected or a dependency is missing |
| assembling, waiting → ready | `convoy assemble` *(2)* | the integrator | every expected vessel merged, `main` merged in, every dependency sailed, migration check passed |
| ready, verifying → assembling | `convoy assemble` *(2)* | the integrator | `main` moved, a vessel was redelivered, or one was added: the ok is cleared |
| ready → verifying | `convoy sail --ok` *(2)* | the harbormaster, holding an unexpired watch | the ok conditions below |
| verifying → same | `convoy approve` *(2)* | the person, from their own terminal | only a critical convoy (`person_ok`); bound to the head |
| verifying → verifying | `convoy verify` *(2)* | the integrator | a run, green or red; fixes in between |
| verifying → sailed | `convoy sail` *(2)* | the integrator | green convoy seal on the exact head at the ok's level; `main` still the ok's base |
| assembling, waiting → same | `convoy defer N STORY` *(2)* | the skipper | an expected vessel is late: it leaves `expected` and goes to the next convoy, so the rest don't wait for it. **Needs your ok:** not in the agreed command list |
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
  block in `state.toml`, landed on `main` the current way (it is the last direct landing); writes
  `.keelokit/local.toml` (asks account and host) and adds it to `.gitignore`; `harbor.py init`;
  `harbor.py account set <account> --max-sessions N` with the number the person gives; proposes
  hotspots (critical areas, migration folders, shared packages, locales, generated files, and the
  paths with most commits in `git log` lately) for the person to confirm; looks for a hand-kept
  board (`git show origin/coord/board:BOARD.md`, or `BOARD.md` in the tree) and, with a yes,
  imports it once.
- **Logbook:** the first commit (`harbormaster.toml`, `logbook.toml`, views); `accounts/<account>`;
  the import.
- **Errors:** `NO_KEELOKIT`, `NO_IDENTITY`, `ALREADY_IMPORTED`; `init` again is a no-op.

### `/harbor:convoy new`

- **Before:** an active worker (`harbor.py worker register`); its account not paused; `--depends`
  convoys exist and aren't aborted.
- **Logbook:** `convoys/<n>.toml` with the next number (after imported ones), base = `origin/main`,
  skipper = this worker, integrator per `[harbor] integrator`; the worker's role becomes skipper.
  Event `new`.
- **Errors:** `NOT_REGISTERED`, `ACCOUNT_PAUSED`, `UNKNOWN_CONVOY`, `NO_MAIN`.

### `/harbor:convoy add N BRANCH`

- **Before:** convoy `N` is assembling or waiting; the caller is its skipper; `origin/BRANCH`
  exists and, with `--head`, is exactly that commit; a green seal for that commit; its hotspots
  (from `git diff` against the merge base with `main`) not held by any vessel of an open convoy;
  the branch in no other open convoy.
- **Logbook:** the vessel row (or replaces it: a redelivery after a fix), event `add` or
  `redelivered`, the skipper's `last_seen`.
- **Errors:** `BRANCH_NOT_PUSHED`, `HEAD_MISMATCH`, `NO_SEAL`, `SEAL_RED`, `HOTSPOT_HELD`,
  `VESSEL_TAKEN`, `NOT_SKIPPER`, `CONVOY_CLOSED`, `UNKNOWN_CONVOY`.
- `convoy status [N]` (read-only) shows, for open convoys, when `main` moved past the base and when
  a vessel's branch moved after delivery ("the delivery is void").

### `/harbor:convoy assemble N` *(phase 2)*

- **Before:** the integrator (the skipper when `integrator = "any"`; a session of the pilot account
  otherwise, which becomes the convoy's integrator); state assembling, waiting, ready or verifying;
  every vessel's remote tip still its delivered head (`VESSEL_MOVED` otherwise).
- **Does:** creates `convoy/<n>` from the base if absent; merges `origin/main` into it if `main`
  moved (merge, not rebase, §4.3); merges each unmerged vessel in order (`depends_on` among
  stories, then the order given, then the order added, §4.4), `--no-ff`. A conflict only in
  `[harbor.generated]` paths: run its command and commit the result (R17). A conflict only in
  formatting: Keelokit's FMT-1 (keep the content, `pnpm format`). Any other conflict: stop with
  `CONFLICT` and the files; the skipper resolves it in a combination commit. Then the migration
  check: two vessels adding migrations with the same timestamp, or one that sorts before `main`'s
  last, fail with `MIGRATION_COLLISION` / `MIGRATION_ORDER` and the rename to make (R16). Pushes
  `convoy/<n>` without force; a rejection means another integrator pushed and it stops.
- **Logbook:** `head`, `base`, `vessels[].merged`, the state, events `assembled` / `main-moved`; a
  move of `main` clears `[ok]`.
- **Errors:** `NOT_INTEGRATOR`, `DIRTY_TREE`, `VESSEL_MOVED`, `CONFLICT`, `GENERATED_FAILED`,
  `MIGRATION_COLLISION`, `MIGRATION_ORDER`, `DIVERGED` (local and remote `convoy/<n>` disagree),
  `CONVOY_PUSH_REJECTED`, `ASSEMBLE_STALE` (vessels changed meanwhile). An open dependency is not an
  error: the convoy waits.

### `/harbor:convoy sail N --ok --level changed|all --reason TEXT` *(phase 2)*

- **Before:** the harbormaster with an unexpired watch; state ready; the convoy's `base` is
  `origin/main`; `ci.py health` says `main` is green where CI is reachable; nothing expected is
  missing (§4.7).
- **The level** (R19): `changed` by default, `all` only for what Keelokit's routing can't bound;
  the reason names the files that decided it. The rules, and why money or migrations don't force
  `all`, are in "Verifying without a bottleneck".
- **Logbook:** `[ok]`, state verifying, event `ok`.
- **Errors:** `NOT_HARBORMASTER` (also for an expired watch), `WRONG_STATE`, `MAIN_MOVED`,
  `CONVOY_MOVED`, `MAIN_RED`.

### `harbor.py convoy approve N [--note TEXT]` *(phase 2)*

- **Who:** the person, from their own terminal. Harbor's PreToolUse hook (`harbor.py guard
  --claude`) blocks the command when an agent runs it; Bash can reach anything, so it is a speed
  bump, as Keelokit's `allowTamper` is, not a sandbox.
- **When it's needed:** `[harbor] person_ok`. `"critical"` (default): a vessel of the full tier or one
  whose diff touches an area of `.keelokit/critical.toml`; `"always"`; `"never"`. The ok records why
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
  seal (§6.3), so there is no fix seal.
- **Does:** nothing, when the convoy is one vessel sealed against today's `main` and its head is
  that vessel's head: the seal already is the convoy verify. Otherwise `pnpm verify --preflight`,
  then the level's command on the convoy head, in the background with a log (Keelokit's agent
  brief), event `verify-start` with the host first, because the verify lock and its state are
  local to one machine (§5.6). After a red and its fixes, the rerun is as narrow as Keelokit allows
  (see "Verifying without a bottleneck").
- **Logbook:** a `kind = "convoy"` seal; `verify-pass` or `verify-fail` with the failed steps.
- **Errors:** `NOT_INTEGRATOR`, `MAIN_MOVED`, `CONVOY_REWRITTEN`, `DIRTY_TREE`, `SEAL_INVALID`
  (HEAD or the tree changed during the run). A red preflight is a red run (`verify-fail`). A green
  run Keelokit didn't record as whole at the ok's level is `verify-unsealed`, and sail refuses it.

### `/harbor:convoy sail N` *(phase 2)*

- **Before:** the integrator; `[ok]` present; a green convoy seal for the exact head at the ok's
  level or above; `origin/main` is the ok's base, so the push is a fast-forward.
- **Does:** `git push origin <head>:main` from the machine that ran the verify, so Keelokit's
  pre-push seal recognises the commit and doesn't repeat the run. Rejected: `MAIN_MOVED`, back to
  assemble.
- **Logbook:** `[sail]`, state sailed, `main.toml`, event `sailed`; the next control records the CI.
- **Errors:** `NO_OK`, `NEEDS_PERSON`, `NOT_SEALED`, `MAIN_MOVED`, `CONVOY_MOVED`, `NOT_INTEGRATOR`, `PUSH_FAILED`
  (the pre-push hook's own refusal included). If the push lands and the logbook write fails, the
  next control finds `main` at a verifying convoy's head and records the sail.

### `/harbor:log [N]`

Read-only: fetches and prints `LOGBOOK.md`, or `convoys/<n>.md`.

### `/harbor:harbormaster takeover` *(phase 2)*

- **Before:** an active worker; the watch empty or expired (`now > expires`). With
  `--relieve REASON`, only when the person asks: their word beats the logbook, as JOUNA's owner's
  did over the board (§5.3).
- **Logbook:** `harbormaster.toml` (worker, since, last_control = now, expires) and a `history` row.
  Two takeovers at once: the second push is rejected, the replay finds the watch held and
  unexpired, and it fails with `WATCH_HELD` naming the holder. First commit wins (R20).
- **Then:** the session schedules its own control every `control_every_minutes`: a task scheduled
  by another session doesn't reach it (§5.3).

### `/harbor:harbormaster control` *(phase 2)*

- **Before:** the holder of the watch (`NOT_HARBORMASTER` otherwise; an expired holder renews it).
- **The round, in ten lines:** heartbeat; `origin/main` against `main.toml` (a move no sail explains
  is recorded as `loose`, R18); CI of `main`; per open convoy, `main` moved, vessels moved after
  delivery, skipper alive (its worker active and seen within the expiry, its account not paused),
  ready convoys waiting for the ok; workers not seen within the expiry marked `lost` (which frees
  their account's places); verifies started with no result (a cut run on another machine).
- **Logbook:** `harbormaster.toml`, `main.toml`, workers marked lost, events. Reassigning a convoy
  whose skipper is gone (`harbor.py convoy skipper N WORKER`) is the harbormaster's call in a
  control. **Needs your ok:** neither the command nor the expiry for workers was in the agreement;
  this uses the watch's.

### `harbor.py` without a slash command

`account set|pause|resume`, `worker register|end`, `seal`, `import-board` are run by the skills.
`sync --hook` is the entry of every Claude Code hook (§"Fresh reads"); `check --hook` is its SessionStart
part, never fails the session and prints one to three lines.

## The watch and its relief

One harbormaster at a time. Its heartbeat is `last_control`, written by every control; the watch
expires `watch_expiry_minutes` after it. Any active worker can take an expired watch, and the first
push wins because the replay rechecks the expiry (R20, §5.3). The harbormaster gives oks, records
the CI after a sail, notices loose pushes and lost workers; it never integrates unless it is also
an integrator. What the harbormaster does not see (a session's local verify lock, its
`.verify-status`) it learns only from logbook events (§5.6). JOUNA ran its coordinator on Opus
(§3.4); that this was intended is a **HIPÓTESIS**, so Harbor's default is Sonnet, with
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
session id). Every fetch has a 5 s cap and `GIT_TERMINAL_PROMPT=0`.

| Hook | What it does | Delay |
| --- | --- | --- |
| SessionStart | fetches, prints the `check` lines ("fetched now", or "offline: as of the last fetch, N min old") | 0 |
| UserPromptSubmit | fetches when the last fetch is 60 s old or more; prints, to stdout, only what changed since the seen tip (at most 1000 characters); nothing if the tip is the same | up to 60 s |
| PostToolUse | the same at 120 s, as `additionalContext` JSON; inside the window it reads only the seen file and starts no git process | up to 2 min in a long turn |
| PreToolUse, Bash | `convoy approve` is denied as before. Before a `git push` to `main` or `convoy/*`, or `harbor.py convoy add\|sail\|verify`, it fetches without waiting and adds the open convoys' states; if one is `verifying` and the push goes to `main` not through `convoy sail`, it says so. It never denies for this | 0 |

The change is the TOML at the seen tip against the new tip: new convoy, state change, vessels added,
the last 5 new events, a new watch holder or `last_control`, workers registered or ended. If the seen
tip is unknown or unreadable, a short summary (watch, open convoys, last events) is printed instead.
Any error is exit 0: one line at SessionStart, silence elsewhere. A failed fetch keeps the last good
fetch time and is not retried inside the window.

Not used: `asyncRewake` hooks or a heartbeat that polls. They wake an idle session, and each wake spends
tokens for a logbook nobody is acting on; a session that is working already passes through the hooks above.

## Verifying without a bottleneck

In a large monorepo the verify is the queue everyone waits in. JOUNA's numbers: `--all` took
62–72 min by its own docs and went red at 82 and 84 min in a 4-core container (§4.9); a piece
verify measured 47 min where the docs said minutes (§6.12); one landing took ten verify runs
(§4.11); train 3 needed four runs, train 5 four `--all`, train 7 one `--all` and five resumes
(§4.9). JOUNA dropped "every piece green with a full verify" four minutes after writing it, because
"a repo of this size can't take a full verify per piece" (§4.2), and grew narrower variants
(`--piece`, `--keep-going`, `--resume`). The fast train 4 was written and reviewed in an hour and
landed four days later, waiting for its batch (§1.8). So Harbor treats verify minutes and machine
time as the scarce resource. Five rules:

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
   JOUNA's middle level (verify plus the full suite of the widest package, §4.6) is what Keelokit's
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

**Measure before tuning.** Every seal records its duration and, from Keelokit's
`keelokit-verify.history`, each step's time, the failed steps and the known causes *(phase 1)*.
Those are the numbers the survey couldn't reconstruct (§4.9: run times; §1.7: working time): verify
minutes per convoy, reds per convoy, wait from delivery to sail, the slowest steps. The balance
between a light vessel verify (fewer minutes per vessel, more reds in the convoy) and a heavy one is
`vessel_verify`, set per project and moved by those numbers, not by a rule. JOUNA's piece check
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
allowed push outside a convoy, §2.4), or a loose push (§6.9, an **INDICIO** of how `train/7`
died). Harbor never rebases a convoy:

- **assembling or waiting:** the next `assemble` merges `origin/main` into `convoy/<n>` and moves
  `base`.
- **ready or verifying:** the ok is void (its level was chosen for other contents); `assemble`
  merges `main`, the state returns to ready, and the harbormaster gives a new ok. `sail` refuses
  while `main` isn't the ok's base, and a rejected push says the same. The new verify is scoped like
  the first, not `--all`: what `main` brought is in the diff only where it meets the convoy's
  packages. Stacking (rule 5 above) avoids most of these re-merges.
- **depending convoys:** a convoy whose `depends_on` hasn't sailed stays waiting; when it sails,
  the next `assemble` merges the new `main` (R15). Convoys from the same base that depend on each
  other can't both be ready: JOUNA's trains 4 and 6 (§1.6) would have queued.
- **vessel seals:** stay valid as entry tickets: they speak for the vessel's own part against the
  main it had. The combination is what the convoy's verify covers.
- **record:** every move goes in `main.toml`, with its cause; a loose one is shown in the logbook
  until the harbormaster acknowledges it.

## Budget cuts and handover

JOUNA's sessions stopped together on account limits for 71 hours (§1.7), and left `wip` commits on
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

*(Decided 2026-11-02; written on Keelokit 0.12's `status.py title`.)* JOUNA's sessions were known
by `session_01…` ids (§5.7), its integration branches had random names (§1.4), "train 8" meant two
things (§1.9), and `train/7` drifted from what it held (§6.9). So a name comes from the data and is
never typed:

| Session | Keelokit alone | With Harbor |
|---|---|---|
| A story | `jouna · ola 1 · CARGA-001` | `jouna · C8 · ola 1 · CARGA-001` |
| Coordinating | `jouna · coordinador` | `jouna · harbormaster` |
| Carrying a convoy | — | `jouna · C8 · skipper` |
| A subagent (an `Agent` description, not a session) | `CARGA-001 · verifier` | the same |

- From the grouping to the item: what groups goes first, so the sessions of one convoy or one
  wave sit together in a list. With Harbor the convoy goes before the wave, because the convoy
  decides what lands together; without it the wave is all that groups. The story id goes whole: it
  is the one stable key (its file, its `Story:` trailer). The word for wave follows
  `[dashboard] lang`.
- **Keelokit owns the rule** (sessions, stories and waves are its concepts): `status.py title <ID>`
  computes the title from `.keelokit/answers.yml`, the story's front matter and the language, and
  the agent brief says every session launched gets it. Harbor calls that command and puts `C<n>`
  first; it copies nothing.
- **Branches keep Keelokit's convention**, the story id in lower case. A cloud session that is
  given its own branch (`claude/…`) can't rename it: the worker file keeps both, `branch` (real)
  and `canonical_branch`, and the views show both.
- **What can be checked:** titles live in the Claude app, not in the repo, so neither Keelokit nor
  Harbor can read the title a session really has. Harbor computes the canonical one (`worker
  register --story`, `convoy new`, `harbormaster takeover` print it, and the skills apply it),
  records it in the worker, and `harbor/LOGBOOK.md` lists sessions by it, as a tree, each under the
  session that launched it (`spawned_by`).

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
model rule changed the practice is an **INDICIO** (§3.7: commit counts, not tokens).

## Assumptions to validate

| Assumption | Source | How it would be checked |
|---|---|---|
| Keelokit's `landing-policy` branch lands on its `main` as reviewed | Keelokit's report; checked here against `4b22a548c` | Harbor's tests use stand-ins; rerun the shared-seal check against Keelokit's release |
| hotspots concentrate on shared types, schema, migrations, locales, generated files | §2.12 (**INDICIO** for the density) | `git log --format=%h -- <path>` counts in the adopting repo |
| a coordinator on Opus was intended | §3.4 (**HIPÓTESIS**) | ask the owner; Harbor defaults to Sonnet |
| trailers name the model of the session that signed | §3.6 (**HIPÓTESIS**) | not needed: Harbor records `model` per worker |
| a reviewer of the right level doesn't replace a real run | §3.15 (**INDICIO**) | the convoy verify is a real run; nothing else assumes it |
| duplicated history comes from rebasing sibling branches that share commits | §6.7 (**INDICIO**) | *(phase 2)* `add` warns when two vessels share commits not on `main` |
| "future" migration names were an ordering convention without a reservation | §6.5 (**INDICIO**) | the migration check at assembly doesn't depend on it |
| the hidden cost of direct landings | §4.11 (**INDICIO**) | the logbook's seal history gives the numbers JOUNA lacked |
| the push that killed `train/7` was a loose push | §6.9 (**INDICIO**) | `main.toml` records the cause of every move |
| BOARD.md's tables look as §5.1 describes | §5.1 | run the import on the real `coord/board` |
| a third review round without P0/P1 was unjustified | §3.14 (**HIPÓTESIS**) | not Harbor's: Keelokit caps rounds |
| process documents conflicting at integration | §6.15 (**INDICIO**) | not Harbor's (R24) |

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
| 6.9 | a loose push kills a train branch | `main.toml` causes; ok void when `main` moves |
| 6.10 | `main` pushed with only Format run | push only with a green convoy seal at the ok's level; Keelokit's hook stays |
| 6.11 | process rules set and withdrawn in minutes | the rules live in Harbor's code and tests, versioned by release; not editable from the logbook |
| 6.12 | container resources and tools | Keelokit's `--preflight` before the convoy verify (R21); step times in every seal; no vessel seal on the integrator's machine while it verifies |
| 6.13 | scheduled CI red four runs in a row | the ok requires `main` green (`ci.py health`) |
| 6.14 | API↔app contract unverified between trains | without a decision (R26) |
| 6.15 | process docs out of date | views can't drift; the rest is Keelokit's (R24) |
| 6.16 | piece reverted and redone in a train | a redelivery replaces the vessel; abort and a new vessel otherwise |

## The 26 candidate rules

| Rule | Harbor | Phase |
|---|---|---|
| R1 one versioned state outside the protected branch, fixed schema, generated | the logbook: `harbor/log`, TOML schemas, only `harbor.py` writes | 1 |
| R2 generate `tren-<n>` from data, on the state branch | `convoys/<n>.md`, rendered on every write | 1 |
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
| R13 counter of review rounds, a third only with P0/P1 | dropped: Keelokit's `build-story` already stops after two rounds, and the case behind it is a **HIPÓTESIS** (§3.14) | — |
| R14 hotspots in config, branches serialized, warn on shared declarations | `[harbor.hotspots]`, `HOTSPOT_HELD` at `add`; the early warning from `touches` | 1, 2 (warning) |
| R15 no parallel convoys that depend on each other from one base; order and re-base | `depends_on`, waiting until the dependency sails, then merge `main` | 1 (field), 2 |
| R16 reserve or renumber migration timestamps; fail on a shared one | the check at assembly fails and names the rename; renumbering without a decision | 2 |
| R17 generated artifacts and fixed totals as known conflicts | `[harbor.generated]` regenerated at assembly; totals without a decision | 2 |
| R18 detect `main` moving under an assembled convoy; record a loose push | `status` shows it (1); `main.toml`, ok void, re-assembly (2) | 1, 2 |
| R19 choose the convoy verify by a risk table; the reason with the ok | `[ok] level` and `reason`: `changed` by default, `all` only for what the routing can't bound ("Verifying without a bottleneck") | 2 |
| R20 heartbeat with expiry, first commit wins | the watch: `last_control`, `expires`, replay on rejection | 2 (the write rule is in 1) |
| R21 a preflight that fails on missing tools or an unfit machine | Keelokit's `verify --preflight` (VER-1) before the convoy verify | delegated |
| R22 structured handover on a budget cut; `wip/*` outside trains | `worker end` with `[handover]`, head checked pushed; `wip/*` dropped (vessels never touch `main`) | 1 |
| R23 structured timestamps for every step | `events` per convoy, seals with start, end and duration | 1 |
| R24 coherence of process docs with the tools | dropped for Harbor: its state is generated, so it can't describe a tool that changed; prose docs are Keelokit's doctor's (vague phrases) | — |
| R25 the CI trigger as a project policy (`landing: train \| direct`) | Keelokit's `[landing] policy`; Harbor runs only under `convoy` | 1 (read) |
| R26 trains that change the API declare the consuming app version and who deploys | without a decision (see above) | — |

## Proposals from JOUNA's process (2026-11-02, not built)

A reading of JOUNA's trains (`3-Tasks/process/trains.md`, `CLAUDE.md`) alongside Keelokit 0.13. Three of
its five coordination ideas are already here: a board off `main` (the logbook, `harbor/log`), relief of
a lost coordinator after 3 hours with the first commit winning (`watch_expiry_minutes = 180`), and a
verification level chosen by risk (`convoy sail --level --reason`). Two are not:

- **A vessel never asks the person directly.** JOUNA lost a train for 2 hours to a session blocked on
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

Fresh reads (§"Fresh reads") came from JOUNA's board incident of 2026-11-07: a convoy started verifying
while another session kept adding pieces, because the second session read the board as of its last fetch.
