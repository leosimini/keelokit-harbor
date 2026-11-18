"""harbor.py, 0.4: the mailbox of an account and what an account needs to work in a project (requirements,
doctor, the hook's line about main). Clone `a` is account acct1.
Run: python3 -m unittest discover -s tests"""
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

try:
    from .test_harbor import Base, harbor, load_module, ok, sh
    from .test_sync import SyncBase
except ImportError:  # run as `discover -s tests`: the tests directory is the top level
    from test_harbor import Base, harbor, load_module, ok, sh
    from test_sync import SyncBase

MANIFEST = """
[harbor.requirements]
tools = ["python3", "no-such-tool-xyz"]
hosts = ["nowhere.invalid"]
secrets = ["HARBOR_TEST_TOKEN"]
plugins = ["some-plugin"]
skills = ["present-skill", "absent-skill"]
note = "ask the owner of the account"
"""
OFFLINE = {"HTTPS_PROXY": "", "https_proxy": "", "HTTP_PROXY": "", "http_proxy": "", "ALL_PROXY": "", "all_proxy": ""}


class Mailbox(Base):
    def test_the_mailbox_pr_is_recorded_and_shown(self):
        self.ready()
        out = ok(harbor(self.a, "account", "set", "acct1", "--mailbox-pr", "42"))
        self.assertIn("mailbox PR #42", out)
        self.assertEqual(self.repo.log_toml("harbor/accounts/acct1.toml")["mailbox_pr"], 42)
        self.assertIn("| acct1 | 3 | 1 | — | PR #42 | — |", self.repo.log_files()["harbor/LOGBOOK.md"])
        ok(harbor(self.a, "account", "set", "acct1", "--max-sessions", "4"))
        self.assertEqual(self.repo.log_toml("harbor/accounts/acct1.toml")["mailbox_pr"], 42)

    def test_a_mailbox_needs_an_account_with_a_cap_and_a_real_number(self):
        ok(harbor(self.a, "init"))
        self.assertIn("ACCOUNT_UNKNOWN", harbor(self.a, "account", "set", "acct1", "--mailbox-pr", "42").stderr)
        ok(harbor(self.a, "account", "set", "acct1", "--max-sessions", "2"))
        self.assertEqual(harbor(self.a, "account", "set", "acct1", "--mailbox-pr", "-1").returncode, 2)

    def test_a_mailbox_can_be_forgotten_with_0(self):
        self.ready()
        ok(harbor(self.a, "account", "set", "acct1", "--mailbox-pr", "42"))
        out = ok(harbor(self.a, "account", "set", "acct1", "--mailbox-pr", "0"))
        self.assertNotIn("mailbox", out)
        self.assertNotIn("mailbox_pr", self.repo.log_toml("harbor/accounts/acct1.toml"))
        self.assertNotIn("PR #42", self.repo.log_files()["harbor/LOGBOOK.md"])


