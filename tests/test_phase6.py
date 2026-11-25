"""harbor.py, phase 6: Keelokit's ledger (docs/ledger-phase6.md).
HRB-1: with a ledger that answers `ledger.py --json` with schema 1, each vessel's merge into convoy/<n> ends with
the trailer `Convoy: <n>`; `convoy add` asks `ledger.py attribution <seal_base>..<head> --json` and refuses a vessel
with an unattributed non-merge commit (`NO_STORY`); the vessel's story comes from the ledger. Without that ledger,
Harbor behaves as 0.5. A stand-in for Keelokit's ledger.py reads the trailers the way the real one does.
Also the HRB-7 nit: a vessel carrying several stories delivers each of them.
HRB-2: taking a story is a lock in the logbook: `story take|release`, `worker register --story`, `wanted take`'s
refusals and the vessel prompt that starts with `ledger.py take`.
HRB-3: the ledger in the harbormaster's round (`ledger.py check --json`'s error-level differences, at most 5 lines;
a loose move of main with the stories that entered and its unattributed commits) and in the ok (`convoy sail N --ok`
refuses LEDGER_DIFF, and fails closed with LEDGER_UNAVAILABLE when a schema-1 ledger can't answer).
Every git subprocess here runs with no GIT_* variable from the caller (a hook or a worktree exports GIT_DIR).
Run: python3 -m unittest discover -s tests"""
import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import sys
import threading
import tomllib
import unittest
from unittest import mock

from test_harbor import GIT_ENV, HARBOR, NOW, harbor, load_module, ok, sh
from test_phase2 import STATUS, Phase2

# Keelokit's ledger.py, as far as Harbor sees it.
# `--json`: HARBOR_FAKE_LEDGER = the JSON value of "schema" (default 1), or bad | sleep | exit2 | binary (not UTF-8).
#   Exits 1, as the real one does when there are differences: an answer with schema 1 counts whatever the exit.
# `attribution A..B --json`: the contract with Keelokit's ledger.py attribution (LEDGER-013, docs/design.md), from
#   Story:/Part-of:/No-story: trailers; exit 0 whenever it answered. A merge is reported unattributed unless it has
#   its own trailer (the worst a ledger may say: Harbor ignores merges itself). HARBOR_FAKE_ATTRIBUTION = usage
#   (Keelokit 0.16.0: no such command, usage and exit 2) | exit3 (history incomplete) | bad | sleep
#   | no-attributed (`attributed` is not a boolean) | short (abbreviated shas).
#   HARBOR_FAKE_STORIES = {"ID": "state" | {"state": ..., "commit": ...}, ...}: the stories `--json` lists (default
#   none); HARBOR_FAKE_STORIES_RAW replaces the whole list (wrong types). `--json` carries `trunk_sha`, origin/main
#   here (HARBOR_FAKE_TRUNK_SHA overrides it). HARBOR_FAKE_LEDGER=huge prints a 2 MB answer.
# `check --json` (Keelokit 0.16.0's shape: {"schema": 1, "diffs": [{"level", "code", "detail"}]}, exit 1 on an
#   error-level one): HARBOR_FAKE_CHECK = the JSON list of diffs (default []), any other JSON value printed as is,
#   or sleep | bad | exit2 | binary. HARBOR_FAKE_CHECK_HOOK: a shell command run before it answers (a race).
#   To that list it adds what Keelokit's check finds in origin/main's history by its rules (computed_diffs:
#   DONE_TWICE, UNKNOWN_STORY; from HARBOR_FAKE_SINCE on UNATTRIBUTED, BAD_CATEGORY, STORY_NO_BODY). `check --ci
#   --json` answers the same.
# `show ID --json`: Keelokit 0.16.0 has no such command (usage, exit 2); HARBOR_FAKE_SHOW = {"ID": "state", ...}
#   makes it answer {"schema": 1, "id", "state"} (exit 1 for an id it doesn't list).
# `check ... --rules-ref REV` (Keelokit LEDGER-013): only with HARBOR_FAKE_RULES_REF set (else usage, exit 2, as
#   0.16.0). With it the usage (`check --help`) names --rules-ref, an unresolved REV is exit 2, and the rule files
#   below are read from REV's committed tree; without --rules-ref, from the checkout (0.16.0 reads them from the
#   trunk's committed tree, which in the judge's landed clone is the convoy's). HARBOR_FAKE_RULES_REF = broken: the
#   usage names it but every --rules-ref run is exit 2; = landed-exit2: exit 2 when REV is not HEAD (the landed
#   clone only); = help-sleep: `check --help` never answers.
#   Rule files: backlog/ledger-corrections.toml (`commit = "<sha>"` lines attribute that commit) and
#   .keelokit/critical.toml (`path = "<prefix>"` lines: from HARBOR_FAKE_SINCE on, a commit touching one with no
#   `Reviewed-by:` trailer is the error CRITICAL_UNREVIEWED).
# Every call is logged to HARBOR_FAKE_LEDGER_LOG.
FAKE_LEDGER = """\
import json, os, re, subprocess, sys, time
if os.environ.get("HARBOR_FAKE_LEDGER_LOG"):
    with open(os.environ["HARBOR_FAKE_LEDGER_LOG"], "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\\n")
def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout
RULES_REF_MODE = os.environ.get("HARBOR_FAKE_RULES_REF", "")
rules_ref = None
if sys.argv[1:2] == ["check"] and RULES_REF_MODE:
    if sys.argv[2:] == ["--help"]:
        if RULES_REF_MODE == "help-sleep":
            time.sleep(30)
        print("usage: ledger.py check [--ci] [--json] [--rules-ref REV]", file=sys.stderr)
        sys.exit(2)
    if "--rules-ref" in sys.argv:
        at = sys.argv.index("--rules-ref")
        if at + 1 >= len(sys.argv) or sys.argv[at + 1].startswith("-"):
            print("usage: ledger.py ...", file=sys.stderr)
            sys.exit(2)
        rules_ref = sys.argv[at + 1]
        del sys.argv[at:at + 2]
        resolved = subprocess.run(["git", "rev-parse", "--verify", "-q", rules_ref + "^{commit}"],
                                  capture_output=True, text=True).stdout.strip()
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if not resolved or RULES_REF_MODE == "broken" or (RULES_REF_MODE == "landed-exit2" and resolved != head):
            print(f"Keelokit: check: --rules-ref {rules_ref!r} does not resolve to a commit here", file=sys.stderr)
            sys.exit(2)
def rule_file(path):
    if rules_ref is not None:
        res = subprocess.run(["git", "show", f"{rules_ref}:{path}"], capture_output=True, text=True)
        return res.stdout if res.returncode == 0 else ""
    try:
        return open(path).read()
    except OSError:
        return ""
def rule_values(path, key):
    return re.findall(r'^\\s*' + key + r'\\s*=\\s*"([^"]*)"', rule_file(path), re.M)
if sys.argv[1:] == ["--json"]:
    mode = os.environ.get("HARBOR_FAKE_LEDGER", "1")
    if mode == "sleep":
        time.sleep(30)
    if mode == "bad":
        print('{"schema": 1, "stories": [')
        sys.exit(0)
    if mode == "exit2":
        print("Keelokit: no trunk", file=sys.stderr)
        sys.exit(2)
    if mode == "binary":
        sys.stdout.buffer.write(b'{"schema": 1, "x": "' + bytes([255, 254]) + b'"}')
        sys.exit(0)
    if mode == "huge":
        sys.stdout.write('{"schema": 1, "pad": "' + "x" * 2_000_000 + '"}')
        sys.exit(0)
    stories = [{"id": k, **(v if isinstance(v, dict) else {"state": v})}
               for k, v in json.loads(os.environ.get("HARBOR_FAKE_STORIES") or "{}").items()]
    trunk = subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/remotes/origin/main^{commit}"],
                           capture_output=True, text=True).stdout.strip()
    trunk = os.environ.get("HARBOR_FAKE_TRUNK_SHA", trunk)
    stories_v = json.loads(os.environ["HARBOR_FAKE_STORIES_RAW"]) if os.environ.get("HARBOR_FAKE_STORIES_RAW") else stories
    print(json.dumps({"schema": json.loads(mode), "trunk": "main", "trunk_sha": trunk, "stories": stories_v,
                      "diffs": [{"level": "warning"}]}))
    sys.exit(1)
def computed_diffs():
    # What Keelokit's check finds in origin/main's history, by its rules: DONE_TWICE (a warning) for a known story
    # whose Story: commits arrived in more than one first-parent commit; UNKNOWN_STORY for an id no story has; from
    # HARBOR_FAKE_SINCE on, UNATTRIBUTED, BAD_CATEGORY and STORY_NO_BODY (errors: enforce = "block").
    trunk = subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/remotes/origin/main^{commit}"],
                           capture_output=True, text=True).stdout.strip()
    if not trunk:
        return []
    known = set(json.loads(os.environ.get("HARBOR_FAKE_STORIES") or "{}"))
    def tr(sha, key):
        out = git("log", "-1", f"--format=%(trailers:key={key},valueonly,separator=%x2C)", sha)
        return [v.strip() for v in out.replace("\\n", ",").split(",") if v.strip()]
    def parents(sha):
        return git("rev-list", "--parents", "-n", "1", sha).split()[1:]
    out, seen = [], {}
    for f in reversed(git("rev-list", "--first-parent", trunk).split()):
        ps = parents(f)
        for c in ([f] if len(ps) < 2 else git("rev-list", f, f"^{ps[0]}").split()):
            for sid in tr(c, "Story"):
                if sid in known:
                    seen.setdefault(sid, {}).setdefault(f, c)
    out += [{"level": "warning", "code": "DONE_TWICE",
             "detail": f"{sid}: Story: commits {', '.join(c[:9] for c in found.values())} arrived separately"}
            for sid, found in sorted(seen.items()) if len(found) > 1]
    since = os.environ.get("HARBOR_FAKE_SINCE", "")
    rng = git("rev-list", trunk, *([f"^{since}"] if since else [])).split()
    subject = lambda c: git("log", "-1", "--format=%s", c).strip()[:80]
    for c in rng:
        unknown = sorted({i for i in tr(c, "Story") + tr(c, "Part-of") if i not in known})
        if unknown:
            out.append({"level": "error", "code": "UNKNOWN_STORY",
                        "detail": f"{c[:9]} {subject(c)!r}: names {', '.join(unknown)}, which no story file of the trunk has"})
    if not since:
        return out
    level = "warning" if os.environ.get("HARBOR_FAKE_WARN") else "error"
    has = lambda c: bool(tr(c, "Story") or tr(c, "Part-of") or tr(c, "No-story"))
    covered = set()
    for c in rng:
        ps = parents(c)
        if len(ps) > 1 and has(c):
            covered |= set(git("rev-list", c, f"^{ps[0]}").split())
    corrected = rule_values("backlog/ledger-corrections.toml", "commit")
    covered |= {c for c in rng if any(x and c.startswith(x) for x in corrected)}
    loose = {c for c in rng if len(parents(c)) < 2 and not has(c) and c not in covered}
    critical = [x for x in rule_values(".keelokit/critical.toml", "path") if x]
    for c in rng:
        if len(parents(c)) < 2 and critical and not tr(c, "Reviewed-by"):
            touched = git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", c).split()
            hit = sorted({x for x in critical for f in touched if f.startswith(x)})
            if hit:
                out.append({"level": "error", "code": "CRITICAL_UNREVIEWED",
                            "detail": f"{c[:9]} {subject(c)!r}: touches {', '.join(hit)} with no Reviewed-by:"})
    for c in rng:
        ps = parents(c)
        if c in loose or (len(ps) > 1 and not has(c) and set(git("rev-list", c, f"^{ps[0]}").split()) & loose):
            out.append({"level": "error", "code": "UNATTRIBUTED",
                        "detail": f"{c[:9]} {subject(c)!r}: no Story:, Part-of: or No-story:"})
        for v in tr(c, "No-story"):
            cat = re.split(r"[\\s:,-]", v.strip(), maxsplit=1)[0].strip()
            if cat not in ("harness", "docs", "release", "deps", "ci"):
                out.append({"level": level, "code": "BAD_CATEGORY", "detail": f"{c[:9]} {subject(c)!r}: No-story: {v!r}"})
        if tr(c, "Story"):
            paras = [p for p in re.split(r"\\n[ \\t]*\\n", git("log", "-1", "--format=%B", c).strip()) if p.strip()]
            if len(paras) <= 2:
                out.append({"level": level, "code": "STORY_NO_BODY",
                            "detail": f"{c[:9]} {subject(c)!r}: closes {', '.join(tr(c, 'Story'))} with no body"})
    return out
if sys.argv[1:2] == ["check"] and sys.argv[-1:] == ["--json"] and set(sys.argv[2:-1]) <= {"--ci"} and len(sys.argv) <= 4:
    if os.environ.get("HARBOR_FAKE_CHECK_HOOK"):
        subprocess.run(os.environ["HARBOR_FAKE_CHECK_HOOK"], shell=True, check=True, stdout=subprocess.DEVNULL)
    mode = os.environ.get("HARBOR_FAKE_CHECK", "[]")
    if mode == "sleep":
        time.sleep(30)
    if mode == "bad":
        print('{"schema": 1, "diffs": [')
        sys.exit(1)
    if mode == "exit2":
        print("usage: ledger.py ...", file=sys.stderr)
        sys.exit(2)
    if mode == "binary":
        sys.stdout.buffer.write(b'{"schema": 1, "diffs": [], "x": "' + bytes([255]) + b'"}')
        sys.exit(0)
    diffs = json.loads(mode)
    if isinstance(diffs, list):
        diffs = diffs + computed_diffs()
    print(json.dumps(diffs if not isinstance(diffs, list) else {"schema": 1, "diffs": diffs}, indent=1))
    sys.exit(1 if isinstance(diffs, list) and any(isinstance(d, dict) and d.get("level") == "error" for d in diffs)
             else 0)
if sys.argv[1:2] == ["show"] and len(sys.argv) == 4 and sys.argv[3] == "--json" and os.environ.get("HARBOR_FAKE_SHOW"):
    states = json.loads(os.environ["HARBOR_FAKE_SHOW"])
    if sys.argv[2] not in states:
        print("Keelokit: no such story", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"schema": 1, "id": sys.argv[2], "state": states[sys.argv[2]]}))
    sys.exit(0)
if sys.argv[1:2] == ["attribution"] and len(sys.argv) == 4 and sys.argv[3] == "--json":
    mode = os.environ.get("HARBOR_FAKE_ATTRIBUTION", "")
    if mode == "usage":
        print("usage: ledger.py ...", file=sys.stderr)
        sys.exit(2)
    if mode == "sleep":
        time.sleep(30)
    if mode == "bad":
        print("not json")
        sys.exit(0)
    if mode == "exit3":
        print("Keelokit: the history is incomplete", file=sys.stderr)
        sys.exit(3)
    commits, stories = [], set()
    for sha in git("rev-list", "--reverse", sys.argv[2]).split():
        parents = git("rev-list", "--parents", "-n", "1", sha).split()[1:]
        def values(key):
            out = git("log", "-1", f"--format=%(trailers:key={key},valueonly,separator=%x2C)", sha)
            return [v.strip() for v in out.split(",") if v.strip()]
        story, part_of, no_story = values("Story"), values("Part-of"), (values("No-story") or [None])[0]
        stories.update(story + part_of)
        attributed = bool(story or part_of or no_story)
        commits.append({"sha": sha, "subject": git("log", "-1", "--format=%s", sha).strip(), "story": story,
                        "part_of": part_of, "no_story": no_story, "merge": len(parents) > 1, "attributed": attributed,
                        "via": "own" if attributed else None})
    if mode == "no-attributed":  # another shape: the commits without a boolean `attributed`
        for c in commits:
            c["attributed"] = "yes" if c.pop("attributed") else None
    if mode == "short":  # abbreviated shas
        for c in commits:
            c["sha"] = c["sha"][:10]
    unattributed = [c["sha"] for c in commits if c["attributed"] is not True]
    print(json.dumps({"schema": 1, "range": sys.argv[2], "ok": not [c for c in commits if not c["merge"] and c["sha"]
                      in unattributed], "commits": commits, "unattributed": unattributed, "stories": sorted(stories)}))
    sys.exit(0)
print("usage: ledger.py ...", file=sys.stderr)
sys.exit(2)
"""


