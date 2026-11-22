# Phase 6: the ledger (designed, not built)

Keelokit's ledger (`docs/ledger.md` and the `LEDGER` epic in `leosimini/keelokit`) is one derived record
of what is being done and what was done, computed by `.keelokit/bin/ledger.py` from facts in git. Harbor
keeps owning what is under way (convoys, vessels, workers, the watch); the ledger reads `harbor/log` and
never writes it. This phase is what Harbor adds so the two fit. Nothing here is written yet.

Rules that hold for the whole phase:
- **Feature detection.** Every new behaviour runs only when the project has `.keelokit/bin/ledger.py` and
  it answers `ledger.py --json` with `"schema": 1` (Keelokit 0.16.0 or later). Without it, Harbor behaves
  exactly as 0.5.
- **The ledger is project code**, like `vessel_verify`: Harbor runs `python3 .keelokit/bin/ledger.py …` from
  the session's checkout, with a timeout, and reads its JSON. Harbor copies none of its code.
- **The logbook keeps `schema = 1`.** The only new key, `story` on a worker, is optional; absent keys are
  omitted, as today.
- **Tests** go in `tests/test_phase6.py`; `scripts/test-with-keelokit.sh` runs against Keelokit 0.16.0.
- Ships as **Harbor 0.6.0**, with a CHANGELOG entry and both READMEs updated.

## HRB-1 · `Convoy:` on the merge, `NO_STORY` in `convoy add`, the story from the ledger

**Depends on:** Keelokit 0.16.0.
**Touches:** `lib/harbor.py`, `tests/test_phase6.py`, `scripts/test-with-keelokit.sh`, `docs/design.md`
("What Harbor takes from Keelokit": rows for `ledger.py attribution` and `--json`; this phase's section),
`skills/convoy/SKILL.md`, `README.md`, `README.es.md`, `CHANGELOG.md`.

- `merge()` in `convoy assemble`: the message of each vessel's merge into `convoy/<n>` ends with the
  trailer `Convoy: <n>`. The vessels' own commits, with their `Story:`/`Part-of:` trailers, reach `main`
  intact through the merge, as today.
- `convoy add N BRANCH`: before recording the vessel, run `ledger.py attribution <seal_base>..<head>
  --json`. If any non-merge commit is unattributed, refuse with `harbor: NO_STORY: <short sha> …` (exit 1)
  and print the ledger's suggestion. A Keelokit without the ledger: skip, as 0.5.
- A vessel's `story` comes from the ledger (`attribution --json` returns the stories of the range), not
  from Harbor reading `Story:` trailers itself; `--story` still overrides. Older Keelokit: today's reading.

Scenarios: [S1] the merge commit of a convoy carries `Convoy: N`; [S2] a vessel with an unattributed commit
is refused with `NO_STORY`; [S3] a project on Keelokit 0.15 behaves as Harbor 0.5; [S4] a vessel on branch
`claude/xyz` whose commits carry `Part-of: AUTH-001` gets `story = "AUTH-001"`.

## HRB-2 · Taking a story is a lock in the logbook

**Depends on:** HRB-1.
**Touches:** `lib/harbor.py`, `tests/test_phase6.py`, `docs/design.md` (schemas of `workers/` and
`wanted/`, the commands list), `skills/dispatch/SKILL.md`, `skills/convoy/SKILL.md`.

- New command `harbor.py story take ID [--worker W]`, one logbook transaction: write `story = "ID"` on the
  calling worker. Refuse with `STORY_TAKEN` (naming the holder) when another worker in state `active`
  holds it, or with `STORY_ON_TRUNK` when `ledger.py show ID --json` says it is `on-trunk` or later. Two
  takes at once: the rejected push replays and the second finds it held (first commit wins, as the watch).
  `harbor.py story release ID` clears it; a worker that ends or is marked `lost` releases its story.
- `worker register --story ID` does the same at registration.
- `wanted take`: refuse a vessel request whose story is taken or on the trunk.
- `wanted prompt`: the prompt for a vessel starts with `python3 .keelokit/bin/ledger.py take <ID>` (which,
  with LEDGER-013, calls `harbor.py story take`).
- `LOGBOOK.md` shows each worker's story.

Scenarios: [S1] two sessions take the same story at once: one wins, the other gets `STORY_TAKEN` with the
holder; [S2] a worker marked `lost` releases its story; [S3] a request for a story already on the trunk is
refused at `wanted take`; [S4] the dispatcher's prompt for a vessel starts with `ledger.py take`.

## HRB-3 · The ledger in the harbormaster's round and in the ok

**Depends on:** HRB-2.
**Touches:** `lib/harbor.py`, `tests/test_phase6.py`, `skills/harbormaster/SKILL.md`, `docs/design.md`.

- `harbormaster control` runs `ledger.py check --json` and adds its error-level differences to the round
  (at most 5 lines, "(+N more)").
- `convoy sail N --ok` refuses with `LEDGER_DIFF` when a vessel's story has an error difference: already
  on the trunk (`DONE_TWICE`), unknown, or unattributed commits in the vessel.
- A loose move of `main` (`cause = "loose"` in `harbor/main.toml`) is reported with the stories that entered
  and the unattributed commits, from `ledger.py --json`.
- Without the ledger, the round says "ledger: not available" once and goes on.

Scenarios: [S1] a difference shows in the round; [S2] the ok for a convoy with a vessel whose story is
already on the trunk is refused with `LEDGER_DIFF`; [S3] a loose move lists what entered; [S4] without
`ledger.py` the round says so and goes on.

## How to launch

After Keelokit 0.16.0 is released, one session in this repo per item, in order:

```
Read docs/ledger-phase6.md and docs/design.md, then build HRB-1 (and only HRB-1): tests in tests/test_phase6.py first, then the code, then docs and CHANGELOG. Verify with python3 -m unittest discover -s tests and scripts/test-with-keelokit.sh.
```

Then the same for HRB-2 and HRB-3. When all three are on `main` and Keelokit's LEDGER-013 and LEDGER-014
are done, the phase's gate (a convoy carrying a swarm delivery lands and `ledger.py show` says each piece's
story, who made it and which convoy sailed it) opens the release of Harbor 0.6.0 (`docs/releasing.md`),
when Leo asks for it.
