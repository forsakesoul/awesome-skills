"""Run with python3 -m unittest discover -s tests."""
from pathlib import Path
import subprocess
import re
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

    def test_catalog_anchors_and_install_commands_cover_both_languages(self):
        page = build_pages.page()
        self.assertNotIn("1 skills", page)
        ids = re.findall(r' id="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)), "category destinations must be unique")
        anchors = set(re.findall(r'href="#([^"]+)"', page))
        self.assertLessEqual(anchors, set(ids), "every category and section link needs a target")
        skills = {name for _, rows in build_pages.skills_from_readme() for name, _ in rows}
        for lang in build_pages.T:
            section = build_pages.section(lang, build_pages.skills_from_readme())
            commands = re.findall(r'data-copy="[^"]+ --skill ([^"]+)"', section)
            self.assertEqual(set(commands), skills)
            self.assertEqual(len(commands), len(skills))
            self.assertLess(section.index(f'id="skills-{lang}"'), section.index(f'id="install-{lang}"'))
            categories = re.findall(r'class="cat" id="([^"]+)"', section)
            self.assertEqual(len(categories), len(build_pages.skills_from_readme()))
            for target in categories:
                self.assertIn(f'href="#{target}"', section)

    def test_committed_page_is_up_to_date(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools/build_pages.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
