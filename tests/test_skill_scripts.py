"""Run with python3 -m unittest discover -s tests. All effects stay in temporary repos."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkillScripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
                    'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid',
                    'XDG_STATE_HOME': str(self.root / 'state'), 'CLAUDE_PROJECT_DIR': str(self.root)}
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'commit.gpgsign', 'false')
        (self.repo / 'tracked.txt').write_text('before\n')
        self.git('add', 'tracked.txt')
        self.git('commit', '-qm', 'initial')
        (self.repo / 'tracked.txt').write_text('after\n')
        self.skill = self.root / 'skill'
        shutil.copytree(ROOT / 'project-commit/scripts', self.skill / 'scripts')
        (self.skill / 'projects.json').write_text(json.dumps({'projects': [{'name': 'sample', 'path': str(self.repo)}]}))

    def run_cmd(self, args, **kwargs):
        return subprocess.run(args, cwd=self.repo, env=self.env, text=True, capture_output=True, timeout=20, **kwargs)

    def git(self, *args):
        result = self.run_cmd(['git', *args])
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def batch(self, *args, **kwargs):
        return self.run_cmd(['bash', str(self.skill / 'scripts/commit_all.sh'), *args], **kwargs)

    def test_dry_run_never_commits_and_interactive_input_works(self):
        before = self.git('rev-parse', 'HEAD')
        r = self.batch('--dry-run', '--message', 'fix: fixture', '--yes')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')
        r = self.batch('--message', 'fix: fixture', input='y\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual(self.git('rev-parse', 'HEAD'), before)

    def test_project_filter_is_exact_and_scan_failures_are_unknown(self):
        config = self.skill / 'projects.json'
        config.write_text(json.dumps({'projects': [
            {'name': 'sample', 'path': str(self.repo)},
            {'name': 'sample-extra', 'path': str(self.root / 'missing')},
            {'name': 'not-repo', 'path': str(self.skill)},
        ]}))
        r = self.batch('--dry-run', '--project', 'sample', '--message', 'fix: fixture')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        scan = ['bash', str(self.skill / 'scripts/scan_projects.sh')]
        r = self.run_cmd([*scan, '--project', 'sample', '--diff'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('tracked.txt', r.stdout)
        self.assertNotIn('missing', r.stdout)
        r = self.run_cmd(scan)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('扫描失败的项目: 2', r.stdout)
        self.assertIn('干净的项目:   0', r.stdout)
        self.assertNotEqual(self.run_cmd([*scan, '--project', 'absent']).returncode, 0)

    def test_untracked_content_reaches_message_preview(self):
        self.git('checkout', '--', 'tracked.txt')
        (self.repo / 'new.txt').write_text('new-content-marker\n')
        generator = self.skill / 'scripts/generate_commit_msg.sh'
        generator.write_text('#!/bin/sh\ncat "$1" > "$PREVIEW"\necho "feat: new file"\n')
        preview = self.root / 'preview'
        self.env['PREVIEW'] = str(preview)
        self.env.pop('ANTHROPIC_AUTH_TOKEN', None)
        r = self.batch('--external-model', input='n\n')
        self.assertIn('没有发送代码', r.stdout)
        self.assertIn('new-content-marker', preview.read_text())
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')

    def test_snapshot_change_does_not_stage(self):
        generator = self.skill / 'scripts/generate_commit_msg.sh'
        generator.write_text('#!/bin/sh\nprintf surprise > tracked.txt\nprintf unapproved > new.txt\necho "fix: fixture"\n')
        r = self.batch('--yes')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('预览后仓库发生变化', r.stdout)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')

    def test_commit_and_push_failure_are_not_success(self):
        hook = self.repo / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\nexit 1\n'); hook.chmod(0o700)
        r = self.batch('--yes', '--message', 'fix: fixture')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('commit-failed', r.stdout)
        hook.unlink()
        r = self.batch('--yes', '--push', '--message', 'fix: fixture')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('committed, push-failed', r.stdout)
        self.assertNotIn('✅ 全部完成', r.stdout)
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'fix: fixture')

    def test_filename_spaces_and_deleted_files(self):
        (self.repo / 'name with spaces.txt').write_text('new')
        (self.repo / 'tracked.txt').unlink()
        r = self.batch('--yes', '--message', 'fix: paths')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git('ls-files'), 'name with spaces.txt')

    def test_external_model_requires_flag_and_dry_run_overrides_it(self):
        fake = self.root / 'bin'; fake.mkdir()
        marker = self.root / 'called'
        curl = fake / 'curl'
        curl.write_text('#!/bin/sh\nprintf called >> "$MARKER"\nprintf \'{"content":[{"type":"text","text":"fix: stub"}]}\'\n')
        curl.chmod(0o700)
        self.env.update(PATH=str(fake) + os.pathsep + self.env['PATH'], MARKER=str(marker),
                        ANTHROPIC_AUTH_TOKEN='synthetic-test-value', ANTHROPIC_BASE_URL='https://example.invalid')
        r = self.batch('--dry-run', '--external-model', '--yes')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(marker.exists())
        diff = self.root / 'fixture.diff'; diff.write_text('+export const fixture = 1\n')
        helper = self.skill / 'scripts/generate_commit_msg.sh'
        self.assertEqual(self.run_cmd(['bash', str(helper), str(diff)]).returncode, 0)
        self.assertFalse(marker.exists())
        r = self.run_cmd(['bash', str(helper), '--external-model', str(diff)])
        self.assertEqual(r.stdout.strip(), 'fix: stub', r.stderr)
        self.assertEqual(marker.read_text(), 'called')

    def test_raw_backup_is_opt_in_private_unique_and_nonblocking(self):
        script = ROOT / 'long-task/scripts/precompact_backup.sh'
        transcript = self.root / 'transcript.jsonl'; transcript.write_text('{"fixture":true}\n')
        payload = json.dumps({'transcript_path': str(transcript), 'trigger': '../unused'})
        self.env['LONG_TASK_BACKUP'] = '0'
        self.assertEqual(self.run_cmd(['sh', str(script)], input=payload).returncode, 0)
        self.assertFalse((self.root / 'state').exists())
        self.env['LONG_TASK_BACKUP'] = '1'
        for _ in range(2):
            self.assertEqual(self.run_cmd(['sh', str(script)], input=payload).returncode, 0)
        backups = list((self.root / 'state').rglob('*.jsonl'))
        self.assertEqual(len(backups), 2)
        for p in backups:
            self.assertEqual(p.read_text(), transcript.read_text())
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(p.parent.stat().st_mode & 0o777, 0o700)
        r = self.run_cmd(['sh', str(script)], input='invalid json')
        self.assertEqual(r.returncode, 0)
        self.assertIn('backup failed', r.stderr)

    def test_media_workers_and_explicit_target_preserve_sources(self):
        script = ROOT / 'copy-media-files/scripts/copy_media.py'
        source = self.root / 'source'; source.mkdir(); (source / 'test.arw').write_text('original')
        target = self.root / 'external'
        r = self.run_cmd(['python3', str(script), str(source), '-o', str(target), '-w', '0'])
        self.assertNotEqual(r.returncode, 0); self.assertNotIn('Traceback', r.stderr)
        self.assertFalse(target.exists())
        for _ in range(2):
            r = self.run_cmd(['python3', str(script), str(source), '-o', str(target), '-w', '1'])
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((target / 'test.arw').read_text(), 'original')
        self.assertEqual((target / 'test_1.arw').read_text(), 'original')
        self.assertEqual((source / 'test.arw').read_text(), 'original')

    def test_daily_partial_failure_is_incomplete(self):
        fake = self.root / 'bin'; fake.mkdir()
        actual_git = shutil.which('git')
        git = fake / 'git'
        # Fail only git log; discovery still identifies a valid repository.
        git.write_text('#!/usr/bin/env python3\nimport os,sys\nif "log" in sys.argv: sys.exit(1)\nos.execv('+repr(actual_git)+', ['+repr(actual_git)+', *sys.argv[1:]])\n')
        git.chmod(0o700)
        self.env['PATH'] = str(fake) + os.pathsep + self.env['PATH']
        r = self.run_cmd(['python3', str(ROOT / 'daily-report/scripts/collect_commits.py'), str(self.repo)])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('incomplete', r.stdout)
        self.assertNotIn('未找到任何提交记录', r.stdout)


if __name__ == '__main__':
    unittest.main()
