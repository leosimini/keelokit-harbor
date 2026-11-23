"""harbor.py, phase 7: lessons from the JOUNA fleet (docs/lessons-phase7.md).
HRB-4: the ok asks Keelokit for the scoped plan and the --all plan, and goes straight to `all` when the
scoped one already covers it, so a convoy never runs a scoped verify and then --all on the same head.
A stand-in for Keelokit's `verify_tools.py plan` and for `pnpm ls` say what each plan holds.
HRB-5: `convoy sail` runs a mechanical preflight before its push to main (history, authors, wip tips,
the expected diff); the same stand-in answers `verify_tools.py wip-inside`.
HRB-6: `convoy assemble` writes a seam report from the vessels' diffs against the base (shared files, exported
names, CSS selectors and tokens, routes one vessel adds and another's tests use), and reaches `ready` only
when the skipper has read every seam with `convoy seam N ID --note`.
HRB-7: `convoy new --cutoff <UTC time> --optional STORY ...`; after the cutoff, `convoy assemble` defers every
optional story not delivered (event `deferred-at-cutoff`), a mandatory one keeps the convoy `waiting`, and the
harbormaster's control names it.
HRB-8: the control every 30 minutes by default, and the message takeover prints for it holds commands, not state.
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import time
import unittest
from pathlib import Path

from test_harbor import harbor, ok, sh, vessel
from test_phase2 import Phase2

# Keelokit's `verify_tools.py plan [--all] --base REF`, as far as Harbor sees it: one line of steps.
# HARBOR_FAKE_PLAN = {"scoped": "...", "all": "..."}; a missing key exits 1 (no plan). Each call is logged.
# `verify_tools.py wip-inside REMOTE SHA`: HARBOR_FAKE_WIP names a wip tip inside SHA (exit 0), else exit 1.
FAKE_PLAN = """\
import json, os, sys
if sys.argv[1:2] == ["wip-inside"]:
    if os.environ.get("HARBOR_FAKE_WIP_LOG"):
        with open(os.environ["HARBOR_FAKE_WIP_LOG"], "a") as f:
            f.write(json.dumps(sys.argv[1:]) + "\\n")
    tip = os.environ.get("HARBOR_FAKE_WIP")
    if tip:
        print(tip)
    sys.exit(0 if tip else 1)
