"""harbor.py, phase 6: Keelokit's ledger (docs/ledger-phase6.md).
HRB-1: with a ledger that answers `ledger.py --json` with schema 1, each vessel's merge into convoy/<n> ends with
the trailer `Convoy: <n>`; `convoy add` asks `ledger.py attribution <seal_base>..<head> --json` and refuses a vessel
with an unattributed non-merge commit (`NO_STORY`); the vessel's story comes from the ledger. Without that ledger,
Harbor behaves as 0.5. A stand-in for Keelokit's ledger.py reads the trailers the way the real one does.
Also the HRB-7 nit: a vessel carrying several stories delivers each of them.
Every git subprocess here runs with no GIT_* variable from the caller (a hook or a worktree exports GIT_DIR).
Run: python3 -m unittest discover -s tests"""
import json
import os
import unittest
from unittest import mock

from test_harbor import harbor, ok, sh
from test_phase2 import Phase2

# Keelokit's ledger.py, as far as Harbor sees it.
# `--json`: HARBOR_FAKE_LEDGER = the JSON value of "schema" (default 1), or bad | sleep | exit2 | binary (not UTF-8).
#   Exits 1, as the real one does when there are differences: an answer with schema 1 counts whatever the exit.
# `attribution A..B --json`: the contract with Keelokit's ledger.py attribution (LEDGER-013, docs/design.md), from
#   Story:/Part-of:/No-story: trailers; exit 0 whenever it answered. A merge is reported unattributed unless it has
#   its own trailer (the worst a ledger may say: Harbor ignores merges itself). HARBOR_FAKE_ATTRIBUTION = usage
#   (Keelokit 0.16.0: no such command, usage and exit 2) | exit3 (history incomplete) | bad | sleep
#   | no-attributed (`attributed` is not a boolean) | short (abbreviated shas).
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
    print(json.dumps({"schema": json.loads(mode), "trunk": "main", "stories": [], "diffs": [{"level": "warning"}]}))
    sys.exit(1)
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
