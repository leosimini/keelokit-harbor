"""harbor.py, phase 1: the logbook (init, accounts, workers, seals, convoys new/add/status, the views,
the one-time BOARD.md import) and what happens when a push is rejected. Each test builds a bare
remote and one or two clones of a Keelokit project with the convoy policy.
Run: python3 -m unittest discover -s tests"""
import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

HARBOR = Path(__file__).resolve().parents[1] / "bin/harbor.py"
NOW = "2026-11-01T16:00:00Z"
GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}

STATE = """\
[landing]
policy = "convoy"

[harbor]
vessel_verify = "{verify}"

[harbor.hotspots]
schema = ["apps/api/prisma/*"]
i18n = ["apps/mobile/src/i18n/locales/"]
"""

BOARD = """\
# Tablero

coordina: session_01KwSx desde 2026-10-25 14:00 · último control 2026-11-01 15:21

## Trenes abiertos

| Tren | Jefe | Rama | Estado | Handoff |
| --- | --- | --- | --- | --- |
| 7 | session_aaa | `train/7-int` | en main | `tren-7.md` |
| 8 | session_bbb | `train/8-carga` | verificando | `tren-8.md` |
| 10 | session_ccc | `train/10-base` | esperando piezas | `tren-10.md` |
| Tren de Eventos | orquestador | `claude/eventos-tren` | en main | — |

## Sesiones activas

| Sesión | Tarea | Tren | Rama |
| --- | --- | --- | --- |
| session_bbb | CARGA ola 1 | 8 | `train/8-carga` |
"""


def sh(cwd: Path, *cmd: str, check: bool = True) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    if check and res.returncode != 0:
        raise AssertionError(f"{cmd} failed: {res.stderr}")
    return res.stdout.strip()


class Repo:
    """A bare remote with main, and clones that each carry their own .keelokit/local.toml."""

    def __init__(self, tmp: Path, verify: str = "true"):
        self.tmp = tmp
        self.remote = tmp / "remote.git"
        sh(tmp, "git", "init", "--quiet", "--bare", "-b", "main", str(self.remote))
        seed = tmp / "seed"
        sh(tmp, "git", "clone", "--quiet", str(self.remote), str(seed))
        sh(seed, "git", "checkout", "--quiet", "-b", "main")
        (seed / ".keelokit").mkdir()
        (seed / ".keelokit/state.toml").write_text(STATE.format(verify=verify))
        (seed / ".gitignore").write_text(".keelokit/local.toml\n")
        (seed / "README.md").write_text("app\n")
        sh(seed, "git", "add", "-A")
        sh(seed, "git", "commit", "--quiet", "-m", "init")
        sh(seed, "git", "push", "--quiet", "origin", "main")

    def clone(self, name: str, account: str = "leo", host: str = "mbp") -> Path:
        path = self.tmp / name
        sh(self.tmp, "git", "clone", "--quiet", str(self.remote), str(path))
        (path / ".keelokit/local.toml").write_text(f'[harbor]\naccount = "{account}"\nhost = "{host}"\n')
        return path

    def main_sha(self) -> str:
        return sh(self.remote, "git", "rev-parse", "main")

    def log_files(self) -> dict[str, str]:
        names = sh(self.remote, "git", "ls-tree", "-r", "--name-only", "harbor/log").splitlines()
        return {n: sh(self.remote, "git", "show", f"harbor/log:{n}") for n in names}

    def log_toml(self, path: str) -> dict:
        return tomllib.loads(sh(self.remote, "git", "show", f"harbor/log:{path}"))


def harbor(cwd: Path, *args: str, session: str | None = "s1", stdin: str | None = None, env: dict | None = None):
    cmd = [sys.executable, str(HARBOR)] + (["--session", session] if session else []) + list(args)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, input=stdin,
                          env={**os.environ, **GIT_ENV, "HARBOR_NOW": NOW, **(env or {})})


def ok(res) -> str:
    if res.returncode != 0:
        raise AssertionError(f"exit {res.returncode}: {res.stdout}{res.stderr}")
    return res.stdout


def vessel(clone: Path, branch: str, path: str, story: str | None = None) -> str:
    """A pushed vessel branch from origin/main with one commit touching `path`."""
    sh(clone, "git", "fetch", "--quiet", "origin", "main")
    sh(clone, "git", "checkout", "--quiet", "-B", branch, "origin/main")
    f = clone / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"{branch}\n")
    sh(clone, "git", "add", "-A")
    sh(clone, "git", "commit", "--quiet", "-m", f"feat: {branch}" + (f"\n\nStory: {story}" if story else ""))
    sh(clone, "git", "push", "--quiet", "-u", "origin", branch)
    return sh(clone, "git", "rev-parse", "HEAD")


