"""harbor.py, phase 2: the watch (takeover, control), and a convoy's life after its vessels are in:
assemble, the ok, the one verify, the sail; abort and defer. A stand-in for Keelokit's verify writes the
history line verify.sh writes, so seals get their level the way they would in a real project.
Run: python3 -m unittest discover -s tests"""
import json
import unittest

from test_harbor import NOW, Base, harbor, ok, sh, vessel

FAKE = """\
# Keelokit's verify.sh, as far as Harbor sees it: one history line per run. $1 head, $2 level, $3 a tag.
# HARBOR_FAKE = JSON fields to override (rc, result, partial, failed_steps, ...).
h=$(git rev-parse --git-common-dir)/keelokit-verify.history
echo "$3" >> "$(git rev-parse --git-common-dir)/fake-runs"
python3 - "$1" "$h" "${2:-changed}" <<'PY'
import json, os, subprocess, sys, time
head, path, level = sys.argv[1], sys.argv[2], sys.argv[3]
base = subprocess.run(["git", "rev-parse", "origin/main"], capture_output=True, text=True).stdout.strip()
entry = {"t": int(time.time()), "head": head, "base": base, "level": level, "result": "pass", "rc": 0,
         "partial": False, "since": False, "scope": "", "clean": True, "planned": ["unit"], "passed": ["unit"], "failed_steps": [],
         "packages": [], "steps": [["unit", 5]], "failed": [], "causes": []}
entry.update(json.loads(os.environ.get("HARBOR_FAKE") or "{}"))
with open(path, "a") as f:
    f.write(json.dumps(entry) + "\\n")
sys.exit(entry["rc"])
PY
"""

CONFIG = """vessel_verify = "sh .keelokit/fake-verify.sh {head} changed vessel"
convoy_verify = "sh .keelokit/fake-verify.sh {head} changed convoy"
convoy_verify_all = "sh .keelokit/fake-verify.sh {head} all convoy-all"
convoy_rerun = "sh .keelokit/fake-verify.sh {head} changed rerun"
convoy_preflight = ""
ci_check = "true"
"""

EXTRA = """
[harbor.generated]
"site/" = "sh -c 'echo regenerated > site/index.json'"

[harbor.migrations]
paths = ["db/migrations"]
"""


