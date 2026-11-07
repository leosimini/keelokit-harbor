"""harbor.py sync --hook: fresh reads of the logbook (docs/design.md, «Fresh reads»). A session `a` reads;
clone `b` writes. Time is HARBOR_NOW; a `git` shim on PATH logs every git process the hook starts.
Run: python3 -m unittest discover -s tests"""
import datetime as dt
import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path

from test_harbor import GIT_ENV, HARBOR, NOW, Base, harbor, ok, sh, vessel

REAL_GIT = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()


def at(seconds: int) -> str:
    return (dt.datetime.strptime(NOW, "%Y-%m-%dT%H:%M:%SZ") + dt.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class SyncBase(Base):
    def setUp(self):
        super().setUp()
        self.b = self.repo.clone("b", account="leo", host="linux")
        self.ready(self.a, session="s1")
        self.ready(self.b, session="s2")
        self.shim = self.tmp / "shim"
        self.shim.mkdir()
        self.gitlog = self.tmp / "git.log"
        (self.shim / "git").write_text(f'#!/bin/sh\necho "$@" >> {self.gitlog}\nexec {REAL_GIT} "$@"\n')
        (self.shim / "git").chmod((self.shim / "git").stat().st_mode | stat.S_IXUSR)

    def hook(self, event: str, secs: int = 0, clone: Path | None = None, session: str | None = "sess", **fields):
        payload = {"hook_event_name": event, **({"session_id": session} if session else {}), **fields}
        return subprocess.run([sys.executable, str(HARBOR), "sync", "--hook"], cwd=clone or self.a, capture_output=True,
                              text=True, input=json.dumps(payload),
                              env={**os.environ, **GIT_ENV, "HARBOR_NOW": at(secs), "CLAUDE_PROJECT_DIR": str(clone or self.a),
                                   "PATH": f"{self.shim}{os.pathsep}{os.environ['PATH']}"})

    def git_calls(self) -> list[str]:
        return self.gitlog.read_text().splitlines() if self.gitlog.exists() else []

    def seen(self, session: str = "sess") -> dict:
        return json.loads((self.a / ".git/harbor/seen" / f"{session}.json").read_text())

    def log_tip(self) -> str:
        return sh(self.repo.remote, "git", "rev-parse", "harbor/log")

    def new_convoy(self) -> None:
        ok(harbor(self.b, "convoy", "new", "--title", "QA wave", session="s2"))

    def set_state(self, n: int, state: str) -> None:
        w = self.tmp / "writer"
        if not w.exists():
            sh(self.tmp, "git", "clone", "--quiet", "-b", "harbor/log", str(self.repo.remote), str(w))
        sh(w, "git", "pull", "--quiet")
        f = w / f"harbor/convoys/{n}.toml"
        f.write_text(f.read_text().replace('state = "assembling"', f'state = "{state}"'))
        sh(w, "git", "commit", "--quiet", "-am", "state")
        sh(w, "git", "push", "--quiet", "origin", "HEAD:harbor/log")


class TestSessionStart(SyncBase):
    def test_it_fetches_and_records_the_tip(self):
        self.new_convoy()
        res = self.hook("SessionStart")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("fetched now", res.stdout)
        self.assertIn("open convoys: assembling 1", res.stdout)
        self.assertEqual(self.seen()["tip"], self.log_tip())
        self.assertEqual(self.seen()["fetched_epoch"], dt.datetime.strptime(NOW, "%Y-%m-%dT%H:%M:%SZ")
                         .replace(tzinfo=dt.timezone.utc).timestamp())

    def test_without_a_session_id_the_state_file_is_a_dash(self):
        self.hook("SessionStart", session=None)
        self.assertTrue((self.a / ".git/harbor/seen/-.json").exists())

    def test_offline_it_says_so_with_the_age_and_exits_0(self):
        self.hook("SessionStart")
        self.repo.remote.rename(self.tmp / "gone.git")
        res = self.hook("SessionStart", secs=600)
        self.assertEqual(res.returncode, 0)
        self.assertIn("offline: as of the last fetch, 10 min old", res.stdout)
        self.assertEqual(self.seen()["fetched_epoch"], dt.datetime.strptime(NOW, "%Y-%m-%dT%H:%M:%SZ")
                         .replace(tzinfo=dt.timezone.utc).timestamp(), "a failed fetch keeps the last good time")

    def test_check_hook_still_works(self):
        res = harbor(self.a, "check", "--hook", stdin='{"session_id": "s42"}')
        self.assertIn("this session is leo/mbp/s42", res.stdout)
        self.assertIn("fetched now", res.stdout)


class TestUserPromptSubmit(SyncBase):
    def test_inside_the_window_it_runs_no_fetch(self):
        self.hook("SessionStart")
        self.new_convoy()
        self.gitlog.unlink(missing_ok=True)
        res = self.hook("UserPromptSubmit", secs=59)
        self.assertEqual((res.returncode, res.stdout), (0, ""))
        self.assertEqual(self.git_calls(), [])

    def test_a_change_by_another_clone_is_printed_as_a_delta(self):
        self.new_convoy()
        self.hook("SessionStart")
        before = self.seen()["tip"]
        ok(harbor(self.b, "convoy", "abort", "1", "--reason", "scope changed", session="s2"))
        vessel(self.b, "claude/qa-1", "apps/web/a.ts")
        res = self.hook("UserPromptSubmit", secs=61)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("convoy 1: assembling -> aborted", res.stdout)
        self.assertIn("new events:", res.stdout)
        self.assertIn("aborted", res.stdout)
        self.assertIn("leo/linux/s2", res.stdout)
        self.assertNotEqual(self.seen()["tip"], before)
        self.assertEqual(self.seen()["tip"], self.log_tip())

    def test_vessels_workers_and_the_watch_show(self):
        self.new_convoy()
        self.hook("SessionStart")
        ok(harbor(self.b, "worker", "register", "--role", "vessel", "--convoy", "1", session="s3"))
        ok(harbor(self.b, "harbormaster", "takeover", session="s2"))
        res = self.hook("UserPromptSubmit", secs=61)
        self.assertIn("worker registered: leo/linux/s3 (vessel, convoy 1)", res.stdout)
        self.assertIn("watch: nobody -> leo/linux/s2", res.stdout)
        ok(harbor(self.b, "worker", "end", session="s3"))
        res = self.hook("UserPromptSubmit", secs=130)
        self.assertIn("worker ended: leo/linux/s3", res.stdout)

    def test_new_vessel_is_listed(self):
        self.new_convoy()
        self.hook("SessionStart")
        vessel(self.b, "claude/qa-1", "apps/web/a.ts")
        ok(harbor(self.b, "seal", session="s2"))
        ok(harbor(self.b, "convoy", "add", "1", "claude/qa-1", session="s2"))
        res = self.hook("UserPromptSubmit", secs=61)
        self.assertIn("convoy 1: vessels added: claude/qa-1", res.stdout)

    def test_unchanged_it_prints_nothing(self):
        self.new_convoy()
        self.hook("SessionStart")
        res = self.hook("UserPromptSubmit", secs=61)
        self.assertEqual((res.returncode, res.stdout), (0, ""))
        self.assertTrue(self.git_calls(), "it did fetch")

    def test_an_unknown_seen_tip_prints_a_short_summary(self):
        self.new_convoy()
        res = self.hook("UserPromptSubmit", secs=0)
        self.assertIn("Harbor: logbook @", res.stdout)
        self.assertIn("convoy 1 'QA wave': assembling", res.stdout)
        self.assertIn("watch: nobody", res.stdout)

    def test_an_unreadable_seen_tip_falls_back_to_the_summary(self):
        self.new_convoy()
        self.hook("SessionStart")
        p = self.a / ".git/harbor/seen/sess.json"
        p.write_text(json.dumps({**self.seen(), "tip": "0" * 40}))
        res = self.hook("UserPromptSubmit", secs=61)
        self.assertIn("convoy 1 'QA wave'", res.stdout)

    def test_the_delta_is_capped(self):
        self.new_convoy()
        self.hook("SessionStart")
        for i in range(40):
            ok(harbor(self.b, "convoy", "new", "--title", "t" * 60 + str(i), session="s2"))
        res = self.hook("UserPromptSubmit", secs=61)
        self.assertLessEqual(len(res.stdout.strip()), 1000)
        self.assertIn("convoy 2 new", res.stdout)

    def test_offline_it_is_silent(self):
        self.hook("SessionStart")
        self.repo.remote.rename(self.tmp / "gone.git")
        res = self.hook("UserPromptSubmit", secs=61)
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""))

    def test_outside_keelokit_it_is_silent(self):
        other = self.tmp / "plain"
        sh(self.tmp, "git", "init", "--quiet", str(other))
        res = self.hook("UserPromptSubmit", clone=other)
        self.assertEqual((res.returncode, res.stdout), (0, ""))
        self.assertEqual(self.git_calls(), [])