class Base(unittest.TestCase):
    verify = "true"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = Repo(self.tmp, self.verify)
        self.a = self.repo.clone("a")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ready(self, clone: Path | None = None, session: str = "s1", cap: int = 3, role: str = "skipper"):
        clone = clone or self.a
        ok(harbor(clone, "init", session=session))
        ok(harbor(clone, "account", "set", "leo", "--max-sessions", str(cap), session=session))
        ok(harbor(clone, "worker", "register", "--role", role, "--model", "sonnet", session=session))


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_without_keelokit_it_says_so_and_does_nothing(self):
        sh(self.tmp, "git", "init", "--quiet")
        res = harbor(self.tmp, "check", "--hook", stdin='{"session_id": "abc"}')
        self.assertEqual(res.returncode, 0)
        self.assertIn("no .keelokit/", res.stdout)
        self.assertIn("does nothing", res.stdout)
        res = harbor(self.tmp, "init")
        self.assertEqual(res.returncode, 2)
        self.assertIn("NO_KEELOKIT", res.stderr)

    def test_without_the_convoy_policy_it_says_so(self):
        sh(self.tmp, "git", "init", "--quiet")
        (self.tmp / ".keelokit").mkdir()
        (self.tmp / ".keelokit/state.toml").write_text('[landing]\npolicy = "direct"\n')
        res = harbor(self.tmp, "check", "--hook", stdin="{}")
        self.assertEqual(res.returncode, 0)
        self.assertIn('policy is "direct"', res.stdout)
        res = harbor(self.tmp, "convoy", "new")
        self.assertEqual(res.returncode, 2)
        self.assertIn("POLICY_NOT_CONVOY", res.stderr)

    def test_outside_a_repo_the_hook_stays_quiet(self):
        res = harbor(self.tmp, "check", "--hook", stdin="{}", env={"CLAUDE_PROJECT_DIR": str(self.tmp)})
        self.assertEqual(res.returncode, 0)


class TestHook(Base):
    def test_the_session_start_hook_runs_check_from_the_plugin(self):
        import json
        hooks = json.loads((HARBOR.parents[1] / "hooks/hooks.json").read_text())
        command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        ok(harbor(self.a, "init"))
        res = subprocess.run(["bash", "-c", command], cwd=self.tmp, capture_output=True, text=True,
                             input='{"session_id": "s42"}',
                             env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(HARBOR.parents[1]), "CLAUDE_PROJECT_DIR": str(self.a)})
        self.assertEqual(res.returncode, 0)
        self.assertIn("this session is leo/mbp/s42", res.stdout)
        self.assertIn("logbook @", res.stdout)


class TestInit(Base):
    def test_init_creates_an_orphan_logbook_and_leaves_main_alone(self):
        main_before = self.repo.main_sha()
        out = ok(harbor(self.a, "init"))
        self.assertIn("created", out)
        parents = sh(self.repo.remote, "git", "rev-list", "--parents", "-n", "1", "harbor/log").split()
        self.assertEqual(len(parents), 1, "the logbook's first commit has no parent")
        self.assertEqual(sh(self.repo.remote, "git", "merge-base", "main", "harbor/log", check=False), "")
        files = self.repo.log_files()
        self.assertIn("harbor/harbormaster.toml", files)
        self.assertIn("Nobody holds the watch.", files["LOGBOOK.md"])
        self.assertTrue(files["LOGBOOK.md"].startswith("<!-- Generated by harbor.py"))
        self.assertEqual(self.repo.main_sha(), main_before)
        self.assertIn("Harbor-Worker: leo/mbp/s1", sh(self.repo.remote, "git", "log", "-1", "--format=%B", "harbor/log"))

    def test_init_again_changes_nothing(self):
        ok(harbor(self.a, "init"))
        tip = sh(self.repo.remote, "git", "rev-parse", "harbor/log")
        self.assertIn("already existed", ok(harbor(self.a, "init")))
        self.assertEqual(sh(self.repo.remote, "git", "rev-parse", "harbor/log"), tip)

    def test_writes_before_init_are_refused(self):
        res = harbor(self.a, "account", "set", "leo", "--max-sessions", "2")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT_INITIALIZED", res.stderr)

    def test_the_hook_names_the_session_and_the_logbook(self):
        ok(harbor(self.a, "init"))
        res = harbor(self.a, "check", "--hook", session=None, stdin='{"session_id": "abc123"}')
        self.assertEqual(res.returncode, 0)
        self.assertIn("this session is leo/mbp/abc123", res.stdout)
        self.assertIn("nobody holds the watch", res.stdout)