def convoy_trailers(repo, sha: str) -> list[str]:
    out = sh(repo, "git", "log", "-1", "--format=%(trailers:key=Convoy,valueonly)", sha)
    return [l.strip() for l in out.splitlines() if l.strip()]


class Phase6(Phase2):
    """Phase 2's project, with Keelokit's ledger (0.16.0) committed on main."""
    ledger = True

    def setUp(self):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()
        self.ledger_log = self.tmp / "ledger.log"
        os.environ["HARBOR_FAKE_LEDGER_LOG"] = str(self.ledger_log)
        if self.ledger:
            tool = self.a / ".keelokit/bin/ledger.py"
            tool.parent.mkdir(parents=True, exist_ok=True)
            tool.write_text(FAKE_LEDGER)
            sh(self.a, "git", "add", "-A")
            sh(self.a, "git", "commit", "--quiet", "-m", "keelokit's ledger", "-m", "No-story: harness")
            sh(self.a, "git", "push", "--quiet", "origin", "main")

    def ledger_calls(self) -> list[list[str]]:
        return [json.loads(l) for l in self.ledger_log.read_text().splitlines()] if self.ledger_log.exists() else []

    def branch(self, name: str, *commits: tuple[str, str], base: str = "origin/main") -> str:
        """A pushed branch from `base` with one commit per (path, message)."""
        sh(self.a, "git", "fetch", "--quiet", "origin", "main")
        sh(self.a, "git", "checkout", "--quiet", "-B", name, base)
        for path, message in commits:
            f = self.a / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"{name} {message}\n")
            sh(self.a, "git", "add", "-A")
            sh(self.a, "git", "commit", "--quiet", "-m", message)
        sh(self.a, "git", "push", "--quiet", "-u", "origin", name)
        return sh(self.a, "git", "rev-parse", "HEAD")

    def vessel_merges(self, n: int = 1) -> dict[str, str]:
        """The merge commits on convoy/<n>'s first-parent chain since main, by the vessel branch they name."""
        out = sh(self.repo.remote, "git", "log", "--first-parent", "--merges", "--format=%H %s", f"main..convoy/{n}")
        return {line.split(": merge ", 1)[1].split("@")[0]: line.split()[0]
                for line in out.splitlines() if ": merge " in line and f": merge main" not in line}


class TestHRB1(Phase6):
    def test_HRB_1_S1_the_merge_commit_of_a_convoy_carries_Convoy_N(self):
        os.environ["HARBOR_FAKE_STORIES"] = json.dumps({"QA-1": "in-progress", "QA-3": "in-progress"})  # the ok asks (HRB-3)
        a, b = self.two_vessels_ready()
        merges = self.vessel_merges()
        self.assertEqual(sorted(merges), ["claude/qa-1", "claude/qa-3"],
                         "each vessel has its own merge, the first one too (never a fast-forward)")
        for branch, sha in merges.items():
            self.assertEqual(convoy_trailers(self.repo.remote, sha), ["1"], branch)
            message = sh(self.repo.remote, "git", "log", "-1", "--format=%B", sha)
            self.assertEqual(message.splitlines()[-1], "Convoy: 1", "the message ends with the trailer")
        for head, story in ((a, "QA-1"), (b, "QA-3")):
            self.assertEqual(sh(self.repo.remote, "git", "log", "-1", "--format=%(trailers:key=Story,valueonly)", head),
                             story, "the vessel's own commit is untouched")
        ok(self.ok_changed())
        ok(harbor(self.a, "convoy", "verify", "1"))
        ok(harbor(self.a, "convoy", "sail", "1"))
        for sha in merges.values():
            sh(self.repo.remote, "git", "merge-base", "--is-ancestor", sha, "main")
        for head in (a, b):
            sh(self.repo.remote, "git", "merge-base", "--is-ancestor", head, "main")

    def test_HRB_1_S2_a_vessel_with_an_unattributed_commit_is_refused_with_NO_STORY(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1"))
        self.branch("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nPart-of: QA-1"), ("apps/web/b.ts", "fix: forgot one"))
        bad = sh(self.a, "git", "rev-parse", "HEAD")
        ok(harbor(self.a, "seal"))
        res = harbor(self.a, "convoy", "add", "1", "claude/qa-1")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(f"harbor: NO_STORY: {bad[:9]}", res.stderr)
        self.assertIn("fix: forgot one", res.stderr)
        self.assertIn(f"harbor: ledger: {bad[:9]}: add `Part-of: <ID>`, `Story: <ID>` or `No-story: <category>`",
                      res.stderr, "what to do with it")
        self.assertEqual(self.convoy()["vessels"], [], "nothing recorded")
        seal = self.repo.log_toml(f"harbor/runs/{bad}.toml")
        self.assertIn(["attribution", f"{seal['base']}..{bad}", "--json"], self.ledger_calls())

    def test_HRB_1_S4_a_vessel_whose_commits_carry_Part_of_gets_that_story(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "AUTH-001"))
        self.branch("claude/xyz", ("apps/web/a.ts", "feat: login form\n\nPart-of: AUTH-001"),
                    ("apps/web/b.ts", "feat: login api\n\nPart-of: AUTH-001"))
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/xyz"))
        self.assertEqual(self.convoy()["vessels"][0]["story"], "AUTH-001")
        self.assertEqual(ok(harbor(self.a, "convoy", "assemble", "1")).count("waiting"), 0)
        self.assertEqual(self.convoy()["state"], "ready")