class Phase2(Base):
    def setUp(self):
        super().setUp()
        self.configure()
        self.ready(cap=6)
        ok(harbor(self.a, "harbormaster", "takeover"))

    def configure(self, extra_harbor: str = ""):
        state = self.a / ".keelokit/state.toml"
        text = state.read_text()
        text = text.replace('vessel_verify = "true"\n', CONFIG + extra_harbor)
        state.write_text(text + EXTRA)
        (self.a / ".keelokit/fake-verify.sh").write_text(FAKE)
        (self.a / "site").mkdir(exist_ok=True)
        (self.a / "site/index.json").write_text("original\n")
        (self.a / "shared.ts").write_text("export const x = 1\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "harbor config")
        sh(self.a, "git", "push", "--quiet", "origin", "main")

    def runs(self) -> list[str]:
        try:
            return (self.a / ".git/fake-runs").read_text().split()
        except OSError:
            return []

    def deliver(self, n: int, branch: str, path: str, story: str, content: str | None = None) -> str:
        head = vessel(self.a, branch, path, story=story)
        if content is not None:
            (self.a / path).write_text(content)
            sh(self.a, "git", "commit", "--quiet", "-am", f"feat: {branch}\n\nStory: {story}")
            sh(self.a, "git", "push", "--quiet", "origin", branch)
            head = sh(self.a, "git", "rev-parse", "HEAD")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", str(n), branch))
        return head

    def convoy(self, n: int = 1) -> dict:
        return self.repo.log_toml(f"harbor/convoys/{n}.toml")

    def events(self, n: int = 1) -> list[str]:
        return [e["what"] for e in self.convoy(n)["events"]]

    def two_vessels_ready(self) -> tuple[str, str]:
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        a = self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        b = self.deliver(1, "claude/qa-3", "apps/web/b.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        return a, b

    def ok_changed(self, n: int = 1, **kw):
        return harbor(self.a, "convoy", "sail", str(n), "--ok", "--level", "changed", "--reason", "apps/web only", **kw)


class TestWatch(Phase2):
    def test_takeover_records_the_watch_and_its_expiry(self):
        hm = self.repo.log_toml("harbor/harbormaster.toml")
        self.assertEqual((hm["worker"], hm["since"], hm["last_control"], hm["expires"]),
                         ("leo/mbp/s1", NOW, NOW, "2026-11-01T19:00:00Z"))
        self.assertEqual(self.repo.log_toml("harbor/workers/leo/mbp/s1.toml")["role"], "harbormaster")
        self.assertIn("leo/mbp/s1, since", self.repo.log_files()["harbor/LOGBOOK.md"])

    def test_a_held_watch_is_refused_until_it_expires(self):
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="s2"))
        res = harbor(self.a, "harbormaster", "takeover", session="s2")
        self.assertEqual(res.returncode, 1)
        self.assertIn("WATCH_HELD", res.stderr)
        later = {"HARBOR_NOW": "2026-11-01T19:00:01Z"}
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="s2", env=later))
        ok(harbor(self.a, "harbormaster", "takeover", session="s2", env=later))
        hm = self.repo.log_toml("harbor/harbormaster.toml")
        self.assertEqual(hm["worker"], "leo/mbp/s2")
        self.assertEqual(hm["history"][0], {"worker": "leo/mbp/s1", "since": NOW, "until": "2026-11-01T19:00:01Z",
                                            "reason": "expired"})

    def test_the_owner_can_relieve_a_live_watch(self):
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="s2"))
        ok(harbor(self.a, "harbormaster", "takeover", "--relieve", "Leo moved the watch", session="s2"))
        hm = self.repo.log_toml("harbor/harbormaster.toml")
        self.assertEqual(hm["worker"], "leo/mbp/s2")
        self.assertEqual(hm["history"][0]["reason"], "relieved by the owner: Leo moved the watch")

    def test_control_renews_the_heartbeat_and_only_the_holder_runs_it(self):
        later = {"HARBOR_NOW": "2026-11-01T17:30:00Z"}
        out = ok(harbor(self.a, "harbormaster", "control", env=later))
        self.assertIn("watch: leo/mbp/s1 until 2026-11-01T20:30:00Z", out)
        self.assertEqual(self.repo.log_toml("harbor/harbormaster.toml")["last_control"], "2026-11-01T17:30:00Z")
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="s2"))
        res = harbor(self.a, "harbormaster", "control", session="s2")
        self.assertIn("NOT_HARBORMASTER", res.stderr)

    def test_control_records_a_loose_push_and_marks_lost_workers(self):
        ok(harbor(self.a, "harbormaster", "control"))
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="s2"))
        sh(self.a, "git", "checkout", "--quiet", "main")
        (self.a / "hotfix.txt").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: red main")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        out = ok(harbor(self.a, "harbormaster", "control", env={"HARBOR_NOW": "2026-11-01T19:30:00Z"}))
        self.assertIn("a loose push, recorded", out)
        self.assertIn("lost: leo/mbp/s2", out)
        moves = self.repo.log_toml("harbor/main.toml")["moves"]
        self.assertEqual((moves[-1]["cause"], moves[-1]["to"]), ("loose", self.repo.main_sha()))
        self.assertEqual(self.repo.log_toml("harbor/workers/leo/mbp/s2.toml")["state"], "lost")
        self.assertIn("Moves no convoy explains", self.repo.log_files()["harbor/LOGBOOK.md"])


