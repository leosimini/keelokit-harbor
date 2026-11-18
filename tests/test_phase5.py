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
    from .test_harbor import GIT_ENV, HARBOR, NOW, harbor, load_module, ok, sh
except ImportError:  # run as `discover -s tests`: the tests directory is the top level
    from test_harbor import GIT_ENV, HARBOR, NOW, harbor, load_module, ok, sh

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
        bare = self.tmp / "bare"
        sh(self.tmp, "git", "clone", "--quiet", str(self.remote), str(bare))
        res = self.hook(bare)  # no logbook on the remote yet
        self.assertEqual((res.stdout, res.returncode), ("", 0))
        self.ready()
        res = self.hook(self.a)
        self.assertIn("logbook @", res.stdout)
        self.assertIn("this session is acct1/mbp/sess", res.stdout)

    def test_the_approve_guard_runs_on_any_input_whatever_repo_the_session_is_rooted_in(self):
        for command in ("harbor.py convoy approve 3", f"cd {self.tmp} && harbor.py convoy approve 3",
                        f"git -C {self.tmp} status && python3 x/harbor.py convoy approve 3"):
            res = self.hook(self.a, "PreToolUse", tool_name="Bash", tool_input={"command": command})
            self.assertEqual(res.returncode, 2, command)
        for command in ('harbor.py convoy "approve" 3', "harbor.py convoy 'approve' 3"):
            res = self.hook(self.a, "PreToolUse", tool_name="Bash", tool_input={"command": command})
            self.assertEqual(res.returncode, 2, command)
        (self.a / ".keelokit").mkdir()
        res = self.hook(self.a, "PreToolUse", tool_name="Bash", tool_input={"command": "harbor.py convoy approve 3"})
        self.assertEqual(res.returncode, 2)

    def test_keelokit_wins_when_both_exist(self):
        self.ready()
        (self.a / ".harbor/config.toml").write_text('[harbor]\nproject = "Ignored"\n')
        (self.a / ".keelokit").mkdir()
        (self.a / ".keelokit/state.toml").write_text('[landing]\npolicy = "convoy"\n')
        (self.a / ".keelokit/local.toml").write_text(IDENTITY.format(a="acct1"))
        self.assertIn(".harbor/config.toml is ignored: this project runs on Keelokit", ok(harbor(self.a, "log")))
        self.assertIn("is ignored", ok(harbor(self.a, "doctor")))
        self.assertNotIn("Ignored", ok(harbor(self.a, "title", "--role", "dispatcher")))


    def test_a_committed_identity_file_is_refused_by_doctor_and_init(self):
        sh(self.a, "git", "add", "-f", ".harbor/local.toml")
        sh(self.a, "git", "commit", "--quiet", "-m", "identity")
        res = harbor(self.a, "doctor")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("committed", res.stdout)
        res = harbor(self.a, "init")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("every clone shares one identity", res.stderr)

    def test_init_keeps_the_identity_file_out_of_git(self):
        ok(harbor(self.a, "init"))
        self.assertIn(".harbor/local.toml", (self.a / ".gitignore").read_text().splitlines())
        sh(self.a, "git", "check-ignore", "-q", ".harbor/local.toml")
        ok(harbor(self.a, "init"))
        self.assertEqual((self.a / ".gitignore").read_text().count(".harbor/local.toml"), 1)

    def test_a_worktree_without_its_own_identity_uses_the_main_checkouts(self):
        wt = self.tmp / "wt"
        sh(self.a, "git", "worktree", "add", "--quiet", "-b", "side", str(wt))
        self.assertFalse((wt / ".harbor/local.toml").exists())
        self.assertEqual(ok(harbor(wt, "title", "--role", "dispatcher")).strip(), "dispatcher · acct1 · a")

    def test_init_gitignore_edit_keeps_a_file_without_a_final_newline_and_adds_the_marker(self):
        (self.a / ".gitignore").write_text("node_modules")
        ok(harbor(self.a, "init"))
        self.assertEqual((self.a / ".gitignore").read_text().splitlines(), ["node_modules", ".harbor/local.toml"])
        self.assertEqual((self.a / ".harbor/config.toml").read_text().strip(), "[harbor]")

    def test_a_clone_that_never_ran_init_hears_about_an_adopted_repo(self):
        ok(harbor(self.a, "init"))
        bare = self.tmp / "bare"
        sh(self.tmp, "git", "clone", "--quiet", str(self.remote), str(bare))
        res = self.hook(bare)
        self.assertEqual(res.returncode, 0)
        self.assertIn("harbor/log", res.stdout)

    def test_a_worktree_identity_fallback_needs_a_plain_main_checkout(self):
        mod = load_module()
        mod.ROOT, mod.COMMON = self.tmp / "x", self.tmp / "elsewhere" / "a.git"
        (self.tmp / "elsewhere/.harbor").mkdir(parents=True)
        (self.tmp / "elsewhere/.harbor/local.toml").write_text("")
        self.assertEqual(mod.identity_file()[1], self.tmp / "x" / ".harbor/local.toml")

    def test_transact_retries_a_fetch_that_cannot_lock_the_ref(self):
        self.ready()
        mod = load_module()
        mod.ROOT, mod.COMMON, mod.REMOTE = self.a, self.a / ".git", "origin"
        real, calls = mod.fetch, []

        def flaky(branch):
            calls.append(branch)
            if len(calls) == 1:
                raise mod.HarborError("FETCH_FAILED", "git fetch: cannot lock ref 'refs/remotes/origin/harbor/log'")
            return real(branch)
        mod.fetch = flaky
        self.assertEqual(mod.transact("noop", "acct1/mbp/s1", lambda files, head: "done"), "done")
        self.assertEqual(len(calls), 2)

    def test_the_project_name_is_trimmed_and_empty_means_the_directory(self):
        (self.a / ".harbor/config.toml").write_text('[harbor]\nproject = "  "\n')
        self.assertEqual(ok(harbor(self.a, "title", "--role", "dispatcher")).strip(), "dispatcher · acct1 · a")
        (self.a / ".harbor/config.toml").write_text('[harbor]\nproject = " Shop "\n')
        self.assertEqual(ok(harbor(self.a, "title", "--role", "dispatcher")).strip(), "dispatcher · acct1 · Shop")

    def test_a_keelokit_repo_does_not_fall_back_to_the_harbor_identity(self):
        (self.a / ".keelokit").mkdir()
        (self.a / ".keelokit/state.toml").write_text('[landing]\npolicy = "convoy"\n')
        res = harbor(self.a, "init")
        self.assertEqual(res.returncode, 2)
        self.assertIn(".keelokit/local.toml", res.stderr)

    def test_the_project_name_is_one_short_line(self):
        for bad in ('"a\\nb"', '"' + "x" * 61 + '"', "3"):
            (self.a / ".harbor/config.toml").write_text(f"[harbor]\nproject = {bad}\n")
            res = harbor(self.a, "title", "--role", "dispatcher")
            self.assertEqual(res.returncode, 2, bad)
            self.assertIn("BAD_CONFIG", res.stderr)

    def test_a_story_worker_without_keelokit_needs_keelokit(self):
        self.ready()
        res = harbor(self.a, "worker", "register", "--role", "vessel", "--story", "X-1", session="s2")
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("NEEDS_KEELOKIT", res.stderr)

    def test_the_fleet_hooks_say_nothing_about_convoys(self):
        self.ready()
        self.assertNotIn("convoy", self.hook(self.a).stdout)
        res = self.hook(self.a, "PreToolUse", tool_name="Bash", tool_input={"command": "git push origin main"})
        self.assertEqual((res.stdout, res.returncode), ("", 0))



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

    def test_an_unknown_remote_tip_asks_for_a_fetch_and_a_known_one_refuses(self):
        sha = self.orphan({"harbor/a.toml": "x = 1\n"})
        res = self.guard("refs/heads/harbor/log", sha, remote_sha="1" * 40)
        self.assertEqual(res.returncode, 1)
        self.assertIn("fetch first", res.stderr)

    def test_the_logbook_falls_back_to_a_local_trunk_and_to_none_but_the_mailbox_needs_a_remote_one(self):
        sha = self.orphan({"harbor/a.toml": "x = 1\n"})
        sh(self.a, "git", "update-ref", "-d", "refs/remotes/origin/main")
        self.assertEqual(self.guard("refs/heads/harbor/log", sha).returncode, 0)  # local main, no shared history
        sh(self.a, "git", "branch", "-m", "main", "other")
        self.assertEqual(self.guard("refs/heads/harbor/log", sha).returncode, 0)  # no trunk at all
        bad = self.orphan({"harbor/a.toml": "x = 1\n", "src/x.py": "y\n"}, name="w2")
        res = self.guard("refs/heads/harbor/log", bad)  # the tree check still applies
        self.assertEqual(res.returncode, 1)
        self.assertIn("only regular files under harbor/", res.stderr)
        res = self.guard("refs/heads/harbor/mailbox/acct1", sha)
        self.assertEqual(res.returncode, 1)
        self.assertIn("push main first, or fetch it", res.stderr)

    def test_a_local_remote_tip_that_is_not_an_ancestor_asks_for_a_fetch(self):
        sha = self.orphan({"harbor/a.toml": "x = 1\n"})
        other = self.orphan({"harbor/b.toml": "x = 1\n"}, name="w2")
        res = self.guard("refs/heads/harbor/log", sha, remote_sha=other)
        self.assertEqual(res.returncode, 1)
        self.assertIn("fetch first", res.stderr)

    def test_a_local_trunk_branch_is_not_the_trunk(self):
        sha = self.mailbox({"harbor/mailbox/acct1.md": "hi\n"})
        sh(self.a, "git", "update-ref", "-d", "refs/remotes/origin/main")
        self.assertEqual(self.guard("refs/heads/harbor/mailbox/acct1", sha).returncode, 1)

    def test_an_error_on_a_harbor_ref_is_exit_1_and_the_repo_is_the_hooks_not_the_sessions(self):
        res = self.guard("refs/heads/harbor/log", "d" * 40)
        self.assertEqual(res.returncode, 1, res.stderr)
        sha = self.orphan({"harbor/a.toml": "x = 1\n"})
        res = harbor(self.a, "push-guard", "refs/heads/harbor/log", sha, "refs/heads/harbor/log", ZERO, session=None,
                     env={"CLAUDE_PROJECT_DIR": str(self.tmp)})
        self.assertEqual(res.returncode, 0, res.stderr)


