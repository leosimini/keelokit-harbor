"""harbor.py, phase 6: Keelokit's ledger (docs/ledger-phase6.md).
HRB-1: with a ledger that answers `ledger.py --json` with schema 1, each vessel's merge into convoy/<n> ends with
the trailer `Convoy: <n>`; `convoy add` asks `ledger.py attribution <seal_base>..<head> --json` and refuses a vessel
with an unattributed non-merge commit (`NO_STORY`); the vessel's story comes from the ledger. Without that ledger,
Harbor behaves as 0.5. A stand-in for Keelokit's ledger.py reads the trailers the way the real one does.
Also the HRB-7 nit: a vessel carrying several stories delivers each of them.
HRB-2: taking a story is a lock in the logbook: `story take|release`, `worker register --story`, `wanted take`'s
refusals and the vessel prompt that starts with `ledger.py take`.
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
#   HARBOR_FAKE_STORIES = {"ID": "state", ...}: the stories `--json` lists (default none).
# `show ID --json`: Keelokit 0.16.0 has no such command (usage, exit 2); HARBOR_FAKE_SHOW = {"ID": "state", ...}
#   makes it answer {"schema": 1, "id", "state"} (exit 1 for an id it doesn't list).
# Every call is logged to HARBOR_FAKE_LEDGER_LOG.
FAKE_LEDGER = """\
import json, os, subprocess, sys, time
if os.environ.get("HARBOR_FAKE_LEDGER_LOG"):
    with open(os.environ["HARBOR_FAKE_LEDGER_LOG"], "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\\n")
def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout
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
    stories = [{"id": k, "state": v} for k, v in json.loads(os.environ.get("HARBOR_FAKE_STORIES") or "{}").items()]
    print(json.dumps({"schema": json.loads(mode), "trunk": "main", "stories": stories, "diffs": [{"level": "warning"}]}))
    sys.exit(1)
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
                  session="spawn"))
        self.assertEqual(self.holders("QA-1"), ["acct1/mbp/spawn"])
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
