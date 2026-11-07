"""Run with python3 -m unittest discover -s tests."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_pages  # noqa: E402


class Pages(unittest.TestCase):
    def test_every_skill_is_listed_in_readme_and_page(self):
        skills = {p.parent.name for p in ROOT.glob("*/SKILL.md")}
        listed = {name for _, rows in build_pages.skills_from_readme() for name, _ in rows}
        self.assertEqual(skills, listed, "add a row to the README skill table for every skill directory")
        page = build_pages.page()
        for name in skills:
            self.assertIn(f"--skill {name}", page)

    def test_committed_page_is_up_to_date(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools/build_pages.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
