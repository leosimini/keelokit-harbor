"""harbor.py, 0.5: the fleet layer in a repo without Keelokit, and push-guard. Clone `a` is account acct1.
Run: python3 -m unittest discover -s tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .test_harbor import GIT_ENV, HARBOR, NOW, harbor, ok, sh
except ImportError:  # run as `discover -s tests`: the tests directory is the top level
    from test_harbor import GIT_ENV, HARBOR, NOW, harbor, ok, sh

IDENTITY = '[harbor]\naccount = "{a}"\nhost = "mbp"\n'
ZERO = "0" * 40


class Plain(unittest.TestCase):
    """A bare remote with main and no .keelokit/ anywhere; clones carry .harbor/local.toml."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.remote = self.tmp / "remote.git"
        sh(self.tmp, "git", "init", "--quiet", "--bare", "-b", "main", str(self.remote))
        seed = self.tmp / "seed"
        sh(self.tmp, "git", "clone", "--quiet", str(self.remote), str(seed))
        sh(seed, "git", "checkout", "--quiet", "-b", "main")
        (seed / "README.md").write_text("app\n")
        sh(seed, "git", "add", "-A")
        sh(seed, "git", "commit", "--quiet", "-m", "init")
        sh(seed, "git", "push", "--quiet", "origin", "main")
        self.a = self.clone("a")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def clone(self, name: str, account: str = "acct1") -> Path:
        path = self.tmp / name
        sh(self.tmp, "git", "clone", "--quiet", str(self.remote), str(path))
        (path / ".harbor").mkdir()
        (path / ".harbor/local.toml").write_text(IDENTITY.format(a=account))
        return path

    def ready(self, role: str = "skipper", session: str = "s1"):
        ok(harbor(self.a, "init", session=session))
        ok(harbor(self.a, "account", "set", "acct1", "--max-sessions", "3", session=session))
        ok(harbor(self.a, "worker", "register", "--role", role, "--model", "sonnet", session=session))

    def hook(self, cwd: Path, event: str = "SessionStart", **fields):
        return subprocess.run([sys.executable, str(HARBOR), "sync", "--hook"], cwd=cwd, capture_output=True, text=True,
                              input=json.dumps({"hook_event_name": event, "session_id": "sess", **fields}),
                              env={**os.environ, **GIT_ENV, "HARBOR_NOW": NOW, "CLAUDE_PROJECT_DIR": str(cwd)})


