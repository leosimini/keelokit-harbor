# Phase 7: lessons from the JOUNA fleet (designed, not built)

On the night of 2026-11-22 the JOUNA project ran about 40 sessions on two accounts and three trains by
hand. Its coordinator wrote down what it learned, with measured impact (the Claude doc *Aprendizajes de
coordinación multiagente (JOUNA, noviembre 2026)*). Keelokit's `docs/fleet-lessons.md` maps every lesson;
most of what JOUNA paid for is already Harbor's design (seals reused, scoped convoy verify, narrowed
reruns after a fix, `convoy defer`, messages between accounts with a watcher, fresh reads), and JOUNA
lacked it because it ran trains by hand. This phase takes the five that are not here yet.

Rules for the whole phase: nothing here needs Keelokit's ledger, except where it says so; the logbook
keeps `schema = 1` (every new key is optional); tests go in `tests/test_phase7.py`; it ships with or after
Harbor 0.6.0, when Leo asks for a release.

## HRB-4 · The ok goes straight to `all` when the scoped plan already covers it

*Built: `tests/test_phase7.py`; how it works is rule 6 of "Verifying without a bottleneck" in
[design.md](design.md#verifying-without-a-bottleneck).*

JOUNA ran a piece-scoped verify of each train's union and then `--all`: about two hours a train for nothing,
because on a wide train the scoped plan is the whole suite and the second run repeats the first.

- `convoy sail --ok` asks Keelokit for both plans (`verify_tools.py plan --base <main>` and `plan --all`).
  When the scoped plan has every step of `--all` and at least `[harbor] all_when_covered` (default 0.9)
  of its packages, the ok's level is `all` and the reason says so; the harbormaster can still pass
  `--level`.
- A convoy never runs a scoped verify and then `--all` on the same head: `convoy verify` at level `all`
  reuses nothing partial and runs once; at `changed` it runs once. A request for the other level on a head
  that already has a whole green run at a covering level is refused (`ALREADY_COVERED`).

Scenarios: [S1] a convoy whose scoped plan equals `--all` gets level `all` from the ok, with the reason; [S2]
a narrow convoy keeps `changed`; [S3] `--level changed` from the harbormaster wins; [S4] asking for `all`
after a green `all` on the same head is `ALREADY_COVERED`.

## HRB-5 · A mechanical preflight before the push to main

*Built: `tests/test_phase7.py`; how it works is the preflight of `/harbor:convoy sail N` in
[design.md](design.md#harborconvoy-sail-n-phase-2).*

JOUNA's coordinator checked every train before its push to main, from a backup branch, in about a minute:
parents, author, commit count, `wip/` branches and the expected diff. It never found a problem, and cost a
minute. Harbor makes it a fixed, mechanical part of `convoy sail`:

- the convoy head's history from `main_before` is exactly the vessels' commits plus one merge per vessel
  and the integrator's recorded fix commits (no stray commit);
- every author is a real identity (not a placeholder; Keelokit's pre-push already refuses those);
- no commit reachable from the head is the tip of an unproven `wip/` branch
  (`verify_tools.py wip-inside`);
- the head's diff against `main_before` equals the union of the vessels' diffs, except for files changed by
  the recorded fix commits and the declared generated files.

A failure stops the sail with `PREFLIGHT_FAILED` and the line that failed; the event goes to the logbook.

Scenarios: [S1] a clean convoy passes in under a minute; [S2] a stray commit stops it; [S3] a `wip/` tip in
the history stops it; [S4] a file changed outside the vessels and the fixes stops it, naming the file.

## HRB-6 · A seam report at assemble

All of JOUNA's train reds were seams between pieces or the environment (~9 seams, ~12 environment), in a
few repeated shapes: a test asserting a route closed while another piece opened it; two pieces adding
their own navigation to one screen; one exported name defined by two pieces; one style rule edited by two.

`convoy assemble` writes a seam report into the convoy's events, mechanically, from the vessels' diffs
against the base:
- files changed by two or more vessels;
- exported names (`export const|function|class|type|interface <Name>` in TypeScript, `def`/`class` at module
  level in Python) defined or changed by two or more vessels;
- CSS selectors and design-token names changed by two or more vessels;
- route paths added by one vessel that appear in another vessel's tests.

The skipper reads each seam and records `seam-read` with one line (fine, fixed in a commit, or a question);
`assemble` reaches `ready` only when every seam has one. This turns JOUNA's dedicated conductor who "reads
the joined result and writes every seam into the playbook" into a list nobody can skip.

Scenarios: [S1] two vessels changing one file produce a seam; [S2] one exported name in two vessels
produces a seam; [S3] a route added by one vessel and asserted closed in another's test produces a seam;
[S4] `ready` waits until every seam is read.

## HRB-7 · A cutoff time for a convoy

JOUNA's hour cutoffs with a clear rule of what is mandatory kept nine finished pieces from waiting on one.
Harbor has `convoy defer` by hand.

- `convoy new --cutoff <UTC time>`; `convoy add --optional` marks a vessel optional (the `expected` list
  stays the mandatory one).
- After the cutoff, `convoy assemble` defers every optional vessel not yet delivered to the next convoy by
  itself (event `deferred-at-cutoff`); a mandatory one missing keeps the convoy `waiting`, and the round
  reports it.

Scenarios: [S1] after the cutoff an optional late vessel is deferred automatically; [S2] a mandatory late
vessel keeps the convoy waiting and shows in the round; [S3] before the cutoff nothing is deferred.

## HRB-8 · A round every 30 minutes, scheduled with commands, not state

JOUNA's coordination rounds every 25–30 minutes, scheduled with a self-contained prompt, survived context
compaction and a night unattended.

- `[harbor] control_every_minutes` defaults to 30 (was 90; the expiry of the watch stays 180).
- The prompt the harbormaster schedules for its control holds the commands to run (`harbor.py
  harbormaster control`, and `ledger.py` when the project has it), never a pasted state, so a compacted or
  new session gets the facts fresh.

Scenarios: [S1] a new watch schedules its control every 30 minutes by default; [S2] the scheduled prompt
has the commands and no state text.

## How to launch

HRB-4 and HRB-5 do not need the ledger and can go with HRB-1; HRB-6, 7 and 8 after. One session per item:

```
Read docs/lessons-phase7.md and docs/design.md, then build HRB-4 (and only HRB-4): tests in tests/test_phase7.py first, then the code, then docs and CHANGELOG. Verify with python3 -m unittest discover -s tests and scripts/test-with-keelokit.sh.
```