class TestOwners(Phase2):
    """Whoever spawns a session owns its result: the logbook knows who, and control names the orphans."""

    def test_a_spawned_session_names_its_owner(self):
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--spawned-by", "leo/mbp/s1", session="s2"))
        self.assertEqual(self.repo.log_toml("harbor/workers/leo/mbp/s2.toml")["spawned_by"], "leo/mbp/s1")
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--branch", "claude/x", session="s2"))
        self.assertEqual(self.repo.log_toml("harbor/workers/leo/mbp/s2.toml")["spawned_by"], "leo/mbp/s1",
                         "registering again keeps the owner")
        self.assertIn("| ↳ leo/mbp/s2 | leo/mbp/s2 | vessel |", self.repo.log_files()["harbor/LOGBOOK.md"])

    def test_the_owner_must_be_an_active_worker(self):
        res = harbor(self.a, "worker", "register", "--role", "vessel", "--spawned-by", "leo/mbp/nobody", session="s2")
        self.assertIn("SPAWNER_UNKNOWN", res.stderr)
        res = harbor(self.a, "worker", "register", "--role", "vessel", "--spawned-by", "leo/mbp/s2", session="s2")
        self.assertIn("doesn't spawn itself", res.stderr)

    def test_ending_with_children_says_so_and_control_names_the_orphans(self):
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="boss"))
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--spawned-by", "leo/mbp/boss", session="kid"))
        out = ok(harbor(self.a, "worker", "end", session="boss"))
        self.assertIn("still running, launched by this session: leo/mbp/kid", out)
        self.assertEqual(self.repo.log_toml("harbor/workers/leo/mbp/boss.toml")["children_at_end"], ["leo/mbp/kid"])
        out = ok(harbor(self.a, "harbormaster", "control"))
        self.assertIn("orphan: leo/mbp/kid, spawned by leo/mbp/boss, which is ended", out)

    def test_an_owner_lost_in_the_round_leaves_an_orphan(self):
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="boss"))
        later = {"HARBOR_NOW": "2026-11-01T18:00:00Z"}
        ok(harbor(self.a, "worker", "register", "--role", "vessel", "--spawned-by", "leo/mbp/boss", session="kid", env=later))
        ok(harbor(self.a, "harbormaster", "takeover", env=later))
        out = ok(harbor(self.a, "harbormaster", "control", env={"HARBOR_NOW": "2026-11-01T19:30:00Z"}))
        self.assertIn("lost: leo/mbp/boss", out)
        self.assertIn("orphan: leo/mbp/kid, spawned by leo/mbp/boss, which is lost", out)


STATUS = """\
import sys
# Keelokit 0.12's status.py title, as far as Harbor sees it.
waves = {"QA-1": 2, "QA-3": 2}
args = sys.argv[1:]
if args[:1] != ["title"]:
    sys.exit(2)
if args[1:] == ["--role", "coordinator"]:
    print("Demo · coordinator")
elif len(args) == 2 and args[1] in waves:
    print(f"Demo · wave {waves[args[1]]} · {args[1]}")
else:
    sys.exit(2)
"""


class TestTitles(Phase2):
    def setUp(self):
        super().setUp()
        (self.a / ".keelokit/bin").mkdir(exist_ok=True)
        (self.a / ".keelokit/bin/status.py").write_text(STATUS)
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "status.py")

    def test_each_role_gets_keelokits_title_with_the_convoy(self):
        out = ok(harbor(self.a, "harbormaster", "takeover"))
        self.assertIn("session title: Demo · harbormaster", out)
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="sk"))
        out = ok(harbor(self.a, "convoy", "new", session="sk"))
        self.assertIn("session title: Demo · C1 · skipper", out)
        out = ok(harbor(self.a, "worker", "register", "--role", "vessel", "--convoy", "1", "--story", "QA-1",
                        "--spawned-by", "leo/mbp/sk", "--branch", "claude/keen-x", session="v1"))
        self.assertIn("session title: Demo · C1 · wave 2 · QA-1", out)
        w = self.repo.log_toml("harbor/workers/leo/mbp/v1.toml")
        self.assertEqual((w["title"], w["story"], w["canonical_branch"]), ("Demo · C1 · wave 2 · QA-1", "QA-1", "qa-1"))
        view = self.repo.log_files()["harbor/LOGBOOK.md"]
        self.assertIn("| Demo · C1 · skipper | leo/mbp/sk |", view)
        self.assertIn("| ↳ Demo · C1 · wave 2 · QA-1 | leo/mbp/v1 | vessel | claude/keen-x (qa-1) |", view)

    def test_the_title_before_the_session_exists(self):
        self.assertEqual(ok(harbor(self.a, "title", "--role", "vessel", "--convoy", "3", "--story", "QA-3")).strip(),
                         "Demo · C3 · wave 2 · QA-3")
        self.assertEqual(ok(harbor(self.a, "title", "--role", "harbormaster")).strip(), "Demo · harbormaster")
        self.assertIn("NO_TITLE", harbor(self.a, "title", "--role", "vessel", "--story", "NOPE-1").stderr)

    def test_an_unknown_story_is_refused(self):
        res = harbor(self.a, "worker", "register", "--role", "vessel", "--story", "NOPE-1", session="v1")
        self.assertIn("UNKNOWN_STORY", res.stderr)