class TestHRB1S3(Phase6):
    """[S3] A project on Keelokit 0.15 behaves as Harbor 0.5: here, no ledger.py at all."""
    ledger = False

    def test_HRB_1_S3_without_the_ledger_harbor_behaves_as_0_5(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.branch("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nStory: QA-1"), ("apps/web/b.ts", "wip, no trailer"))
        ok(harbor(self.a, "seal"))
        out = ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        self.assertNotIn("ledger", out)
        self.assertEqual(self.convoy()["vessels"][0]["story"], "QA-1", "0.5's reading of the Story: trailers")
        b = self.deliver(1, "claude/qa-3", "apps/web/c.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        log = sh(self.repo.remote, "git", "log", "--format=%B", "main..convoy/1")
        self.assertNotIn("Convoy:", log)
        merges = self.vessel_merges()
        self.assertEqual(list(merges), ["claude/qa-3"], "the first vessel fast-forwards, as in 0.5")
        self.assertEqual(sh(self.repo.remote, "git", "log", "-1", "--format=%B", merges["claude/qa-3"]),
                         f"convoy 1: merge claude/qa-3@{b[:9]}")
        self.assertEqual(self.ledger_calls(), [])


class Without(Phase6):
    """A ledger.py whose `--json` is not schema 1 is no ledger for Harbor: 0.5 exactly."""

    def assert_as_0_5(self, env: dict):
        os.environ.update(env)
        ok(harbor(self.a, "convoy", "new"))
        self.branch("claude/qa-1", ("apps/web/a.ts", "no trailer at all"))
        ok(harbor(self.a, "seal"))
        out = ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        self.assertNotIn("ledger", out)
        self.assertNotIn("story", self.convoy()["vessels"][0])
        self.deliver(1, "claude/qa-3", "apps/web/c.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertNotIn("Convoy:", sh(self.repo.remote, "git", "log", "--format=%B", "main..convoy/1"))
        self.assertFalse([c for c in self.ledger_calls() if c[:1] == ["attribution"]], "attribution is never asked")


class TestFeatureDetection(Without):
    def test_schema_2_is_not_schema_1(self):
        self.assert_as_0_5({"HARBOR_FAKE_LEDGER": "2"})

    def test_a_boolean_schema_is_not_schema_1(self):
        self.assert_as_0_5({"HARBOR_FAKE_LEDGER": "true"})

    def test_no_schema_at_all(self):
        self.assert_as_0_5({"HARBOR_FAKE_LEDGER": "null"})

    def test_bad_json(self):
        self.assert_as_0_5({"HARBOR_FAKE_LEDGER": "bad"})

    def test_an_environment_failure(self):
        self.assert_as_0_5({"HARBOR_FAKE_LEDGER": "exit2"})

    def test_output_that_is_not_utf8(self):
        self.assert_as_0_5({"HARBOR_FAKE_LEDGER": "binary"})

    def test_a_ledger_that_never_answers_is_cut_by_the_timeout(self):
        self.assert_as_0_5({"HARBOR_FAKE_LEDGER": "sleep", "HARBOR_LEDGER_SECONDS": "1"})


class TestHRB1Edges(Phase6):
    def add(self, branch: str, *commits: tuple[str, str], **kw):
        head = self.branch(branch, *commits, **kw)
        ok(harbor(self.a, "seal"))
        return head, harbor(self.a, "convoy", "add", "1", branch)

    def test_no_story_commits_are_attributed(self):
        ok(harbor(self.a, "convoy", "new"))
        _, res = self.add("claude/docs", ("docs/a.md", "docs: a\n\nNo-story: docs"))
        ok(res)
        self.assertNotIn("story", self.convoy()["vessels"][0], "work outside stories has no story")

    def test_a_merge_with_no_trailer_is_not_a_NO_STORY(self):
        ok(harbor(self.a, "convoy", "new"))
        self.branch("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nPart-of: QA-1"))
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "pull", "--quiet", "--ff-only", "origin", "main")
        (self.a / "apps/api/x.ts").parent.mkdir(parents=True, exist_ok=True)
        (self.a / "apps/api/x.ts").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "chore: on main\n\nNo-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        sh(self.a, "git", "checkout", "--quiet", "claude/qa-1")
        sh(self.a, "git", "merge", "--quiet", "--no-ff", "--no-edit", "main")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-1")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        self.assertEqual(self.convoy()["vessels"][0]["story"], "QA-1")

    def test_an_unattributed_commit_main_already_has_is_not_the_vessels(self):
        # main gets a commit with no trailer (before the ledger's `since`, say); the vessel, sealed on an older main,
        # merges it in. It is main's commit, not the vessel's: no NO_STORY.
        ok(harbor(self.a, "convoy", "new"))
        old = sh(self.a, "git", "rev-parse", "origin/main")
        self.branch("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nPart-of: QA-1"))
        ok(harbor(self.a, "seal"))
        sh(self.a, "git", "checkout", "--quiet", "-B", "main", "origin/main")
        (self.a / "apps/api/old.ts").parent.mkdir(parents=True, exist_ok=True)
        (self.a / "apps/api/old.ts").write_text("old\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "an old habit, no trailer")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        sh(self.a, "git", "checkout", "--quiet", "claude/qa-1")
        sh(self.a, "git", "merge", "--quiet", "--no-ff", "--no-edit", "main")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-1")
        ok(harbor(self.a, "seal"))
        seal = self.repo.log_toml(f"harbor/runs/{sh(self.a, 'git', 'rev-parse', 'HEAD')}.toml")
        self.assertNotEqual(seal["base"], old)
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        self.assertEqual(self.convoy()["vessels"][0]["story"], "QA-1")

    def test_story_still_overrides_the_ledger(self):
        ok(harbor(self.a, "convoy", "new"))
        self.branch("claude/xyz", ("apps/web/a.ts", "feat: a\n\nPart-of: AUTH-001"))
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/xyz", "--story", "AUTH-002"))
        self.assertEqual(self.convoy()["vessels"][0]["story"], "AUTH-002")

    def test_a_vessel_with_several_stories_records_them_all(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "AUTH-001", "AUTH-002"))
        self.branch("claude/xyz", ("apps/web/a.ts", "feat: a\n\nPart-of: AUTH-002"),
                    ("apps/web/b.ts", "feat: b\n\nStory: AUTH-001"))
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/xyz"))
        self.assertEqual(self.convoy()["vessels"][0]["story"], "AUTH-001, AUTH-002")

    def test_a_ledger_without_attribution_falls_back_to_the_story_trailers_with_a_note(self):
        # Keelokit 0.16.0: `--json` is schema 1, `attribution` is not a command yet.
        os.environ["HARBOR_FAKE_ATTRIBUTION"] = "usage"
        ok(harbor(self.a, "convoy", "new"))
        _, res = self.add("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nStory: QA-1"), ("apps/web/b.ts", "no trailer"))
        out = ok(res)
        self.assertIn("ledger: attribution not available", out)
        self.assertIn("exit 2", out)
        self.assertEqual(self.convoy()["vessels"][0]["story"], "QA-1")

    def test_an_incomplete_history_falls_back_with_a_note(self):
        os.environ["HARBOR_FAKE_ATTRIBUTION"] = "exit3"
        ok(harbor(self.a, "convoy", "new"))
        _, res = self.add("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nStory: QA-1"), ("apps/web/b.ts", "none"))
        out = ok(res)
        self.assertIn("ledger: attribution not available", out)
        self.assertIn("exit 3", out)
        self.assertEqual(self.convoy()["vessels"][0]["story"], "QA-1")

    def test_an_attribution_that_times_out_falls_back_with_a_note(self):
        os.environ.update(HARBOR_FAKE_ATTRIBUTION="sleep", HARBOR_LEDGER_SECONDS="1")
        ok(harbor(self.a, "convoy", "new"))
        _, res = self.add("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nStory: QA-1"))
        out = ok(res)
        self.assertIn("ledger: attribution not available", out)
        self.assertIn("did not answer in 1 s", out)
        self.assertEqual(self.convoy()["vessels"][0]["story"], "QA-1")

    def test_an_attribution_with_bad_json_falls_back_with_a_note(self):
        os.environ["HARBOR_FAKE_ATTRIBUTION"] = "bad"
        ok(harbor(self.a, "convoy", "new"))
        _, res = self.add("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nStory: QA-1"))
        out = ok(res)
        self.assertIn("ledger: attribution not available", out)
        self.assertIn("not JSON", out)

    def test_an_answer_without_a_boolean_attributed_is_no_answer_never_a_refusal(self):
        os.environ["HARBOR_FAKE_ATTRIBUTION"] = "no-attributed"
        ok(harbor(self.a, "convoy", "new"))
        _, res = self.add("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nStory: QA-1"))
        out = ok(res)
        self.assertIn("ledger: attribution not available", out)
        self.assertEqual(self.convoy()["vessels"][0]["story"], "QA-1")

    def test_abbreviated_shas_are_matched(self):
        os.environ["HARBOR_FAKE_ATTRIBUTION"] = "short"
        ok(harbor(self.a, "convoy", "new"))
        head, res = self.add("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nPart-of: QA-1"), ("apps/web/b.ts", "none"))
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn(f"NO_STORY: {head[:9]}", res.stderr)

    def test_the_trailer_stays_last_with_merge_log_on(self):
        sh(self.a, "git", "config", "merge.log", "true")
        self.two_vessels_ready()
        for branch, sha in self.vessel_merges().items():
            self.assertEqual(convoy_trailers(self.repo.remote, sha), ["1"], branch)
            self.assertEqual(sh(self.repo.remote, "git", "log", "-1", "--format=%B", sha).splitlines()[-1], "Convoy: 1")

    def test_NO_STORY_names_every_unattributed_commit(self):
        ok(harbor(self.a, "convoy", "new"))
        h2 = self.branch("claude/qa-1", ("apps/web/a.ts", "one"), ("apps/web/b.ts", "two"))
        ok(harbor(self.a, "seal"))
        res = harbor(self.a, "convoy", "add", "1", "claude/qa-1")
        self.assertEqual(res.returncode, 1)
        line = next(l for l in res.stderr.splitlines() if "NO_STORY" in l)
        self.assertIn(sh(self.a, "git", "rev-parse", "HEAD~1")[:9], line)
        self.assertIn(h2[:9], line)

    def test_a_redelivery_gets_its_own_merge_with_one_trailer(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-2"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        sh(self.a, "git", "checkout", "--quiet", "claude/qa-1")
        (self.a / "apps/web/a.ts").write_text("fixed\n")
        sh(self.a, "git", "commit", "--quiet", "-am", "fix: a\n\nPart-of: QA-1")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-1")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        out = sh(self.repo.remote, "git", "log", "--first-parent", "--merges", "--format=%H", "main..convoy/1")
        shas = out.split()
        self.assertEqual(len(shas), 2)
        for sha in shas:
            self.assertEqual(convoy_trailers(self.repo.remote, sha), ["1"])

    def test_the_trailer_survives_a_rebuilt_generated_conflict(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/one", "site/index.json", "QA-1", content="one\n")
        self.deliver(1, "claude/two", "site/index.json", "QA-2", content="two\n")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        sha = self.vessel_merges()["claude/two"]
        self.assertEqual(convoy_trailers(self.repo.remote, sha), ["1"])
        message = sh(self.repo.remote, "git", "log", "-1", "--format=%B", sha)
        self.assertEqual(message.splitlines()[-1], "Convoy: 1")
        self.assertNotIn("Conflicts", message)

    def test_a_real_conflict_tells_the_skipper_to_keep_the_trailer(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/one", "shared.ts", "QA-1", content="export const x = 2\n")
        self.deliver(1, "claude/two", "shared.ts", "QA-2", content="export const x = 3\n")
        res = harbor(self.a, "convoy", "assemble", "1")
        self.assertIn("CONFLICT", res.stderr)
        self.assertIn("Convoy: 1", res.stderr)

    def test_a_hand_merge_without_the_trailer_is_named(self):
        ok(harbor(self.a, "convoy", "new"))
        one = self.deliver(1, "claude/one", "shared.ts", "QA-1", content="export const x = 2\n")
        two = self.deliver(1, "claude/two", "shared.ts", "QA-2", content="export const x = 3\n")
        harbor(self.a, "convoy", "assemble", "1")
        sh(self.a, "git", "checkout", "--quiet", "convoy/1")
        sh(self.a, "git", "merge", "--quiet", "--no-edit", two, check=False)
        (self.a / "shared.ts").write_text("export const x = 23\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "--no-edit")
        out = ok(harbor(self.a, "convoy", "assemble", "1"))
        named = [l for l in out.splitlines() if "no `Convoy: 1` trailer" in l]
        self.assertEqual(len(named), 1, out)
        self.assertIn(f"claude/two@{two[:9]}", named[0])
        self.assertNotIn("claude/one", named[0])

    def test_main_merged_into_the_convoy_carries_no_trailer(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        sh(self.a, "git", "checkout", "--quiet", "-B", "main", "origin/main")
        (self.a / "apps/api/m.ts").parent.mkdir(parents=True, exist_ok=True)
        (self.a / "apps/api/m.ts").write_text("m\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "main moves\n\nNo-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        tip = sh(self.repo.remote, "git", "rev-parse", "convoy/1")
        self.assertIn(": merge main", sh(self.repo.remote, "git", "log", "-1", "--format=%s", tip))
        self.assertEqual(convoy_trailers(self.repo.remote, tip), [])


class TestHRB7MultiStory(Phase2):
    """The HRB-7 nit: a vessel carrying several stories delivers each one, not their joined text."""
    CUTOFF, AFTER = "2026-11-01T17:00Z", {"HARBOR_NOW": "2026-11-01T17:30:00Z"}

    def deliver_both(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3", "--cutoff", self.CUTOFF))
        from test_harbor import vessel
        vessel(self.a, "claude/qa-13", "apps/web/a.ts", story="QA-1")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-13", "--story", "QA-1, QA-3"))

    def test_the_round_does_not_call_a_story_of_a_multi_story_vessel_missing(self):
        self.deliver_both()
        out = ok(harbor(self.a, "harbormaster", "control", env=self.AFTER))
        line = next(l for l in out.splitlines() if l.startswith("convoy 1"))
        self.assertNotIn("not delivered", line)

    def test_assemble_does_not_wait_for_a_story_a_multi_story_vessel_carries(self):
        self.deliver_both()
        out = ok(harbor(self.a, "convoy", "assemble", "1", env=self.AFTER))
        self.assertNotIn("waiting", out)
        self.assertEqual(self.convoy()["state"], "ready")

    def test_status_does_not_list_a_story_a_multi_story_vessel_carries(self):
        self.deliver_both()
        self.assertNotIn("not delivered", ok(harbor(self.a, "convoy", "status", "1")))

    def test_the_convoy_page_does_not_list_a_story_a_multi_story_vessel_carries(self):
        self.deliver_both()
        page = self.repo.log_files()["harbor/convoys/1.md"]
        self.assertIn("QA-1, QA-3", page)
        self.assertNotIn("Expected, not delivered", page)

    def test_a_story_a_multi_story_vessel_carries_cannot_be_deferred(self):
        self.deliver_both()
        res = harbor(self.a, "convoy", "defer", "1", "QA-3")
        self.assertEqual(res.returncode, 1)
        self.assertIn("ALREADY_DELIVERED", res.stderr)


if __name__ == "__main__":
    unittest.main()


# --- HRB-2: taking a story is a lock in the logbook -------------------------------------------------

def later(minutes: float) -> dict:
    t = dt.datetime.strptime(NOW, "%Y-%m-%dT%H:%M:%SZ") + dt.timedelta(minutes=minutes)
    return {"HARBOR_NOW": t.strftime("%Y-%m-%dT%H:%M:%SZ")}


class Phase6Lock(Phase6):
    """Clone `a` (acct1/mbp: s1 holds the watch) and clone `b` (acct1/linux), both with the ledger."""

    def setUp(self):
        super().setUp()
        self.b = self.repo.clone("b", host="linux")

    def worker(self, wid: str) -> dict:
        return self.repo.log_toml(f"harbor/workers/{wid}.toml")

    def holders(self, story: str) -> list[str]:
        out = []
        for path, text in self.repo.log_files().items():
            if path.startswith("harbor/workers/") and path.endswith(".toml"):
                w = tomllib.loads(text)
                if w.get("state") == "active" and w.get("story") == story:
                    out.append(w["id"])
        return out

    def log_tip(self) -> str:
        return sh(self.repo.remote, "git", "rev-parse", "harbor/log")

    def take(self, clone, session: str, story: str, *extra: str, env: dict | None = None):
        return harbor(clone, "story", "take", story, *extra, session=session, env=env)

    def in_process(self, clone, argv: list[str], meanwhile) -> tuple[int, str]:
        saved = {k: os.environ.get(k) for k in {**GIT_ENV, "HARBOR_NOW": NOW}}
        os.environ.update({**GIT_ENV, "HARBOR_NOW": NOW})
        try:
            mod = load_module()
            mod.BEFORE_PUSH = meanwhile
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                rc = mod.main(argv, root=clone)
            return rc, err.getvalue()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class TestHRB2(Phase6Lock):
    def test_HRB_2_S1_two_sessions_take_the_same_story_at_once_one_wins_the_other_gets_STORY_TAKEN(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="va"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb"))
        ids = {"va": "acct1/mbp/va", "vb": "acct1/linux/vb"}
        for story in ("QA-1", "QA-3", "QA-4", "QA-5"):
            go = threading.Barrier(2)
            results: dict[str, subprocess.CompletedProcess] = {}

            def race(clone, session):
                go.wait()
                results[session] = self.take(clone, session, story)
            threads = [threading.Thread(target=race, args=(self.a, "va")), threading.Thread(target=race, args=(self.b, "vb"))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            won = [s for s, r in results.items() if r.returncode == 0]
            lost = [s for s, r in results.items() if r.returncode != 0]
            self.assertEqual(len(won), 1, {s: r.stdout + r.stderr for s, r in results.items()})
            self.assertEqual(results[lost[0]].returncode, 1)
            self.assertIn("STORY_TAKEN", results[lost[0]].stderr)
            self.assertIn(ids[won[0]], results[lost[0]].stderr, "the refusal names the holder")
            self.assertEqual(self.holders(story), [ids[won[0]]], "exactly one holder in the logbook")

    def test_HRB_2_S1_the_rejected_push_replays_and_finds_the_story_held(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="va"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb"))

        def b_takes_first():
            ok(self.take(self.b, "vb", "QA-1"))

        rc, err = self.in_process(self.a, ["--session", "va", "story", "take", "QA-1"], b_takes_first)
        self.assertEqual(rc, 1)
        self.assertIn("STORY_TAKEN", err)
        self.assertIn("acct1/linux/vb", err)
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/vb"], "first commit wins, as the watch")
        self.assertNotIn("story", self.worker("acct1/mbp/va"))

    def test_HRB_2_S2_a_worker_marked_lost_releases_its_story(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="s2"))
        ok(self.take(self.a, "s2", "QA-1"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="s3", env=later(1)))
        self.assertIn("STORY_TAKEN", self.take(self.b, "s3", "QA-1", env=later(1)).stderr)
        ok(harbor(self.b, "worker", "end", session="s3", env=later(1)))
        out = ok(harbor(self.a, "harbormaster", "control", env=later(190)))
        self.assertIn("lost: acct1/mbp/s2", out)
        self.assertIn("QA-1", out, "the round says which story the lost worker released")
        self.assertEqual(self.worker("acct1/mbp/s2")["state"], "lost")
        self.assertEqual(self.holders("QA-1"), [])
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="s4", env=later(190)))
        ok(self.take(self.b, "s4", "QA-1", env=later(190)))
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/s4"])

    def test_HRB_2_S3_a_request_for_a_story_already_on_the_trunk_is_refused_at_wanted_take(self):
        os.environ["HARBOR_FAKE_STORIES"] = json.dumps({"QA-1": "on-trunk", "QA-3": "in-production", "QA-4": "in-progress"})
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1"))
        for story in ("QA-1", "QA-3", "QA-4"):
            ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", story))
        for rid, state in (("w-0001", "on-trunk"), ("w-0002", "in-production")):
            res = harbor(self.a, "wanted", "take", rid, session="d1")
            self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
            self.assertIn("STORY_ON_TRUNK", res.stderr)
            self.assertIn(state, res.stderr)
            self.assertEqual(self.repo.log_toml(f"harbor/wanted/{rid}.toml")["state"], "open")
        ok(harbor(self.a, "wanted", "take", "w-0003", session="d1"))

    def test_HRB_2_S4_the_dispatchers_prompt_for_a_vessel_starts_with_ledger_take(self):
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1"))
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1"))
        prompt = ok(harbor(self.a, "wanted", "prompt", "w-0001", session="d1"))
        self.assertEqual(prompt.splitlines()[0], "python3 .keelokit/bin/ledger.py take QA-1")
        self.assertIn("worker register --role vessel --story QA-1", prompt, "register still takes it in Harbor")
        ok(harbor(self.a, "wanted", "add", "--role", "dispatcher", "--account", "acct1"))
        ok(harbor(self.a, "wanted", "take", "w-0002", session="d1"))
        self.assertNotIn("ledger.py take", ok(harbor(self.a, "wanted", "prompt", "w-0002", session="d1")))


class TestHRB2Lock(Phase6Lock):
    def setUp(self):
        super().setUp()
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="va"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb"))

    def test_taking_again_is_idempotent_and_writes_nothing(self):
        ok(self.take(self.a, "va", "QA-1"))
        tip = self.log_tip()
        out = ok(self.take(self.a, "va", "QA-1"))
        self.assertIn("already yours", out)
        self.assertEqual(self.log_tip(), tip)

    def test_the_story_key_is_written_and_released_and_the_logbook_stays_schema_1(self):
        self.assertNotIn("story", self.worker("acct1/mbp/va"), "absent keys are omitted")
        ok(self.take(self.a, "va", "QA-1"))
        w = self.worker("acct1/mbp/va")
        self.assertEqual((w["schema"], w["story"]), (1, "QA-1"))
        self.assertIn("QA-1", self.repo.log_files()["harbor/LOGBOOK.md"], "LOGBOOK.md shows each worker's story")
        ok(harbor(self.a, "story", "release", "QA-1", session="va"))
        text = self.repo.log_files()["harbor/workers/acct1/mbp/va.toml"]
        self.assertNotIn("story", text)
        self.assertEqual(tomllib.loads(text)["schema"], 1)
        for path, body in self.repo.log_files().items():
            if path.endswith(".toml"):
                self.assertEqual(tomllib.loads(body).get("schema"), 1, path)

    def test_release_by_a_worker_that_does_not_hold_it_is_refused(self):
        ok(self.take(self.a, "va", "QA-1"))
        res = harbor(self.b, "story", "release", "QA-1", session="vb")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT_HOLDER", res.stderr)
        self.assertIn("acct1/mbp/va", res.stderr)
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/va"])

    def test_releasing_a_story_nobody_holds_changes_nothing(self):
        tip = self.log_tip()
        out = ok(harbor(self.a, "story", "release", "QA-1", session="va"))
        self.assertIn("nobody holds", out)
        self.assertEqual(self.log_tip(), tip)

    def test_a_lost_worker_releasing_does_not_touch_the_new_holder(self):
        ok(self.take(self.a, "va", "QA-1"))
        ok(harbor(self.a, "harbormaster", "control", env=later(190)))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vc", env=later(190)))
        ok(self.take(self.b, "vc", "QA-1", env=later(190)))
        res = harbor(self.a, "story", "release", "QA-1", session="va", env=later(191))
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT_HOLDER", res.stderr)
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/vc"])
        res = self.take(self.a, "va", "QA-1", env=later(191))
        self.assertEqual(res.returncode, 1, "a lost worker holds nothing and takes nothing")
        self.assertIn("NOT_REGISTERED", res.stderr)

    def test_an_ended_worker_releases_its_story(self):
        ok(self.take(self.a, "va", "QA-1"))
        ok(harbor(self.a, "worker", "end", session="va"))
        self.assertEqual(self.holders("QA-1"), [])
        ok(self.take(self.b, "vb", "QA-1"))
        res = harbor(self.a, "story", "release", "QA-1", session="va")
        self.assertIn("NOT_HOLDER", res.stderr, "an ended worker releasing can't clear the new holder")
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/vb"])

    def test_a_re_registered_worker_does_not_get_back_a_story_it_released(self):
        ok(self.take(self.a, "va", "QA-1"))
        ok(harbor(self.a, "worker", "end", session="va"))
        ok(self.take(self.b, "vb", "QA-1"))
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="va"))
        self.assertNotIn("story", self.worker("acct1/mbp/va"))
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/vb"])

    def test_the_story_is_compared_without_case(self):
        ok(self.take(self.a, "va", "QA-1"))
        res = self.take(self.b, "vb", "qa-1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("STORY_TAKEN", res.stderr)

    def test_a_story_id_is_one_plain_word(self):
        self.assertEqual(self.take(self.a, "va", "QA-1, QA-3").returncode, 2)
        self.assertEqual(self.take(self.a, "va", "").returncode, 2)

    def test_taking_another_story_releases_the_first(self):
        ok(self.take(self.a, "va", "QA-1"))
        out = ok(self.take(self.a, "va", "QA-3"))
        self.assertIn("was QA-1", out)
        self.assertEqual(self.holders("QA-1"), [])
        ok(self.take(self.b, "vb", "QA-1"))

    def test_an_unregistered_session_is_checked_but_nothing_is_written(self):
        tip = self.log_tip()
        out = ok(self.take(self.a, "nobody", "QA-1"))
        self.assertIn("not registered", out)
        self.assertEqual(self.log_tip(), tip)
        ok(self.take(self.b, "vb", "QA-1"))
        res = self.take(self.a, "nobody", "QA-1")
        self.assertEqual(res.returncode, 1, "a held story is refused even before registering")
        self.assertIn("STORY_TAKEN", res.stderr)

    def test_worker_names_a_worker_its_caller_answers_for(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--spawned-by", "acct1/mbp/s1", session="kid"))
        ok(self.take(self.a, "s1", "QA-1", "--worker", "acct1/mbp/kid"))
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/kid"])
        other = self.repo.clone("c", account="acct2", host="pc")
        ok(harbor(other, "account", "set", "acct2", "--max-sessions", "2", session="x"))
        ok(harbor(other, "worker", "register", "--role", "vessel", session="x"))
        res = harbor(other, "story", "release", "QA-1", "--worker", "acct1/mbp/kid", session="x")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT_YOURS", res.stderr)
        res = self.take(other, "x", "QA-3", "--worker", "acct1/mbp/va")
        self.assertIn("NOT_YOURS", res.stderr)
        res = self.take(self.a, "s1", "QA-3", "--worker", "acct1/mbp/ghost")
        self.assertIn("NOT_REGISTERED", res.stderr)

    def test_the_harbormaster_releases_a_stuck_lock_by_naming_its_holder(self):
        ok(self.take(self.b, "vb", "QA-1"))
        ok(harbor(self.a, "story", "release", "QA-1", "--worker", "acct1/linux/vb"))
        self.assertEqual(self.holders("QA-1"), [])

    def test_acting_for_another_worker_does_not_renew_its_last_seen(self):
        ok(self.take(self.b, "vb", "QA-1"))
        seen = self.worker("acct1/linux/vb")["last_seen"]
        ok(harbor(self.a, "story", "release", "QA-1", "--worker", "acct1/linux/vb", env=later(100)))
        self.assertEqual(self.worker("acct1/linux/vb")["last_seen"], seen, "a silent holder must still go lost")
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--spawned-by", "acct1/mbp/s1", session="kid"))
        seen = self.worker("acct1/mbp/kid")["last_seen"]
        ok(self.take(self.a, "s1", "QA-3", "--worker", "acct1/mbp/kid", env=later(100)))
        self.assertEqual(self.worker("acct1/mbp/kid")["last_seen"], seen)

    def test_a_take_replayed_after_the_round_marked_its_worker_lost_is_refused(self):
        def the_round_lands_first():
            ok(harbor(self.a, "harbormaster", "control", env=later(190)))

        rc, err = self.in_process(self.b, ["--session", "vb", "story", "take", "QA-1"], the_round_lands_first)
        self.assertEqual(rc, 1)
        self.assertIn("NOT_REGISTERED", err)
        self.assertEqual(self.worker("acct1/linux/vb")["state"], "lost")
        self.assertEqual(self.holders("QA-1"), [])

    def test_a_take_that_dies_before_its_push_leaves_nothing(self):
        def dies():
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.in_process(self.a, ["--session", "va", "story", "take", "QA-1"], dies)
        self.assertEqual(self.holders("QA-1"), [])
        ok(self.take(self.b, "vb", "QA-1"))

    def test_STORY_ON_TRUNK_from_the_facts_of_ledger_json(self):
        os.environ["HARBOR_FAKE_STORIES"] = json.dumps({"QA-1": "in-version", "QA-3": "ready"})
        res = self.take(self.a, "va", "QA-1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("STORY_ON_TRUNK", res.stderr)
        self.assertIn("in-version", res.stderr)
        self.assertNotIn("story", self.worker("acct1/mbp/va"))
        ok(self.take(self.a, "va", "QA-3"))
        self.assertIn(["show", "QA-1", "--json"], self.ledger_calls(), "show --json is asked first")

    def test_show_json_is_used_when_the_ledger_answers_it(self):
        os.environ["HARBOR_FAKE_STORIES"] = json.dumps({"QA-1": "in-progress"})
        os.environ["HARBOR_FAKE_SHOW"] = json.dumps({"QA-1": "on-trunk"})
        res = self.take(self.a, "va", "QA-1")
        self.assertIn("STORY_ON_TRUNK", res.stderr)

    def test_a_ledger_that_cannot_say_is_never_a_refusal(self):
        os.environ["HARBOR_FAKE_STORIES"] = json.dumps({"QA-3": "on-trunk"})
        out = ok(self.take(self.a, "va", "QA-1"))
        self.assertEqual(len([l for l in out.splitlines() if "ledger" in l]), 1, out)
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/va"])


class TestHRB2Register(Phase6Lock):
    def setUp(self):
        super().setUp()
        for clone in (self.a, self.b):
            (clone / ".keelokit/bin/status.py").write_text(STATUS)

    def test_worker_register_story_takes_it(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-1", session="va"))
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/va"])
        res = harbor(self.b, "worker", "register", "--role", "vessel", "--story", "QA-1", session="vb")
        self.assertEqual(res.returncode, 1)
        self.assertIn("STORY_TAKEN", res.stderr)
        self.assertIn("acct1/mbp/va", res.stderr)
        self.assertNotIn("harbor/workers/acct1/linux/vb.toml", self.repo.log_files())
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-1", session="va"))  # again: its own

    def test_worker_register_refuses_a_story_on_the_trunk(self):
        os.environ["HARBOR_FAKE_STORIES"] = json.dumps({"QA-1": "on-trunk"})
        res = harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-1", session="va")
        self.assertEqual(res.returncode, 1)
        self.assertIn("STORY_ON_TRUNK", res.stderr)

    def test_a_lost_worker_re_registering_for_a_story_now_held_is_refused(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-1", session="va"))
        ok(harbor(self.a, "harbormaster", "control", env=later(190)))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", "--story", "QA-1", session="vb", env=later(190)))
        res = harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-1", session="va", env=later(191))
        self.assertIn("STORY_TAKEN", res.stderr)
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/vb"])


class TestHRB2WantedTake(Phase6Lock):
    def test_a_request_for_a_story_an_active_worker_holds_is_refused(self):
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb"))
        ok(self.take(self.b, "vb", "QA-1"))
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        res = harbor(self.a, "wanted", "take", "w-0001", session="d1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("STORY_TAKEN", res.stderr)
        self.assertIn("acct1/linux/vb", res.stderr)
        ok(harbor(self.b, "story", "release", "QA-1", session="vb"))
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1"))


class TestHRB2WithoutLedger(Phase6Lock):
    """No ledger.py: the prompt and `wanted take` are 0.5's; the lock itself is the logbook's."""
    ledger = False

    def test_the_prompt_and_wanted_take_are_0_5s(self):
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1"))
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1"))
        prompt = ok(harbor(self.a, "wanted", "prompt", "w-0001", session="d1"))
        self.assertNotIn("ledger.py", prompt)
        self.assertTrue(prompt.startswith("You are a Harbor vessel session"))
        self.assertEqual(self.ledger_calls(), [])

    def test_story_take_still_locks(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="va"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb"))
        ok(self.take(self.a, "va", "QA-1"))
        self.assertIn("STORY_TAKEN", self.take(self.b, "vb", "QA-1").stderr)
        self.assertEqual(self.ledger_calls(), [])


# --- HRB-2, second breaker round: the lock never depends on the ledger; requests hold; the round repairs ------

class Forge:
    """Write the logbook by hand, as a Harbor older than 0.6.0 (or legacy data) would leave it."""

    def forge(self, edits: dict, message: str = "an older Harbor wrote this"):
        w = self.tmp / f"forger-{len(list(self.tmp.glob('forger-*')))}"
        sh(self.tmp, "git", "clone", "--quiet", "-b", "harbor/log", str(self.repo.remote), str(w))
        for path, edit in edits.items():
            f = w / path
            data = tomllib.loads(f.read_text()) if f.exists() else {}
            data = edit(data)
            lines = []
            for k, v in data.items():
                lines.append(f"{k} = {json.dumps(v)}")
            f.write_text("\n".join(lines) + "\n")
        sh(w, "git", "add", "-A")
        sh(w, "git", "commit", "--quiet", "-m", message)
        sh(w, "git", "push", "--quiet", "origin", "HEAD:harbor/log")


class TestHRB2F1LockWithoutLedger(Phase6Lock):
    """F1: STORY_TAKEN is the logbook's lock: a ledger that fails on one call, or no ledger, never skips it."""

    def setUp(self):
        super().setUp()
        for c in (self.a, self.b):
            (c / ".keelokit/bin/status.py").write_text(STATUS)
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-1", session="va"))

    def assert_refused(self, env: dict):
        res = harbor(self.b, "worker", "register", "--role", "vessel", "--story", "QA-1", session="vb", env=env)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("STORY_TAKEN", res.stderr)
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/va"])

    def test_F1_register_story_is_refused_when_the_ledger_exits_2_on_that_call(self):
        self.assert_refused({"HARBOR_FAKE_LEDGER": "exit2"})

    def test_F1_register_story_is_refused_when_the_ledger_times_out_on_that_call(self):
        self.assert_refused({"HARBOR_FAKE_LEDGER": "sleep", "HARBOR_LEDGER_SECONDS": "0.5"})

    def test_F1_register_story_is_refused_when_the_ledger_prints_bad_json_on_that_call(self):
        self.assert_refused({"HARBOR_FAKE_LEDGER": "bad"})


class TestHRB2F1NoLedger(Phase6Lock):
    ledger = False

    def test_F1_without_a_ledger_register_story_after_a_story_take_is_refused(self):
        for c in (self.a, self.b):
            (c / ".keelokit/bin").mkdir(parents=True, exist_ok=True)
            (c / ".keelokit/bin/status.py").write_text(STATUS)
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="va"))
        ok(self.take(self.a, "va", "QA-1"))
        res = harbor(self.b, "worker", "register", "--role", "vessel", "--story", "QA-1", session="vb")
        self.assertIn("STORY_TAKEN", res.stderr)
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/va"])

    def test_F1_without_a_ledger_wanted_take_refuses_a_held_story(self):
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb"))
        ok(self.take(self.b, "vb", "QA-1"))
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        res = harbor(self.a, "wanted", "take", "w-0001", session="d1")
        self.assertIn("STORY_TAKEN", res.stderr)


class TestHRB2F2Requests(Forge, Phase6Lock):
    """F2: a taken vessel request holds its story until its session registers or ends, or its taker ends."""

    def setUp(self):
        super().setUp()
        for c in (self.a, self.b):
            (c / ".keelokit/bin/status.py").write_text(STATUS)
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1"))

    def second_request(self):
        """w-0002 for QA-1 too, as an older Harbor's wanted add would have let in."""
        self.forge({"harbor/wanted/w-0002.toml": lambda _: {
            **self.repo.log_toml("harbor/wanted/w-0001.toml"), "id": "w-0002", "state": "open", "taken_by": "",
            "taken_at": ""}})

    def test_F2a_a_flaky_ledger_does_not_skip_STORY_TAKEN_at_wanted_take(self):
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb"))
        ok(self.take(self.b, "vb", "QA-1"))
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        res = harbor(self.a, "wanted", "take", "w-0001", session="d1", env={"HARBOR_FAKE_LEDGER": "exit2"})
        self.assertEqual(res.returncode, 1)
        self.assertIn("STORY_TAKEN", res.stderr)

    def test_F2b_a_second_open_request_for_a_story_is_refused_at_wanted_add(self):
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        res = harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("STORY_REQUESTED", res.stderr)
        self.assertIn("w-0001", res.stderr)
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1"))
        self.assertIn("STORY_REQUESTED", harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1").stderr)
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-3"))

    def test_F2b_a_taken_request_holds_its_story_against_another_request(self):
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        self.second_request()
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1"))
        res = harbor(self.a, "wanted", "take", "w-0002", session="d1")
        self.assertEqual(res.returncode, 1, "two vessels would be spawned for QA-1")
        self.assertIn("STORY_TAKEN", res.stderr)
        self.assertIn("w-0001", res.stderr)

    def test_F2b_the_session_spawned_for_the_request_registers_and_others_are_refused(self):
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1"))
        res = harbor(self.b, "worker", "register", "--role", "vessel", session="other")
        ok(res)
        self.assertIn("STORY_TAKEN", self.take(self.b, "other", "QA-1").stderr, "the request holds it for its spawn")
        out = ok(self.take(self.a, "spawn", "QA-1"))  # its prompt's first line, before it registers
        self.assertIn("not registered", out)
        ok(harbor(self.a, "wanted", "started", "w-0001", "--session", "spawn", session="d1"))
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-1", "--spawned-by", "acct1/mbp/d1",
                  "--request", "w-0001", session="spawn"))
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/spawn"])
        self.assertEqual(self.repo.log_toml("harbor/wanted/w-0001.toml")["claimed_by"], "acct1/mbp/spawn")
        ok(harbor(self.a, "worker", "end", session="spawn"))
        ok(self.take(self.b, "other", "QA-1"))  # its session ended: the request holds nothing any more

    def test_F2b_a_request_whose_session_never_registers_holds_only_until_the_watch_expiry(self):
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1"))
        ok(harbor(self.a, "wanted", "started", "w-0001", "--session", "died", session="d1"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb", env=later(170)))
        self.assertIn("STORY_TAKEN", self.take(self.b, "vb", "QA-1", env=later(170)).stderr)
        ok(self.take(self.b, "vb", "QA-1", env=later(181)))

    def test_F2b_a_request_whose_taker_ended_holds_nothing(self):
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb"))
        self.assertIn("STORY_TAKEN", self.take(self.b, "vb", "QA-1").stderr)
        ok(harbor(self.a, "worker", "end", session="d1"))
        ok(self.take(self.b, "vb", "QA-1"))


class TestHRB2F3Repair(Forge, Phase6Lock):
    """F3: an older Harbor leaves two active holders; the harbormaster's round keeps the first and releases the rest."""

    def setUp(self):
        super().setUp()
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="va"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vb"))

    def test_F3a_the_round_repairs_a_double_hold_an_old_client_wrote(self):
        ok(self.take(self.a, "va", "QA-1"))
        self.forge({"harbor/workers/acct1/linux/vb.toml": lambda w: {**w, "story": "QA-1"}})
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/vb", "acct1/mbp/va"])
        out = ok(harbor(self.a, "harbormaster", "control"))
        self.assertIn("QA-1", out)
        self.assertIn("acct1/linux/vb", out)
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/va"], "the first take keeps it")
        self.assertNotIn("story", self.worker("acct1/linux/vb"))

    def test_F3a_a_lost_worker_an_old_client_revived_loses_to_the_holder_since(self):
        ok(self.take(self.a, "va", "QA-1"))
        ok(harbor(self.a, "harbormaster", "control", env=later(190)))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="vc", env=later(190)))
        ok(self.take(self.b, "vc", "QA-1", env=later(190)))
        # 0.5's worker register keeps the old story when it revives a lost worker
        self.forge({"harbor/workers/acct1/mbp/va.toml": lambda w: {**w, "state": "active", "last_seen": later(191)["HARBOR_NOW"]}})
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/vc", "acct1/mbp/va"])
        out = ok(harbor(self.a, "harbormaster", "control", env=later(192)))
        self.assertIn("QA-1", out)
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/vc"], "vc held it first in this active stretch")

    def test_F3d_a_holder_re_taking_with_legacy_duplicates_gets_already_yours(self):
        ok(self.take(self.a, "va", "QA-1"))
        self.forge({"harbor/workers/acct1/linux/vb.toml": lambda w: {**w, "story": "QA-1"}})
        out = ok(self.take(self.a, "va", "QA-1"))
        self.assertIn("already yours", out)


class TestHRB2N(Phase6Lock):
    """Third breaker round: a request belongs to exactly one session, the one that claims it with
    `worker register --request` (its prompt's register line). No other child of the dispatcher, and no clock."""

    def setUp(self):
        super().setUp()
        for c in (self.a, self.b):
            (c / ".keelokit/bin/status.py").write_text(STATUS)
        ok(harbor(self.a, "account", "set", "acct1", "--max-sessions", "9"))
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1"))

    def request(self, take_env: dict | None = None):
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1", env=take_env))

    def spawn(self, clone, session: str, *extra: str, env: dict | None = None):
        return harbor(clone, "worker", "register", "--role", "vessel", "--story", "QA-1", "--spawned-by", "acct1/mbp/d1",
                      *extra, session=session, env=env)

    def test_N1_an_earlier_child_of_the_dispatcher_cannot_take_a_requested_story(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-3", "--spawned-by", "acct1/mbp/d1",
                  session="v1"))
        self.request()
        res = self.take(self.a, "v1", "QA-1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("STORY_TAKEN", res.stderr)
        self.assertIn("w-0001", res.stderr)
        ok(self.spawn(self.a, "spawn", "--request", "w-0001"))
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/spawn"])

    def test_N1_a_register_without_the_claim_gets_STORY_TAKEN(self):
        self.request()
        res = self.spawn(self.b, "stranger")
        self.assertEqual(res.returncode, 1)
        self.assertIn("STORY_TAKEN", res.stderr)
        self.assertEqual(self.holders("QA-1"), [])

    def test_N1_a_claim_from_a_session_the_taker_did_not_launch_is_REQUEST_NOT_YOURS(self):
        self.request()
        res = harbor(self.b, "worker", "register", "--role", "vessel", "--story", "QA-1", "--spawned-by", "acct1/mbp/s1",
                     "--request", "w-0001", session="stranger")
        self.assertEqual(res.returncode, 1)
        self.assertIn("REQUEST_NOT_YOURS", res.stderr)
        res = harbor(self.b, "worker", "register", "--role", "vessel", "--story", "QA-1", "--request", "w-0001",
                     session="stranger")
        self.assertIn("REQUEST_NOT_YOURS", res.stderr)
        self.assertNotIn("claimed_by", self.repo.log_toml("harbor/wanted/w-0001.toml"))

    def test_N1_the_first_claim_wins_and_the_next_gets_REQUEST_CLAIMED(self):
        self.request()
        ok(self.spawn(self.b, "stranger", "--request", "w-0001"))  # declares the dispatcher as its launcher: first claim
        res = self.spawn(self.a, "spawn", "--request", "w-0001")
        self.assertEqual(res.returncode, 1)
        self.assertIn("REQUEST_CLAIMED", res.stderr)
        self.assertIn("acct1/linux/stranger", res.stderr)
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/stranger"])

    def test_N1_a_claim_for_another_story_is_refused(self):
        self.request()
        res = harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-3", "--spawned-by", "acct1/mbp/d1",
                     "--request", "w-0001", session="spawn")
        self.assertIn("REQUEST_NOT_YOURS", res.stderr)

    def test_N2_a_claimed_request_holds_nothing_whatever_the_dispatchers_clock(self):
        self.request(take_env=later(30))  # the dispatcher's clock runs 30 minutes ahead
        ok(self.spawn(self.b, "spawn", "--request", "w-0001", env=later(1)))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="x", env=later(2)))
        self.assertIn("STORY_TAKEN", self.take(self.b, "x", "QA-1", env=later(2)).stderr, "the claimant holds it")
        ok(harbor(self.b, "worker", "end", session="spawn", env=later(3)))
        ok(self.take(self.b, "x", "QA-1", env=later(4)))

    def test_N2_a_release_before_started_frees_the_story(self):
        self.request()
        ok(self.spawn(self.a, "spawn", "--request", "w-0001"))
        ok(harbor(self.a, "story", "release", "QA-1", session="spawn"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="x"))
        ok(self.take(self.b, "x", "QA-1"))

    def test_N_the_prompt_registers_with_the_claim(self):
        self.request()
        prompt = ok(harbor(self.a, "wanted", "prompt", "w-0001", session="d1"))
        self.assertIn("--story QA-1", prompt)
        self.assertIn("--request w-0001", prompt)


class TestHRB2A2(Phase6Lock):
    """Fourth breaker round: a started request whose session never claims it can always be lifted, and
    `wanted started` never extends a lock. Mixed versions are unsupported, but they reduce to this same state: m1, an
    old vessel that never registers (it doesn't know --request); m2, an old dispatcher's prompt without --request, so
    the new vessel is refused by its own request."""

    def setUp(self):
        super().setUp()
        for c in (self.a, self.b):
            (c / ".keelokit/bin/status.py").write_text(STATUS)
        ok(harbor(self.a, "account", "set", "acct1", "--max-sessions", "9"))
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1"))
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-1"))
        ok(harbor(self.a, "wanted", "take", "w-0001", session="d1"))
        ok(harbor(self.a, "wanted", "started", "w-0001", "--session", "died", session="d1"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="x"))

    def state(self) -> str:
        return self.repo.log_toml("harbor/wanted/w-0001.toml")["state"]

    def test_A2_m1_the_taker_drops_a_started_unclaimed_request(self):
        self.assertIn("STORY_TAKEN", self.take(self.b, "x", "QA-1").stderr)
        out = ok(harbor(self.a, "wanted", "drop", "w-0001", session="d1"))
        self.assertIn("unclaimed", out)
        self.assertEqual(self.state(), "dropped")
        ok(self.take(self.b, "x", "QA-1"))

    def test_A2_m2_the_harbormaster_drops_it_and_the_refused_vessel_registers(self):
        res = harbor(self.b, "worker", "register", "--role", "vessel", "--story", "QA-1", "--spawned-by",
                     "acct1/mbp/d1", session="died")  # an old dispatcher's prompt: no --request
        self.assertIn("STORY_TAKEN", res.stderr)
        ok(harbor(self.a, "wanted", "drop", "w-0001"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", "--story", "QA-1", "--spawned-by", "acct1/mbp/d1",
                  session="died"))
        self.assertEqual(self.holders("QA-1"), ["acct1/linux/died"])

    def test_A2_nobody_else_drops_it_and_a_claimed_request_stays(self):
        res = harbor(self.b, "wanted", "drop", "w-0001", session="x")
        self.assertIn("NOT_YOURS", res.stderr)
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--story", "QA-1", "--spawned-by", "acct1/mbp/d1",
                  "--request", "w-0001", session="died"))
        res = harbor(self.a, "wanted", "drop", "w-0001")
        self.assertEqual(res.returncode, 1)
        self.assertIn("WRONG_STATE", res.stderr)
        self.assertIn("claimed", res.stderr)
        ok(harbor(self.a, "worker", "end", session="died"))
        ok(harbor(self.a, "wanted", "drop", "w-0001"))  # its claimant ended: unclaimed again

    def test_A2_story_release_by_the_harbormaster_drops_the_holding_request(self):
        out = ok(harbor(self.a, "story", "release", "QA-1"))
        self.assertNotIn("nobody holds", out)
        self.assertIn("w-0001", out)
        self.assertEqual(self.state(), "dropped")
        ok(self.take(self.b, "x", "QA-1"))

    def test_A2_story_release_by_the_taker_drops_it_too(self):
        ok(harbor(self.a, "story", "release", "QA-1", session="d1"))
        self.assertEqual(self.state(), "dropped")

    def test_A2_story_release_by_anyone_else_names_the_request_and_the_drop(self):
        res = harbor(self.b, "story", "release", "QA-1", session="x")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT_HOLDER", res.stderr)
        self.assertIn("w-0001", res.stderr)
        self.assertIn("wanted drop w-0001", res.stderr)
        self.assertEqual(self.state(), "started")

    def test_A2_the_round_drops_a_started_unclaimed_request_whose_taker_is_gone(self):
        ok(harbor(self.a, "worker", "end", session="d1"))
        out = ok(harbor(self.a, "harbormaster", "control"))
        self.assertIn("w-0001", out)
        self.assertEqual(self.state(), "dropped")

    def test_A2_the_round_names_a_started_unclaimed_request_older_than_the_expiry(self):
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1", env=later(170)))  # alive
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="x", env=later(170)))
        out = ok(harbor(self.a, "harbormaster", "control", env=later(181)))
        self.assertIn("w-0001", out)
        self.assertIn("wanted drop w-0001", out)

    def test_A2_wanted_started_does_not_extend_the_hold(self):
        ok(harbor(self.a, "wanted", "add", "--role", "vessel", "--story", "QA-3"))
        ok(harbor(self.a, "wanted", "take", "w-0002", session="d1"))
        ok(harbor(self.a, "wanted", "started", "w-0002", "--session", "late", session="d1", env=later(100)))
        ok(harbor(self.a, "worker", "register", "--role", "dispatcher", session="d1", env=later(170)))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", session="x", env=later(170)))
        ok(self.take(self.b, "x", "QA-3", env=later(181)))


# --- HRB-3: the ledger in the harbormaster's round and in the ok -----------------------------------------------

def diff(code: str, detail: str, level: str = "error", **more) -> dict:
    return {"level": level, "code": code, "detail": detail, **more}


class Phase6Ok(Phase6):
    """Two vessels (QA-1, QA-3) in a ready convoy; the ledger knows both stories, in progress."""

    def setUp(self):
        super().setUp()
        self.stories(**{"QA-1": "in-progress", "QA-3": "in-progress"})

    def stories(self, **states):
        os.environ["HARBOR_FAKE_STORIES"] = json.dumps(states)

    def checks(self, *diffs: dict):
        os.environ["HARBOR_FAKE_CHECK"] = json.dumps(list(diffs))

    def refused(self, res, code: str) -> str:
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(f"harbor: {code}: ", res.stderr)
        c = self.convoy()
        self.assertEqual(c["state"], "ready", "nothing changed")
        self.assertNotIn("ok", c)
        return res.stderr

    def round_ledger_lines(self, out: str) -> list[str]:
        return [l for l in out.splitlines() if l.startswith("ledger: ")]


class TestHRB3(Phase6Ok):
    def test_HRB_3_S1_a_difference_shows_in_the_round(self):
        self.checks(diff("UNATTRIBUTED", "abc1234 'fix: x': no Story:, Part-of: or No-story:"),
                    diff("STALE_BRANCH", "QA-9: in progress with no commit in 14 days", level="warning"))
        out = ok(harbor(self.a, "harbormaster", "control"))
        self.assertIn("ledger: UNATTRIBUTED abc1234 'fix: x': no Story:, Part-of: or No-story:", out)
        self.assertNotIn("STALE_BRANCH", out, "only the error-level differences")
        self.assertIn(["check", "--json"], self.ledger_calls())

    def test_HRB_3_S2_the_ok_for_a_convoy_with_a_vessel_whose_story_is_already_on_the_trunk_is_refused_with_LEDGER_DIFF(self):
        self.two_vessels_ready()
        self.stories(**{"QA-1": {"state": "on-trunk", "commit": "f" * 40}, "QA-3": "in-progress"})
        runs = self.runs()
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn("claude/qa-1", err)
        self.assertIn("DONE_TWICE: QA-1 is on-trunk", err)
        self.assertNotIn("claude/qa-3", err)
        self.assertEqual(self.runs(), runs, "no verify started")

    def test_HRB_3_S3_a_loose_move_lists_what_entered(self):
        before = self.repo.main_sha()
        ok(harbor(self.a, "harbormaster", "control"))
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "pull", "--quiet", "origin", "main")
        commits = []
        for path, message in (("hot.txt", "fix: hot\n\nStory: QA-4"), ("tidy.txt", "chore: tidy")):
            (self.a / path).write_text("x\n")
            sh(self.a, "git", "add", "-A")
            sh(self.a, "git", "commit", "--quiet", "-m", message)
            commits.append(sh(self.a, "git", "rev-parse", "HEAD"))
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.stories(**{"QA-4": {"state": "on-trunk", "commit": commits[0]},
                        "QA-1": {"state": "on-trunk", "commit": before}})
        self.checks(diff("UNATTRIBUTED", f"{commits[1][:7]} 'chore: tidy': no Story:, Part-of: or No-story:"),
                    diff("UNATTRIBUTED", f"{before[:7]} 'older': no Story:, Part-of: or No-story:"))
        out = ok(harbor(self.a, "harbormaster", "control"))
        loose = next(l for l in out.splitlines() if "a loose push, recorded" in l)
        self.assertIn("stories that entered: QA-4", loose)
        self.assertNotIn("QA-1", loose, "a story that entered before is not this move's")
        self.assertIn(f"unattributed: {commits[1][:9]}", loose)
        self.assertNotIn(before[:9], loose.split("unattributed:")[1], "an unattributed commit before the move")
        move = self.repo.log_toml("harbor/main.toml")["moves"][-1]
        self.assertEqual((move["cause"], move["stories"], move["unattributed"]), ("loose", ["QA-4"], [commits[1]]))


class TestHRB3S4(Phase6):
    """[S4] No ledger.py: the round says so once and goes on; the ok is 0.5's."""
    ledger = False

    def test_HRB_3_S4_without_ledger_py_the_round_says_so_and_goes_on(self):
        ok(harbor(self.a, "convoy", "new"))
        out = ok(harbor(self.a, "harbormaster", "control"))
        self.assertEqual(out.count("ledger: not available"), 1, out)
        self.assertIn("watch: acct1/mbp/s1", out)
        self.assertIn("convoy 1 · assembling", out)
        self.assertEqual(self.ledger_calls(), [])

    def test_without_ledger_py_the_ok_is_0_5s(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        self.assertEqual(self.convoy()["state"], "verifying")


class TestHRB3Ok(Phase6Ok):
    def setUp(self):
        super().setUp()
        self.two_vessels_ready()

    def test_the_ok_goes_through_when_the_ledger_finds_nothing(self):
        ok(self.ok_changed())
        self.assertEqual(self.convoy()["state"], "verifying")
        self.assertIn(["check", "--ci", "--json"], self.ledger_calls(), "main's ledger, as the CI reads")

    def test_an_unknown_story_is_refused(self):
        self.stories(**{"QA-3": "in-progress"})
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn("claude/qa-1", err)
        self.assertIn("UNKNOWN_STORY: QA-1", err)

    def test_a_story_whose_state_is_unknown_is_refused(self):
        self.stories(**{"QA-1": {"state": "unknown", "reason": "the history is cut"}, "QA-3": "in-progress"})
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn("QA-1", err)
        self.assertIn("the history is cut", err)

    def test_every_state_from_on_trunk_on_is_done_twice(self):
        for state in ("in-version", "in-staging", "in-production"):
            with self.subTest(state=state):
                self.stories(**{"QA-1": "in-progress", "QA-3": state})
                self.assertIn(f"DONE_TWICE: QA-3 is {state}", self.refused(self.ok_changed(), "LEDGER_DIFF"))

    def test_ids_compare_with_case_as_keelokits_do(self):
        """Keelokit's ids are case-sensitive (EPIC-NNN): a ledger story `qa-3` is not the vessel's QA-3."""
        self.stories(**{"QA-1": "in-progress", "qa-3": "in-progress"})
        self.assertIn("UNKNOWN_STORY: QA-3", self.refused(self.ok_changed(), "LEDGER_DIFF"))

    def test_a_ledger_listing_ids_that_differ_only_in_case_is_read_exactly(self):
        """Breaker round 1, F3: the first case variant must not hide the exact id's state."""
        os.environ["HARBOR_FAKE_STORIES_RAW"] = json.dumps([
            {"id": "QA-1", "state": "in-progress"}, {"id": "qa-3", "state": "in-progress"},
            {"id": "QA-3", "state": "on-trunk", "commit": "f" * 40}])
        self.assertIn("DONE_TWICE: QA-3", self.refused(self.ok_changed(), "LEDGER_DIFF"))

    def test_a_ledger_listing_one_id_twice_fails_closed(self):
        os.environ["HARBOR_FAKE_STORIES_RAW"] = json.dumps([
            {"id": "QA-1", "state": "in-progress"}, {"id": "QA-3", "state": "in-progress"},
            {"id": "QA-3", "state": "on-trunk", "commit": "f" * 40}])
        self.assertIn("QA-3", self.refused(self.ok_changed(), "LEDGER_UNAVAILABLE"))

    def test_an_unattributed_fix_on_the_convoy_branch_is_refused(self):
        """Breaker round 1, F4: an integrator's fix commit on convoy/<n> reaches main too."""
        sh(self.a, "git", "fetch", "--quiet", "origin")
        sh(self.a, "git", "checkout", "--quiet", "-B", "convoy/1", "origin/convoy/1")
        (self.a / "fix.txt").write_text("fix\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: make it build")
        fix = sh(self.a, "git", "rev-parse", "HEAD")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertEqual(self.convoy()["state"], "ready")
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn(f"UNATTRIBUTED: {fix[:9]}", err)
        self.assertIn("convoy/1", err)

    def test_a_done_twice_from_check_naming_the_story_is_refused_whatever_its_level(self):
        self.checks(diff("DONE_TWICE", "QA-3: Story: commits abc1234, def5678 arrived separately", level="warning"))
        self.assertIn("DONE_TWICE", self.refused(self.ok_changed(), "LEDGER_DIFF"))

    def test_a_difference_naming_a_longer_id_is_not_the_storys(self):
        self.checks(diff("DONE_TWICE", "QA-10: Story: commits abc1234, def5678 arrived separately", level="warning"),
                    diff("DONE_TWICE", "XQA-1: Story: commits abc1234, def5678 arrived separately", level="warning"))
        ok(self.ok_changed())

    def test_an_error_difference_with_the_story_field_is_refused_and_another_storys_is_not(self):
        self.checks(diff("CORRECTION_INVALID", "row 3: bad", story="QA-9"))
        ok(self.ok_changed())

    def test_an_error_difference_with_the_story_field_is_refused(self):
        self.checks(diff("CORRECTION_INVALID", "row 3: bad", story="QA-1"))
        self.assertIn("CORRECTION_INVALID", self.refused(self.ok_changed(), "LEDGER_DIFF"))

    def test_main_read_at_another_commit_fails_closed(self):
        os.environ["HARBOR_FAKE_TRUNK_SHA"] = "e" * 40
        self.assertIn("eeeeeeeee", self.refused(self.ok_changed(), "LEDGER_UNAVAILABLE"))

    def test_a_ledger_that_cannot_answer_json_fails_closed(self):
        for env in ({"HARBOR_FAKE_LEDGER": "sleep", "HARBOR_LEDGER_SECONDS": "1"}, {"HARBOR_FAKE_LEDGER": "bad"},
                    {"HARBOR_FAKE_LEDGER": "binary"}, {"HARBOR_FAKE_LEDGER": "exit2"},
                    {"HARBOR_FAKE_LEDGER": "true"}, {"HARBOR_FAKE_LEDGER": "null"}, {"HARBOR_FAKE_LEDGER": '"1"'},
                    {"HARBOR_FAKE_LEDGER": "huge", "HARBOR_LEDGER_MAX_BYTES": "100000"},
                    {"HARBOR_FAKE_STORIES_RAW": '"none"'}, {"HARBOR_FAKE_STORIES_RAW": '[{"id": 1, "state": "on-trunk"}]'},
                    {"HARBOR_FAKE_STORIES_RAW": '[{"id": "QA-1", "state": ["on-trunk"]}]'},
                    {"HARBOR_FAKE_TRUNK_SHA": ""}):
            with self.subTest(env=env):
                err = self.refused(self.ok_changed(env=env), "LEDGER_UNAVAILABLE")
                self.assertIn("fails closed", err)

    def test_a_check_that_cannot_answer_fails_closed(self):
        for mode in ("sleep", "bad", "binary", "exit2", '{"schema": 1, "diffs": "none"}', '{"schema": 2, "diffs": []}',
                     '[{"level": 1, "code": "X", "detail": "y"}]', '[{"level": "error", "code": "X"}]', '["x"]'):
            with self.subTest(mode=mode):
                env = {"HARBOR_FAKE_CHECK": mode, "HARBOR_LEDGER_SECONDS": "1"}
                self.refused(self.ok_changed(env=env), "LEDGER_UNAVAILABLE")

    def test_another_schema_is_no_ledger_the_ok_is_0_5s(self):
        ok(self.ok_changed(env={"HARBOR_FAKE_LEDGER": "2"}))
        self.assertEqual(self.convoy()["state"], "verifying")
        self.assertNotIn(["check", "--json"], self.ledger_calls())

    def test_a_vessel_redelivered_while_the_ledger_answers_is_not_okd(self):
        """The ok asks the ledger outside its transaction; the vessels it checked must be the ones it records."""
        b = self.repo.clone("b", host="linux")
        once = self.tmp / "redelivered"  # the judge asks check twice (main, the convoy as landed): one redelivery
        hook = (f"[ -e {once} ] || (cd {b} && touch {once} && git fetch -q origin harbor/log && "
                f"git checkout -q -B log origin/harbor/log && sed -i 's/^story = \"QA-1\"$/story = \"QA-1, QA-3\"/' "
                f"harbor/convoys/1.toml && git -c user.name=t -c user.email=t@example.com commit -qam 'a redelivery' && "
                f"git push -q origin log:harbor/log)")  # the judge's env has no GIT_AUTHOR_*: an identity of its own
        err = self.refused(self.ok_changed(env={"HARBOR_FAKE_CHECK_HOOK": hook}), "CONVOY_MOVED")
        self.assertIn("vessels changed", err)


class TestHRB3Vessels(Phase6Ok):
    """What the ok reads of the vessel's own commits."""

    def ready_with(self, *commits: tuple[str, str], at_add: dict | None = None):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        head = self.branch("claude/qa-1", *commits)
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1", env=at_add))
        self.deliver(1, "claude/qa-3", "apps/web/c.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        return head

    def test_an_unattributed_commit_in_the_vessel_is_refused(self):
        head = self.ready_with(("apps/web/a.ts", "feat: a\n\nStory: QA-1"), ("apps/web/b.ts", "fix: forgot"),
                               at_add={"HARBOR_FAKE_ATTRIBUTION": "usage"})
        for env in ({}, {"HARBOR_FAKE_ATTRIBUTION": "usage"}, {"HARBOR_FAKE_ATTRIBUTION": "bad"}):
            with self.subTest(env=env):
                err = self.refused(self.ok_changed(env=env), "LEDGER_DIFF")
                self.assertIn(f"UNATTRIBUTED: {head[:9]}", err)
                self.assertIn("claude/qa-1", err)

    def test_an_unknown_id_in_a_vessels_commit_is_refused(self):
        self.ready_with(("apps/web/a.ts", "feat: a\n\nStory: QA-1"), ("apps/web/b.ts", "feat: b\n\nPart-of: QA-77"),
                        at_add={"HARBOR_FAKE_ATTRIBUTION": "usage"})
        for env in ({}, {"HARBOR_FAKE_ATTRIBUTION": "usage"}):
            with self.subTest(env=env):
                self.assertIn("UNKNOWN_STORY: QA-77", self.refused(self.ok_changed(env=env), "LEDGER_DIFF"))

    def test_a_follow_up_with_part_of_a_story_on_the_trunk_is_not_done_twice(self):
        """Keelokit's DONE_TWICE counts Story: commits: a Part-of: follow-up of a done story is allowed."""
        self.ready_with(("apps/web/a.ts", "fix: a\n\nPart-of: QA-1"))
        self.stories(**{"QA-1": "on-trunk", "QA-3": "in-progress"})
        ok(self.ok_changed())
        self.assertEqual(self.convoy()["state"], "verifying")

    def test_the_part_of_follow_up_is_allowed_from_the_trailers_too(self):
        self.ready_with(("apps/web/a.ts", "fix: a\n\nPart-of: QA-1"))
        self.stories(**{"QA-1": "on-trunk", "QA-3": "in-progress"})
        ok(self.ok_changed(env={"HARBOR_FAKE_ATTRIBUTION": "usage"}))

    def test_a_merge_in_the_vessel_closing_a_story_on_the_trunk_is_done_twice(self):
        """Breaker round 1, F1: Keelokit counts a merge's Story: too."""
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.branch("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nPart-of: QA-1"))
        sh(self.a, "git", "checkout", "--quiet", "-b", "sub")
        (self.a / "apps/web/s.ts").write_text("s\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "feat: s\n\nPart-of: QA-1")
        sh(self.a, "git", "checkout", "--quiet", "claude/qa-1")
        sh(self.a, "git", "merge", "--quiet", "--no-ff", "-m", "feat: finish QA-1\n\ndone\n\nStory: QA-1", "sub")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-1")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        self.deliver(1, "claude/qa-3", "apps/web/c.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.stories(**{"QA-1": {"state": "on-trunk", "commit": "f" * 40}, "QA-3": "in-progress"})
        for env in ({}, {"HARBOR_FAKE_ATTRIBUTION": "usage"}):
            with self.subTest(env=env):
                self.assertIn("DONE_TWICE: QA-1", self.refused(self.ok_changed(env=env), "LEDGER_DIFF"))

    def test_a_lowercase_story_trailer_is_not_the_story(self):
        """Breaker round 1, F2: `Story: qa-1` is no id to Keelokit (STORY_ID is upper case)."""
        self.ready_with(("apps/web/a.ts", "feat: a\n\nStory: qa-1"), at_add={"HARBOR_FAKE_ATTRIBUTION": "usage"})
        self.assertEqual(self.convoy()["state"], "waiting", "QA-1 is expected and qa-1 is not it")
        res = self.ok_changed()
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("harbor: LEDGER_DIFF: ", res.stderr)
        self.assertIn("UNKNOWN_STORY: qa-1", res.stderr)
        self.assertNotIn("ok", self.convoy())

    def test_a_closing_commit_of_a_story_on_the_trunk_is_done_twice_under_another_vessel_story(self):
        self.ready_with(("apps/web/a.ts", "feat: a\n\nStory: QA-1"), ("apps/web/b.ts", "feat: b\n\nStory: QA-5"))
        self.stories(**{"QA-1": "in-progress", "QA-3": "in-progress", "QA-5": "in-production"})
        self.assertIn("DONE_TWICE: QA-5", self.refused(self.ok_changed(), "LEDGER_DIFF"))


class TestHRB3Round(Phase6Ok):
    def test_five_differences_are_five_lines(self):
        self.checks(*(diff("UNATTRIBUTED", f"c{i}") for i in range(5)), diff("X", "w", level="warning"))
        lines = self.round_ledger_lines(ok(harbor(self.a, "harbormaster", "control")))
        self.assertEqual(lines, [f"ledger: UNATTRIBUTED c{i}" for i in range(5)])

    def test_six_differences_are_four_lines_and_the_rest_counted(self):
        self.checks(*(diff("UNATTRIBUTED", f"c{i}") for i in range(6)))
        lines = self.round_ledger_lines(ok(harbor(self.a, "harbormaster", "control")))
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[:4], [f"ledger: UNATTRIBUTED c{i}" for i in range(4)])
        self.assertTrue(lines[4].startswith("ledger: (+2 more"), lines[4])
        self.assertIn("ledger.py check", lines[4])

    def test_no_error_difference_says_nothing(self):
        self.checks(diff("STALE_BRANCH", "QA-9", level="warning"))
        self.assertEqual(self.round_ledger_lines(ok(harbor(self.a, "harbormaster", "control"))), [])

    def test_a_hostile_detail_is_one_short_line(self):
        self.checks(diff("UNATTRIBUTED\nwatch: forged", "a\nwatch: forged\x1b[31m" + "x" * 5000))
        out = ok(harbor(self.a, "harbormaster", "control"))
        self.assertEqual([l for l in out.splitlines() if l.startswith("watch: ")][1:], [], "no forged line")
        self.assertNotIn("\x1b", out)
        line = self.round_ledger_lines(out)[0]
        self.assertLessEqual(len(line), 240)

    def test_a_check_that_cannot_answer_is_one_line_and_the_round_goes_on(self):
        ok(harbor(self.a, "convoy", "new"))
        for mode in ("sleep", "bad", "binary", "exit2", '["x"]'):
            with self.subTest(mode=mode):
                out = ok(harbor(self.a, "harbormaster", "control",
                                env={"HARBOR_FAKE_CHECK": mode, "HARBOR_LEDGER_SECONDS": "1"}))
                lines = self.round_ledger_lines(out)
                self.assertEqual(len(lines), 1, out)
                self.assertIn("not available", lines[0])
                self.assertIn("convoy 1 · assembling", out)

    def test_a_ledger_whose_json_cannot_answer_is_one_line_and_the_round_goes_on(self):
        out = ok(harbor(self.a, "harbormaster", "control", env={"HARBOR_FAKE_LEDGER": "sleep", "HARBOR_LEDGER_SECONDS": "1"}))
        self.assertEqual(len(self.round_ledger_lines(out)), 1, out)
        self.assertIn("watch: acct1/mbp/s1", out)

    def test_a_loose_move_without_an_answer_says_so(self):
        ok(harbor(self.a, "harbormaster", "control"))
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "pull", "--quiet", "origin", "main")
        (self.a / "hot.txt").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: hot")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        out = ok(harbor(self.a, "harbormaster", "control", env={"HARBOR_FAKE_LEDGER": "bad"}))
        loose = next(l for l in out.splitlines() if "a loose push, recorded" in l)
        self.assertIn("ledger", loose)
        self.assertNotIn("stories", self.repo.log_toml("harbor/main.toml")["moves"][-1])


class TestHRB3Breaker2(Phase6Ok):
    """Breaker round 2: a story id that can't be written, case in check's story field, a ledger.py that isn't a file."""

    def test_a_story_id_that_is_not_one_plain_word_is_no_answer_and_the_round_completes(self):
        ok(harbor(self.a, "harbormaster", "control"))
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "pull", "--quiet", "origin", "main")
        (self.a / "hot.txt").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: hot\n\nStory: QA-4")
        c = sh(self.a, "git", "rev-parse", "HEAD")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        os.environ["HARBOR_FAKE_STORIES_RAW"] = '[{"id": "QA-\\ud800", "state": "on-trunk", "commit": "%s"}]' % c
        res = harbor(self.a, "harbormaster", "control")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(len(self.round_ledger_lines(res.stdout)), 1, res.stdout)
        self.assertNotIn("stories", self.repo.log_toml("harbor/main.toml")["moves"][-1])

    def test_a_story_id_that_is_not_one_plain_word_fails_the_ok_closed(self):
        self.two_vessels_ready()
        os.environ["HARBOR_FAKE_STORIES_RAW"] = json.dumps([{"id": "QA-1", "state": "in-progress"},
                                                            {"id": "QA-3", "state": "in-progress"},
                                                            {"id": "QA 9\n", "state": "on-trunk"}])
        self.refused(self.ok_changed(), "LEDGER_UNAVAILABLE")

    def test_a_check_difference_naming_another_case_of_the_id_is_not_the_storys(self):
        self.two_vessels_ready()
        self.stories(**{"QA-1": "in-progress", "QA-3": "in-progress", "qa-1": "in-progress"})
        self.checks(diff("X", "something about qa-1", story="qa-1"),
                    diff("DONE_TWICE", "qa-3: Story: commits abc1234, def5678 arrived separately", level="warning"))
        ok(self.ok_changed())

    def test_a_ledger_py_on_main_that_is_not_a_file_fails_the_ok_closed(self):
        """The ok judges with main's ledger: main's ledger.py a dangling link is a ledger that can't answer."""
        tool = self.a / ".keelokit/bin/ledger.py"
        sh(self.a, "git", "checkout", "--quiet", "main")
        tool.unlink()
        tool.symlink_to("/nonexistent/ledger.py")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "a broken ledger", "-m", "No-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.two_vessels_ready()
        self.refused(self.ok_changed(), "LEDGER_UNAVAILABLE")

    def test_a_ledger_py_in_the_checkout_that_is_not_a_file_is_one_line_in_the_round(self):
        tool = self.a / ".keelokit/bin/ledger.py"
        tool.unlink()
        tool.mkdir()
        out = ok(harbor(self.a, "harbormaster", "control"))
        self.assertEqual(len(self.round_ledger_lines(out)), 1, out)
        self.assertIn("not available", self.round_ledger_lines(out)[0])