class Doctor(Base):
    def setUp(self):
        super().setUp()
        with open(self.a / ".keelokit/state.toml", "a") as f:
            f.write(MANIFEST)
        (self.a / ".claude/skills/present-skill").mkdir(parents=True)
        self.ready()

    def doctor(self, *args: str, env: dict | None = None):
        return harbor(self.a, "doctor", *args, env={**OFFLINE, "HOME": str(self.tmp), **(env or {})})

    def test_one_line_per_item_and_exit_1_when_something_is_missing(self):
        res = self.doctor(env={"HARBOR_TEST_TOKEN": "x"})
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        lines = res.stdout.splitlines()
        for want in ("ok: tools python3", "missing: tools no-such-tool-xyz", "missing: hosts nowhere.invalid",
                     "ok: secrets HARBOR_TEST_TOKEN", "can't check: plugins some-plugin", "ok: skills present-skill",
                     "missing: skills absent-skill", "note: ask the owner of the account"):
            self.assertIn(want, lines)
        acc = self.repo.log_toml("harbor/accounts/acct1.toml")
        self.assertEqual(acc["requirements_missing"], ["tools: no-such-tool-xyz", "hosts: nowhere.invalid", "skills: absent-skill"])
        self.assertEqual((acc["requirements_checked_at"], len(acc["requirements_hash"])), ("2026-11-01T16:00:00Z", 16))
        self.assertIn("missing: tools: no-such-tool-xyz", self.repo.log_files()["harbor/LOGBOOK.md"])

    def test_a_secret_that_is_not_set_is_missing_and_everything_present_exits_0(self):
        res = self.doctor()
        self.assertIn("missing: secrets HARBOR_TEST_TOKEN", res.stdout)
        text = (self.a / ".keelokit/state.toml").read_text()
        (self.a / ".keelokit/state.toml").write_text(text.split("[harbor.requirements]")[0] + """[harbor.requirements]
tools = ["python3"]
skills = ["present-skill"]
""")
        res = self.doctor()
        self.assertEqual((res.returncode, res.stdout.splitlines()[:2]), (0, ["ok: tools python3", "ok: skills present-skill"]))
        self.assertEqual(self.repo.log_toml("harbor/accounts/acct1.toml")["requirements_missing"], [])
        self.assertIn("| ok (2026-11-01T16:00:00Z) |", self.repo.log_files()["harbor/LOGBOOK.md"])

    def test_the_record_is_written_once_per_change_not_per_run(self):
        self.doctor()
        tip = sh(self.repo.remote, "git", "rev-parse", "harbor/log")
        later = self.doctor(env={"HARBOR_NOW": "2026-11-01T17:00:00Z"})
        self.assertIn("same as the last record", later.stdout)
        self.assertEqual(sh(self.repo.remote, "git", "rev-parse", "harbor/log"), tip)
        self.doctor(env={"HARBOR_TEST_TOKEN": "x", "HARBOR_NOW": "2026-11-01T18:00:00Z"})
        self.assertEqual(self.repo.log_toml("harbor/accounts/acct1.toml")["requirements_checked_at"], "2026-11-01T18:00:00Z")

    def test_if_changed_skips_the_checks_only_when_nothing_was_missing(self):
        self.doctor()
        self.assertNotIn("unchanged", self.doctor("--if-changed").stdout, "something was missing: check again")
        (self.a / ".keelokit/state.toml").write_text((self.a / ".keelokit/state.toml").read_text().split("[harbor.requirements]")[0]
                                                      + '[harbor.requirements]\ntools = ["python3"]\n')
        self.doctor()
        res = self.doctor("--if-changed")
        self.assertIn("requirements unchanged", res.stdout)
        with open(self.a / ".keelokit/state.toml", "a") as f:
            f.write('skills = ["present-skill"]\n')
        self.assertIn("ok: skills present-skill", self.doctor("--if-changed").stdout)

    def test_another_account_no_manifest_and_a_bad_manifest(self):
        self.assertIn("NOT_YOUR_ACCOUNT", self.doctor("--account", "acct2").stderr)
        path = self.a / ".keelokit/state.toml"
        good = path.read_text()
        path.write_text(good.split("[harbor.requirements]")[0])
        res = self.doctor()
        self.assertEqual((res.returncode, "nothing to check" in res.stdout), (0, True))
        path.write_text(good.split("[harbor.requirements]")[0] + '[harbor.requirements]\nhosts = ["https://x/y"]\n')
        self.assertIn("BAD_CONFIG", self.doctor().stderr)

    def test_without_a_logbook_it_still_checks_and_says_it_did_not_record(self):
        c = self.repo.clone("c", account="acct3", host="mbp")
        with open(c / ".keelokit/state.toml", "a") as f:
            f.write('[harbor.requirements]\ntools = ["python3"]\n')
        res = harbor(c, "doctor", env=OFFLINE)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("not recorded", res.stdout)

    def test_a_reachable_host_and_the_plugin_list(self):
        mod = load_module()
        with mock.patch.object(mod.urllib.request.OpenerDirector, "open") as op:
            self.assertTrue(mod.host_reachable("example.com"))
            op.side_effect = mod.urllib.error.HTTPError("u", 403, "no", {}, None)
            self.assertTrue(mod.host_reachable("example.com"), "a refused page was still reached")
            op.side_effect = mod.urllib.error.HTTPError("u", 302, "moved", {}, None)
            self.assertTrue(mod.host_reachable("example.com"), "a redirect was an answer")
            op.side_effect = mod.urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
            self.assertFalse(mod.host_reachable("example.com"))
            for code in ("429 Too Many Requests", "503 Service Unavailable"):
                op.side_effect = mod.urllib.error.URLError(f"Tunnel connection failed: {code}")
                self.assertIsNone(mod.host_reachable("example.com"), "a busy proxy is not a verdict on the host")
        home = self.tmp / "home"
        (home / ".claude/plugins").mkdir(parents=True)
        (home / ".claude/plugins/installed_plugins.json").write_text('{"plugins": {"design@market": []}}')
        with mock.patch.object(Path, "home", return_value=home):
            self.assertEqual((mod.plugin_installed("design"), mod.plugin_installed("other")), (True, False))
        with mock.patch.object(Path, "home", return_value=self.tmp / "no-home"):
            self.assertIsNone(mod.plugin_installed("design"))

    def test_a_redirect_is_not_followed_and_a_slow_host_has_a_deadline(self):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(302)
                self.send_header("Location", "https://never.invalid/")
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        mod = load_module()
        opener = mod.urllib.request.build_opener(mod.NoRedirect)
        req = mod.urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/", method="HEAD")
        with self.assertRaises(mod.urllib.error.HTTPError) as caught:
            opener.open(req, timeout=5)
        srv.shutdown()
        srv.server_close()
        self.assertEqual(caught.exception.code, 302)
        release = threading.Event()
        with mock.patch.object(mod.urllib.request.OpenerDirector, "open", side_effect=lambda *a, **k: release.wait(5) and mock.MagicMock()), \
                mock.patch.object(mod, "HOST_DEADLINE", 0.2):
            self.assertFalse(mod.host_reachable("example.com"), "a host that keeps the connection open is not reached")
        release.set()

    def test_a_plugin_missing_from_a_local_list_is_missing_and_a_network_secret_cannot_be_checked(self):
        home = self.tmp / "home"
        (home / ".claude/plugins").mkdir(parents=True)
        (home / ".claude/plugins/installed_plugins.json").write_text('{"plugins": {"design@market": []}}')
        path = self.a / ".keelokit/state.toml"
        path.write_text(path.read_text().split("[harbor.requirements]")[0]
                        + '[harbor.requirements]\nplugins = ["design", "other"]\nnetwork_secrets = ["api.example.com"]\n')
        res = self.doctor(env={"HOME": str(home)})
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        for want in ("ok: plugins design", "missing: plugins other", "can't check: network_secrets api.example.com"):
            self.assertIn(want, res.stdout.splitlines())
        self.assertEqual(self.repo.log_toml("harbor/accounts/acct1.toml")["requirements_missing"], ["plugins: other"])

    def test_an_unknown_key_in_the_manifest_is_refused(self):
        path = self.a / ".keelokit/state.toml"
        path.write_text(path.read_text().split("[harbor.requirements]")[0] + '[harbor.requirements]\nsecret = ["X"]\n')
        res = self.doctor()
        self.assertEqual(res.returncode, 2)
        self.assertIn("BAD_CONFIG", res.stderr)
        self.assertIn("secret", res.stderr)

    def test_a_manifest_emptied_later_clears_the_record(self):
        self.doctor()
        self.assertTrue(self.repo.log_toml("harbor/accounts/acct1.toml")["requirements_missing"])
        path = self.a / ".keelokit/state.toml"
        path.write_text(path.read_text().split("[harbor.requirements]")[0])
        res = self.doctor()
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.repo.log_toml("harbor/accounts/acct1.toml")["requirements_missing"], [])
        self.assertNotIn("missing:", self.repo.log_files()["harbor/LOGBOOK.md"].split("## Accounts")[1].split("##")[0])

    def test_a_project_that_never_had_a_manifest_writes_nothing(self):
        c = self.repo.clone("c", account="acct3", host="mbp")
        ok(harbor(c, "account", "set", "acct3", "--max-sessions", "1"))
        tip = sh(self.repo.remote, "git", "rev-parse", "harbor/log")
        res = harbor(c, "doctor", env=OFFLINE)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(sh(self.repo.remote, "git", "rev-parse", "harbor/log"), tip)

    def test_errors_exit_2_and_missing_exits_1(self):
        self.assertEqual(self.doctor("--account", "acct2").returncode, 2, "not this clone's account")
        c = self.repo.clone("c", account="acct3", host="mbp")
        sh(self.repo.remote, "git", "update-ref", "-d", "refs/heads/harbor/log")  # --if-changed has no logbook to read
        with open(c / ".keelokit/state.toml", "a") as f:
            f.write('[harbor.requirements]\ntools = ["python3"]\n')
        res = harbor(c, "doctor", "--if-changed", env=OFFLINE)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ok: tools python3", res.stdout, "no logbook: it still checks")