class TestModels(Phase2):
    def test_defaults_and_overrides(self):
        out = ok(harbor(self.a, "models"))
        self.assertIn("control haiku (default)", out)
        self.assertIn("skipper sonnet (default)", out)
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text() + '\n[harbor.models]\nharbormaster = "opus"\n')
        out = ok(harbor(self.a, "models"))
        self.assertIn("harbormaster opus (state.toml [harbor.models])", out)


class TestAssemble(Phase2):
    def test_two_vessels_are_merged_pushed_and_ready(self):
        a, b = self.two_vessels_ready()
        c = self.convoy()
        self.assertEqual(c["state"], "ready")
        head = sh(self.repo.remote, "git", "rev-parse", "convoy/1")
        self.assertEqual(c["head"], head)
        self.assertEqual(c["base"], self.repo.main_sha())
        for sha in (a, b, self.repo.main_sha()):
            sh(self.repo.remote, "git", "merge-base", "--is-ancestor", sha, head)
        self.assertTrue(all(v.get("merged") for v in c["vessels"]))
        self.assertEqual(self.events()[-1], "assembled")

    def test_one_vessel_is_a_fast_forward(self):
        ok(harbor(self.a, "convoy", "new"))
        head = self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertEqual(self.convoy()["head"], head)

    def test_a_missing_story_or_an_open_dependency_waits(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        out = ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertIn("waiting for stories QA-3", out)
        self.assertEqual(self.convoy()["state"], "waiting")
        ok(harbor(self.a, "convoy", "new", "--depends", "1"))
        self.deliver(2, "claude/qa-7", "apps/web/c.ts", "QA-7")
        self.assertIn("waiting for convoy 1", ok(harbor(self.a, "convoy", "assemble", "2")))

    def test_a_moved_vessel_stops_the_assembly(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        (self.a / "apps/web/a.ts").write_text("later\n")
        sh(self.a, "git", "commit", "--quiet", "-am", "later")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-1")
        res = harbor(self.a, "convoy", "assemble", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("VESSEL_MOVED", res.stderr)

    def test_a_real_conflict_is_reported_not_resolved(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/one", "shared.ts", "QA-1", content="export const x = 2\n")
        self.deliver(1, "claude/two", "shared.ts", "QA-2", content="export const x = 3\n")
        res = harbor(self.a, "convoy", "assemble", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("CONFLICT", res.stderr)
        self.assertIn("shared.ts", res.stderr)
        self.assertEqual(sh(self.a, "git", "status", "--porcelain"), "", "the merge was aborted")
        self.assertEqual(self.convoy()["state"], "assembling")
        self.assertNotIn("head", self.convoy())

    def test_a_conflict_only_in_generated_files_is_rebuilt(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/one", "site/index.json", "QA-1", content="one\n")
        self.deliver(1, "claude/two", "site/index.json", "QA-2", content="two\n")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertEqual(self.convoy()["state"], "ready")
        self.assertEqual(sh(self.repo.remote, "git", "show", "convoy/1:site/index.json"), "regenerated")

    def test_two_migrations_with_one_timestamp_fail(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/m1", "db/migrations/20261101120000_a/up.sql", "QA-1")
        self.deliver(1, "claude/m2", "db/migrations/20261101120000_b/up.sql", "QA-2")
        res = harbor(self.a, "convoy", "assemble", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("MIGRATION_COLLISION", res.stderr)
        self.assertIn("20261101120000", res.stderr)

    def test_a_migration_older_than_mains_last_fails(self):
        sh(self.a, "git", "checkout", "--quiet", "main")
        (self.a / "db/migrations/20261105000000_main").mkdir(parents=True)
        (self.a / "db/migrations/20261105000000_main/up.sql").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "migration on main")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/m1", "db/migrations/20261101000000_a/up.sql", "QA-1")
        res = harbor(self.a, "convoy", "assemble", "1")
        self.assertIn("MIGRATION_ORDER", res.stderr)

    def test_a_pilot_account_integrates_and_others_dont(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace("[harbor]\n", '[harbor]\nintegrator = "leo"\n', 1))
        sh(self.a, "git", "commit", "--quiet", "-am", "pilot leo")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ana = self.repo.clone("ana", account="ana", host="air")
        ok(harbor(ana, "account", "set", "ana", "--max-sessions", "1", session="z1"))
        ok(harbor(ana, "worker", "register", "--role", "skipper", session="z1"))
        res = harbor(ana, "convoy", "assemble", "1", session="z1")
        self.assertIn("NOT_INTEGRATOR", res.stderr)
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertEqual(self.convoy()["integrator"], "leo/mbp/s1")


class TestSail(Phase2):
    def test_the_whole_way_to_main(self):
        a, b = self.two_vessels_ready()
        ok(self.ok_changed())
        c = self.convoy()
        self.assertEqual((c["state"], c["ok"]["level"], c["ok"]["reason"]), ("verifying", "changed", "apps/web only"))
        out = ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertIn("sealed, ready to sail", out)
        head = self.convoy()["head"]
        seal = self.repo.log_toml(f"harbor/runs/{head}.toml")
        self.assertEqual((seal["kind"], seal["level"], seal["exit"], seal["convoy"]), ("convoy", "changed", 0, 1))
        self.assertEqual(self.events()[-2:], ["verify-start", "verify-pass"])
        ok(harbor(self.a, "convoy", "sail", "1"))
        self.assertEqual(self.repo.main_sha(), head)
        c = self.convoy()
        self.assertEqual((c["state"], c["sail"]["main_after"]), ("sailed", head))
        self.assertEqual(self.repo.log_toml("harbor/main.toml")["moves"][-1]["cause"], "convoy 1")
        trailers = sh(self.repo.remote, "git", "log", "main", "--format=%(trailers:key=Story,valueonly)")
        self.assertIn("QA-1", trailers)
        self.assertIn("QA-3", trailers)
        files = self.repo.log_files()
        self.assertIn("Sailed:", files["harbor/convoys/1.md"])
        self.assertEqual([p for p in files if not p.startswith("harbor/")], [],
                         "Keelokit 0.12 lets the logbook through unverified only when every file is under harbor/")

    def test_a_one_vessel_convoy_reuses_the_vessel_seal(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        ok(self.ok_changed())
        before = self.runs()
        self.assertIn("nothing to run", ok(harbor(self.a, "convoy", "verify", "1")))
        self.assertEqual(self.runs(), before, "no verify ran")
        ok(harbor(self.a, "convoy", "sail", "1"))
        self.assertEqual(self.repo.main_sha(), self.convoy()["head"])

    def test_the_ok_needs_the_harbormaster_a_ready_convoy_and_a_green_main(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        res = self.ok_changed()
        self.assertIn("WRONG_STATE", res.stderr)
        self.deliver(1, "claude/qa-3", "apps/web/b.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="s2"))
        res = harbor(self.a, "convoy", "sail", "1", "--ok", "--level", "changed", "--reason", "x", session="s2")
        self.assertIn("NOT_HARBORMASTER", res.stderr)
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace('ci_check = "true"', 'ci_check = "false"'))
        sh(self.a, "git", "update-index", "--assume-unchanged", ".keelokit/state.toml")
        res = self.ok_changed()
        self.assertIn("MAIN_RED", res.stderr)

    def test_a_red_verify_reruns_narrow_after_the_fix(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        res = harbor(self.a, "convoy", "verify", "1", env={"HARBOR_FAKE": json.dumps(
            {"rc": 1, "result": "fail", "failed_steps": ["unit"]})})
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.events()[-1], "verify-fail")
        self.assertIn("failed unit", self.convoy()["events"][-1]["detail"])
        (self.a / "apps/web/fix.ts").write_text("fix\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: the seam")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertEqual(self.runs()[-1], "rerun")
        self.assertEqual(self.convoy()["head"], sh(self.a, "git", "rev-parse", "HEAD"))
        ok(harbor(self.a, "convoy", "sail", "1"))

    def test_a_green_partial_run_does_not_seal(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        res = harbor(self.a, "convoy", "verify", "1", env={"HARBOR_FAKE": json.dumps({"partial": True})})
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.events()[-1], "verify-unsealed")
        res = harbor(self.a, "convoy", "sail", "1")
        self.assertIn("NOT_SEALED", res.stderr)

    def test_the_level_all_needs_an_all_seal(self):
        self.two_vessels_ready()
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", "--level", "all", "--reason", "scripts/ changed"))
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertEqual(self.runs()[-1], "convoy-all")
        seal = self.repo.log_toml(f"harbor/runs/{self.convoy()['head']}.toml")
        self.assertEqual(seal["level"], "all")

    def test_main_moving_voids_the_ok_and_assembly_merges_it(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "pull", "--quiet", "origin", "main")
        (self.a / "hotfix.txt").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: red main")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        res = harbor(self.a, "convoy", "verify", "1")
        self.assertIn("MAIN_MOVED", res.stderr)
        ok(harbor(self.a, "convoy", "assemble", "1"))
        c = self.convoy()
        self.assertEqual((c["state"], c["base"]), ("ready", self.repo.main_sha()))
        self.assertNotIn("ok", c)
        self.assertIn("ok-cleared", self.events())
        self.assertIn("main-moved", self.events())

    def test_main_moving_after_the_verify_stops_the_sail(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        ok(harbor(self.a, "convoy", "verify", "1"))
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "pull", "--quiet", "origin", "main")
        (self.a / "hotfix.txt").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        res = harbor(self.a, "convoy", "sail", "1")
        self.assertIn("MAIN_MOVED", res.stderr)
        self.assertEqual(self.convoy()["state"], "verifying")

    def test_a_sailed_convoy_frees_its_hotspots(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/schema-1", "apps/api/prisma/schema.prisma", "DB-1")
        ok(harbor(self.a, "convoy", "new"))
        vessel(self.a, "claude/schema-2", "apps/api/prisma/seed.ts", story="DB-2")
        ok(harbor(self.a, "seal"))
        self.assertIn("HOTSPOT_HELD", harbor(self.a, "convoy", "add", "2", "claude/schema-2").stderr)
        ok(harbor(self.a, "convoy", "assemble", "1"))
        ok(self.ok_changed())
        ok(harbor(self.a, "convoy", "verify", "1"))
        ok(harbor(self.a, "convoy", "sail", "1"))
        ok(harbor(self.a, "convoy", "add", "2", "claude/schema-2"))

    def test_control_records_a_sail_whose_logbook_write_was_lost(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        ok(harbor(self.a, "convoy", "verify", "1"))
        ok(harbor(self.a, "harbormaster", "control"))
        head = self.convoy()["head"]
        sh(self.a, "git", "push", "--quiet", "origin", f"{head}:refs/heads/main")
        ok(harbor(self.a, "harbormaster", "control"))
        c = self.convoy()
        self.assertEqual((c["state"], c["sail"]["main_after"]), ("sailed", head))
        self.assertEqual(self.repo.log_toml("harbor/main.toml")["moves"][-1]["cause"], "convoy 1")


class TestPrePushSeal(Phase2):
    """Keelokit's pre-push verifies every push. The one assemble triggers is recorded as the convoy's seal."""

    def setUp(self):
        super().setUp()
        hook = self.a / ".githooks/pre-push"
        hook.parent.mkdir(exist_ok=True)
        # Keelokit's hook, with the change Harbor asked for: a push of only the logbook branch verifies nothing.
        hook.write_text("#!/bin/sh\nrefs=$(cat | awk '{print $3}' | sort -u)\n"
                        "[ \"$refs\" = refs/heads/harbor/log ] && exit 0\n"
                        "exec sh .keelokit/fake-verify.sh \"$(git rev-parse HEAD)\" changed pre-push\n")
        hook.chmod(0o755)
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "pre-push hook")
        sh(self.a, "git", "config", "core.hooksPath", ".githooks")
        sh(self.a, "git", "push", "--quiet", "origin", "main")

    def test_the_assembly_push_verify_is_the_convoy_verify(self):
        a, b = self.two_vessels_ready()
        head = self.convoy()["head"]
        seal = self.repo.log_toml(f"harbor/runs/{head}.toml")
        self.assertEqual((seal["kind"], seal["level"], seal["reused"]), ("convoy", "changed", True))
        ok(self.ok_changed())
        runs = self.runs()
        self.assertIn("nothing to run", ok(harbor(self.a, "convoy", "verify", "1")))
        self.assertEqual(self.runs(), runs)
        ok(harbor(self.a, "convoy", "sail", "1"))
        self.assertEqual(self.repo.main_sha(), head)

    def test_a_red_pre_push_leaves_the_merge_local(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        res = harbor(self.a, "convoy", "assemble", "1", env={"HARBOR_FAKE": json.dumps({"rc": 1, "result": "fail"})})
        self.assertEqual(res.returncode, 1)
        self.assertIn("CONVOY_PUSH_FAILED", res.stderr)
        self.assertEqual(sh(self.repo.remote, "git", "branch", "--list", "convoy/1"), "")


class TestPersonOk(Phase2):
    """Critical convoys (a full-tier vessel, or a critical area) also wait for a person's yes, bound to the exact head."""

    def full_convoy(self, tier="full"):
        ok(harbor(self.a, "convoy", "new"))
        vessel(self.a, "claude/pay", "apps/web/pay.ts", story="PAY-1")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/pay", "--tier", tier))
        ok(harbor(self.a, "convoy", "assemble", "1"))

    def test_a_full_tier_convoy_waits_for_the_person(self):
        self.full_convoy()
        out = ok(self.ok_changed())
        self.assertIn("needs the person's yes before it sails (full-tier vessels claude/pay)", out)
        ok(harbor(self.a, "convoy", "verify", "1"))
        res = harbor(self.a, "convoy", "sail", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("NEEDS_PERSON", res.stderr)
        self.assertIn("waiting for the person's yes", ok(harbor(self.a, "harbormaster", "control")))
        out = ok(harbor(self.a, "convoy", "approve", "1", "--note", "read the diff", session=None,
                        env={"HARBOR_SESSION": "", "CLAUDE_SESSION_ID": ""}))
        self.assertIn("approved", out)
        person = self.convoy()["ok"]["person"]
        self.assertEqual((person["by"], person["head"], person["note"]), ("leo/mbp/-", self.convoy()["head"], "read the diff"))
        self.assertIn("Person's yes: given by leo/mbp/-", self.repo.log_files()["harbor/convoys/1.md"])
        ok(harbor(self.a, "convoy", "sail", "1"))
        self.assertEqual(self.repo.main_sha(), self.convoy()["head"])

    def test_a_commit_after_the_yes_needs_another(self):
        self.full_convoy()
        ok(self.ok_changed())
        ok(harbor(self.a, "convoy", "verify", "1"))
        ok(harbor(self.a, "convoy", "approve", "1"))
        (self.a / "apps/web/fix.ts").write_text("fix\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "verify", "1"))
        res = harbor(self.a, "convoy", "sail", "1")
        self.assertIn("NEEDS_PERSON", res.stderr)
        self.assertIn("they approved", res.stderr)

    def test_a_critical_area_needs_the_person_whatever_the_tier(self):
        (self.a / ".keelokit/critical.toml").write_text(
            'mutation_break = 70\n\n[[area]]\nname = "payments"\npaths = ["apps/web/pay.ts"]\n')
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "critical area")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.full_convoy(tier="light")
        self.assertEqual(self.convoy()["vessels"][0]["critical"], ["payments"])
        self.assertIn("critical areas payments", ok(self.ok_changed()))

    def test_a_light_convoy_sails_on_the_harbormasters_ok(self):
        self.full_convoy(tier="light")
        ok(self.ok_changed())
        self.assertNotIn("needs_person", self.convoy()["ok"])
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertIn("NOT_NEEDED", harbor(self.a, "convoy", "approve", "1").stderr)
        ok(harbor(self.a, "convoy", "sail", "1"))

    def test_never_and_always(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace('ci_check = "true"', 'ci_check = "true"\nperson_ok = "never"'))
        sh(self.a, "git", "update-index", "--assume-unchanged", ".keelokit/state.toml")
        self.full_convoy()
        ok(self.ok_changed())
        self.assertNotIn("needs_person", self.convoy()["ok"])
        state.write_text(state.read_text().replace('person_ok = "never"', 'person_ok = "always"'))
        ok(harbor(self.a, "convoy", "new"))
        vessel(self.a, "claude/doc", "docs/x.md", story="DOC-1")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "2", "claude/doc", "--tier", "trivial"))
        ok(harbor(self.a, "convoy", "assemble", "2"))
        ok(self.ok_changed(2))
        self.assertEqual(self.convoy(2)["ok"]["needs_person"], '[harbor] person_ok = "always"')


class TestGuard(unittest.TestCase):
    def guard(self, stdin: str) -> int:
        import subprocess, sys
        from test_harbor import HARBOR
        return subprocess.run([sys.executable, str(HARBOR), "guard", "--claude"], input=stdin, capture_output=True,
                              text=True, cwd="/").returncode

    def test_an_agent_cant_approve(self):
        bash = lambda cmd: json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
        self.assertEqual(self.guard(bash('python3 "$H" --session s convoy approve 3')), 2)
        self.assertEqual(self.guard(bash("python3 harbor.py convoy  approve 3 --note ok")), 2)
        self.assertEqual(self.guard(bash("python3 harbor.py convoy sail 3")), 0)
        self.assertEqual(self.guard(bash("git status")), 0)
        self.assertEqual(self.guard(json.dumps({"tool_name": "Read", "tool_input": {"file_path": "convoy approve"}})), 0)
        self.assertEqual(self.guard("not json: harbor.py convoy approve 1"), 2)
        self.assertEqual(self.guard(""), 0)


class TestAbortDefer(Phase2):
    def test_abort_frees_the_vessels(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ok(harbor(self.a, "convoy", "abort", "1", "--reason", "the story changed"))
        self.assertEqual(self.convoy()["state"], "aborted")
        ok(harbor(self.a, "convoy", "new"))
        ok(harbor(self.a, "convoy", "add", "2", "claude/qa-1"))

    def test_defer_takes_a_late_story_out(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ok(harbor(self.a, "convoy", "defer", "1", "QA-3"))
        c = self.convoy()
        self.assertEqual((c["expected"], c["deferred"]), (["QA-1"], ["QA-3"]))
        self.assertIn("NOT_EXPECTED", harbor(self.a, "convoy", "defer", "1", "QA-9").stderr)
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertEqual(self.convoy()["state"], "ready")
        self.assertIn("WRONG_STATE", harbor(self.a, "convoy", "defer", "1", "QA-1").stderr)


if __name__ == "__main__":
    unittest.main()
