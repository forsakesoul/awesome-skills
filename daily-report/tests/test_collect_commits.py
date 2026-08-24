import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional


SCRIPT = Path(__file__).parents[1] / "scripts" / "collect_commits.py"


class CollectCommitsCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Daily Report Test")
        self.git("config", "user.email", "daily-report@example.com")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def git(self, *args: str, env: Optional[Dict[str, str]] = None) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

    def commit(self, subject: str, committed_at: str) -> None:
        marker = self.repo / "commits.txt"
        marker.write_text(marker.read_text() + subject + "\n" if marker.exists() else subject + "\n")
        self.git("add", "commits.txt")
        env = os.environ | {
            "GIT_AUTHOR_DATE": committed_at,
            "GIT_COMMITTER_DATE": committed_at,
        }
        self.git("commit", "-q", "-m", subject, env=env)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.repo), *args],
            capture_output=True,
            text=True,
        )

    def test_exact_date_uses_explicit_timezone_and_half_open_interval(self) -> None:
        self.commit("before-window", "2026-08-20T23:59:59+08:00")
        self.commit("inside-start", "2026-08-21T00:00:01+08:00")
        self.commit("inside-end", "2026-08-21T23:59:59+08:00")
        self.commit("after-window", "2026-08-22T00:00:00+08:00")

        result = self.run_cli(
            "--date",
            "2026-08-21",
            "--timezone",
            "Asia/Shanghai",
            "--no-body",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "[2026-08-21T00:00:00+08:00, 2026-08-22T00:00:00+08:00)",
            result.stdout,
        )
        self.assertIn("inside-start", result.stdout)
        self.assertIn("inside-end", result.stdout)
        self.assertNotIn("before-window", result.stdout)
        self.assertNotIn("after-window", result.stdout)

    def test_zero_commits_does_not_claim_zero_work(self) -> None:
        result = self.run_cli(
            "--date",
            "2026-08-21",
            "--timezone",
            "Asia/Shanghai",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("不等于当天没有其他工作", result.stdout)


if __name__ == "__main__":
    unittest.main()