HOOK = """#!/bin/sh
H={harbor}
while read l ls r rs; do
  python3 "$H" push-guard "$l" "$ls" "$r" "$rs"; c=$?
  case $c in 0) continue;; 3) ;; *) exit 1;; esac
done
exit 0
"""


class InstalledHook(Plain):
    """The documented pre-push snippet, installed for real."""

    def test_push_retries_when_the_hook_asks_for_a_fetch_about_a_tip_the_clone_fetched_meanwhile(self):
        self.ready(role="dispatcher")
        old = sh(self.a, "git", "rev-parse", "origin/harbor/log")
        commit = sh(self.a, "git", "commit-tree", f"{old}^{{tree}}", "-p", old, "-m", "x")
        b = self.clone("b")
        sh(b, "git", "fetch", "--quiet", "origin")
        ok(harbor(b, "msg", "send", "--to", "account:acct1", "from b"))
        self.install(self.a)
        hook = self.a / ".git/hooks/pre-push"  # a sibling process fetches between git's advertisement and the guard
        hook.write_text(hook.read_text().replace("while read", "git fetch -q origin harbor/log:refs/remotes/origin/harbor/log\nwhile read", 1))
        saved = {k: os.environ.get(k) for k in GIT_ENV}
        os.environ.update(GIT_ENV)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in saved.items()])
        mod = load_module()
        mod.ROOT, mod.REMOTE = self.a, "origin"
        self.assertFalse(mod.push(commit))

    def test_init_works_through_the_hook_when_the_trunk_was_never_pushed(self):
        lone = self.tmp / "lone"
        sh(self.tmp, "git", "init", "--quiet", "-b", "main", str(lone))
        sh(lone, "git", "remote", "add", "origin", str(self.remote))
        (lone / "f").write_text("x\n")
        sh(lone, "git", "add", "-A")
        sh(lone, "git", "commit", "--quiet", "-m", "first")
        sh(self.tmp, "git", "init", "--quiet", "--bare", "-b", "main", str(self.tmp / "empty.git"))
        sh(lone, "git", "remote", "set-url", "origin", str(self.tmp / "empty.git"))
        (lone / ".harbor").mkdir()
        (lone / ".harbor/local.toml").write_text(IDENTITY.format(a="acct1"))
        self.install(lone)
        ok(harbor(lone, "init"))

    def install(self, clone: Path, harbor_path=HARBOR):
        hook = clone / ".git/hooks/pre-push"
        hook.write_text(HOOK.format(harbor=harbor_path))
        hook.chmod(0o755)

    def test_two_clones_racing_on_the_logbook_both_land_through_the_hook(self):
        import contextlib
        import io
        self.ready(role="dispatcher")
        b = self.clone("b")
        sh(b, "git", "fetch", "--quiet", "origin")
        for c in (self.a, b):
            self.install(c)
        saved = {k: os.environ.get(k) for k in (*GIT_ENV, "HARBOR_NOW", "CLAUDE_PROJECT_DIR")}
        os.environ.update({**GIT_ENV, "HARBOR_NOW": NOW})
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in saved.items()])
        mod = load_module()
        mod.BEFORE_PUSH = lambda: ok(harbor(b, "msg", "send", "--to", "account:acct1", "from b"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            rc = mod.main(["--session", "s1", "msg", "send", "--to", "account:acct1", "from a"], root=self.a)
        self.assertEqual(rc, 0, err.getvalue())
        log = ok(harbor(self.a, "msg", "list"))
        self.assertIn("from a", log)
        self.assertIn("from b", log)

    def test_a_hook_that_cannot_run_harbor_refuses_the_push(self):
        self.ready(role="dispatcher")
        self.install(self.a, self.tmp / "gone.py")
        res = harbor(self.a, "msg", "send", "--to", "account:acct1", "hi")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("PUSH_FAILED", res.stderr)


if __name__ == "__main__":
    unittest.main()
