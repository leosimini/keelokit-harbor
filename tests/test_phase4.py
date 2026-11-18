"""harbor.py, 0.4: the mailbox of an account and what an account needs to work in a project (requirements,
doctor, the hook's line about main). Clone `a` is account acct1.
Run: python3 -m unittest discover -s tests"""
import unittest

try:
    from .test_harbor import Base, harbor, ok, sh
except ImportError:  # run as `discover -s tests`: the tests directory is the top level
    from test_harbor import Base, harbor, ok, sh


class Mailbox(Base):
    def test_the_mailbox_pr_is_recorded_and_shown(self):
        self.ready()
        out = ok(harbor(self.a, "account", "set", "acct1", "--mailbox-pr", "42"))
        self.assertIn("mailbox PR #42", out)
        self.assertEqual(self.repo.log_toml("harbor/accounts/acct1.toml")["mailbox_pr"], 42)
        self.assertIn("| acct1 | 3 | 1 | — | PR #42 |", self.repo.log_files()["harbor/LOGBOOK.md"])
        ok(harbor(self.a, "account", "set", "acct1", "--max-sessions", "4"))
        self.assertEqual(self.repo.log_toml("harbor/accounts/acct1.toml")["mailbox_pr"], 42)

    def test_a_mailbox_needs_an_account_with_a_cap_and_a_real_number(self):
        ok(harbor(self.a, "init"))
        self.assertIn("ACCOUNT_UNKNOWN", harbor(self.a, "account", "set", "acct1", "--mailbox-pr", "42").stderr)
        ok(harbor(self.a, "account", "set", "acct1", "--max-sessions", "2"))
        self.assertEqual(harbor(self.a, "account", "set", "acct1", "--mailbox-pr", "0").returncode, 2)


if __name__ == "__main__":
    unittest.main()