class TestHRB3Breaker3(Phase6Ok):
    """Breaker round 3: separators forged in a commit message must not hide an unattributed commit."""

    def forged(self, message: str, n: int) -> str:
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        branch = f"claude/qa-1-{n}"
        self.branch(branch, ("apps/web/a.ts", "feat: a\n\nStory: QA-1"))
        (self.a / "apps/web/evil.ts").write_text("evil\n")
        sh(self.a, "git", "add", "-A")
        msg = self.tmp / "msg"
        msg.write_bytes(message.encode())
        sh(self.a, "git", "commit", "--quiet", "--cleanup=verbatim", "-F", str(msg))
        evil = sh(self.a, "git", "rev-parse", "HEAD")
        sh(self.a, "git", "push", "--quiet", "origin", branch)
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", str(n), branch, env={"HARBOR_FAKE_ATTRIBUTION": "usage"}))
        self.deliver(n, f"claude/qa-3-{n}", "apps/web/b.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", str(n)))
        return evil

    def test_a_subject_forging_records_does_not_hide_an_unattributed_commit(self):
        for n, forge in enumerate(("fix: sneaky\x1fQA-1\x1f\x1f\x1fend\x1e" + "f" * 40 + "\x1fa b\x1fx\n",
                      "fix: sneaky\x1e" + "f" * 40 + "\x1e\x1f\x1f\n"), start=1):
            with self.subTest(forge=forge):
                evil = self.forged(forge, n)
                res = self.ok_changed(n, env={"HARBOR_FAKE_ATTRIBUTION": "usage"})
                self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
                self.assertIn(f"UNATTRIBUTED: {evil[:9]}", res.stderr)
                self.assertNotIn("ok", self.convoy(n))
                ok(harbor(self.a, "convoy", "abort", str(n), "--reason", "next forge"))


