"""harbor.py with [harbor] own_verify = true: the verify commands are the project's own, not Keelokit's, so
no keelokit-verify.history line says what a run covered. Harbor gives a green convoy run its level
itself, a convoy sails on it, and no shared seal is ever written for it.
Run: python3 -m unittest discover -s tests"""
import json
import unittest

from test_harbor import Base, harbor, ok, sh, vessel
from test_phase2 import FAKE

# The project's own commands: each run leaves its name in .git/own-runs; a file .git/red makes them fail.
OWN = """own_verify = {own}
convoy_preflight = ""
convoy_verify = "sh -c 'echo changed >> .git/own-runs; test ! -f .git/red'"
convoy_verify_all = "sh -c 'echo all >> .git/own-runs; test ! -f .git/red'"
ci_check = "true"
"""


class Own(Base):
    own = "true"
    config = OWN

    def setUp(self):
        super().setUp()
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace('vessel_verify = "true"\n',
                                                   'vessel_verify = "true"\n' + self.config.format(own=self.own)))
        sh(self.a, "git", "commit", "--quiet", "-am", "the project's own verify")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.ready(cap=6)
        ok(harbor(self.a, "harbormaster", "takeover"))

    def runs(self) -> list[str]:
        try:
            return (self.a / ".git/own-runs").read_text().split()
        except OSError:
            return []

    def convoy(self, n: int = 1) -> dict:
        return self.repo.log_toml(f"harbor/convoys/{n}.toml")

    def record(self, n: int = 1) -> dict:
        return self.repo.log_toml(f"harbor/runs/{self.convoy(n)['head']}.toml")

    def seals(self) -> list[str]:
        return [p for p in self.repo.log_files() if p.startswith("harbor/seals/")]

    def deliver(self, n: int, branch: str, path: str, story: str) -> str:
        head = vessel(self.a, branch, path, story=story)
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", str(n), branch))
        return head

    def assembled(self, n: int = 1, vessels: int = 2) -> None:
        ok(harbor(self.a, "convoy", "new"))
        for i in range(vessels):
            self.deliver(n, f"claude/qa-{n}-{i}", f"apps/web/{n}-{i}.ts", f"QA-{n}{i}")
        ok(harbor(self.a, "convoy", "assemble", str(n)))

    def sail_ok(self, level: str, n: int = 1):
        return harbor(self.a, "convoy", "sail", str(n), "--ok", "--level", level, "--reason", "apps/web only")


class TestOwnVerify(Own):
    def test_a_convoy_sails_at_changed_and_nothing_becomes_a_shared_seal(self):
        self.assembled()
        vessel_head = self.convoy()["vessels"][0]["head"]
        vessel_seal = self.repo.log_toml(f"harbor/runs/{vessel_head}.toml")
        self.assertEqual((vessel_seal["exit"], vessel_seal.get("level"), vessel_seal.get("level_source")), (0, None, None),
                         "add asks a vessel's seal for exit 0 only: it gets no level")
        ok(self.sail_ok("changed"))
        self.assertIn("sealed, ready to sail", ok(harbor(self.a, "convoy", "verify", "1")))
        self.assertEqual(self.runs(), ["changed"])
        run = self.record()
        self.assertEqual((run["kind"], run["exit"], run["level"], run["level_source"]), ("convoy", 0, "changed", "harbor"))
        self.assertNotIn("keelokit_level", run)
        detail = self.convoy()["events"][-1]["detail"]
        self.assertIn("changed (own verify)", detail)
        self.assertIn("changed (own verify)", self.repo.log_files()["harbor/convoys/1.md"])
        self.assertEqual(self.seals(), [], "Keelokit's pre-push never sees a level Harbor gave")
        ok(harbor(self.a, "convoy", "sail", "1"))
        self.assertEqual(self.repo.main_sha(), self.convoy()["head"])
        self.assertEqual(self.convoy()["state"], "sailed")
        self.assertEqual(self.seals(), [])

    def test_a_convoy_sails_at_all(self):
        self.assembled()
        ok(self.sail_ok("all"))
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertEqual(self.runs(), ["all"])
        run = self.record()
        self.assertEqual((run["level"], run["level_source"]), ("all", "harbor"))
        ok(harbor(self.a, "convoy", "sail", "1"))
        self.assertEqual(self.repo.main_sha(), self.convoy()["head"])
        self.assertEqual(self.seals(), [])

    def test_a_changed_run_does_not_cover_an_all_ok(self):
        self.assembled(vessels=1)  # one vessel: the convoy's head is the vessel's, in this convoy and the next
        ok(self.sail_ok("changed"))
        ok(harbor(self.a, "convoy", "verify", "1"))
        head = self.convoy()["head"]
        ok(harbor(self.a, "convoy", "abort", "1", "--reason", "it goes in the next one"))
        ok(harbor(self.a, "convoy", "new"))
        ok(harbor(self.a, "convoy", "add", "2", "claude/qa-1-0"))
        ok(harbor(self.a, "convoy", "assemble", "2"))
        self.assertEqual(self.convoy(2)["head"], head)
        ok(self.sail_ok("all", 2))
        res = harbor(self.a, "convoy", "sail", "2")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT_SEALED", res.stderr)
        ok(harbor(self.a, "convoy", "verify", "2"))
        self.assertEqual(self.runs(), ["changed", "all"], "the changed run was not reused for an all ok")
        self.assertEqual(self.record(2)["level"], "all")
        ok(harbor(self.a, "convoy", "sail", "2"))
        self.assertEqual(self.repo.main_sha(), head)

    def test_an_all_run_covers_a_changed_ok(self):
        self.assembled(vessels=1)
        ok(self.sail_ok("all"))
        ok(harbor(self.a, "convoy", "verify", "1"))
        ok(harbor(self.a, "convoy", "abort", "1", "--reason", "it goes in the next one"))
        ok(harbor(self.a, "convoy", "new"))
        ok(harbor(self.a, "convoy", "add", "2", "claude/qa-1-0"))
        ok(harbor(self.a, "convoy", "assemble", "2"))
        ok(self.sail_ok("changed", 2))
        out = ok(harbor(self.a, "convoy", "verify", "2"))
        self.assertIn("nothing to run", out)
        self.assertEqual(self.runs(), ["all"])
        self.assertIn("all (own verify)", self.convoy(2)["events"][-1]["detail"])
        ok(harbor(self.a, "convoy", "sail", "2"))

    def test_a_red_run_gets_no_level_and_the_levels_command_runs_again_after_the_fix(self):
        self.assembled()
        ok(self.sail_ok("changed"))
        (self.a / ".git/red").write_text("")
        res = harbor(self.a, "convoy", "verify", "1")
        self.assertEqual(res.returncode, 1)
        run = self.record()
        self.assertEqual((run["exit"], run["result"], run.get("level"), run.get("level_source")), (1, "fail", None, None))
        self.assertEqual(self.convoy()["events"][-1]["what"], "verify-fail")
        self.assertIn("NOT_SEALED", harbor(self.a, "convoy", "sail", "1").stderr)
        (self.a / ".git/red").unlink()
        (self.a / "apps/web/fix.ts").write_text("fix\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: the seam")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertEqual(self.runs(), ["changed", "changed"], "not convoy_rerun: a project's own rerun proves no whole verify")
        self.assertEqual(self.record()["level"], "changed")
        ok(harbor(self.a, "convoy", "sail", "1"))
        self.assertEqual(self.repo.main_sha(), sh(self.a, "git", "rev-parse", "HEAD"))
        self.assertEqual(self.seals(), [])

    def test_own_verify_must_be_true_or_false(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace("own_verify = true", 'own_verify = "yes"'))
        res = harbor(self.a, "convoy", "status")
        self.assertEqual(res.returncode, 2)
        self.assertIn("BAD_CONFIG: [harbor] own_verify", res.stderr)
        self.assertEqual(harbor(self.a, "check", "--hook", stdin="{}").returncode, 0)