class TestAccountsAndWorkers(Base):
    def test_account_set_pause_resume(self):
        ok(harbor(self.a, "init"))
        ok(harbor(self.a, "account", "set", "leo", "--max-sessions", "2"))
        self.assertEqual(self.repo.log_toml("harbor/accounts/leo.toml")["max_sessions"], 2)
        ok(harbor(self.a, "account", "pause", "leo", "--until", "2026-11-02T03:00:00Z", "--reason", "weekly limit"))
        acc = self.repo.log_toml("harbor/accounts/leo.toml")
        self.assertEqual((acc["paused_until"], acc["reason"]), ("2026-11-02T03:00:00Z", "weekly limit"))
        self.assertIn("2026-11-02T03:00:00Z (weekly limit)", self.repo.log_files()["LOGBOOK.md"])
        ok(harbor(self.a, "account", "resume", "leo"))
        self.assertNotIn("paused_until", self.repo.log_toml("harbor/accounts/leo.toml"))

    def test_only_your_own_account(self):
        ok(harbor(self.a, "init"))
        res = harbor(self.a, "account", "set", "ana", "--max-sessions", "2")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT_YOUR_ACCOUNT", res.stderr)

    def test_a_time_without_zone_is_refused(self):
        ok(harbor(self.a, "init"))
        ok(harbor(self.a, "account", "set", "leo", "--max-sessions", "2"))
        res = harbor(self.a, "account", "pause", "leo", "--until", "2026-11-02T03:00:00")
        self.assertEqual(res.returncode, 2)
        self.assertIn("no time zone", res.stderr)

    def test_register_needs_an_account_cap(self):
        ok(harbor(self.a, "init"))
        res = harbor(self.a, "worker", "register", "--role", "vessel")
        self.assertEqual(res.returncode, 1)
        self.assertIn("ACCOUNT_UNKNOWN", res.stderr)

    def test_register_writes_the_worker_and_the_view(self):
        self.ready(role="vessel")
        w = self.repo.log_toml("harbor/workers/leo/mbp/s1.toml")
        self.assertEqual((w["id"], w["role"], w["state"], w["model"], w["last_seen"]),
                         ("leo/mbp/s1", "vessel", "active", "sonnet", NOW))
        self.assertIn("| leo/mbp/s1 | vessel |", self.repo.log_files()["LOGBOOK.md"])

    def test_register_respects_the_cap_and_ending_frees_a_place(self):
        self.ready(cap=1)
        res = harbor(self.a, "worker", "register", "--role", "vessel", session="s2")
        self.assertEqual(res.returncode, 1)
        self.assertIn("ACCOUNT_AT_CAP", res.stderr)
        self.assertIn("leo/mbp/s1", res.stderr)
        ok(harbor(self.a, "worker", "register", "--role", "skipper"))   # the same worker again is not a second one
        ok(harbor(self.a, "worker", "end"))
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="s2"))

    def test_register_refuses_a_paused_account(self):
        self.ready()
        ok(harbor(self.a, "account", "pause", "leo", "--until", "2026-11-02T03:00:00Z"))
        res = harbor(self.a, "worker", "register", "--role", "vessel", session="s2")
        self.assertEqual(res.returncode, 1)
        self.assertIn("ACCOUNT_PAUSED", res.stderr)
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="s2", env={"HARBOR_NOW": "2026-11-02T03:00:01Z"}))

    def test_end_with_a_handover_needs_the_pushed_head(self):
        self.ready(role="vessel")
        head = vessel(self.a, "claude/qa-sedes", "apps/web/a.ts")
        (self.a / "apps/web/b.ts").write_text("wip\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "wip")
        local = sh(self.a, "git", "rev-parse", "HEAD")
        res = harbor(self.a, "worker", "end", "--branch", "claude/qa-sedes", "--head", local)
        self.assertEqual(res.returncode, 1)
        self.assertIn("HANDOVER_NOT_PUSHED", res.stderr)
        ok(harbor(self.a, "worker", "end", "--branch", "claude/qa-sedes", "--head", head, "--verified", "seal of " + head[:9],
                  "--pending", "screenshots", "--worktree", "../app-qa-sedes"))
        w = self.repo.log_toml("harbor/workers/leo/mbp/s1.toml")
        self.assertEqual(w["state"], "ended")
        self.assertEqual(w["handover"]["head"], head)
        self.assertEqual(w["handover"]["pending"], "screenshots")

    def test_a_session_is_required_for_worker_writes(self):
        ok(harbor(self.a, "init"))
        res = harbor(self.a, "worker", "register", "--role", "vessel", session=None,
                     env={"HARBOR_SESSION": "", "CLAUDE_SESSION_ID": ""})
        self.assertEqual(res.returncode, 2)
        self.assertIn("NO_SESSION", res.stderr)

    def test_identity_comes_from_local_toml(self):
        ok(harbor(self.a, "init"))
        (self.a / ".keelokit/local.toml").unlink()
        res = harbor(self.a, "worker", "register", "--role", "vessel")
        self.assertEqual(res.returncode, 2)
        self.assertIn("NO_IDENTITY", res.stderr)


class TestSeal(Base):
    def test_a_green_run_is_recorded_by_hash_with_its_base(self):
        self.ready(role="vessel")
        head = vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        out = ok(harbor(self.a, "seal"))
        self.assertIn("pass", out)
        seal = self.repo.log_toml(f"harbor/seals/{head}.toml")
        self.assertEqual((seal["head"], seal["branch"], seal["exit"], seal["result"]), (head, "claude/qa-1", 0, "pass"))
        self.assertEqual(seal["base"], self.repo.main_sha())
        self.assertEqual(seal["command"], "true")
        self.assertEqual(seal["kind"], "vessel")

    def test_a_dirty_tree_is_refused(self):
        self.ready(role="vessel")
        vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        (self.a / "apps/web/a.ts").write_text("changed\n")
        res = harbor(self.a, "seal")
        self.assertEqual(res.returncode, 1)
        self.assertIn("DIRTY_TREE", res.stderr)

    def test_the_base_is_passed_to_the_verify_command(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace('vessel_verify = "true"', 'vessel_verify = "test {base} != x"'))
        sh(self.a, "git", "commit", "--quiet", "-am", "verify command")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.ready(role="vessel")
        head = vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        ok(harbor(self.a, "seal"))
        seal = self.repo.log_toml(f"harbor/seals/{head}.toml")
        self.assertEqual(seal["command"], f"test {seal['base']} != x")


FAKE_VERIFY = """\
# A stand-in for Keelokit's verify.sh: appends the history line verify.sh writes, with the fields Harbor reads.
# $1 = head; HARBOR_FAKE = JSON fields to override (partial, clean, base, result, level).
h=$(git rev-parse --git-common-dir)/keelokit-verify.history
python3 - "$1" "$h" <<'PY'
import json, os, subprocess, sys, time
head, path = sys.argv[1], sys.argv[2]
base = subprocess.run(["git", "rev-parse", "origin/main"], capture_output=True, text=True).stdout.strip()
entry = {"t": int(time.time()), "head": head, "base": base, "level": "changed", "result": "pass", "rc": 0,
         "partial": False, "scope": "", "clean": True, "planned": ["lint", "unit", "e2e-stack"],
         "passed": ["lint", "unit", "e2e-stack"], "failed_steps": [], "packages": ["apps/web"],
         "steps": [["lint", 12], ["unit", 340], ["e2e-stack", 1210]], "failed": [], "causes": []}
entry.update(json.loads(os.environ.get("HARBOR_FAKE") or "{}"))
with open(path, "a") as f:
    f.write(json.dumps(entry) + "\\n")
sys.exit(entry["rc"])
PY
"""


class TestSealAndKeelokit(Base):
    """What a seal takes from Keelokit's history: the steps, and `level` only for a whole green verify, which is
    what lets Keelokit's pre-push accept it as a shared seal. A run Keelokit already made is reused."""
    verify = "sh .keelokit/fake-verify.sh {head}"

    def setUp(self):
        super().setUp()
        (self.a / ".keelokit/fake-verify.sh").write_text(FAKE_VERIFY)
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fake verify")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.ready(role="vessel")
        self.head = vessel(self.a, "claude/qa-1", "apps/web/a.ts")

    def seal(self, **fake):
        import json
        return harbor(self.a, "seal", env={"HARBOR_FAKE": json.dumps(fake)})

    def recorded(self) -> dict:
        return self.repo.log_toml(f"harbor/seals/{self.head}.toml")

    def test_a_whole_green_verify_gets_a_level_and_its_steps(self):
        out = ok(self.seal())
        self.assertIn("pre-push accepts it (changed)", out)
        seal = self.recorded()
        self.assertEqual(seal["level"], "changed")
        self.assertEqual(seal["steps"], [{"name": "lint", "seconds": 12}, {"name": "unit", "seconds": 340},
                                         {"name": "e2e-stack", "seconds": 1210}])
        self.assertEqual((seal["planned"], seal["packages"], seal["partial"]), (["lint", "unit", "e2e-stack"], ["apps/web"], False))

    def test_a_partial_run_gets_no_level(self):
        out = ok(self.seal(partial=True, scope="./apps/web"))
        self.assertIn("not a shared seal", out)
        seal = self.recorded()
        self.assertNotIn("level", seal)
        self.assertEqual(seal["exit"], 0)

    def test_a_dirty_start_or_another_base_gets_no_level(self):
        ok(self.seal(clean=False))
        self.assertNotIn("level", self.recorded())
        ok(self.seal(base="0" * 40))
        self.assertNotIn("level", self.recorded())

    def test_a_red_run_gets_no_level(self):
        res = self.seal(result="fail", rc=1, failed_steps=["unit"], causes=["heap"])
        self.assertEqual(res.returncode, 1)
        seal = self.recorded()
        self.assertNotIn("level", seal)
        self.assertEqual((seal["failed_steps"], seal["causes"]), (["unit"], ["heap"]))

    def test_keelokits_own_green_run_is_reused_not_repeated(self):
        ok(self.seal())  # stands for build-story's `pnpm verify`, which writes the same history line
        (self.a / ".keelokit/state.toml").write_text(
            (self.a / ".keelokit/state.toml").read_text().replace("sh .keelokit/fake-verify.sh {head}", "false"))
        sh(self.a, "git", "update-index", "--assume-unchanged", ".keelokit/state.toml")
        out = ok(harbor(self.a, "seal"))
        self.assertIn("already passed Keelokit's verify", out)
        seal = self.recorded()
        self.assertEqual((seal["reused"], seal["exit"], seal["level"], seal["duration_seconds"]), (True, 0, "changed", 1562))
        res = harbor(self.a, "seal", "--rerun")
        self.assertEqual(res.returncode, 1, "--rerun runs the command (here `false`) instead of reusing")

    def test_a_partial_green_run_is_not_reused(self):
        ok(self.seal(partial=True))
        (self.a / ".keelokit/state.toml").write_text(
            (self.a / ".keelokit/state.toml").read_text().replace("sh .keelokit/fake-verify.sh {head}", "false"))
        sh(self.a, "git", "update-index", "--assume-unchanged", ".keelokit/state.toml")
        self.assertEqual(harbor(self.a, "seal").returncode, 1)


class TestRedSeal(Base):
    verify = "false"

    def test_a_red_run_is_recorded_and_the_exit_says_so(self):
        self.ready(role="vessel")
        head = vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        res = harbor(self.a, "seal")
        self.assertEqual(res.returncode, 1)
        seal = self.repo.log_toml(f"harbor/seals/{head}.toml")
        self.assertEqual((seal["exit"], seal["result"]), (1, "fail"))

    def test_a_red_seal_does_not_enter(self):
        self.ready()
        ok(harbor(self.a, "convoy", "new"))
        vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        harbor(self.a, "seal")
        res = harbor(self.a, "convoy", "add", "1", "claude/qa-1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("SEAL_RED", res.stderr)


class TestConvoy(Base):
    def test_new_numbers_convoys_and_records_the_base(self):
        self.ready()
        ok(harbor(self.a, "convoy", "new", "--title", "QA wave", "--expect", "QA-1", "QA-3"))
        ok(harbor(self.a, "convoy", "new", "--depends", "1"))
        c1 = self.repo.log_toml("harbor/convoys/1.toml")
        self.assertEqual((c1["state"], c1["branch"], c1["skipper"], c1["integrator"]),
                         ("assembling", "convoy/1", "leo/mbp/s1", "leo/mbp/s1"))
        self.assertEqual(c1["base"], self.repo.main_sha())
        self.assertEqual(c1["expected"], ["QA-1", "QA-3"])
        self.assertEqual(c1["events"][0]["what"], "new")
        self.assertEqual(self.repo.log_toml("harbor/convoys/2.toml")["depends_on"], [1])
        files = self.repo.log_files()
        self.assertIn("convoys/1.md", files)
        self.assertIn("## Expected, not delivered", files["convoys/1.md"])
        self.assertIn("| [2](convoys/2.md) | assembling |", files["LOGBOOK.md"])
        self.assertEqual(self.repo.log_toml("harbor/workers/leo/mbp/s1.toml")["convoy"], 2)

    def test_new_refuses_an_unknown_dependency_and_an_unregistered_worker(self):
        self.ready()
        res = harbor(self.a, "convoy", "new", "--depends", "4")
        self.assertIn("UNKNOWN_CONVOY", res.stderr)
        res = harbor(self.a, "convoy", "new", session="s9")
        self.assertIn("NOT_REGISTERED", res.stderr)

    def test_a_pilot_account_is_the_integrator(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace("[harbor]\n", '[harbor]\nintegrator = "ana"\n'))
        sh(self.a, "git", "commit", "--quiet", "-am", "pilot")
        self.ready()
        ok(harbor(self.a, "convoy", "new"))
        self.assertEqual(self.repo.log_toml("harbor/convoys/1.toml")["integrator"], "account:ana")

    def add_ready(self):
        self.ready()
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1"))

    def test_add_with_branch_hash_and_seal(self):
        self.add_ready()
        head = vessel(self.a, "claude/qa-1", "apps/web/a.ts", story="QA-1")
        ok(harbor(self.a, "seal"))
        out = ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1", "--head", head, "--tier", "light"))
        self.assertIn("added to convoy 1", out)
        c = self.repo.log_toml("harbor/convoys/1.toml")
        v = c["vessels"][0]
        self.assertEqual((v["branch"], v["head"], v["story"], v["tier"], v["hotspots"]),
                         ("claude/qa-1", head, "QA-1", "light", []))
        self.assertEqual(c["events"][-1]["what"], "add")
        view = self.repo.log_files()["convoys/1.md"]
        self.assertIn("| `claude/qa-1` |", view)
        self.assertIn("exit 0", view)
        self.assertNotIn("## Expected, not delivered", view)

    def test_add_refuses_an_unpushed_branch(self):
        self.add_ready()
        sh(self.a, "git", "checkout", "--quiet", "-b", "claude/local")
        res = harbor(self.a, "convoy", "add", "1", "claude/local")
        self.assertEqual(res.returncode, 1)
        self.assertIn("BRANCH_NOT_PUSHED", res.stderr)

    def test_add_refuses_without_a_seal(self):
        self.add_ready()
        vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        res = harbor(self.a, "convoy", "add", "1", "claude/qa-1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NO_SEAL", res.stderr)

    def test_a_commit_after_the_seal_voids_the_delivery(self):
        self.add_ready()
        sealed = vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        ok(harbor(self.a, "seal"))
        (self.a / "apps/web/a.ts").write_text("review fix\n")
        sh(self.a, "git", "commit", "--quiet", "-am", "fix: review")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-1")
        res = harbor(self.a, "convoy", "add", "1", "claude/qa-1", "--head", sealed)
        self.assertEqual(res.returncode, 1)
        self.assertIn("HEAD_MISMATCH", res.stderr)
        res = harbor(self.a, "convoy", "add", "1", "claude/qa-1")
        self.assertIn("NO_SEAL", res.stderr, "the new tip has no seal of its own")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))

    def test_a_moved_branch_shows_in_status_and_redelivery_replaces_it(self):
        self.add_ready()
        first = vessel(self.a, "claude/qa-1", "apps/web/a.ts", story="QA-1")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        (self.a / "apps/web/a.ts").write_text("fix\n")
        sh(self.a, "git", "commit", "--quiet", "-am", "fix")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-1")
        self.assertIn("after delivery: the delivery is void", ok(harbor(self.a, "convoy", "status", "1")))
        ok(harbor(self.a, "seal"))
        self.assertIn("redelivered", ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1")))
        c = self.repo.log_toml("harbor/convoys/1.toml")
        self.assertEqual(len(c["vessels"]), 1)
        self.assertNotEqual(c["vessels"][0]["head"], first)
        self.assertEqual(c["events"][-1]["what"], "redelivered")

    def test_only_the_skipper_adds(self):
        self.add_ready()
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="s2"))
        vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        ok(harbor(self.a, "seal", session="s2"))
        res = harbor(self.a, "convoy", "add", "1", "claude/qa-1", session="s2")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NOT_SKIPPER", res.stderr)

    def test_two_vessels_on_one_hotspot_are_serialized(self):
        self.add_ready()
        vessel(self.a, "claude/org-orga", "apps/api/prisma/schema.prisma")
        ok(harbor(self.a, "seal"))
        out = ok(harbor(self.a, "convoy", "add", "1", "claude/org-orga"))
        self.assertIn("hotspots: schema", out)
        vessel(self.a, "claude/org-orgb", "apps/api/prisma/seed.ts")
        ok(harbor(self.a, "seal"))
        res = harbor(self.a, "convoy", "add", "1", "claude/org-orgb")
        self.assertEqual(res.returncode, 1)
        self.assertIn("HOTSPOT_HELD", res.stderr)
        self.assertIn("claude/org-orga in convoy 1", res.stderr)
        vessel(self.a, "claude/ui", "apps/web/x.ts")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/ui"))

    def test_a_vessel_is_in_one_convoy(self):
        self.add_ready()
        ok(harbor(self.a, "convoy", "new"))
        ok(harbor(self.a, "worker", "register", "--role", "skipper", "--convoy", "1"))
        vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        ok(harbor(self.a, "seal"))
        # s1 is skipper of both: convoy new made it skipper of 2, and convoy 1 still names it.
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        res = harbor(self.a, "convoy", "add", "2", "claude/qa-1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("VESSEL_TAKEN", res.stderr)

    def test_status_reports_main_moving_and_missing_vessels(self):
        self.add_ready()
        sh(self.a, "git", "checkout", "--quiet", "main")
        (self.a / "hotfix.txt").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: red main")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        out = ok(harbor(self.a, "convoy", "status"))
        self.assertIn("convoy 1 · assembling", out)
        self.assertIn("main moved", out)
        self.assertIn("expected, not delivered: QA-1", out)

    def test_log_prints_the_logbook(self):
        self.add_ready()
        out = ok(harbor(self.a, "log"))
        self.assertIn("# Logbook", out)
        self.assertIn("(logbook @", out)

    def test_main_is_never_written(self):
        before = self.repo.main_sha()
        self.add_ready()
        vessel(self.a, "claude/qa-1", "apps/web/a.ts")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-1"))
        self.assertEqual(self.repo.main_sha(), before)
        tree = sh(self.repo.remote, "git", "ls-tree", "-r", "--name-only", "main").splitlines()
        self.assertFalse([p for p in tree if p.startswith(("harbor/", "convoys/")) or p == "LOGBOOK.md"])


class TestImportBoard(Base):
    def test_imports_numbered_trains_once(self):
        ok(harbor(self.a, "init"))
        board = self.tmp / "BOARD.md"
        board.write_text(BOARD)
        out = ok(harbor(self.a, "import-board", str(board)))
        self.assertIn("imported 3 convoy(s)", out)
        self.assertIn("watch is not imported", out)
        c8 = self.repo.log_toml("harbor/convoys/8.toml")
        self.assertEqual((c8["state"], c8["branch"], c8["imported_skipper"], c8["imported"]),
                         ("verifying", "train/8-carga", "session_bbb", True))
        self.assertEqual(self.repo.log_toml("harbor/convoys/7.toml")["state"], "sailed")
        self.assertEqual(self.repo.log_toml("harbor/convoys/10.toml")["state"], "waiting")
        meta = self.repo.log_toml("harbor/imported/board.toml")
        self.assertEqual(meta["convoys"], [7, 8, 10])
        self.assertTrue(any("Tren de Eventos" in s for s in meta["skipped"]))
        self.assertIn("session_01KwSx", meta["coordinator"])
        files = self.repo.log_files()
        self.assertEqual(files["harbor/imported/BOARD.md"].strip(), BOARD.strip())
        self.assertIn("(imported)", files["LOGBOOK.md"])
        self.assertNotIn("worker", self.repo.log_toml("harbor/harbormaster.toml"))
        res = harbor(self.a, "import-board", str(board))
        self.assertEqual(res.returncode, 1)
        self.assertIn("ALREADY_IMPORTED", res.stderr)

    def test_new_convoys_number_after_the_imported_ones(self):
        self.ready()
        board = self.tmp / "BOARD.md"
        board.write_text(BOARD)
        ok(harbor(self.a, "import-board", str(board)))
        ok(harbor(self.a, "convoy", "new"))
        self.assertEqual(self.repo.log_toml("harbor/convoys/11.toml")["state"], "assembling")


def load_module():
    spec = importlib.util.spec_from_file_location("harbor_under_test", HARBOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRejectedPush(Base):
    """Two clones write at once: the second push is rejected and replayed on the new tip, never forced."""

    def setUp(self):
        super().setUp()
        self.b = self.repo.clone("b", host="linux")
        self.env = {**GIT_ENV, "HARBOR_NOW": NOW}
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def run_in_process(self, clone: Path, argv: list[str], meanwhile) -> int:
        mod = load_module()
        mod.BEFORE_PUSH = meanwhile
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return mod.main(argv, root=clone)

    def test_both_writes_land_one_after_the_other(self):
        ok(harbor(self.a, "init"))
        ok(harbor(self.a, "account", "set", "leo", "--max-sessions", "4"))
        pushed_by_b = []

        def b_writes_first():
            ok(harbor(self.b, "worker", "register", "--role", "vessel", session="sb"))
            pushed_by_b.append(sh(self.repo.remote, "git", "rev-parse", "harbor/log"))

        rc = self.run_in_process(self.a, ["--session", "sa", "worker", "register", "--role", "skipper"], b_writes_first)
        self.assertEqual(rc, 0)
        files = self.repo.log_files()
        self.assertIn("harbor/workers/leo/linux/sb.toml", files)
        self.assertIn("harbor/workers/leo/mbp/sa.toml", files)
        self.assertIn("leo/linux/sb", files["LOGBOOK.md"])
        self.assertIn("leo/mbp/sa", files["LOGBOOK.md"])
        # a's commit sits on top of b's: linear history, nothing overwritten
        tip_parent = sh(self.repo.remote, "git", "rev-parse", "harbor/log^")
        self.assertEqual(tip_parent, pushed_by_b[0])

    def test_the_replay_checks_preconditions_again(self):
        ok(harbor(self.a, "init"))
        ok(harbor(self.a, "account", "set", "leo", "--max-sessions", "1"))

        def b_takes_the_last_place():
            ok(harbor(self.b, "worker", "register", "--role", "vessel", session="sb"))

        rc = self.run_in_process(self.a, ["--session", "sa", "worker", "register", "--role", "skipper"], b_takes_the_last_place)
        self.assertEqual(rc, 1, "after the replay the cap is full, so a is refused instead of overwriting b")
        self.assertNotIn("harbor/workers/leo/mbp/sa.toml", self.repo.log_files())

    def test_a_hotspot_taken_meanwhile_refuses_the_replayed_add(self):
        ok(harbor(self.a, "init"))
        ok(harbor(self.a, "account", "set", "leo", "--max-sessions", "4"))
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="sa"))
        ok(harbor(self.b, "worker", "register", "--role", "skipper", session="sb"))
        ok(harbor(self.a, "convoy", "new", session="sa"))
        ok(harbor(self.b, "convoy", "new", session="sb"))
        vessel(self.a, "claude/mig-a", "apps/api/prisma/migrations/20261101_a/migration.sql")
        ok(harbor(self.a, "seal", session="sa"))
        vessel(self.b, "claude/mig-b", "apps/api/prisma/migrations/20261101_b/migration.sql")
        ok(harbor(self.b, "seal", session="sb"))

        def b_adds_first():
            ok(harbor(self.b, "convoy", "add", "2", "claude/mig-b", session="sb"))

        rc = self.run_in_process(self.a, ["--session", "sa", "convoy", "add", "1", "claude/mig-a"], b_adds_first)
        self.assertEqual(rc, 1)
        self.assertEqual(self.repo.log_toml("harbor/convoys/1.toml")["vessels"], [])
        self.assertEqual(self.repo.log_toml("harbor/convoys/2.toml")["vessels"][0]["branch"], "claude/mig-b")

    def test_two_inits_at_once_make_one_logbook(self):
        def b_inits_first():
            ok(harbor(self.b, "init", session="sb"))

        rc = self.run_in_process(self.a, ["--session", "sa", "init"], b_inits_first)
        self.assertEqual(rc, 0)
        self.assertEqual(sh(self.repo.remote, "git", "rev-list", "--count", "harbor/log"), "1")


class TestToml(unittest.TestCase):
    def test_round_trip(self):
        mod = load_module()
        data = {"schema": 1, "title": 'quotes " and \\ and ñ and \x7f', "ok": True, "none": None, "list": ["a", "b"],
                "empty": [], "handover": {"branch": "claude/x", "head": None},
                "vessels": [{"branch": "a", "hotspots": ["schema"]}, {"branch": "b", "hotspots": []}],
                "events": [{"at": NOW, "what": "new", "detail": None}]}
        back = tomllib.loads(mod.dumps(data))
        self.assertEqual(back["title"], data["title"])
        self.assertNotIn("none", back)
        self.assertEqual(back["handover"], {"branch": "claude/x"})
        self.assertEqual(back["vessels"], data["vessels"])
        self.assertEqual(back["empty"], [])
        self.assertEqual(back["events"], [{"at": NOW, "what": "new"}])


if __name__ == "__main__":
    unittest.main()
