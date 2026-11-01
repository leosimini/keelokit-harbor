# How Harbor is built

This is the design, written before most of the code exists. **Phase 1 is implemented** (`bin/harbor.py`:
logbook init, accounts, workers, seals, `convoy new|add|status`, the generated views, the one-time
`BOARD.md` import; `tests/test_harbor.py`). Everything marked *(phase 2)* is designed but not
written. The evidence is the survey of a week of convoys run by hand in JOUNA
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
| `[landing] policy = "convoy"` in `.keelokit/state.toml` | the switch. **Assumption:** the key name; Keelokit is adding it in parallel. Also assumed: with this policy `build-story` stops at a pushed branch instead of pushing to `main` (its step 7 pushes today). Both to validate against Keelokit's change |
| `pnpm verify --since REF` | the vessel's own verify (its part only, routed by `verify-routing.toml`) |
| `pnpm verify [--all] --keep-going`, `--preflight` | the convoy's one verify, after a preflight that fails in minutes on missing tools or a busy machine (VER-1) |
| the seal (`keelokit-verify.seal`, `--use-seal`) | the push to `main` from the machine that ran the convoy verify skips the repeat. Keelokit's seal is per clone and `--since` is never sealed (`verify.sh:17`, `:70`), so the vessel's result is recorded by Harbor, in the logbook |
| `doctor.py --scope ID`, `--brief` | the vessel session's own check before it delivers; Harbor does not rerun it *(phase 2: record its exit in the seal)* |
| `status.py`, `ci.py health` | the harbormaster's round: machine state, CI of `main` |
| tiers trivial / light / full | the first agent of a vessel and its model |
| `touches`, `critical.toml` | an early hotspot warning, before any code *(phase 2)* |
| the `Story:` trailer | which story a vessel carries, read from its commits |

## Configuration

Project-wide, committed, in `.keelokit/state.toml` (read from the working tree of the session):

```toml
[landing]
policy = "convoy"                  # Keelokit's key; Harbor runs only with this value

[harbor]
integrator = "any"                 # "any": a convoy's skipper integrates on its own machine; or a pilot account name
vessel_verify = "pnpm verify --since {base}"   # {base} = origin/main when the seal runs; also {head}, {branch}
control_every_minutes = 90         # JOUNA's value (§5.3)
watch_expiry_minutes = 180         # JOUNA's value (§5.3): relief after 3 hours without a control

[harbor.models]                    # model per role; Harbor names it on every Agent and create_session (§3.3)
skipper = "sonnet"
harbormaster = "sonnet"
verifier = "sonnet"
builder = "sonnet"
reviewer = "sonnet"                # light; full stories: see "Models and the first agent"
breaker = "sonnet"

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
LOGBOOK.md                      generated: watch, convoys, workers, accounts, import
convoys/<n>.md                  generated: one convoy, its vessels and events
harbor/logbook.toml             created, created_by
harbor/harbormaster.toml        the watch
harbor/accounts/<account>.toml  cap and pause of one account
harbor/workers/<account>/<host>/<session>.toml
harbor/convoys/<n>.toml
harbor/seals/<sha>.toml         one verify result for one exact commit
harbor/main.toml                (phase 2) the last main Harbor saw, and every move of it
harbor/imported/BOARD.md        (once) the hand-kept board, verbatim
harbor/imported/board.toml      (once) what the import took and left
```

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

**Reads.** Every command fetches first. The SessionStart line reads the last fetched tip without
the network and says so ("as of the last fetch").

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

### `harbor/seals/<sha>.toml`

```toml
schema = 1
kind = "vessel"                  # vessel | fix (2) | convoy (2)
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
level = "all"                    # (2) kind = convoy: the level the ok asked for
```

`harbor.py seal` runs the command itself on a clean tree and refuses to record if `HEAD` or the
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
| verifying → verifying | `convoy verify` *(2)* | the integrator | a run, green or red; fixes in between |
| verifying → sailed | `convoy sail` *(2)* | the integrator | green convoy seal on the exact head at the ok's level; `main` still the ok's base |
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
- **Errors:** `NOT_INTEGRATOR`, `VESSEL_MOVED`, `CONFLICT`, `MIGRATION_COLLISION`,
  `MIGRATION_ORDER`, `DEPENDENCY_OPEN` (stays waiting).

### `/harbor:convoy sail N --ok --level changed|all --reason TEXT` *(phase 2)*

- **Before:** the harbormaster with an unexpired watch; state ready; the convoy's `base` is
  `origin/main`; `ci.py health` says `main` is green where CI is reachable; nothing expected is
  missing (§4.7).