plan = json.loads(os.environ.get("HARBOR_FAKE_PLAN") or "{}")
key = "all" if "--all" in sys.argv else "scoped"
with open(os.environ["HARBOR_FAKE_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if key not in plan:
    sys.exit(1)
print(plan[key])
"""

# `pnpm ls --depth -1 --parseable`: one absolute folder per package. A --filter is the scoped run
# (`...[base]`, without the root), -r every package and the root. HARBOR_FAKE_PNPM = {"scoped": [...], "all": [...]}.
FAKE_PNPM = """\
#!/usr/bin/env python3
import json, os, sys
p = json.loads(os.environ.get("HARBOR_FAKE_PNPM") or "{}")
scoped = "--filter" in sys.argv
if not scoped:
    print(os.getcwd())
for d in p.get("scoped" if scoped else "all", []):
    print(os.path.join(os.getcwd(), d))
"""

PACKAGES = ["apps/web", "apps/api", "packages/a", "packages/b", "packages/c",
            "packages/d", "packages/e", "packages/f", "packages/g", "packages/h"]


class Phase7(Phase2):
    def setUp(self):
        super().setUp()
        tool = self.a / ".keelokit/bin/verify_tools.py"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text(FAKE_PLAN)
        (self.a / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*\n  - packages/*\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "keelokit's plan")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        (bin_ / "pnpm").write_text(FAKE_PNPM)
        (bin_ / "pnpm").chmod(0o755)
        self.log = self.tmp / "plan.log"
        self.wip_log = self.tmp / "wip.log"
        self.env = {"PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "HARBOR_FAKE_LOG": str(self.log),
                    "HARBOR_FAKE_WIP_LOG": str(self.wip_log)}

    def plans(self, scoped: str, all_: str = "all", packages: list[str] | None = None) -> dict:
        return {**self.env, "HARBOR_FAKE_PLAN": json.dumps({"scoped": scoped, "all": all_}),
                "HARBOR_FAKE_PNPM": json.dumps({"scoped": PACKAGES if packages is None else packages, "all": PACKAGES})}

    def calls(self) -> list[list[str]]:
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []


class TestHRB4(Phase7):
    def test_HRB_4_S1_a_scoped_plan_equal_to_all_gets_level_all_with_the_reason(self):
        self.two_vessels_ready()
        out = ok(harbor(self.a, "convoy", "sail", "1", "--ok", env=self.plans("all")))
        self.assertIn("level all", out)
        o = self.convoy()["ok"]
        self.assertEqual((o["level"], o["level_by"]), ("all", "plan"))
        self.assertIn("covers --all", o["reason"])
        self.assertIn("10 of 10 packages", o["reason"])
        main = self.repo.main_sha()
        self.assertEqual(sorted(map(tuple, self.calls())), [("plan", "--all"), ("plan", "--base", main)],
                         "both plans, the scoped one against the main of the ok")
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertEqual(self.runs()[-1], "convoy-all", "one run, at all: no scoped run before it")
        self.assertEqual(self.runs().count("convoy"), 0)
        ok(harbor(self.a, "convoy", "sail", "1"))

    def test_HRB_4_S2_a_narrow_convoy_keeps_changed(self):
        self.two_vessels_ready()
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", "--reason", "apps/web only",
                  env=self.plans("format lint typecheck unit", packages=["apps/web"])))
        o = self.convoy()["ok"]
        self.assertEqual((o["level"], o["level_by"]), ("changed", "plan"))
        self.assertTrue(o["reason"].startswith("apps/web only; "), o["reason"])
        self.assertIn("narrower than --all", o["reason"])
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertEqual(self.runs()[-1], "convoy")

    def test_HRB_4_S3_level_changed_from_the_harbormaster_wins(self):
        self.two_vessels_ready()
        out = ok(harbor(self.a, "convoy", "sail", "1", "--ok", "--level", "changed", "--reason", "apps/web only",
                        env=self.plans("all")))
        o = self.convoy()["ok"]
        self.assertEqual((o["level"], o["level_by"], o["reason"]), ("changed", "harbormaster", "apps/web only"))
        self.assertIn("covers --all", o["plan"])
        self.assertIn("the harbormaster's changed wins", out)

    def test_HRB_4_S4_asking_for_all_after_a_green_all_on_the_same_head_is_already_covered(self):
        self.two_vessels_ready()
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", env=self.plans("all")))
        ok(harbor(self.a, "convoy", "verify", "1"))
        before = self.convoy()["ok"]
        for level in ("all", "changed"):
            res = harbor(self.a, "convoy", "sail", "1", "--ok", "--level", level, "--reason", "again", env=self.plans("all"))
            self.assertEqual(res.returncode, 1)
            self.assertIn("ALREADY_COVERED", res.stderr)
        self.assertEqual(self.convoy()["ok"], before)
        self.assertEqual(self.runs().count("convoy-all"), 1)
        ok(harbor(self.a, "convoy", "sail", "1"))


class TestHRB4Edges(Phase7):
    def test_every_step_but_too_few_packages_keeps_changed(self):
        self.two_vessels_ready()
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", env=self.plans("all", packages=PACKAGES[:8])))
        o = self.convoy()["ok"]
        self.assertEqual(o["level"], "changed")
        self.assertIn("8 of 10 packages", o["reason"])

    def test_the_threshold_is_configurable(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace('ci_check = "true"', 'ci_check = "true"\nall_when_covered = 0.8'))
        sh(self.a, "git", "commit", "--quiet", "-am", "threshold")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.two_vessels_ready()
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", env=self.plans("all", packages=PACKAGES[:8])))
        self.assertEqual(self.convoy()["ok"]["level"], "all")

    def test_a_bad_threshold_is_bad_config(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace('ci_check = "true"', 'ci_check = "true"\nall_when_covered = 2'))
        res = harbor(self.a, "convoy", "status")
        self.assertIn("BAD_CONFIG", res.stderr)

    def test_without_a_plan_the_ok_needs_a_level_as_before(self):
        self.two_vessels_ready()
        res = harbor(self.a, "convoy", "sail", "1", "--ok", "--reason", "x", env=self.env)  # the plan exits 1
        self.assertEqual(res.returncode, 2)
        self.assertIn("--ok needs --level", res.stderr)
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", "--level", "changed", "--reason", "apps/web only", env=self.env))
        o = self.convoy()["ok"]
        self.assertEqual((o["level"], o["reason"]), ("changed", "apps/web only"))
        self.assertNotIn("plan", o)

    def test_a_changed_seal_that_already_ran_the_whole_plan_is_not_run_again_at_all(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ok(harbor(self.a, "convoy", "assemble", "1"))  # one vessel: its changed seal is the convoy's
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", env=self.plans("all")))
        o = self.convoy()["ok"]
        self.assertEqual(o["level"], "changed")
        self.assertIn("no second run", o["reason"])
        before = self.runs()
        self.assertIn("nothing to run", ok(harbor(self.a, "convoy", "verify", "1")))
        self.assertEqual(self.runs(), before)

    def test_HRB_4_S5_at_level_all_a_red_is_followed_by_the_all_level_rerun_not_a_second_whole_all(self):
        self.two_vessels_ready()
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", env=self.plans("all")))
        res = harbor(self.a, "convoy", "verify", "1", env={"HARBOR_FAKE": json.dumps(
            {"rc": 1, "result": "fail", "failed_steps": ["unit"]})})
        self.assertEqual(res.returncode, 1)
        (self.a / "apps/web/fix.ts").write_text("fix\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: the seam")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertEqual(self.runs()[-2:], ["convoy-all", "rerun-all"], "one fix round, at level all")
        self.assertEqual(self.repo.log_toml(f"harbor/runs/{self.convoy()['head']}.toml")["level"], "all")
        ok(harbor(self.a, "convoy", "sail", "1"))

    def test_the_plan_leaves_no_worktree_behind(self):
        self.two_vessels_ready()
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", env=self.plans("all")))
        self.assertEqual(len(sh(self.a, "git", "worktree", "list").splitlines()), 1)



class TestHRB5(Phase7):
    """The preflight of `convoy sail`: what main receives is exactly the vessels, their merges and the
    integrator's recorded fixes, by real authors, with no unproven wip tip, and no file nobody delivered."""

    def verified(self, fix: bool = False) -> None:
        """Two vessels assembled, the ok, and a green convoy verify; with `fix`, a red first and the
        integrator's fix commit on convoy/1 (recorded by the verify that follows)."""
        self.two_vessels_ready()
        ok(self.ok_changed())
        if fix:
            harbor(self.a, "convoy", "verify", "1", env={"HARBOR_FAKE": json.dumps({"rc": 1, "result": "fail"})})
            (self.a / "apps/web/fix.ts").write_text("fix\n")
            sh(self.a, "git", "add", "-A")
            sh(self.a, "git", "commit", "--quiet", "-m", "fix: the seam")
            sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "verify", "1"))

    def refused(self, res, *needles: str) -> str:
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("PREFLIGHT_FAILED", res.stderr)
        for n in needles:
            self.assertIn(n, res.stderr)
        c = self.convoy()
        self.assertEqual(c["state"], "verifying", "nothing sailed")
        self.assertNotIn("sailing", c)
        self.assertEqual(self.events()[-1], "preflight-failed", "the failure is in the logbook")
        self.assertNotEqual(self.repo.main_sha(), c["head"])
        return c["events"][-1]["detail"]

    def test_HRB_5_S1_a_clean_convoy_passes_in_under_a_minute(self):
        self.verified(fix=True)
        c = self.convoy()
        fix = sh(self.a, "git", "rev-parse", "convoy/1")
        self.assertEqual(c["fixes"], [fix], "the verify after the red recorded the integrator's fix")
        self.assertIn("fix", self.events())
        t0 = time.monotonic()
        out = ok(harbor(self.a, "convoy", "sail", "1", env=self.env))
        self.assertLess(time.monotonic() - t0, 60)
        self.assertIn("preflight passed", out)
        self.assertEqual(self.repo.main_sha(), c["head"])
        self.assertEqual([l for l in map(json.loads, self.wip_log.read_text().splitlines())],
                         [["wip-inside", "origin", c["head"]]], "Keelokit's wip-inside was asked about the head")
        sailing = [e for e in self.convoy()["events"] if e["what"] == "sailing"][-1]
        self.assertIn("preflight passed", sailing["detail"])

    def test_HRB_5_S2_a_stray_commit_stops_the_sail(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        harbor(self.a, "convoy", "verify", "1", env={"HARBOR_FAKE": json.dumps({"rc": 1, "result": "fail"})})
        # Something nobody delivered comes in through a merge on convoy/1: not a vessel, not a fix.
        sh(self.a, "git", "checkout", "--quiet", "-b", "claude/stray", "origin/main")
        (self.a / "apps/web").mkdir(parents=True, exist_ok=True)
        (self.a / "apps/web/stray.ts").write_text("stray\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "feat: not in any vessel")
        stray = sh(self.a, "git", "rev-parse", "HEAD")
        sh(self.a, "git", "checkout", "--quiet", "convoy/1")
        sh(self.a, "git", "merge", "--quiet", "--no-edit", "claude/stray")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertNotIn(stray, self.convoy().get("fixes") or [], "a merged-in commit is never a fix")
        detail = self.refused(harbor(self.a, "convoy", "sail", "1", env=self.env), "stray commit", stray[:8])
        self.assertIn(stray[:8], detail)

    def test_HRB_5_S3_a_wip_tip_in_the_history_stops_the_sail(self):
        a, _ = self.two_vessels_ready()
        ok(self.ok_changed())
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.refused(harbor(self.a, "convoy", "sail", "1", env={**self.env, "HARBOR_FAKE_WIP": a}), "wip", a[:8])

    def test_HRB_5_S4_a_file_changed_outside_the_vessels_and_the_fixes_stops_the_sail_naming_it(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        b = self.deliver(1, "claude/qa-3", "apps/web/b.ts", "QA-3")
        # The integrator merges a vessel by hand and slips another file into the merge commit.
        sh(self.a, "git", "checkout", "--quiet", "-B", "convoy/1", "origin/main")
        sh(self.a, "git", "merge", "--quiet", "--no-ff", "--no-commit", b)
        (self.a / "apps/api/evil.ts").parent.mkdir(parents=True, exist_ok=True)
        (self.a / "apps/api/evil.ts").write_text("nobody delivered this\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "--no-edit")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        ok(self.ok_changed())
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.assertEqual(self.convoy().get("fixes") or [], [], "a merge is not a fix")
        detail = self.refused(harbor(self.a, "convoy", "sail", "1", env=self.env), "apps/api/evil.ts")
        self.assertIn("apps/api/evil.ts", detail)

    def test_HRB_5_a_placeholder_author_stops_the_sail(self):
        self.two_vessels_ready()
        ok(self.ok_changed())
        harbor(self.a, "convoy", "verify", "1", env={"HARBOR_FAKE": json.dumps({"rc": 1, "result": "fail"})})
        (self.a / "apps/web/fix.ts").write_text("fix\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "fix: the seam", "--author", "Your Name <you@example.com>")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        ok(harbor(self.a, "convoy", "verify", "1"))
        self.refused(harbor(self.a, "convoy", "sail", "1", env=self.env), "placeholder author", "you@example.com")

    def test_HRB_5_a_generated_file_rebuilt_in_a_merge_is_expected(self):
        ok(harbor(self.a, "convoy", "new"))
        self.deliver(1, "claude/qa-1", "site/index.json", "QA-1", content="one\n")
        self.deliver(1, "claude/qa-3", "site/index.json", "QA-3", content="three\n")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        ok(self.ok_changed())
        ok(harbor(self.a, "convoy", "verify", "1"))
        ok(harbor(self.a, "convoy", "sail", "1", env=self.env))

    def test_HRB_5_without_wip_inside_the_check_is_skipped_with_a_note(self):
        (self.a / ".keelokit/bin/verify_tools.py").write_text("import sys\nsys.exit(2)\n")
        sh(self.a, "git", "commit", "--quiet", "-am", "an older keelokit")
        sh(self.a, "git", "push", "--quiet", "origin", "main")
        self.verified()
        out = ok(harbor(self.a, "convoy", "sail", "1", env=self.env))
        self.assertIn("wip tips not checked", out)


class Seams(Phase2):
    """The seam report: what two vessels both touch, found mechanically, read by the skipper one by one."""

    def on_main(self, files: dict[str, str]) -> None:
        sh(self.a, "git", "checkout", "--quiet", "main")
        sh(self.a, "git", "pull", "--quiet", "origin", "main")
        for path, text in files.items():
            (self.a / path).parent.mkdir(parents=True, exist_ok=True)
            (self.a / path).write_text(text)
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", "base for the seams")
        sh(self.a, "git", "push", "--quiet", "origin", "main")

    def vessel(self, branch: str, story: str, files: dict[str, str]) -> str:
        """A sealed vessel from origin/main that writes `files`, added to convoy 1."""
        sh(self.a, "git", "fetch", "--quiet", "origin", "main")
        sh(self.a, "git", "checkout", "--quiet", "-B", branch, "origin/main")
        for path, text in files.items():
            (self.a / path).parent.mkdir(parents=True, exist_ok=True)
            (self.a / path).write_text(text)
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "--quiet", "-m", f"feat: {branch}\n\nStory: {story}")
        sh(self.a, "git", "push", "--quiet", "-u", "origin", branch)
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", branch))
        return sh(self.a, "git", "rev-parse", "HEAD")

    def seams(self) -> list[dict]:
        return self.convoy().get("seams") or []

    def seam(self, kind: str, key: str) -> dict:
        found = [s for s in self.seams() if (s["kind"], s["key"]) == (kind, key)]
        self.assertEqual(len(found), 1, self.seams())
        return found[0]

    def report(self) -> str:
        return [e for e in self.convoy()["events"] if e["what"] == "seams"][-1]["detail"]

    LINES = "".join(f"line {i}\n" for i in range(1, 21))


class TestHRB6(Seams):
    def test_HRB_6_S1_two_vessels_changing_one_file_produce_a_seam(self):
        self.on_main({"apps/web/page.ts": self.LINES})
        ok(harbor(self.a, "convoy", "new"))
        self.vessel("claude/qa-1", "QA-1", {"apps/web/page.ts": self.LINES.replace("line 1\n", "one\n")})
        self.vessel("claude/qa-3", "QA-3", {"apps/web/page.ts": self.LINES.replace("line 20\n", "twenty\n")})
        out = ok(harbor(self.a, "convoy", "assemble", "1"))
        s = self.seam("file", "apps/web/page.ts")
        self.assertEqual(s["vessels"], ["claude/qa-1", "claude/qa-3"])
        self.assertRegex(s["id"], r"^s-[0-9a-f]{7}$")
        self.assertEqual(len(self.seams()), 1, "nothing else is shared")
        self.assertIn(f"{s['id']} file apps/web/page.ts", self.report())
        self.assertIn("claude/qa-1, claude/qa-3", self.report())
        self.assertLess(self.events().index("seams"), self.events().index("assembled"))
        self.assertIn(s["id"], out, "assemble prints the report")
        self.assertEqual(self.convoy()["state"], "waiting")

    def test_HRB_6_S2_one_exported_name_in_two_vessels_produces_a_seam(self):
        ok(harbor(self.a, "convoy", "new"))
        self.vessel("claude/qa-1", "QA-1", {
            "apps/web/date.ts": "import x from 'y'\n\nexport function formatDate(d: Date) {\n  return d\n}\n",
            "tools/a.py": "def build():\n    return 1\n"})
        self.vessel("claude/qa-3", "QA-3", {
            "apps/api/format.ts": "export const formatDate = (d: Date) => d\nconst local = 1\n",
            "tools/b.py": "class Thing:\n    def build(self):\n        return 2\n"})
        ok(harbor(self.a, "convoy", "assemble", "1"))
        s = self.seam("name", "formatDate")
        self.assertEqual(s["vessels"], ["claude/qa-1", "claude/qa-3"])
        self.assertEqual([x["kind"] for x in self.seams()], ["name"],
                         "different files; a method named like a module-level def is not a seam; `local` isn't exported")
        self.assertIn("name formatDate", self.report())

    def test_HRB_6_S3_a_route_added_by_one_vessel_and_asserted_closed_in_anothers_test_produces_a_seam(self):
        ok(harbor(self.a, "convoy", "new"))
        self.vessel("claude/qa-1", "QA-1", {
            "apps/api/routes.ts": "router.get('/admin/reports', reports)\nimport a from './local'\n"})
        self.vessel("claude/qa-3", "QA-3", {
            "apps/web/nav.test.ts": "it('keeps admin closed', async () => {\n"
                                    "  expect((await get(\"/admin/reports\")).status).toBe(404)\n})\n"})
        ok(harbor(self.a, "convoy", "assemble", "1"))
        s = self.seam("route", "/admin/reports")
        self.assertEqual(s["vessels"], ["claude/qa-1", "claude/qa-3"])
        self.assertIn("added by claude/qa-1", s["detail"])
        self.assertIn("claude/qa-3's tests (apps/web/nav.test.ts)", s["detail"])
        self.assertEqual(len(self.seams()), 1, "./local is an import, not a route")

    def test_HRB_6_S4_ready_waits_until_every_seam_is_read(self):
        self.on_main({"apps/web/page.ts": self.LINES})
        ok(harbor(self.a, "convoy", "new"))
        self.vessel("claude/qa-1", "QA-1", {"apps/web/page.ts": self.LINES.replace("line 1\n", "one\n"),
                                            "apps/web/a.ts": "export type Shared = 1\n"})
        self.vessel("claude/qa-3", "QA-3", {"apps/web/page.ts": self.LINES.replace("line 20\n", "twenty\n"),
                                            "apps/web/b.ts": "export interface Shared {}\n"})
        out = ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertIn("2 seam(s) to read", out)
        self.assertEqual(self.convoy()["state"], "waiting")
        res = self.ok_changed()
        self.assertEqual(res.returncode, 1, "no ok before the seams are read")
        f, n = self.seam("file", "apps/web/page.ts")["id"], self.seam("name", "Shared")["id"]
        res = harbor(self.a, "convoy", "seam", "1", f, "--note", "looks ok")
        self.assertEqual(res.returncode, 2)
        self.assertIn("fine, fixed in <commit>, or a question", res.stderr)
        res = harbor(self.a, "convoy", "seam", "1", "s-0000000", "--note", "fine")
        self.assertIn("UNKNOWN_SEAM", res.stderr)
        self.assertIn("1 seam(s) left", ok(harbor(self.a, "convoy", "seam", "1", f, "--note", "fine: different lines")))
        self.assertEqual(self.events()[-1], "seam-read")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertEqual(self.convoy()["state"], "waiting", "one seam is still unread")
        # The skipper fixes the seam on convoy/1 and says so.
        sh(self.a, "git", "checkout", "--quiet", "convoy/1")
        (self.a / "apps/web/b.ts").write_text("export interface SharedProps {}\n")
        sh(self.a, "git", "commit", "--quiet", "-am", "fix: one Shared")
        sh(self.a, "git", "push", "--quiet", "origin", "convoy/1")
        fix = sh(self.a, "git", "rev-parse", "HEAD")
        res = harbor(self.a, "convoy", "seam", "1", n, "--note", "fixed in 1234567")
        self.assertIn("NOT_ON_CONVOY", res.stderr)
        out = ok(harbor(self.a, "convoy", "seam", "1", n, "--note", f"fixed in {fix[:9]}"))
        self.assertIn("every seam is read", out)
        self.assertEqual(self.seam("name", "Shared")["note"], f"fixed in {fix[:9]}")
        self.assertEqual(self.seam("name", "Shared")["read_by"], "acct1/mbp/s1")
        ok(harbor(self.a, "convoy", "assemble", "1"))
        c = self.convoy()
        self.assertEqual(c["state"], "ready")
        self.assertEqual(self.events().count("seams"), 1, "the same seams are not reported twice")
        self.assertIn("seam", self.repo.log_files()["harbor/convoys/1.md"].lower())
        ok(self.ok_changed())


class TestHRB6Edges(Seams):
    def test_a_question_is_a_read_and_shows_in_status(self):
        self.on_main({"apps/web/page.ts": self.LINES})
        ok(harbor(self.a, "convoy", "new"))
        self.vessel("claude/qa-1", "QA-1", {"apps/web/page.ts": self.LINES.replace("line 1\n", "one\n")})
        self.vessel("claude/qa-3", "QA-3", {"apps/web/page.ts": self.LINES.replace("line 20\n", "twenty\n")})
        ok(harbor(self.a, "convoy", "assemble", "1"))
        sid = self.seams()[0]["id"]
        self.assertIn(f"seam {sid} to read", ok(harbor(self.a, "convoy", "status", "1")))
        ok(harbor(self.a, "convoy", "seam", "1", sid, "--note", "does qa-3 expect line 1 unchanged?"))
        self.assertIn("question", ok(harbor(self.a, "convoy", "status", "1")))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertEqual(self.convoy()["state"], "ready")

    def test_css_selectors_and_tokens_changed_by_two_vessels(self):
        css = ":root {\n  --brand: red;\n  --gap: 4px;\n}\n\n" + "".join(f".r{i} {{ color: red; }}\n" for i in range(8)) \
              + "\n.button {\n  color: red;\n  padding: 0;\n  margin: 0;\n}\n"
        self.on_main({"apps/web/a.css": css, "apps/web/b.css": ".other { color: blue; }\n"})
        ok(harbor(self.a, "convoy", "new"))
        self.vessel("claude/qa-1", "QA-1", {"apps/web/a.css": css.replace("--brand: red", "--brand: blue"),
                                            "apps/web/c.scss": "/* .ghost { } */\n.button {\n  gap: 0;\n}\n"})
        self.vessel("claude/qa-3", "QA-3", {"apps/web/a.css": css.replace("margin: 0", "margin: 1px"),
                                            "apps/web/b.css": ".other { color: blue; }\n:root { --brand: green; }\n"
                                                              ".button { border: 0; }\n"})
        ok(harbor(self.a, "convoy", "assemble", "1"))
        kinds = {(s["kind"], s["key"]) for s in self.seams()}
        self.assertIn(("token", "--brand"), kinds)
        self.assertIn(("selector", ".button"), kinds)
        self.assertIn(("selector", ":root"), kinds)
        self.assertIn(("file", "apps/web/a.css"), kinds)
        self.assertNotIn(("token", "--gap"), kinds)
        self.assertNotIn(("selector", ".other"), kinds, "untouched by qa-1")
        self.assertNotIn(("selector", ".ghost"), kinds, "a comment is not a rule")

    def test_the_report_lists_at_most_twenty_seams(self):
        base = {f"apps/web/f{i:02}.ts": self.LINES for i in range(25)}
        self.on_main(base)
        ok(harbor(self.a, "convoy", "new"))
        self.vessel("claude/qa-1", "QA-1", {p: self.LINES.replace("line 1\n", "one\n") for p in base})
        self.vessel("claude/qa-3", "QA-3", {p: self.LINES.replace("line 20\n", "twenty\n") for p in base})
        out = ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertEqual(len(self.seams()), 25, "every seam is kept and must be read")
        report = self.report()
        self.assertEqual(report.count(" file apps/web/"), 20)
        self.assertIn("(+5 more)", report)
        self.assertIn("(+5 more)", out)

    def test_a_redelivered_vessel_makes_its_seams_unread_again(self):
        self.on_main({"apps/web/page.ts": self.LINES})
        ok(harbor(self.a, "convoy", "new"))
        self.vessel("claude/qa-1", "QA-1", {"apps/web/page.ts": self.LINES.replace("line 1\n", "one\n")})
        self.vessel("claude/qa-3", "QA-3", {"apps/web/page.ts": self.LINES.replace("line 20\n", "twenty\n")})
        ok(harbor(self.a, "convoy", "assemble", "1"))
        ok(harbor(self.a, "convoy", "seam", "1", self.seams()[0]["id"], "--note", "fine"))
        sh(self.a, "git", "checkout", "--quiet", "claude/qa-3")
        (self.a / "apps/web/page.ts").write_text(self.LINES.replace("line 19\n", "nineteen\n"))
        sh(self.a, "git", "commit", "--quiet", "-am", "more")
        sh(self.a, "git", "push", "--quiet", "origin", "claude/qa-3")
        ok(harbor(self.a, "seal"))
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-3"))
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertNotIn("note", self.seams()[0], "new code: read it again")
        self.assertEqual(self.convoy()["state"], "waiting")

    def test_generated_files_and_one_vessel_make_no_seams(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3"))
        self.vessel("claude/qa-1", "QA-1", {"site/index.json": "one\n"})
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertNotIn("seams", self.events(), "one vessel has nobody to meet")
        self.vessel("claude/qa-3", "QA-3", {"site/index.json": "three\n"})
        ok(harbor(self.a, "convoy", "assemble", "1"))
        self.assertEqual(self.seams(), [], "declared generated files are rebuilt, not read")
        self.assertIn("no seams", self.report())
        self.assertEqual(self.convoy()["state"], "ready")

    def test_only_the_skipper_or_the_integrator_reads_a_seam(self):
        self.on_main({"apps/web/page.ts": self.LINES})
        ok(harbor(self.a, "convoy", "new"))
        self.vessel("claude/qa-1", "QA-1", {"apps/web/page.ts": self.LINES.replace("line 1\n", "one\n")})
        self.vessel("claude/qa-3", "QA-3", {"apps/web/page.ts": self.LINES.replace("line 20\n", "twenty\n")})
        ok(harbor(self.a, "convoy", "assemble", "1"))
        ok(harbor(self.a, "worker", "register", "--role", "vessel", session="s2"))
        res = harbor(self.a, "convoy", "seam", "1", self.seams()[0]["id"], "--note", "fine", session="s2")
        self.assertIn("NOT_SKIPPER", res.stderr)


# 2026-11-01T16:00:00Z is the tests' now (NOW); the cutoff is an hour later.
CUTOFF = "2026-11-01T17:00Z"
BEFORE = {"HARBOR_NOW": "2026-11-01T16:30:00Z"}
AFTER = {"HARBOR_NOW": "2026-11-01T17:30:00Z"}


class TestHRB7(Phase2):
    def test_HRB_7_S1_after_the_cutoff_an_optional_late_vessel_is_deferred_automatically(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "--optional", "QA-3", "--cutoff", CUTOFF))
        c = self.convoy()
        self.assertEqual((c["cutoff"], c["expected"], c["optional"]), ("2026-11-01T17:00:00Z", ["QA-1"], ["QA-3"]))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        out = ok(harbor(self.a, "convoy", "assemble", "1", env=AFTER))
        self.assertIn("QA-3 deferred at the cutoff", out)
        c = self.convoy()
        self.assertEqual(c["state"], "ready")
        self.assertEqual((c["expected"], c.get("optional"), c["deferred"]), (["QA-1"], None, ["QA-3"]))
        e = [e for e in c["events"] if e["what"] == "deferred-at-cutoff"]
        self.assertEqual(len(e), 1)
        self.assertIn("QA-3", e[0]["detail"])
        self.assertIn("2026-11-01T17:00:00Z", e[0]["detail"])
        self.assertEqual(e[0]["at"], "2026-11-01T17:30:00Z")

    def test_HRB_7_S2_a_mandatory_late_vessel_keeps_the_convoy_waiting_and_shows_in_the_round(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3", "--cutoff", CUTOFF))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        out = ok(harbor(self.a, "convoy", "assemble", "1", env=AFTER))
        c = self.convoy()
        self.assertEqual(c["state"], "waiting")
        self.assertEqual(c["expected"], ["QA-1", "QA-3"])
        self.assertNotIn("deferred", c)
        self.assertNotIn("deferred-at-cutoff", self.events())
        self.assertIn("QA-3", out)
        out = ok(harbor(self.a, "harbormaster", "control", env=AFTER))
        line = next(l for l in out.splitlines() if l.startswith("convoy 1"))
        self.assertIn("waiting", line)
        self.assertIn("past its cutoff 2026-11-01T17:00:00Z", line)
        self.assertIn("mandatory QA-3 not delivered", line)

    def test_HRB_7_S3_before_the_cutoff_nothing_is_deferred(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "--optional", "QA-3", "--cutoff", CUTOFF))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        out = ok(harbor(self.a, "convoy", "assemble", "1", env=BEFORE))
        c = self.convoy()
        self.assertEqual(c["state"], "waiting", "an optional story is waited for until the cutoff")
        self.assertEqual(c["optional"], ["QA-3"])
        self.assertNotIn("deferred", c)
        self.assertNotIn("deferred-at-cutoff", self.events())
        self.assertIn("optional QA-3 until the cutoff 2026-11-01T17:00:00Z", out)
        out = ok(harbor(self.a, "harbormaster", "control", env=BEFORE))
        self.assertNotIn("cutoff", next(l for l in out.splitlines() if l.startswith("convoy 1")))


class TestHRB7Edges(Phase2):
    def test_an_optional_vessel_delivered_in_time_sails_with_the_rest(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "--optional", "QA-3", "--cutoff", CUTOFF))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        self.deliver(1, "claude/qa-3", "apps/web/b.ts", "QA-3")
        ok(harbor(self.a, "convoy", "assemble", "1", env=AFTER))
        c = self.convoy()
        self.assertEqual((c["state"], c["optional"]), ("ready", ["QA-3"]))
        self.assertNotIn("deferred-at-cutoff", self.events())

    def test_the_cutoff_is_a_utc_time(self):
        for bad in ("tomorrow", "2026-11-01T17:00", "2026-11-01T17:00+02:00x"):
            res = harbor(self.a, "convoy", "new", "--cutoff", bad)
            self.assertEqual(res.returncode, 2, bad)
            self.assertIn("USAGE", res.stderr)
        self.assertNotIn("harbor/convoys/1.toml", self.repo.log_files())
        ok(harbor(self.a, "convoy", "new", "--cutoff", "2026-11-01T19:00+02:00"))
        self.assertEqual(self.convoy()["cutoff"], "2026-11-01T17:00:00Z", "stored in UTC")

    def test_without_a_cutoff_or_optional_stories_the_logbook_has_neither_key(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1"))
        c = self.convoy()
        self.assertNotIn("cutoff", c)
        self.assertNotIn("optional", c)
        self.assertEqual(c["schema"], 1)

    def test_a_story_is_either_expected_or_optional(self):
        res = harbor(self.a, "convoy", "new", "--expect", "QA-1", "--optional", "QA-1")
        self.assertEqual(res.returncode, 2)
        self.assertIn("USAGE", res.stderr)

    def test_without_a_cutoff_an_optional_story_waits_until_the_skipper_defers_it(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "--optional", "QA-3"))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        ok(harbor(self.a, "convoy", "assemble", "1", env=AFTER))
        self.assertEqual(self.convoy()["state"], "waiting")
        ok(harbor(self.a, "convoy", "defer", "1", "QA-3"))
        c = self.convoy()
        self.assertEqual((c.get("optional"), c["deferred"]), (None, ["QA-3"]))
        self.assertEqual(self.events()[-1], "deferred")
        ok(harbor(self.a, "convoy", "assemble", "1", env=AFTER))
        self.assertEqual(self.convoy()["state"], "ready")

    def test_add_optional_marks_the_vessel_and_takes_its_story_out_of_expected(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-3", "--cutoff", CUTOFF))
        head = vessel_(self, "claude/qa-3", "apps/web/b.ts", "QA-3")
        ok(harbor(self.a, "convoy", "add", "1", "claude/qa-3", "--optional"))
        c = self.convoy()
        self.assertEqual((c["expected"], c["optional"]), (["QA-1"], ["QA-3"]))
        self.assertEqual([(v["head"], v.get("optional")) for v in c["vessels"]], [(head, True)])
        self.assertIn("optional", ok(harbor(self.a, "convoy", "status", "1")))

    def test_every_late_optional_story_goes_and_mandatory_ones_still_wait(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "QA-2", "--optional", "QA-3", "QA-4", "--cutoff", CUTOFF))
        self.deliver(1, "claude/qa-1", "apps/web/a.ts", "QA-1")
        out = ok(harbor(self.a, "harbormaster", "control", env=AFTER))
        line = next(l for l in out.splitlines() if l.startswith("convoy 1"))
        self.assertIn("mandatory QA-2 not delivered", line)
        self.assertIn("the next assemble defers QA-3, QA-4", line)
        ok(harbor(self.a, "convoy", "assemble", "1", env=AFTER))
        c = self.convoy()
        self.assertEqual((c["state"], c["expected"], c["deferred"]), ("waiting", ["QA-1", "QA-2"], ["QA-3", "QA-4"]))
        self.assertEqual(self.events().count("deferred-at-cutoff"), 2)
        ok(harbor(self.a, "convoy", "assemble", "1", env=AFTER))
        self.assertEqual(self.events().count("deferred-at-cutoff"), 2, "deferred once")
        line = next(l for l in ok(harbor(self.a, "harbormaster", "control", env=AFTER)).splitlines()
                    if l.startswith("convoy 1"))
        self.assertNotIn("defers", line)
        self.assertIn("mandatory QA-2 not delivered", line)

    def test_the_view_shows_the_cutoff_and_the_optional_stories(self):
        ok(harbor(self.a, "convoy", "new", "--expect", "QA-1", "--optional", "QA-3", "--cutoff", CUTOFF))
        view = self.repo.log_files()["harbor/convoys/1.md"]
        self.assertIn("Cutoff: 2026-11-01T17:00:00Z", view)
        self.assertIn("Optional: QA-3", view)
        out = ok(harbor(self.a, "convoy", "status", "1"))
        self.assertIn("cutoff 2026-11-01T17:00:00Z", out)
        self.assertIn("optional, not delivered: QA-3", out)


def vessel_(t, branch: str, path: str, story: str) -> str:
    head = vessel(t.a, branch, path, story=story)
    ok(harbor(t.a, "seal"))
    return head



# HRB-8: a round every 30 minutes, scheduled with commands, not state.
PROMPT = "harbor: schedule this message to this session every "


def scheduled_prompt(out: str) -> str:
    line = next(l for l in out.splitlines() if l.startswith(PROMPT))
    return line.split("word for word: ", 1)[1]


class TestHRB8(Phase2):
    def relieve(self, session: str) -> str:
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session=session))
        return ok(harbor(self.a, "harbormaster", "takeover", "--relieve", "the owner moved the watch", session=session))

    def test_HRB_8_S1_a_new_watch_schedules_its_control_every_30_minutes_by_default(self):
        out = self.relieve("s2")
        self.assertIn("control every 30 minutes", out)
        self.assertIn(PROMPT + "30 minutes", out)
        self.assertIn("again in 30 minutes", scheduled_prompt(out))
        hm = self.repo.log_toml("harbor/harbormaster.toml")
        self.assertEqual(hm["expires"], "2026-11-01T19:00:00Z")  # the expiry stays 180 minutes

    def test_HRB_8_S1_a_project_that_set_its_own_interval_keeps_it(self):
        state = self.a / ".keelokit/state.toml"
        state.write_text(state.read_text().replace("[harbor]\n", "[harbor]\ncontrol_every_minutes = 90\n", 1))
        sh(self.a, "git", "commit", "--quiet", "-am", "keep 90")
        out = self.relieve("s2")
        self.assertIn("control every 90 minutes", out)
        self.assertIn("again in 90 minutes", scheduled_prompt(out))

    def test_HRB_8_S2_the_scheduled_prompt_has_the_commands_and_no_state_text(self):
        empty = scheduled_prompt(self.relieve("s2"))
        self.assertIn('lib/harbor.py" --session s2 harbormaster control', empty)
        self.assertNotIn("ledger.py", empty)  # this project has no ledger
        # Now the logbook holds a convoy with two vessels, a head and workers: the prompt doesn't change.
        a, b = self.two_vessels_ready()
        later = {"HARBOR_NOW": "2026-11-01T19:00:01Z"}
        ok(harbor(self.a, "worker", "register", "--role", "skipper", session="s2", env=later))
        busy = scheduled_prompt(ok(harbor(self.a, "harbormaster", "takeover", session="s2", env=later)))
        self.assertEqual(busy, empty)
        main = sh(self.a, "git", "rev-parse", "origin/main")
        for fact in (a, b, main, a[:7], b[:7], main[:7], "convoy 1", "convoy/1", "QA-1", "QA-3", "vessel"):
            self.assertNotIn(fact, busy)
        digits = "".join(ch for ch in busy.replace("python3", "").replace("30 minutes", "").replace("s2", "") if ch.isdigit())
        self.assertEqual(digits, "")  # no counts, numbers or heads: only the commands and the interval

    def test_HRB_8_S2_the_prompt_runs_the_ledger_when_the_project_has_it(self):
        ledger = self.a / ".keelokit/bin/ledger.py"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("print('ledger')\n")
        prompt = scheduled_prompt(self.relieve("s2"))
        self.assertIn("harbormaster control and python3 .keelokit/bin/ledger.py", prompt)

    def test_HRB_8_S2_the_skill_schedules_the_printed_commands_never_a_state(self):
        root = Path(__file__).resolve().parent.parent
        skill = (root / "skills/harbormaster/SKILL.md").read_text()
        agent = (root / "agents/harbormaster.md").read_text()
        for text in (skill, agent):
            flat = " ".join(text.split())
            self.assertIn("word for word", flat)
            self.assertIn("never a state", flat)
        self.assertIn("ledger.py", " ".join(skill.split()))


if __name__ == "__main__":
    unittest.main()
