"""harbor.py, phase 7: lessons from the JOUNA fleet (docs/lessons-phase7.md).
HRB-4: the ok asks Keelokit for the scoped plan and the --all plan, and goes straight to `all` when the
scoped one already covers it, so a convoy never runs a scoped verify and then --all on the same head.
A stand-in for Keelokit's `verify_tools.py plan` and for `pnpm ls` say what each plan holds.
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import unittest
from pathlib import Path

from test_harbor import harbor, ok, sh
from test_phase2 import Phase2

# Keelokit's `verify_tools.py plan [--all] --base REF`, as far as Harbor sees it: one line of steps.
# HARBOR_FAKE_PLAN = {"scoped": "...", "all": "..."}; a missing key exits 1 (no plan). Each call is logged.
FAKE_PLAN = """\
import json, os, sys
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
        self.env = {"PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "HARBOR_FAKE_LOG": str(self.log)}

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

    def test_at_level_all_a_red_is_followed_by_a_whole_all_run_not_a_partial_rerun(self):
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
        self.assertEqual(self.runs()[-2:], ["convoy-all", "convoy-all"])
        ok(harbor(self.a, "convoy", "sail", "1"))

    def test_the_plan_leaves_no_worktree_behind(self):
        self.two_vessels_ready()
        ok(harbor(self.a, "convoy", "sail", "1", "--ok", env=self.plans("all")))
        self.assertEqual(len(sh(self.a, "git", "worktree", "list").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