- **The level** (R19, from §4.6 mapped to Keelokit): `changed` (`pnpm verify` against the base)
  for docs, copy, screens and isolated modules; `all` for money, bookings, credits, quotas,
  notices, permissions, migrations, dependencies, `scripts/`, test config, any critical area, or
  vessels that meet in the same code (shared hotspot or critical area). In doubt, `all`. JOUNA's
  middle level ("verify plus the full suite of the widest package") has no Keelokit flag; Harbor
  maps it to `all`. **Needs your ok.**
- **Logbook:** `[ok]`, state verifying, event `ok`.
- **Errors:** `NOT_HARBORMASTER`, `WATCH_EXPIRED`, `NOT_READY`, `MAIN_MOVED`, `MAIN_RED`.

### `/harbor:convoy verify N` *(phase 2)*

- **Before:** the integrator; state verifying; `origin/main` is still the ok's base (else
  `MAIN_MOVED`: back to assemble); every commit on `convoy/<n>` after the ok's head is a fix with a
  green fix seal (`harbor.py seal --fix` = `pnpm verify --since <previous head>`, R7, §6.3).
- **Does:** `pnpm verify --preflight`, then `pnpm verify [--all] --keep-going` on the convoy head,
  in the background with a log (Keelokit's agent brief), event `verify-start` with the host first,
  because the verify lock and its state are local to one machine (§5.6).
- **Logbook:** a `kind = "convoy"` seal; `verify-pass` or `verify-fail` with the failed steps.
- **Errors:** `NOT_INTEGRATOR`, `MAIN_MOVED`, `UNSEALED_FIX`, `PREFLIGHT_FAILED`.

### `/harbor:convoy sail N` *(phase 2)*

- **Before:** the integrator; `[ok]` present; a green convoy seal for the exact head at the ok's
  level or above; `origin/main` is the ok's base, so the push is a fast-forward.
- **Does:** `git push origin <head>:main` from the machine that ran the verify, so Keelokit's
  pre-push seal recognises the commit and doesn't repeat the run. Rejected: `MAIN_MOVED`, back to
  assemble.
- **Logbook:** `[sail]`, state sailed, `main.toml`, event `sailed`; the next control records the CI.
- **Errors:** `NO_OK`, `NOT_SEALED`, `MAIN_MOVED`, `NOT_INTEGRATOR`.

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
`check --hook` is the SessionStart hook: never fails the session; prints one to three lines.

## The watch and its relief

One harbormaster at a time. Its heartbeat is `last_control`, written by every control; the watch
expires `watch_expiry_minutes` after it. Any active worker can take an expired watch, and the first
push wins because the replay rechecks the expiry (R20, §5.3). The harbormaster gives oks, records
the CI after a sail, notices loose pushes and lost workers; it never integrates unless it is also
an integrator. What the harbormaster does not see (a session's local verify lock, its
`.verify-status`) it learns only from logbook events (§5.6). JOUNA ran its coordinator on Opus
(§3.4); that this was intended is a **HIPÓTESIS**, so Harbor's default is Sonnet, with
`[harbor.models] harbormaster` to change it.

## When main moves with a convoy assembled

`main` moves for three reasons: another convoy sailed, a fix for a red `main` was pushed (the only
allowed push outside a convoy, §2.4), or a loose push (§6.9, an **INDICIO** of how `train/7`
died). Harbor never rebases a convoy:

- **assembling or waiting:** the next `assemble` merges `origin/main` into `convoy/<n>` and moves
  `base`.
- **ready or verifying:** the ok is void (its level was chosen for other contents); `assemble`
  merges `main`, the state returns to ready, and the harbormaster gives a new ok. `sail` refuses
  while `main` isn't the ok's base, and a rejected push says the same.
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

## Models and the first agent

The vessel's tier is Keelokit's (trivial, light, full), chosen by the vessel session's
`build-story`; Harbor records it when the skipper adds the vessel. The tier is not stored
anywhere machine-readable in Keelokit, so the skipper copies it from the vessel's report: an
**assumption** that the report is right, to replace with a recorded value when Keelokit has one.

| Tier | First agent | Model |
|---|---|---|
| trivial | builder | `[harbor.models] builder` |
| light | verifier (mode A: tests before code, R9) | `verifier` |
| full | verifier (mode A) | `verifier`; reviewer and breaker as Keelokit's `build-story` says for `integrity` |

Every `Agent` and `create_session` Harbor starts names its model from `[harbor.models]` (§3.3). The
defaults are the cheap case and the expensive one is the exception (R11, §3.11, §3.12). That the
model rule changed the practice is an **INDICIO** (§3.7: commit counts, not tokens).

## Assumptions to validate

| Assumption | Source | How it would be checked |
|---|---|---|
| Keelokit's key is `[landing] policy = "convoy"` and `build-story` stops at a pushed branch under it | the decision; Keelokit's change in progress | read Keelokit's change when it lands |
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
- **A future API over the logbook.** Missing: who would serve it. The schema above is the contract.

## Failure modes of the survey, and where Harbor answers

| § | Failure | Harbor |
|---|---|---|
| 6.1 | two green branches, red together | one convoy verify on the combination; fixes as sealed commits on `convoy/<n>` |
| 6.2 | the piece didn't run what broke; a fix voids the green | seal by exact hash; a new commit has no seal (R3) |
| 6.3 | chain of reds on resume | fix seals before rerunning (R7) |
| 6.4 | tests bound to date, zone or text | Keelokit's (time invariants, FLAKY-1); not Harbor's |
| 6.5 | migration timestamp collisions | migration check at assembly (R16) |
| 6.6 | generated artifacts and fixed totals in conflict | `[harbor.generated]`; totals without a decision |
| 6.7 | duplicated history from sibling branches | assumption above; a warning at `add` *(2)* |
| 6.8 | sessions cut by account limits | account pause, cap, handover with pushed head |
| 6.9 | a loose push kills a train branch | `main.toml` causes; ok void when `main` moves |
| 6.10 | `main` pushed with only Format run | push only with a green convoy seal at the ok's level; Keelokit's hook stays |
| 6.11 | process rules set and withdrawn in minutes | the rules live in Harbor's code and tests, versioned by release; not editable from the logbook |
| 6.12 | container resources and tools | Keelokit's `--preflight` before the convoy verify (R21) |
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
| R7 validate the fix commit before each verify resume | fix seals required by `convoy verify` | 2 |
| R8 risk level from the diff; unknown goes up; the agent can't lower it | Keelokit's `build-story` tier rules (escalate only); Harbor records the tier | delegated |
| R9 the first agent of N1/N2 is the test writer | tier → first agent (verifier mode A for light and full) | 2 (skills) |
| R10 roles enforced by tools | Harbor's agents have `tools:` lists (skipper without Write, harbormaster read-only). Keelokit's reviewer and breaker are read-only by tools; its verifier needs Write for tests, and weakened tests are caught by `doctor --scope` (VERIFY-2), not by tools. Bash in any list is not a sandbox | 1 (agents) |
| R11 model per role and level in project config, coordinator included; cheap defaults | `[harbor.models]`, Sonnet defaults, named on every launch | 1 (config), 2 (launches) |
| R12 concurrency cap tied to budget, staggered starts | per-account `max_sessions` and `paused_until`; staggering without a decision | 1 |
| R13 counter of review rounds, a third only with P0/P1 | dropped: Keelokit's `build-story` already stops after two rounds, and the case behind it is a **HIPÓTESIS** (§3.14) | — |
| R14 hotspots in config, branches serialized, warn on shared declarations | `[harbor.hotspots]`, `HOTSPOT_HELD` at `add`; the early warning from `touches` | 1, 2 (warning) |
| R15 no parallel convoys that depend on each other from one base; order and re-base | `depends_on`, waiting until the dependency sails, then merge `main` | 1 (field), 2 |
| R16 reserve or renumber migration timestamps; fail on a shared one | the check at assembly fails and names the rename; renumbering without a decision | 2 |
| R17 generated artifacts and fixed totals as known conflicts | `[harbor.generated]` regenerated at assembly; totals without a decision | 2 |
| R18 detect `main` moving under an assembled convoy; record a loose push | `status` shows it (1); `main.toml`, ok void, re-assembly (2) | 1, 2 |
| R19 choose the convoy verify by a risk table; the reason with the ok | `[ok] level` and `reason`, the table under `sail --ok` | 2 |
| R20 heartbeat with expiry, first commit wins | the watch: `last_control`, `expires`, replay on rejection | 2 (the write rule is in 1) |
| R21 a preflight that fails on missing tools or an unfit machine | Keelokit's `verify --preflight` (VER-1) before the convoy verify | delegated |
| R22 structured handover on a budget cut; `wip/*` outside trains | `worker end` with `[handover]`, head checked pushed; `wip/*` dropped (vessels never touch `main`) | 1 |
| R23 structured timestamps for every step | `events` per convoy, seals with start, end and duration | 1 |
| R24 coherence of process docs with the tools | dropped for Harbor: its state is generated, so it can't describe a tool that changed; prose docs are Keelokit's doctor's (vague phrases) | — |
| R25 the CI trigger as a project policy (`landing: train \| direct`) | Keelokit's `[landing] policy`; Harbor runs only under `convoy` | 1 (read) |
| R26 trains that change the API declare the consuming app version and who deploys | without a decision (see above) | — |