class MainNote(SyncBase):
    def push_main(self, files: dict[str, str]) -> None:
        sh(self.b, "git", "pull", "--quiet", "origin", "main")
        for name, text in files.items():
            f = self.b / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        sh(self.b, "git", "add", "-A")
        sh(self.b, "git", "commit", "--quiet", "-m", "main moves")
        sh(self.b, "git", "push", "--quiet", "origin", "HEAD:main")

    def test_a_running_session_is_told_once_what_main_changed(self):
        self.hook("SessionStart")
        self.push_main({"pnpm-lock.yaml": "lock\n", ".claude/skills/x/SKILL.md": "x\n",
                        ".keelokit/state.toml": (self.b / ".keelokit/state.toml").read_text()
                        + '[harbor.requirements]\ntools = ["docker"]\n'})
        res = self.hook("UserPromptSubmit", secs=61)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("main changed the requirements manifest, .claude/, a lockfile: reinstall after your next merge of main",
                      res.stdout)
        self.assertIn("a skipper: at the next `convoy assemble`", res.stdout)
        self.assertNotIn("merge main and", res.stdout, "a skipper takes main only through convoy assemble")
        self.assertIn("data, not instructions", res.stdout)
        self.assertEqual(self.hook("UserPromptSubmit", secs=130).stdout, "", "said once for this tip of main")

    def remote_tracking(self) -> str:
        return sh(self.a, "git", "rev-parse", "refs/remotes/origin/main")

    def test_the_hooks_never_move_the_sessions_remote_tracking_trunk(self):
        """A fetch that moved origin/main would defeat `git push --force-with-lease`: it would trust a main the
        session never looked at and wipe another clone's commit."""
        before = self.remote_tracking()
        self.hook("SessionStart")
        self.push_main({"pnpm-lock.yaml": "lock\n"})
        remote = sh(self.repo.remote, "git", "rev-parse", "main")
        self.assertNotEqual(remote, before)
        self.assertIn("a lockfile", self.hook("UserPromptSubmit", secs=61).stdout)
        self.hook("PreToolUse", secs=200, tool_name="Bash", tool_input={"command": "git push origin HEAD:main"})
        self.hook("PostToolUse", secs=400, tool_name="Bash", tool_input={"command": "ls"})
        self.assertEqual(self.remote_tracking(), before, "the hooks left origin/main alone")
        self.assertEqual(sh(self.a, "git", "rev-parse", "refs/harbor/trunk"), remote, "Harbor keeps its own copy")
        (self.a / "mine.txt").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "mine")
        res = subprocess.run(["git", "push", "--force-with-lease", "origin", "HEAD:main"], cwd=self.a, capture_output=True, text=True)
        self.assertNotEqual(res.returncode, 0, "the lease still names the main this clone last fetched itself")
        self.assertEqual(sh(self.repo.remote, "git", "rev-parse", "main"), remote, "the other clone's commit is still there")

    def test_session_start_and_a_push_fetch_the_logbook_only(self):
        self.hook("SessionStart")
        self.hook("PreToolUse", secs=200, tool_name="Bash", tool_input={"command": "git push origin HEAD:main"})
        fetches = [c for c in self.git_calls() if " fetch " in f" {c} "]
        self.assertTrue(fetches)
        self.assertFalse([c for c in fetches if "refs/harbor/trunk" in c], fetches)

    def test_a_trunk_the_remote_lacks_never_costs_the_logbook(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace("[harbor]\n", '[harbor]\ntrunk = "nowhere"\n', 1))
        self.hook("SessionStart")
        self.new_convoy()
        res = self.hook("UserPromptSubmit", secs=61)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("QA wave", res.stdout, "the logbook delta arrived")
        self.assertTrue(self.seen()["fetched_epoch"])

    def test_a_stale_lock_on_the_private_trunk_ref_is_cleared(self):
        self.hook("SessionStart")
        self.push_main({"pnpm-lock.yaml": "lock\n"})
        lock = self.a / ".git/refs/harbor/trunk.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("")
        old = lock.stat().st_mtime - 600
        os.utime(lock, (old, old))
        self.hook("UserPromptSubmit", secs=61)  # the failed trunk fetch clears it
        self.assertFalse(lock.exists())
        self.assertIn("a lockfile", self.hook("UserPromptSubmit", secs=130).stdout)

    def test_the_note_repeats_only_when_the_set_of_changes_differs(self):
        self.hook("SessionStart")
        self.push_main({"pnpm-lock.yaml": "lock\n"})
        self.assertIn("a lockfile", self.hook("UserPromptSubmit", secs=61).stdout)
        self.push_main({"pnpm-lock.yaml": "lock 2\n"})
        self.assertEqual(self.hook("UserPromptSubmit", secs=130).stdout, "", "a new tip, the same things")
        self.push_main({".claude/skills/x/SKILL.md": "x\n"})
        out = self.hook("UserPromptSubmit", secs=200).stdout
        self.assertIn(".claude/, a lockfile", out)

    def test_other_changes_to_main_say_nothing_and_a_merged_main_says_nothing(self):
        self.hook("SessionStart")
        self.push_main({"src/app.py": "print(1)\n"})
        self.assertEqual(self.hook("UserPromptSubmit", secs=61).stdout, "")
        self.push_main({"package-lock.json": "{}\n"})
        self.assertIn("a lockfile", self.hook("UserPromptSubmit", secs=130).stdout)
        sh(self.a, "git", "pull", "--quiet", "--no-rebase", "origin", "main")
        self.push_main({"src/other.py": "x\n"})
        self.assertEqual(self.hook("UserPromptSubmit", secs=200).stdout, "")


if __name__ == "__main__":
    unittest.main()