class TestHRB3Judge(Phase6Ok):
    """The coordinator's breaker on 88f5aab: the judge is main's ledger, run on the convoy as if it had landed, and the
    ok is bound to the exact convoy tip."""

    def vessel_branch(self, name: str, *commits: tuple[str, str], at_add: dict | None = None, n: int = 1) -> str:
        head = self.branch(name, *commits)
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", str(n), name, env=at_add))
        return head

    def test_A2_a_vessel_that_deletes_the_ledger_is_judged_by_mains(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.branch("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nStory: QA-1"))
        sh(self.a, "git", "rm", "--quiet", ".keelokit/bin/ledger.py")
        sh(self.a, "git", "commit", "--quiet", "-m", "chore: no ledger")
        late = sh(self.a, "git", "rev-parse", "HEAD")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-1")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        self.deliver(1, "claude/qa-3", "apps/web/c.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertFalse((self.a / ".keelokit/bin/ledger.py").exists(), "the checkout is the convoy's, without it")
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn(f"UNATTRIBUTED: {late[:9]}", err)

    def test_A2b_a_vessel_whose_ledger_answers_another_schema_or_nothing_is_judged_by_mains(self):
        for n, body in enumerate(('import json; print(json.dumps({"schema": 2}))',
                                  'import json, sys\nprint(json.dumps({"schema": 1, "trunk_sha": "", "stories": [], '
                                  '"diffs": []}))'), start=1):
            with self.subTest(body=body):
                ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
                self.branch(f"claude/qa-1-{n}", ("apps/web/a.ts", "feat: a\n\nStory: QA-1"))
                (self.a / ".keelokit/bin/ledger.py").write_text(body + "\n")
                sh(self.a, "git", "commit", "--quiet", "-am", "chore: my own ledger")
                late = sh(self.a, "git", "rev-parse", "HEAD")
                sh(self.a, "git", "push", "--quiet", "origin", f"claude/qa-1-{n}")
                ok(harbor(self.a, "seal"))
                harbor(self.a, "convoy", "add", str(n), f"claude/qa-1-{n}")
                self.deliver(n, f"claude/qa-3-{n}", "apps/web/c.ts", "QA-3")
                ok(harbor(self.a, "convoy", "assemble", str(n)))
                res = self.ok_changed(n)
                self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
                self.assertIn("harbor: LEDGER_DIFF: ", res.stderr)
                self.assertIn(f"UNATTRIBUTED: {late[:9]}", res.stderr)
                self.assertNotIn("ok", self.convoy(n))
                ok(harbor(self.a, "convoy", "abort", str(n), "--reason", "next"))

    def test_A1_a_commit_after_the_ok_voids_it(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        before = self.repo.main_sha()
        sh(self.a, "git", "fetch", "--quiet", "origin")
        sh(self.a, "git", "checkout", "--quiet", "-B", "convoy/1", "origin/convoy/1")
        (self.a / "late.txt").write_text("late\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: late, no trailer")
        late = sh(self.a, "git", "rev-parse", "HEAD")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertIn("stale", self.convoy()["ok"])
        res = harbor(self.a, "convoy", "sail", "1")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("harbor: OK_STALE: ", res.stderr)
        self.assertEqual(self.repo.main_sha(), before, "main did not move")
        res = self.ok_changed()
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("harbor: LEDGER_DIFF: ", res.stderr)
        self.assertIn(f"UNATTRIBUTED: {late[:9]}", res.stderr)

    def test_a_fix_after_the_ok_sails_once_a_new_ok_checks_it(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        sh(self.a, "git", "fetch", "--quiet", "origin")
        sh(self.a, "git", "checkout", "--quiet", "-B", "convoy/1", "origin/convoy/1")
        (self.a / "late.txt").write_text("late\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: late\n\nPart-of: QA-1")
        tip = sh(self.a, "git", "rev-parse", "HEAD")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertIn("OK_STALE", harbor(self.a, "convoy", "sail", "1").stderr)
        ok(self.ok_changed())
        self.assertEqual((self.convoy()["ok"]["head"], self.convoy()["state"]), (tip, "verifying"))
        self.assertNotIn("stale", self.convoy()["ok"])
        ok(harbor(self.a, "convoy", "verify", "1"))
        ok(harbor(self.a, "convoy", "sail", "1"))
        self.assertEqual(self.repo.main_sha(), tip)

    def test_A3_two_vessels_closing_one_story_are_a_done_twice_on_main(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1"))
        self.vessel_branch("claude/qa-1a", ("apps/web/a.ts", "feat: a\n\nStory: QA-1"))
        self.vessel_branch("claude/qa-1b", ("apps/web/b.ts", "feat: b\n\nStory: QA-1"))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn("DONE_TWICE", err)
        self.assertIn("QA-1", err)

    def since_ready(self, *qa1: tuple[str, str]):
        os.environ["HARBOR_FAKE_SINCE"] = self.repo.main_sha()
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.vessel_branch("claude/qa-1", *qa1)
        self.vessel_branch("claude/qa-3", ("apps/web/c.ts", "feat: c\n\nThe change.\n\nStory: QA-3"))
        ok(harbor(self.a, "convoy", "assemble", "1"))

    def test_F4_a_no_story_category_keelokit_refuses_is_refused(self):
        self.since_ready(("apps/web/a.ts", "feat: a\n\nThe change.\n\nStory: QA-1"),
                         ("apps/web/b.ts", "chore: b\n\nNo-story: anything goes"))
        self.assertIn("BAD_CATEGORY", self.refused(self.ok_changed(), "LEDGER_DIFF"))

    def test_F4_a_story_commit_with_no_body_is_refused(self):
        self.since_ready(("apps/web/a.ts", "feat: a\n\nStory: QA-1"))
        self.assertIn("STORY_NO_BODY", self.refused(self.ok_changed(), "LEDGER_DIFF"))

    def test_a_convoy_that_follows_keelokits_rules_passes_with_since(self):
        self.since_ready(("apps/web/a.ts", "feat: a\n\nThe change.\n\nStory: QA-1"),
                         ("apps/web/b.ts", "docs: b\n\nNo-story: docs"))
        ok(self.ok_changed())
        self.assertEqual(self.convoy()["ok"]["ledger"], "checked")

    def test_a_difference_main_already_has_is_not_the_convoys(self):
        os.environ["HARBOR_FAKE_SINCE"] = self.repo.main_sha()
        sh(self.a, "git", "checkout", "--quiet", "main")
        (self.a / "old.txt").write_text("old\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "chore: on main already, no trailer")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.vessel_branch("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nThe change.\n\nStory: QA-1"))
        self.vessel_branch("claude/qa-3", ("apps/web/c.ts", "feat: c\n\nThe change.\n\nStory: QA-3"))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        ok(self.ok_changed())


class TestHRB3Coordinator(Phase6Ok):
    """The coordinator's additions: Keelokit's own rules whatever level they come at; a bounded timeout."""

    def test_a_bad_category_at_warning_level_is_still_the_convoys(self):
        os.environ["HARBOR_FAKE_SINCE"] = self.repo.main_sha()
        os.environ["HARBOR_FAKE_WARN"] = "1"  # the fake's enforce = "warn": BAD_CATEGORY and STORY_NO_BODY are warnings
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        for name, commits in (("claude/qa-1", (("apps/web/a.ts", "feat: a\n\nThe change.\n\nStory: QA-1"),
                                               ("apps/web/b.ts", "chore: b\n\nNo-story: anything goes"))),
                              ("claude/qa-3", (("apps/web/c.ts", "feat: c\n\nStory: QA-3"),))):
            self.branch(name, *commits)
            ok(harbor(self.a, "seal"))
            ok(harbor(self.a, "convoy", "add", "1", name))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn("BAD_CATEGORY", err)
        self.assertIn("STORY_NO_BODY", err)

    def test_the_timeout_is_bounded(self):
        mod = load_module()
        for value in ("nan", "inf", "-inf", "0", "-5", "junk", ""):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"HARBOR_LEDGER_SECONDS": value}):
                self.assertEqual(mod.ledger_seconds(), mod.LEDGER_SECONDS)
        with mock.patch.dict(os.environ, {"HARBOR_LEDGER_SECONDS": "1e9"}):
            self.assertEqual(mod.ledger_seconds(), mod.LEDGER_MAX_SECONDS)
        with mock.patch.dict(os.environ, {"HARBOR_LEDGER_SECONDS": "2.5"}):
            self.assertEqual(mod.ledger_seconds(), 2.5)


PWN_LEDGER = """import json, os, sys
open(os.environ["PWN_MARK"], "a").write("CONVOY CODE RAN " + " ".join(sys.argv[1:]) + "\\n")
print(json.dumps({"schema": 1, "diffs": []})); sys.exit(0)
"""


class TestHRB3Breaker4(Phase6Ok):
    """Breaker on ad486dc: a link in main's .keelokit/bin must not run the convoy's code; refs the judge's clone copies
    must not lock every ok out."""

    def test_a_link_in_mains_bin_never_runs_the_convoys_code(self):
        sh(self.a, "git", "checkout", "--quiet", "main")
        lib = self.a / ".keelokit/lib"
        lib.mkdir(parents=True, exist_ok=True)
        (lib / "impl.py").write_text(FAKE_LEDGER)
        (self.a / ".keelokit/bin/ledger.py").unlink()
        os.symlink("../lib/impl.py", self.a / ".keelokit/bin/ledger.py")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "ledger via a link", "-m", "No-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        os.environ["PWN_MARK"] = str(self.tmp / "mark")
        os.environ["HARBOR_FAKE_SINCE"] = self.repo.main_sha()
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.branch("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nThe change.\n\nStory: QA-1"),
                    ("apps/web/b.ts", "chore: b\n\nNo-story: anything goes"))
        (self.a / ".keelokit/lib/impl.py").write_text(PWN_LEDGER)
        sh(self.a, "git", "commit", "--quiet", "-am", "chore: tidy\n\nNo-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-1")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        self.branch("claude/qa-3", ("apps/web/c.ts", "feat: c\n\nThe change.\n\nStory: QA-3"))
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-3"))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        mark = self.tmp / "mark"
        mark.unlink(missing_ok=True)  # add and assemble run the checkout's ledger, as in HRB-1: only the ok is the judge
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn("BAD_CATEGORY", err)
        self.assertFalse(mark.exists(), "the convoy's code ran as the ok's judge")

    def test_a_link_in_mains_bin_out_of_the_tree_fails_closed(self):
        sh(self.a, "git", "checkout", "--quiet", "main")
        (self.a / ".keelokit/bin/ledger.py").unlink()
        os.symlink("../../../outside.py", self.a / ".keelokit/bin/ledger.py")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "a link out", "-m", "No-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.two_vessels_ready()
        self.refused(self.ok_changed(), "LEDGER_UNAVAILABLE")

    def ok_despite(self):
        self.two_vessels_ready()
        res = self.ok_changed()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.convoy()["ok"]["ledger"], "checked")

    def test_a_remote_branch_whose_name_is_not_utf8_does_not_lock_the_ok_out(self):
        subprocess.run([b"git", b"update-ref", b"refs/heads/claude/caf\xe9", self.repo.main_sha().encode()],
                       cwd=self.repo.remote, check=True)
        sh(self.a, "git", "fetch", "--quiet", "origin")
        self.ok_despite()

    def test_a_local_branch_and_a_remote_one_below_it_do_not_lock_the_ok_out(self):
        sh(self.a, "git", "branch", "topic", self.repo.main_sha())
        sh(self.repo.remote, "git", "update-ref", "refs/heads/topic/x", self.repo.main_sha())
        sh(self.a, "git", "fetch", "--quiet", "origin")
        self.ok_despite()


