"""Run with python3 -m unittest discover -s tests. All effects stay in a temporary repo."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "daily-report/scripts/collect_commits.py"
# 2026-10-21 01:00 Beijing time is still 2026-10-20 10:00 in Los Angeles.
WHEN = "2026-10-21T01:00:00+08:00"


class CollectCommits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name) / "repo"
        cls.repo.mkdir()
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_AUTHOR_NAME": "Probe Author", "GIT_AUTHOR_EMAIL": "probe@example.invalid",
               "GIT_COMMITTER_NAME": "Probe Author", "GIT_COMMITTER_EMAIL": "probe@example.invalid",
               "GIT_AUTHOR_DATE": WHEN, "GIT_COMMITTER_DATE": WHEN}
        for args in (["init", "-q"], ["config", "commit.gpgsign", "false"],
                     ["commit", "-q", "--allow-empty", "-m", "probe-commit"]):
            subprocess.run(["git", *args], cwd=cls.repo, env=env, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def collect(self, *args, tz="America/Los_Angeles"):
        # The machine time zone is set far from Beijing on purpose: attribution must not follow it.
        env = {**os.environ, "TZ": tz}
        return subprocess.run([sys.executable, str(SCRIPT), str(self.repo), *args],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_default_day_is_beijing_regardless_of_machine_time_zone(self):
        r = self.collect("--date", "2026-10-21", "-a", "Probe")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("probe-commit", r.stdout)
        self.assertIn("Asia/Shanghai", r.stdout)
        r = self.collect("--date", "2026-10-20", "-a", "Probe")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("probe-commit", r.stdout)

    def test_explicit_time_zone_still_overrides(self):
        r = self.collect("--date", "2026-10-20", "--timezone", "America/Los_Angeles", "-a", "Probe")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("probe-commit", r.stdout)

    def test_pipe_in_author_warns_and_repeated_flags_match(self):
        r = self.collect("--date", "2026-10-21", "-a", "Probe|Nobody")
        self.assertIn("-a a -a b", r.stderr)
        r = self.collect("--date", "2026-10-21", "-a", "Nobody", "-a", "Probe")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.strip(), "")
        self.assertIn("probe-commit", r.stdout)


if __name__ == "__main__":
    unittest.main()
