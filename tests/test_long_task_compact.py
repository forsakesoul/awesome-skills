"""Isolated Herdr/session fixtures; never start a real agent or call a model."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'long-task/scripts/compact.py'
FAKE = r'''#!/usr/bin/env python3
from datetime import datetime, timezone
import json, os, pathlib, sys
root = pathlib.Path(os.environ['COMPACT_FIXTURE'])
config = json.loads((root / 'config.json').read_text())
args = sys.argv[1:]
if args[:2] == ['agent', 'get']:
    phase = config.get('mode', '').removeprefix('cancel_before_')
    if phase in ['compact_sending', 'restore_sending']:
        for state in (root / 'state/long-task/compactions').glob('*/state.json'):
            if json.loads(state.read_text()).get('phase') == phase:
                event = config['cancel_event']
                event['timestamp'] = datetime.now(timezone.utc).isoformat()
                with pathlib.Path(config['transcript']).open('a') as out:
                    out.write(json.dumps(event) + '\n')
    print(json.dumps({'result': {'agent': config['agent']}}))
elif args[:2] == ['agent', 'prompt']:
    with (root / 'calls.jsonl').open('a') as out:
        out.write(json.dumps(args) + '\n')
    mode = config.get('mode', 'success')
    if args[-1] == '/compact':
        if mode == 'compact_error':
            print(json.dumps({'error': {'code': 'timeout'}}), file=sys.stderr)
            sys.exit(1)
        if mode != 'stall':
            kind = config['agent']['agent']
            now = datetime.now(timezone.utc).isoformat()
            if kind == 'codex': event = {'type': 'compacted', 'payload': {'message': 'summary', 'replacement_history': []}}
            elif kind == 'pi': event = {'type': 'compaction', 'id': 'compact-new', 'summary': 'summary', 'firstKeptEntryId': 'kept', 'tokensBefore': 10000}
            else: event = {'type': 'system', 'subtype': 'compact_boundary', 'sessionId': 'session-test', 'compactMetadata': {'trigger': 'manual'}}
            event['timestamp'] = now
            with pathlib.Path(config['transcript']).open('a') as out:
                if kind == 'claude':
                    out.write(json.dumps({'type': 'user', 'timestamp': now, 'sessionId': 'session-test', 'isCompactSummary': True, 'message': {'role': 'user', 'content': 'generated summary'}}) + '\n')
                out.write(json.dumps(event) + '\n')
                if mode == 'cancel_after_compact':
                    config['cancel_event']['timestamp'] = now
                    out.write(json.dumps(config['cancel_event']) + '\n')
    elif mode == 'restore_error':
        print(json.dumps({'error': {'code': 'timeout'}}), file=sys.stderr)
        sys.exit(1)
    print(json.dumps({'result': {'submitted': True}}))
else:
    sys.exit(2)
'''


class AutoCompact(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pids = []
        self.addCleanup(self.stop_controllers)
        self.fake = self.root / 'herdr'
        self.fake.write_text(FAKE)
        self.fake.chmod(0o700)
        self.env = {**os.environ, 'HOME': str(self.root), 'XDG_STATE_HOME': str(self.root / 'state'),
                    'HERDR_ENV': '1', 'HERDR_PANE_ID': 'w1:p1', 'HERDR_BIN_PATH': str(self.fake),
                    'COMPACT_FIXTURE': str(self.root)}
        self.capsule = self.root / 'capsule.json'
        self.capsule.write_text(json.dumps({'role': 'advisor', 'task_id': 'task-test', 'instance': 'A1',
                                            'resume_mode': 'wait', 'context': 'Read-only. Waiting for Owner; preserve request A1-003.'}))
        self.configure()

    def stop_controllers(self):
        for pid, request in self.pids:
            try:
                command = subprocess.run(['ps', '-p', str(pid), '-o', 'args='],
                                         text=True, capture_output=True).stdout
                if str(SCRIPT) in command and str(request) in command and 'run --request' in command:
                    os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def configure(self, kind='codex', mode='success'):
        self.kind = kind
        self.native = self.root / 'session-test.jsonl'
        header = {'type': 'session_meta', 'payload': {'id': 'session-test'}} if kind == 'codex' else (
            {'type': 'session', 'id': 'session-test', 'cwd': str(self.root)} if kind == 'pi' else
            {'type': 'system', 'sessionId': 'session-test'})
        self.native.write_text(json.dumps(header) + '\n')
        self.config = {'agent': {'name': 'advisor', 'pane_id': 'w1:p1', 'terminal_id': 'term-test',
                                'agent': kind, 'agent_session': {'value': 'session-test'},
                                'agent_status': 'working', 'interactive_ready': False, 'cwd': str(self.root)},
                       'mode': mode, 'transcript': str(self.native), 'cancel_event': self.message('user', 'cancel')}
        self.write_config()

    def write_config(self):
        temporary = self.root / 'config.tmp'
        temporary.write_text(json.dumps(self.config))
        temporary.replace(self.root / 'config.json')

    def command(self, *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root,
                              env=env or self.env, text=True, capture_output=True, timeout=15)

    def start(self, timeout=4):
        result = self.command('start', '--capsule', str(self.capsule), '--transcript', str(self.native), '--timeout', str(timeout))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.directory = Path(output['request'])
        self.pids.append((output['controller_pid'], self.directory))
        self.marker = output['ready_marker']
        return output

    def message(self, role, content):
        event = {'timestamp': datetime.now(timezone.utc).isoformat()}
        if self.kind == 'codex':
            event.update(type='response_item', payload={'type': 'message', 'role': role, 'channel': 'final', 'content': [{'type': 'output_text' if role == 'assistant' else 'input_text', 'text': content}]})
        else:
            event.update(type='message' if self.kind == 'pi' else role, sessionId='session-test',
                         message={'role': role, 'stopReason': 'stop', 'content': [{'type': 'text', 'text': content}]})
        return event

    def append(self, event):
        with self.native.open('a') as out:
            out.write(json.dumps(event) + '\n')

    def ready(self):
        self.append(self.message('assistant', self.marker))
        self.config['agent']['agent_status'] = 'idle'
        if 'interactive_ready' in self.config['agent']:
            self.config['agent']['interactive_ready'] = True
        self.write_config()

    def wait(self, phase):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            state = json.loads((self.directory / 'state.json').read_text())
            if state['phase'] == phase:
                return state
            if state['phase'] == 'blocked' and phase != 'blocked':
                self.fail(str(state))
            time.sleep(0.05)
        self.fail((self.directory / 'controller.log').read_text())

    def calls(self):
        p = self.root / 'calls.jsonl'
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_each_host_compacts_once_then_restores_same_role(self):
        for kind in ['codex', 'claude', 'pi']:
            with self.subTest(kind=kind):
                self.configure(kind)
                (self.root / 'calls.jsonl').unlink(missing_ok=True)
                self.start()
                time.sleep(0.15)
                self.assertEqual(self.calls(), [], 'never inject into the current model turn')
                self.ready()
                self.wait('restore_sent')
                calls = self.calls()
                self.assertEqual([c[2] for c in calls], ['w1:p1', 'w1:p1'])
                self.assertEqual(calls[0][-1], '/compact')
                self.assertIn('LONG_TASK_RESTORE', calls[1][-1])
                self.assertIn('wait', calls[1][-1])
                self.assertEqual(json.loads((self.directory / 'capsule.json').read_text())['role'], 'advisor')
                self.assertEqual((self.directory / 'capsule.json').stat().st_mode & 0o777, 0o600)
                self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)

    def test_idle_and_old_compaction_never_prove_current_completion(self):
        self.configure(mode='stall')
        self.append({'type': 'compacted', 'timestamp': '2020-01-01T00:00:00Z', 'payload': {'message': 'old'}})
        self.start(timeout=2)
        self.ready()
        state = self.wait('blocked')
        self.assertEqual(state['stopped_at'], 'waiting_compaction')
        self.assertEqual(len(self.calls()), 1)

    def test_readiness_timeout_records_the_unmet_condition(self):
        self.start(timeout=2)
        self.ready()
        self.config['agent']['interactive_ready'] = False
        self.write_config()
        state = self.wait('blocked')
        self.assertEqual(state['stopped_at'], 'waiting_ready')
        self.assertEqual(state['observation'], {'agent_status': 'idle', 'interactive_ready': False,
                                               'ready_marker_seen': True})
        self.assertEqual(self.calls(), [])

    def test_real_claude_get_shape_without_optional_ready_field(self):
        self.configure('claude')
        self.config['agent'].pop('interactive_ready')
        self.config['agent'].update(completion_seq=3300, state_change_seq=3300,
                                    foreground_cwd=str(self.root))
        self.write_config()
        self.start(timeout=3)
        self.ready()
        self.wait('restore_sent')
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(self.calls()[0][-1], '/compact')

    def test_claude_local_slash_command_is_not_new_input(self):
        # The TUI records /model, /compact ... as a user turn, but no agent turn starts.
        self.configure('claude')
        self.start()
        self.append(self.message('user', '<command-name>/model</command-name>\n<command-message>model</command-message>'))
        self.ready()
        self.wait('restore_sent')
        self.assertEqual(len(self.calls()), 2)

    def test_fresh_automatic_compaction_is_reused(self):
        self.start()
        self.append({'type': 'compacted', 'timestamp': datetime.now(timezone.utc).isoformat(), 'payload': {'message': 'automatic'}})
        self.ready()
        self.wait('restore_sent')
        self.assertEqual(len(self.calls()), 1)
        self.assertNotEqual(self.calls()[0][-1], '/compact')

    def test_identity_change_and_new_input_stop_without_sending(self):
        for change in ['identity', 'input', 'checkpoint', 'blocked']:
            with self.subTest(change=change):
                self.configure()
                (self.root / 'calls.jsonl').unlink(missing_ok=True)
                self.start()
                self.ready()
                if change == 'identity':
                    self.config['agent']['terminal_id'] = 'other-terminal'
                    self.write_config()
                elif change == 'input':
                    self.append(self.message('user', 'cancel this task'))
                elif change == 'checkpoint':
                    (self.directory / 'capsule.json').write_text('{}')
                else:
                    self.config['agent']['agent_status'] = 'blocked'
                    self.write_config()
                self.wait('blocked')
                self.assertEqual(self.calls(), [])
                # Retained lock deliberately forbids a new request for the same identity.
                locks = list((self.root / 'state/long-task/compactions/locks').iterdir())
                for lock in locks:
                    lock.rmdir()  # Test-fixture cleanup only; production never clears uncertain locks.

    def test_uncertain_delivery_is_not_retried(self):
        for mode, expected in [('compact_error', 1), ('restore_error', 2), ('cancel_after_compact', 1)]:
            with self.subTest(mode=mode):
                self.configure(mode=mode)
                self.config['cancel_event'] = self.message('user', 'stop')
                self.write_config()
                (self.root / 'calls.jsonl').unlink(missing_ok=True)
                self.start()
                self.ready()
                self.wait('blocked')
                self.assertEqual(len(self.calls()), expected)
                repeat = self.command('run', '--request', str(self.directory))
                self.assertNotEqual(repeat.returncode, 0)
                self.assertEqual(len(self.calls()), expected)
                for lock in (self.root / 'state/long-task/compactions/locks').iterdir():
                    lock.rmdir()

    def test_duplicate_controller_and_request_are_rejected(self):
        self.start()
        time.sleep(0.1)
        repeat = self.command('run', '--request', str(self.directory))
        self.assertNotEqual(repeat.returncode, 0)
        repeat = self.command('start', '--capsule', str(self.capsule), '--transcript', str(self.native))
        self.assertNotEqual(repeat.returncode, 0)
        self.ready()
        self.wait('restore_sent')
        self.assertEqual(len(self.calls()), 2)

    def test_outside_herdr_and_wrong_session_fail_before_control(self):
        env = {**self.env, 'HERDR_ENV': ''}
        self.assertNotEqual(self.command('start', '--capsule', str(self.capsule), env=env).returncode, 0)
        self.native.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'wrong-session'}}) + '\n')
        result = self.command('start', '--capsule', str(self.capsule), '--transcript', str(self.native))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_absolute_session_path_cannot_be_overridden(self):
        self.config['agent']['agent_session']['value'] = str(self.native)
        self.write_config()
        other = self.root / 'other.jsonl'
        other.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'different-session'}}) + '\n')
        result = self.command('start', '--capsule', str(self.capsule), '--transcript', str(other))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('override differs', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_input_is_rechecked_after_recording_each_send(self):
        for phase, count in [('compact_sending', 0), ('restore_sending', 1)]:
            with self.subTest(phase=phase):
                self.configure(mode='cancel_before_' + phase)
                (self.root / 'calls.jsonl').unlink(missing_ok=True)
                self.start()
                self.ready()
                state = self.wait('blocked')
                self.assertEqual(state['stopped_at'], phase)
                self.assertEqual(len(self.calls()), count)
                for lock in (self.root / 'state/long-task/compactions/locks').iterdir():
                    lock.rmdir()


if __name__ == '__main__':
    unittest.main()