class TestHRB3Breaker5(Phase6Ok):
    """Breaker on d6dd828: a message git prints in another encoding, the clone's own branch below the trunk's name,
    a link at directory level in main's tree."""

    def test_a_message_that_is_not_utf8_is_no_traceback(self):
        self.two_vessels_ready()
        sh(self.a, "git", "fetch", "--quiet", "origin")
        sh(self.a, "git", "checkout", "--quiet", "-B", "convoy/1", "origin/convoy/1")
        (self.a / "fix.txt").write_text("fix\n")
        sh(self.a, "git", "add", "-A")
        msg = self.tmp / "msg"
        msg.write_bytes(b"fix: caf\xe9 build\n\nPart-of: QA-1\n")
        sh(self.a, "git", "-c", "i18n.commitEncoding=x-bogus", "commit", "--quiet", "-F", str(msg))
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        res = self.ok_changed()
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_the_clones_own_branch_below_the_trunks_name_does_not_lock_the_ok_out(self):
        self.two_vessels_ready()
        sh(self.a, "git", "branch", "-D", "main")
        sh(self.a, "git", "checkout", "--quiet", "-B", "main/wip", "origin/main")
        res = self.ok_changed()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.convoy()["ok"]["ledger"], "checked")

    def test_a_link_at_directory_level_in_main_is_resolved_in_mains_tree(self):
        sh(self.a, "git", "checkout", "--quiet", "main")
        real = self.a / "tools/kkbin"
        real.mkdir(parents=True)
        (real / "ledger.py").write_text(FAKE_LEDGER)
        sh(self.a, "git", "rm", "-q", "-r", ".keelokit/bin")
        os.symlink("../tools/kkbin", self.a / ".keelokit/bin")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "bin via a link", "-m", "No-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.stories(**{"QA-3": "in-progress"})  # QA-1 unknown: main's ledger refuses it
        self.two_vessels_ready()
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn("UNKNOWN_STORY: QA-1", err)
        self.assertIn(["check", "--ci", "--json"], self.ledger_calls())

    def test_a_link_at_directory_level_out_of_mains_tree_fails_closed(self):
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "rm", "-q", "-r", ".keelokit/bin")
        os.symlink("/usr/lib", self.a / ".keelokit/bin")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "bin out of the tree", "-m", "No-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.two_vessels_ready()
        self.refused(self.ok_changed(), "LEDGER_UNAVAILABLE")