class TestOwnVerifyOff(Own):
    own = "false"

    def test_the_same_commands_without_own_verify_never_seal(self):
        self.assembled()
        ok(self.sail_ok("changed"))
        res = harbor(self.a, "convoy", "verify", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("green but not a whole verify", res.stdout)
        self.assertEqual(self.runs(), ["changed"])
        run = self.record()
        self.assertEqual((run["exit"], run.get("level"), run.get("level_source")), (0, None, None))
        self.assertEqual(self.convoy()["events"][-1]["what"], "verify-unsealed")
        res = harbor(self.a, "convoy", "sail", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT_SEALED", res.stderr)
        self.assertEqual(self.seals(), [])


class TestOwnVerifyInvalid(Own):
    config = OWN.replace("echo changed >> .git/own-runs; test ! -f .git/red", "echo x > left-behind.txt")

    def test_a_run_that_changes_the_tree_speaks_for_no_commit(self):
        self.assembled()
        ok(self.sail_ok("changed"))
        res = harbor(self.a, "convoy", "verify", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("SEAL_INVALID", res.stderr)
        self.assertNotIn(f"harbor/runs/{self.convoy()['head']}.toml", self.repo.log_files())


class TestOwnVerifyWithKeelokitsRecord(Own):
    """own_verify gives a level only when Keelokit left no record of the run. When the command did run Keelokit's
    verify, its history line decides, as it does without own_verify."""
    config = OWN.replace("sh -c 'echo changed >> .git/own-runs; test ! -f .git/red'",
                         "sh .keelokit/fake-verify.sh {{head}} changed convoy")

    def setUp(self):
        super().setUp()
        (self.a / ".keelokit/fake-verify.sh").write_text(FAKE)
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "a stand-in for Keelokit's verify")
        sh(self.a, "git", "push", "--quiet", "origin", "main")

    def test_a_partial_keelokit_run_stays_unsealed(self):
        self.assembled()
        ok(self.sail_ok("changed"))
        res = harbor(self.a, "convoy", "verify", "1", env={"HARBOR_FAKE": json.dumps({"partial": True})})
        self.assertEqual(res.returncode, 1)
        run = self.record()
        self.assertEqual((run["exit"], run["partial"], run.get("level"), run.get("level_source")), (0, True, None, None))
        self.assertIn("NOT_SEALED", harbor(self.a, "convoy", "sail", "1").stderr)

    def test_a_whole_keelokit_run_gets_keelokits_level_and_its_shared_seal(self):
        self.assembled()
        ok(self.sail_ok("changed"))
        ok(harbor(self.a, "convoy", "verify", "1"))
        run = self.record()
        self.assertEqual((run["level"], run["keelokit_level"], run.get("level_source")), ("changed", "changed", None))
        self.assertEqual(self.seals(), [f"harbor/seals/{self.convoy()['head']}.toml"])


if __name__ == "__main__":
    unittest.main()
