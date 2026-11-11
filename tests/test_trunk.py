"""harbor.py with [harbor] trunk: a project whose integration branch isn't main. Here `develop` is the
trunk and `main` is production: convoys are measured against develop, merge it and sail to it, and main
is never pushed. The fake verify is test_phase2's, with Keelokit's base read from origin/develop.
Run: python3 -m unittest discover -s tests"""
import json
import subprocess
import unittest
from pathlib import Path

from test_harbor import Base, harbor, ok, sh
from test_phase2 import CONFIG, EXTRA, FAKE
from test_sync import SyncBase


def set_trunk(clone: Path, value: str) -> None:
    """`value` is the TOML as written: '"develop"', '7'."""
    state = clone / ".keelokit/state.toml"
    state.write_text(state.read_text().replace("[harbor]\n", f"[harbor]\ntrunk = {value}\n", 1))


class Trunk(Base):
    def setUp(self):
        super().setUp()
        self.main = self.repo.main_sha()
        sh(self.a, "git", "checkout", "--quiet", "-b", "develop")
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace('vessel_verify = "true"\n', CONFIG) + EXTRA)
        set_trunk(self.a, '"develop"')
        (self.a / ".keelokit/fake-verify.sh").write_text(FAKE.replace("origin/main", "origin/develop"))
        # Only on develop: measured against main, every vessel below would seem to touch the schema hotspot.
        (self.a / "apps/api/prisma").mkdir(parents=True)
        (self.a / "apps/api/prisma/schema.prisma").write_text("model A {}\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "harbor config, on develop")
        sh(self.a, "git", "push", "--quiet", "origin", "develop")
        self.ready(cap=6)
        ok(harbor(self.a, "harbormaster", "takeover"))

    def develop(self) -> str:
        return sh(self.repo.remote, "git", "rev-parse", "develop")

    def convoy(self, n: int = 1) -> dict:
        return self.repo.log_toml(f"harbor/convoys/{n}.toml")

    def deliver(self, n: int, branch: str, path: str, story: str) -> str:
        sh(self.a, "git", "fetch", "--quiet", "origin", "develop")
        sh(self.a, "git", "checkout", "--quiet", "-B", branch, "origin/develop")
        (self.a / path).parent.mkdir(parents=True, exist_ok=True)
        (self.a / path).write_text(f"{branch}\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", f"feat: {branch}\n\nStory: {story}")
        sh(self.a, "git", "push", "--quiet", "-u", "origin", branch)
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", str(n), branch))
        return sh(self.a, "git", "rev-parse", "HEAD")

    def push_from_another_clone(self, branch: str) -> None:
        b = self.tmp / "b"
        if not b.exists():
            b = self.repo.clone("b")
        sh(b, "git", "fetch", "--quiet", "origin", branch)
        sh(b, "git", "checkout", "--quiet", "-B", branch, f"origin/{branch}")
        (b / f"hotfix-{branch}.txt").write_text("x\n")
        sh(b, "git", "add", "-A")
        sh(b, "git", "commit", "--quiet", "-m", f"fix: on {branch}")
        sh(b, "git", "push", "--quiet", "origin", branch)

    def sail_ok(self, n: int = 1):
        return harbor(self.a, "convoy", "sail", str(n), "--ok", "--level", "changed", "--reason", "apps/web only")


class TestTrunk(Trunk):
    def test_a_convoy_is_measured_against_develop_and_sails_to_it(self):
        develop = self.develop()
        self.assertNotEqual(develop, self.main)
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.assertEqual(self.convoy()["base"], develop)
        a = self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        b = self.deliver(1, "claude/qa-3", "apps/web/b.ts", "QA-3")
        vessels = self.convoy()["vessels"]
        self.assertEqual([v["hotspots"] for v in vessels], [[], []], "the diff is against develop, not main")
        self.assertEqual({v["seal_base"] for v in vessels}, {develop})
        self.assertEqual(self.repo.log_toml(f"harbor/seals/{a}.toml")["base"], develop)
        out = ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertIn(f"on develop {develop[:9]}: ready", out)
        ok(self.sail_ok())
        self.assertEqual(self.convoy()["ok"]["base"], develop)
        self.assertIn("sealed, ready to sail", ok(harbor(self.a, "convoy", "verify", "1")))
        head = self.convoy()["head"]
        self.assertEqual(self.repo.log_toml(f"harbor/runs/{head}.toml")["base"], develop)
        out = ok(harbor(self.a, "convoy", "sail", "1"))
        self.assertIn(f"sailed: develop {develop[:9]} → {head[:9]}", out)
        self.assertEqual(self.develop(), head)
        self.assertEqual(self.repo.main_sha(), self.main, "main is production: nothing Harbor did moved it")
        for sha in (a, b, develop):
            sh(self.repo.remote, "git", "merge-base", "--is-ancestor", sha, head)
        c = self.convoy()
        self.assertEqual((c["state"], c["sail"]["main_before"], c["sail"]["main_after"]), ("sailed", develop, head))
        # The schema keeps its names (harbor/main.toml, main_before): what they hold is the trunk.
        mt = self.repo.log_toml("harbor/main.toml")
        self.assertEqual((mt["head"], mt["moves"][-1]["cause"]), (head, "convoy 1"))
        files = self.repo.log_files()
        self.assertIn(f"develop {develop[:9]} → {head[:9]}", files["harbor/convoys/1.md"])
        self.assertIn("## Trunk (`develop`)", files["harbor/LOGBOOK.md"])

    def test_develop_moving_voids_the_ok_and_main_moving_does_not(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        self.deliver(1, "claude/qa-3", "apps/web/b.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        ok(self.sail_ok())
        self.push_from_another_clone("main")
        self.assertNotEqual(self.repo.main_sha(), self.main)
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.push_from_another_clone("develop")
        res = harbor(self.a, "convoy", "sail", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("MAIN_MOVED: develop moved to", res.stderr)
        self.assertIn("  develop moved: ", ok(harbor(self.a, "convoy", "status", "1")))
        self.assertIn("develop moved: assemble again", ok(harbor(self.a, "harbormaster", "control")))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        c = self.convoy()
        self.assertEqual((c["state"], c["base"]), ("ready", self.develop()))
        self.assertNotIn("ok", c)
        self.assertIn("main-moved", [e["what"] for e in c["events"]], "event names are the schema's")
        self.assertIn("merge develop", sh(self.repo.remote, "git", "log", "-1", "--format=%s", "convoy/1"))
        sh(self.repo.remote, "git", "merge-base", "--is-ancestor", self.develop(), "convoy/1")
        res = subprocess.run(["git", "merge-base", "--is-ancestor", self.repo.main_sha(), "convoy/1"], cwd=self.repo.remote)
        self.assertEqual(res.returncode, 1, "main's hotfix is not merged into the convoy")

    def test_a_remote_without_the_trunk_is_refused(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace('trunk = "develop"', 'trunk = "staging"'))
        res = harbor(self.a, "convoy", "new")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NO_MAIN: origin has no staging", res.stderr)


class TestTrunkConfig(Base):
    def test_a_trunk_that_is_not_a_branch_or_is_one_of_harbors_is_refused(self):
        original = (self.a / ".keelokit/state.toml").read_text()
        for value, why in (('"harbor/log"', "can't be harbor/log"), ('"convoy/3"', "can't be convoy/3"),
                           ('"convoy"', "can't be convoy"), ('"harbor"', "can't be harbor"),
                           ('"my branch"', "not a branch name"), ('"-x"', "not a branch name"),
                           ('"a..b"', "not a branch name"), ('"x/"', "not a branch name"), ('""', "not a branch name"),
                           ("7", "not a branch name")):
            (self.a / ".keelokit/state.toml").write_text(original)
            set_trunk(self.a, value)
            res = harbor(self.a, "init")
            self.assertEqual(res.returncode, 2, value)
            self.assertIn("BAD_CONFIG: [harbor] trunk", res.stderr, value)
            self.assertIn(why, res.stderr, value)
        self.assertEqual(sh(self.repo.remote, "git", "branch", "--list", "harbor/log"), "", "nothing was written")

    def test_a_bad_trunk_never_fails_a_hook(self):
        set_trunk(self.a, '"harbor/log"')
        res = harbor(self.a, "check", "--hook", stdin='{"session_id": "abc"}')
        self.assertEqual(res.returncode, 0)
        self.assertIn("Harbor: [harbor] trunk can't be harbor/log", res.stdout)
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse"):
            payload = {"hook_event_name": event, "session_id": "abc", "tool_name": "Bash",
                       "tool_input": {"command": "git push origin main"}}
            res = harbor(self.a, "sync", "--hook", stdin=json.dumps(payload), env={"CLAUDE_PROJECT_DIR": str(self.a)})
            self.assertEqual(res.returncode, 0, event)

    def test_a_trunk_with_a_slash(self):
        sh(self.a, "git", "checkout", "--quiet", "-b", "release/1.x")
        set_trunk(self.a, '"release/1.x"')
        sh(self.a, "git", "commit", "--quiet", "-am", "trunk")
        sh(self.a, "git", "push", "--quiet", "origin", "release/1.x")
        self.ready()
        ok(harbor(self.a, "convoy", "new"))
        self.assertEqual(self.repo.log_toml("harbor/convoys/1.toml")["base"],
                         sh(self.repo.remote, "git", "rev-parse", "release/1.x"))


class TestTrunkHook(SyncBase):
    """The PreToolUse note goes to a push that moves the trunk, whatever its name."""

    def setUp(self):
        super().setUp()
        set_trunk(self.a, '"develop"')

    def bash(self, command: str):
        return self.hook("PreToolUse", secs=1, tool_name="Bash", tool_input={"command": command})

    def noted(self, command: str, branch: str) -> bool:
        sh(self.a, "git", "checkout", "--quiet", "-B", branch)
        res = self.bash(command)
        self.assertEqual(res.returncode, 0, res.stderr)
        return "open convoys" in res.stdout

    def test_a_push_to_the_trunk_gets_the_note_and_a_push_to_main_does_not(self):
        for c in ("git push origin HEAD:develop", "git push origin develop", "git push origin +refs/heads/develop",
                  "git push --all origin", "cd x && git push origin x:develop"):
            self.assertTrue(self.noted(c, "x"), c)
        for c in ("git push", "git push origin HEAD"):
            self.assertTrue(self.noted(c, "develop"), c)
        for c in ("git push origin main", "git push origin HEAD:main", "git push origin x", "git push",
                  "git push origin develop:other"):
            self.assertFalse(self.noted(c, "x"), c)
        self.assertFalse(self.noted("git push", "main"), "main is not the trunk here")

    def test_the_verifying_warning_names_the_trunk(self):
        self.new_convoy()
        self.hook("SessionStart")
        self.set_state(1, "verifying")
        ctx = json.loads(self.bash("git push origin HEAD:develop").stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Convoy 1 is verifying: a push to develop now moves develop under its verify", ctx)


if __name__ == "__main__":
    unittest.main()