class TestHRB3RulesRef(Phase6Ok):
    """Phase 6 follow-up (Keelokit LEDGER-013): the judge passes `--rules-ref <main tip>` to `check` whenever main's
    ledger supports it, so every rule file (critical.toml, the corrections, the approval, the review files) comes from
    main's committed tree, never the convoy's. Supported means: main's ledger, in the judge's clone of main, answers
    `check --ci --rules-ref <main tip> --json`; a ledger that doesn't answer it but whose `check --help` names
    --rules-ref fails the ok closed; one that doesn't name it is Keelokit 0.16.0, judged as before."""

    def setUp(self):
        super().setUp()
        os.environ["HARBOR_FAKE_RULES_REF"] = "1"
        self.mark = self.tmp / "pwn.mark"
        os.environ["PWN_MARK"] = str(self.mark)

    def on_main(self, path: str, text: str) -> str:
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "pull", "--quiet", "--ff-only", "origin", "main")
        f = self.a / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", f"chore: {path}", "-m", "No-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        return self.repo.main_sha()

    def vessel_branch(self, name: str, *commits: tuple[str, str], extra=None) -> str:
        """A pushed vessel from main: one commit per (path, message); `extra(checkout)` runs before the last commit
        is pushed, its changes committed with the vessel's last message's trailers."""
        self.branch(name, *commits)
        if extra:
            extra(self.a)
            sh(self.a, "git", "add", "-A")
            sh(self.a, "git", "commit", "--quiet", "-m", f"chore: {name} rules", "-m", "No-story: harness")
            sh(self.a, "git", "push", "--quiet", "origin", name)
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", name))
        return sh(self.a, "git", "rev-parse", name)

    def critical_convoy(self, relax: bool = True):
        """main says apps/api/ is critical; QA-1's vessel touches it with no review and empties critical.toml."""
        main_tip = self.on_main(".keelokit/critical.toml", 'path = "apps/api/"\n')
        os.environ["HARBOR_FAKE_SINCE"] = main_tip
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        relaxed = (lambda d: (d / ".keelokit/critical.toml").write_text("# nothing is critical\n")) if relax else None
        self.vessel_branch("claude/qa-1", ("apps/api/a.ts", "feat: a\n\nThe change.\n\nStory: QA-1"), extra=relaxed)
        self.vessel_branch("claude/qa-3", ("apps/web/c.ts", "feat: c\n\nThe change.\n\nStory: QA-3"))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        return main_tip

    def rules_ref_checks(self, main_tip: str) -> list[list[str]]:
        return [c for c in self.ledger_calls() if c[:1] == ["check"] and "--rules-ref" in c
                and c[c.index("--rules-ref") + 1] == main_tip]

    def test_HRB_3_RR1_the_ok_passes_rules_ref_main_tip_to_both_checks(self):
        self.two_vessels_ready()
        main_tip = self.repo.main_sha()
        res = ok(self.ok_changed())
        calls = self.rules_ref_checks(main_tip)
        self.assertEqual(len(calls), 2, self.ledger_calls())  # main as it is, and the convoy as landed
        self.assertTrue(all("--ci" in c and c[-1] == "--json" for c in calls), calls)
        self.assertFalse([c for c in self.ledger_calls() if c[:1] == ["check"] and "--rules-ref" not in c
                          and c != ["check", "--help"]], "no check without --rules-ref when main's ledger has it")
        self.assertIn(f"rules from {main_tip[:9]}", res)
        self.assertEqual(self.convoy()["ok"]["ledger"], "checked")

    def test_HRB_3_RR2_a_convoy_that_relaxes_critical_toml_is_judged_by_mains(self):
        self.critical_convoy()
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn("as landed, by main's ledger: CRITICAL_UNREVIEWED", err)
        self.assertIn("apps/api/", err)

    def test_HRB_3_RR3_without_rules_ref_the_ok_is_as_before_and_reads_the_convoys_rules(self):
        os.environ["HARBOR_FAKE_RULES_REF"] = ""  # Keelokit 0.16.0: check knows no --rules-ref
        self.critical_convoy()
        main_tip = self.repo.main_sha()
        res = ok(self.ok_changed())  # the documented residual: the convoy's critical.toml is read
        checks = [c for c in self.ledger_calls() if c[:1] == ["check"]]
        # the probe (usage, exit 2), the help, then main and the convoy as landed as before
        self.assertEqual(checks, [["check", "--ci", "--rules-ref", main_tip, "--json"], ["check", "--help"],
                                  ["check", "--ci", "--json"], ["check", "--ci", "--json"]])
        self.assertIn("no check --rules-ref", res)

    def test_HRB_3_RR4_a_correction_row_the_convoy_adds_attributes_nothing(self):
        main_tip = self.repo.main_sha()
        os.environ["HARBOR_FAKE_SINCE"] = main_tip
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.vessel_branch("claude/qa-1", ("apps/web/a.ts", "feat: a\n\nThe change.\n\nStory: QA-1"))
        self.vessel_branch("claude/qa-3", ("apps/web/c.ts", "feat: c\n\nThe change.\n\nStory: QA-3"))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        sh(self.a, "git", "fetch", "--quiet", "origin")
        sh(self.a, "git", "checkout", "--quiet", "-B", "convoy/1", "origin/convoy/1")
        (self.a / "fix.txt").write_text("fix\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: the integrator's, no trailer")
        late = sh(self.a, "git", "rev-parse", "HEAD")
        (self.a / "backlog").mkdir(exist_ok=True)
        (self.a / "backlog/ledger-corrections.toml").write_text(f'[[row]]\ncommit = "{late}"\nstory = "QA-1"\n')
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "chore: my own correction", "-m", "No-story: harness")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        landed = err.split("as landed, by main's ledger: ", 1)[1]
        self.assertIn(f"UNATTRIBUTED: {late[:9]}", landed)

    def test_HRB_3_RR5_the_convoys_own_ledger_cannot_turn_rules_ref_off(self):
        main_tip = self.repo.main_sha()
        os.environ["HARBOR_FAKE_SINCE"] = main_tip
        self.on_main(".keelokit/critical.toml", 'path = "apps/api/"\n')
        main_tip = self.repo.main_sha()
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))

        def own_ledger(d):  # a ledger that knows no --rules-ref and finds nothing; it marks that it ran
            (d / ".keelokit/bin/ledger.py").write_text(PWN_LEDGER)
            (d / ".keelokit/critical.toml").write_text("")
        self.vessel_branch("claude/qa-1", ("apps/api/a.ts", "feat: a\n\nThe change.\n\nStory: QA-1"), extra=own_ledger)
        self.vessel_branch("claude/qa-3", ("apps/web/c.ts", "feat: c\n\nThe change.\n\nStory: QA-3"))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.mark.unlink(missing_ok=True)  # the checkout's ledger is the convoy's for add and the round; not for the ok
        err = self.refused(self.ok_changed(), "LEDGER_DIFF")
        self.assertIn("as landed, by main's ledger: CRITICAL_UNREVIEWED", err)
        self.assertEqual(len(self.rules_ref_checks(main_tip)), 2, self.ledger_calls())
        self.assertFalse(self.mark.exists() and "CONVOY CODE RAN" in self.mark.read_text(), "the convoy's ledger ran")

    def test_HRB_3_RR6_a_ledger_that_names_rules_ref_but_cannot_answer_it_fails_closed(self):
        self.two_vessels_ready()
        os.environ["HARBOR_FAKE_RULES_REF"] = "broken"
        err = self.refused(self.ok_changed(), "LEDGER_UNAVAILABLE")
        self.assertIn("--rules-ref", err)
        self.assertFalse([c for c in self.ledger_calls() if c[:1] == ["check"] and "--rules-ref" not in c
                          and c != ["check", "--help"]], "never a fallback to the convoy's rules")

    def test_HRB_3_RR7_the_landed_check_refusing_rules_ref_fails_closed(self):
        self.two_vessels_ready()
        os.environ["HARBOR_FAKE_RULES_REF"] = "landed-exit2"
        err = self.refused(self.ok_changed(), "LEDGER_UNAVAILABLE")
        self.assertIn("as landed", err)
        self.assertFalse([c for c in self.ledger_calls() if c[:1] == ["check"] and "--rules-ref" not in c
                          and c != ["check", "--help"]], "never a fallback to the convoy's rules")

    def test_HRB_3_RR8_a_help_that_never_answers_fails_closed(self):
        self.two_vessels_ready()
        os.environ.update(HARBOR_FAKE_RULES_REF="help-sleep", HARBOR_FAKE_CHECK="exit2", HARBOR_LEDGER_SECONDS="2")
        self.refused(self.ok_changed(), "LEDGER_UNAVAILABLE")

    def test_HRB_3_RR9_the_round_never_passes_rules_ref(self):
        ok(harbor(self.a, "harbormaster", "control"))
        self.assertIn(["check", "--json"], self.ledger_calls())  # the round reads the checkout's, as before
        self.assertFalse([c for c in self.ledger_calls() if "--rules-ref" in c], self.ledger_calls())