class Fleet(Plain):
    def test_init_account_worker_and_the_views(self):
        self.ready()
        out = ok(harbor(self.a, "log"))
        self.assertIn("acct1", out)
        self.assertNotIn("ignored", out)
        ok(harbor(self.a, "worker", "end"))

    def test_messages_end_to_end(self):
        self.ready(role="dispatcher")
        self.assertIn("m-0001", ok(harbor(self.a, "msg", "send", "--to", "account:acct1", "hello")))
        self.assertIn("hello", ok(harbor(self.a, "msg", "list")))
        ok(harbor(self.a, "msg", "ack", "m-0001"))
        ok(harbor(self.a, "msg", "done", "m-0001"))
        ok(harbor(self.a, "msg", "status"))
        res = harbor(self.a, "msg", "watch", "--account", "acct1", "--poll", "0.1", "--cap", "0.01")
        self.assertEqual(res.returncode, 75, res.stdout + res.stderr)

    def test_the_watch_and_a_control_without_convoys(self):
        self.ready()
        ok(harbor(self.a, "harbormaster", "takeover"))
        out = ok(harbor(self.a, "harbormaster", "control"))
        self.assertIn("watch: acct1/mbp/s1", out)
        self.assertNotIn("main:", out)

    def test_a_dispatcher_request_works_and_vessel_and_skipper_need_keelokit(self):
        self.ready()
        ok(harbor(self.a, "harbormaster", "takeover"))
        ok(harbor(self.a, "wanted", "add", "--role", "dispatcher"))
        for extra in (("--role", "vessel", "--story", "X-1"), ("--role", "skipper")):
            res = harbor(self.a, "wanted", "add", *extra)
            self.assertEqual(res.returncode, 2, res.stderr)
            self.assertIn("NEEDS_KEELOKIT", res.stderr)

    def test_the_convoy_layer_needs_keelokit(self):
        self.ready()
        (self.a / "board.md").write_text("# x\n")
        for cmd in (("convoy", "new"), ("convoy", "status"), ("seal",), ("import-board", "board.md")):
            res = harbor(self.a, *cmd)
            self.assertEqual(res.returncode, 2, cmd)
            self.assertIn("NEEDS_KEELOKIT", res.stderr)

    def test_titles_use_the_project_name_or_the_directory(self):
        self.assertEqual(ok(harbor(self.a, "title", "--role", "dispatcher")).strip(), "dispatcher · acct1 · a")
        (self.a / ".harbor/config.toml").write_text('[harbor]\nproject = "Demo"\n')
        self.assertEqual(ok(harbor(self.a, "title", "--role", "harbormaster")).strip(), "harbormaster · acct1 · Demo")
        res = harbor(self.a, "title", "--role", "vessel", "--story", "S-1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NO_TITLE", res.stderr)

    def test_identity_comes_from_harbor_local_toml(self):
        (self.a / ".harbor/local.toml").unlink()
        res = harbor(self.a, "init")
        self.assertEqual(res.returncode, 2)
        self.assertIn(".harbor/local.toml", res.stderr)

    def test_the_trunk_comes_from_harbor_config(self):
        (self.a / ".harbor/config.toml").write_text('[harbor]\ntrunk = "a..b"\n')
        res = harbor(self.a, "models")
        self.assertEqual(res.returncode, 2)
        self.assertIn("BAD_CONFIG", res.stderr)
        self.assertIn(".harbor/config.toml", res.stderr)

    def test_doctor_reads_the_requirements_of_harbor_config(self):
        self.ready()
        (self.a / ".harbor/config.toml").write_text('[harbor.requirements]\ntools = ["python3", "no-such-tool-xyz"]\n')
        res = harbor(self.a, "doctor")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("ok: tools python3", res.stdout)
        self.assertIn("missing: tools no-such-tool-xyz", res.stdout)

    def test_the_hooks_work_and_a_repo_with_neither_directory_stays_quiet(self):
        self.ready()
        res = self.hook(self.a)
        self.assertIn("logbook @", res.stdout)
        self.assertIn("this session is acct1/mbp/sess", res.stdout)
        bare = self.tmp / "bare"
        sh(self.tmp, "git", "clone", "--quiet", str(self.remote), str(bare))
        res = self.hook(bare)
        self.assertIn("does nothing", res.stdout)
        self.assertEqual(res.returncode, 0)

    def test_the_approve_guard_only_runs_where_there_is_keelokit(self):
        fields = {"tool_name": "Bash", "tool_input": {"command": "harbor.py convoy approve 3"}}
        self.assertEqual(self.hook(self.a, "PreToolUse", **fields).returncode, 0)
        (self.a / ".keelokit").mkdir()
        self.assertEqual(self.hook(self.a, "PreToolUse", **fields).returncode, 2)

    def test_keelokit_wins_when_both_exist(self):
        self.ready()
        (self.a / ".harbor/config.toml").write_text('[harbor]\nproject = "Ignored"\n')
        (self.a / ".keelokit").mkdir()
        (self.a / ".keelokit/state.toml").write_text('[landing]\npolicy = "convoy"\n')
        (self.a / ".keelokit/local.toml").write_text(IDENTITY.format(a="acct1"))
        self.assertIn(".harbor/config.toml is ignored: this project runs on Keelokit", ok(harbor(self.a, "log")))
        self.assertIn("is ignored", ok(harbor(self.a, "doctor")))
        self.assertNotIn("Ignored", ok(harbor(self.a, "title", "--role", "dispatcher")))