class TestPostToolUse(SyncBase):
    def test_json_shape_and_the_120_s_window(self):
        self.new_convoy()
        self.hook("SessionStart")
        ok(harbor(self.b, "convoy", "abort", "1", "--reason", "x", session="s2"))
        self.gitlog.unlink(missing_ok=True)
        res = self.hook("PostToolUse", secs=119, tool_name="Read")
        self.assertEqual((res.returncode, res.stdout, self.git_calls()), (0, "", []))
        res = self.hook("PostToolUse", secs=121, tool_name="Read")
        out = json.loads(res.stdout)
        self.assertEqual(list(out), ["hookSpecificOutput"])
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("convoy 1: assembling -> aborted", out["hookSpecificOutput"]["additionalContext"])
        res = self.hook("PostToolUse", secs=250, tool_name="Read")
        self.assertEqual((res.returncode, res.stdout), (0, ""), "nothing new, nothing printed")


class TestPreToolUse(SyncBase):
    def bash(self, command: str, secs: int = 0):
        return self.hook("PreToolUse", secs=secs, tool_name="Bash", tool_input={"command": command})

    def test_a_push_to_main_fetches_at_once_and_says_verifying(self):
        self.new_convoy()
        self.hook("SessionStart")
        self.set_state(1, "verifying")
        res = self.bash("git push origin HEAD:main", secs=1)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PreToolUse")
        self.assertIn("convoy 1 'QA wave': verifying", out["additionalContext"])
        self.assertIn("Convoy 1 is verifying", out["additionalContext"])
        self.assertEqual(self.seen()["tip"], self.log_tip())

    def test_convoy_sail_does_not_get_the_verifying_warning(self):
        self.new_convoy()
        self.set_state(1, "verifying")
        res = self.bash("python3 bin/harbor.py convoy sail 1")
        ctx = json.loads(res.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("verifying", ctx)
        self.assertNotIn("Convoy 1 is verifying", ctx)

    def test_a_push_to_a_convoy_branch_gets_the_state_but_no_warning(self):
        self.new_convoy()
        self.set_state(1, "verifying")
        ctx = json.loads(self.bash("git push origin convoy/1").stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("Convoy 1 is verifying", ctx)
        self.assertIn("convoy 1", ctx)

    def test_it_does_not_wait_for_the_window(self):
        self.new_convoy()
        self.hook("SessionStart")
        res = self.bash("harbor.py --session x convoy add 1 claude/x", secs=1)
        self.assertIn("convoy 1", json.loads(res.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_other_commands_cost_no_git(self):
        self.hook("SessionStart")
        self.gitlog.unlink(missing_ok=True)
        for c in ("ls -la", "git push origin claude/feature", "git status"):
            res = self.bash(c, secs=1)
            self.assertEqual((res.returncode, res.stdout), (0, ""), c)
        self.assertEqual(self.git_calls(), [])

    def test_approve_is_still_denied(self):
        res = self.bash("python3 bin/harbor.py convoy approve 3")
        self.assertEqual(res.returncode, 2)
        self.assertIn("only the person approves", res.stderr)

    def test_approve_is_denied_even_outside_a_repo(self):
        other = self.tmp / "plain"
        other.mkdir()
        res = self.hook("PreToolUse", clone=other, tool_name="Bash", tool_input={"command": "harbor.py convoy approve 1"})
        self.assertEqual(res.returncode, 2)

    def test_offline_a_push_still_gets_the_last_known_state(self):
        self.new_convoy()
        self.hook("SessionStart")
        self.repo.remote.rename(self.tmp / "gone.git")
        res = self.bash("git push origin main", secs=300)
        self.assertEqual(res.returncode, 0)
        self.assertIn("offline, 5 min old", json.loads(res.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_garbage_on_stdin_exits_0(self):
        res = subprocess.run([sys.executable, str(HARBOR), "sync", "--hook"], cwd=self.a, input="not json",
                             capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.a)})
        self.assertEqual((res.returncode, res.stdout), (0, ""))


class TestHooksJson(unittest.TestCase):
    def test_every_event_calls_sync_with_a_timeout(self):
        hooks = json.loads((HARBOR.parents[1] / "hooks/hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"})
        for name, entries in hooks.items():
            h = entries[0]["hooks"][0]
            self.assertIn("harbor.py\" sync --hook", h["command"], name)
            self.assertEqual(h["timeout"], 15 if name in ("SessionStart", "PreToolUse") else 10, name)
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Bash")


if __name__ == "__main__":
    unittest.main()