# Keelokit's `ledger.py take <ID>` with Harbor (LEDGER-013, its run_harbor/harbor_take_ready on main fc9692f), as far as
# it reaches Harbor: `git config --local harbor.py`, the probe `story take --help` (exit 0), then `story take <ID>` run
# with `-E -s`, CLAUDE_PROJECT_DIR the checkout, no stdin, and the session only in the environment: HARBOR_SESSION or
# CLAUDE_SESSION_ID as they are, else CLAUDE_CODE_SESSION_ID handed over as HARBOR_SESSION. Exit 1 relays Harbor's
# `harbor: CODE: why` line.
KEELOKIT_TAKE = r"""
import os, re, subprocess, sys
tool = subprocess.run(["git", "config", "--local", "--get", "harbor.py"], capture_output=True, text=True).stdout.strip()
assert os.path.isabs(tool) and os.path.basename(tool) == "harbor.py", tool
root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
env = {**os.environ, "CLAUDE_PROJECT_DIR": root}
if not (env.get("HARBOR_SESSION") or env.get("CLAUDE_SESSION_ID")) \
        and re.fullmatch(r"[A-Za-z0-9._-]{1,200}", env.get("CLAUDE_CODE_SESSION_ID", "")):
    env["HARBOR_SESSION"] = env["CLAUDE_CODE_SESSION_ID"]
def run(*args):
    return subprocess.run([sys.executable, "-E", "-s", tool, *args], cwd=root, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True)
probe = run("story", "take", "--help")
if probe.returncode != 0:
    print("no story take", probe.returncode); sys.exit(3)
res = run("story", "take", sys.argv[1])
lines = [l.strip() for l in (res.stderr + "\n" + res.stdout).splitlines() if l.strip()]
coded = [l for l in lines if re.fullmatch(r"harbor: [A-Z][A-Z0-9_]*: .*", l)]
print(coded[0] if coded else (lines[-1] if lines else ""))
sys.exit(0 if res.returncode == 0 else 1 if res.returncode == 1 else 2)
"""


class TestHRB2KeelokitTake(Phase6Lock):
    """Phase 6 follow-up: the session Keelokit's `ledger.py take` hands over is the one Harbor records."""

    def setUp(self):
        super().setUp()
        for clone in (self.a, self.b):
            ok(harbor(clone, "check"))  # SessionStart records `git config --local harbor.py`
        self.take_py = self.tmp / "keelokit_take.py"
        self.take_py.write_text(KEELOKIT_TAKE)

    def keelokit_take(self, clone, story: str, **session):
        env = {k: v for k, v in os.environ.items()
               if k not in ("HARBOR_SESSION", "CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
        return subprocess.run([sys.executable, str(self.take_py), story], cwd=clone, capture_output=True, text=True,
                              env={**env, **GIT_ENV, "HARBOR_NOW": NOW, **session})

    def test_HRB_2_K1_session_start_records_the_absolute_harbor_py_keelokit_runs(self):
        for clone in (self.a, self.b):
            self.assertEqual(sh(clone, "git", "config", "--local", "--get", "harbor.py"), str(HARBOR.resolve()))
        self.assertEqual(subprocess.run([sys.executable, str(HARBOR), "story", "take", "--help"], cwd=self.a,
                                        capture_output=True).returncode, 0, "Keelokit's probe: exit 0")

    def test_HRB_2_K2_claude_code_session_id_handed_over_as_harbor_session_is_the_taker(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--model", "sonnet", session="va"))
        res = self.keelokit_take(self.a, "QA-1", CLAUDE_CODE_SESSION_ID="va")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/va"])

    def test_HRB_2_K3_harbor_session_as_it_is_is_the_taker(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--model", "sonnet", session="vh"))
        res = self.keelokit_take(self.a, "QA-1", HARBOR_SESSION="vh", CLAUDE_CODE_SESSION_ID="other")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/vh"])

    def test_HRB_2_K4_a_second_sessions_take_is_STORY_TAKEN_relayed_as_one_line(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--model", "sonnet", session="va"))
        ok(self.take(self.a, "va", "QA-1"))
        ok(harbor(self.b, "worker", "register", "--role", "vessel", "--model", "sonnet", session="vb"))
        res = self.keelokit_take(self.b, "QA-1", CLAUDE_CODE_SESSION_ID="vb")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertEqual(res.stdout.strip().splitlines(),
                         [res.stdout.strip()], "one line")
        self.assertTrue(res.stdout.startswith("harbor: STORY_TAKEN: QA-1 is held by acct1/mbp/va"), res.stdout)
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/va"])