class PushGuard(Plain):
    def guard(self, ref, sha, remote_sha=ZERO):
        return harbor(self.a, "push-guard", ref, sha, ref, remote_sha, session=None)

    def orphan(self, files: dict, name: str = "w", mode: int = 0o644) -> str:
        """A commit with no parent holding `files`, brought into clone a."""
        w = self.tmp / name
        sh(self.tmp, "git", "init", "--quiet", str(w))
        for n, text in files.items():
            (w / n).parent.mkdir(parents=True, exist_ok=True)
            (w / n).write_text(text)
            (w / n).chmod(mode)
        sh(w, "git", "add", "-A")
        sh(w, "git", "commit", "--quiet", "-m", "log")
        sh(self.a, "git", "fetch", "--quiet", str(w), "HEAD")
        return sh(self.a, "git", "rev-parse", "FETCH_HEAD")

    def test_a_ref_that_is_not_harbors_exits_3(self):
        main = sh(self.a, "git", "rev-parse", "HEAD")
        self.assertEqual(self.guard("refs/heads/main", main).returncode, 3)
        self.assertEqual(self.guard("refs/heads/harbor/other", main).returncode, 3)

    def test_the_logbook_accepts_a_sound_push_and_a_fast_forward(self):
        sha = self.orphan({"harbor/a.toml": "x = 1\n"})
        self.assertEqual(self.guard("refs/heads/harbor/log", sha).returncode, 0)
        self.ready()
        sh(self.a, "git", "fetch", "--quiet", "origin", "harbor/log")
        tip = sh(self.a, "git", "rev-parse", "FETCH_HEAD")
        self.assertEqual(self.guard("refs/heads/harbor/log", tip, remote_sha=tip).returncode, 0)

    def test_the_logbook_refuses_a_delete_dropped_commits_and_other_files(self):
        res = self.guard("refs/heads/harbor/log", ZERO)
        self.assertEqual(res.returncode, 1)
        self.assertIn("never deleted", res.stderr)
        one = self.orphan({"harbor/a.toml": "x = 1\n"}, "w1")
        other = self.orphan({"harbor/b.toml": "x = 2\n"}, "w2")
        res = self.guard("refs/heads/harbor/log", other, remote_sha=one)
        self.assertEqual(res.returncode, 1)
        self.assertIn("drop commits", res.stderr)
        res = self.guard("refs/heads/harbor/log", self.orphan({"harbor/a.toml": "x\n", "src/b.txt": "y\n"}, "w3"))
        self.assertEqual(res.returncode, 1)
        self.assertIn("src/b.txt", res.stderr)
        res = self.guard("refs/heads/harbor/log", self.orphan({"harbor/run.sh": "#!/bin/sh\n"}, "w4", 0o755))
        self.assertEqual(res.returncode, 1)
        self.assertIn("regular files", res.stderr)

    def test_the_logbook_refuses_a_branch_that_shares_history_with_the_trunk(self):
        (self.a / "harbor").mkdir()
        (self.a / "harbor/a.toml").write_text("x = 1\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "on main")
        res = self.guard("refs/heads/harbor/log", sh(self.a, "git", "rev-parse", "HEAD"))
        self.assertEqual(res.returncode, 1)
        self.assertIn("shares history", res.stderr)

    def mailbox(self, files: dict, mode: int = 0o644) -> str:
        sh(self.a, "git", "checkout", "--quiet", "-B", "mb", "origin/main")
        for n, text in files.items():
            (self.a / n).parent.mkdir(parents=True, exist_ok=True)
            (self.a / n).write_text(text)
            (self.a / n).chmod(mode)
        sh(self.a, "git", "add", *files)
        sh(self.a, "git", "commit", "--quiet", "-m", "mailbox")
        return sh(self.a, "git", "rev-parse", "HEAD")

    def test_a_mailbox_accepts_one_file_per_commit_on_the_trunk(self):
        sha = self.mailbox({"harbor/mailbox/acct1.md": "hi\n"})
        self.assertEqual(self.guard("refs/heads/harbor/mailbox/acct1", sha).returncode, 0)

    def test_a_mailbox_refuses_a_delete_other_files_the_wrong_account_and_a_bad_name(self):
        sha = self.mailbox({"harbor/mailbox/acct1.md": "hi\n", "other.txt": "x\n"})
        res = self.guard("refs/heads/harbor/mailbox/acct1", sha)
        self.assertEqual(res.returncode, 1)
        self.assertIn("exactly", res.stderr)
        sha = self.mailbox({"harbor/mailbox/acct2.md": "hi\n"})
        self.assertEqual(self.guard("refs/heads/harbor/mailbox/acct1", sha).returncode, 1)
        self.assertEqual(self.guard("refs/heads/harbor/mailbox/acct1", ZERO).returncode, 1)
        self.assertEqual(self.guard("refs/heads/harbor/mailbox/-bad", sha).returncode, 1)

    def test_a_mailbox_refuses_a_branch_off_the_trunk_and_an_executable_file(self):
        sha = self.orphan({"harbor/mailbox/acct1.md": "hi\n"})
        self.assertEqual(self.guard("refs/heads/harbor/mailbox/acct1", sha).returncode, 1)
        sha = self.mailbox({"harbor/mailbox/acct1.md": "hi\n"}, 0o755)
        self.assertEqual(self.guard("refs/heads/harbor/mailbox/acct1", sha).returncode, 1)


if __name__ == "__main__":
    unittest.main()
