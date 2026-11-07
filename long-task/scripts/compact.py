#!/usr/bin/env python3
"""Preserve a role checkpoint, compact its Herdr TUI once, then request restoration."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def secure_dir(path):
    require(not path.is_symlink(), 'state directory must not be a symlink')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def state_root():
    base = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
    parent = secure_dir(base / 'long-task')
    return secure_dir(parent / 'compactions').resolve()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('x', encoding='utf-8') as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')
    temporary.replace(path)


def herdr(*args):
    require(os.environ.get('HERDR_ENV') == '1', 'automatic compaction requires a Herdr-managed TUI')
    result = subprocess.run([os.environ.get('HERDR_BIN_PATH', 'herdr'), *args],
                            capture_output=True, text=True, timeout=15)
    # CLI output can contain conversation text; retain only the error class/code.
    if result.returncode:
        try:
            code = json.loads(result.stderr or result.stdout).get('error', {}).get('code', 'cli_failed')
        except (ValueError, AttributeError):
            code = 'cli_failed'
        raise RuntimeError('Herdr command failed: ' + str(code))
    return json.loads(result.stdout)


def agent(pane):
    value = herdr('agent', 'get', pane).get('result', {}).get('agent', {})
    session = value.get('agent_session') or {}
    identity = {key: value.get(key) for key in ['name', 'pane_id', 'terminal_id', 'agent']}
    identity['session'] = session.get('value')
    require(all(identity.values()), 'agent identity/session is incomplete')
    require(value.get('agent') in ['codex', 'claude', 'pi'], 'unsupported agent kind')
    require(value.get('agent_status') in ['working', 'idle', 'done'], 'agent is blocked, unknown or has no status')
    require(bool(value.get('cwd')), 'agent cwd is unavailable')
    return value, identity


def tail(path):
    # shortcut: evidence must fit in a 2 MiB tail; use a streaming cursor if larger records become common.
    with path.open('rb') as source:
        size = source.seek(0, 2)
        offset = max(0, size - 2 * 1024 * 1024)
        source.seek(offset)
        if offset:
            source.readline()
        records = []
        for line in source:
            try:
                records.append(json.loads(line))
            except (ValueError, UnicodeDecodeError):
                continue
    return records


def record_time(record):
    try:
        return datetime.fromisoformat(record.get('timestamp', '').replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return 0


def text(content):
    if isinstance(content, str):
        return content
    return '\n'.join(item.get('text', '') for item in content or []
                     if isinstance(item, dict) and item.get('type') in ['text', 'input_text', 'output_text'])


def messages(record, kind):
    """Return only user text and final assistant text, never tool/thinking payloads."""
    if kind == 'codex':
        payload = record.get('payload', {})
        if record.get('type') == 'event_msg':
            if payload.get('type') == 'task_complete':
                return '', payload.get('last_agent_message') or ''
            if payload.get('type') == 'user_message':
                return payload.get('message') or '', ''
        if record.get('type') == 'response_item' and payload.get('type') == 'message':
            role = payload.get('role')
            content = text(payload.get('content'))
            return (content if role == 'user' else '',
                    content if role == 'assistant' and payload.get('channel') == 'final' else '')
    elif record.get('type') in ['message', 'user', 'assistant']:
        if record.get('isCompactSummary') is True:
            return '', ''
        message = record.get('message', {})
        role = message.get('role')
        content = text(message.get('content'))
        if kind == 'claude' and role == 'user' and content.lstrip().startswith('<command-name>'):
            return '', ''  # a local slash command (/model, /compact ...) is handled by the TUI and starts no agent turn
        final = role == 'assistant' and (kind != 'pi' or message.get('stopReason') == 'stop')
        return content if role == 'user' else '', content if final else ''
    return '', ''


def compaction(record, kind):
    if kind == 'codex':
        valid = record.get('type') == 'compacted' and isinstance(record.get('payload'), dict)
    elif kind == 'pi':
        valid = (record.get('type') == 'compaction' and bool(record.get('summary'))
                 and bool(record.get('firstKeptEntryId')))
    else:
        valid = record.get('type') == 'system' and record.get('subtype') == 'compact_boundary'
    return digest(json.dumps(record, sort_keys=True)) if valid else None


def transcript(identity, override):
    session = identity['session']
    kind = identity['agent']
    roots = {'codex': '.codex/sessions', 'pi': '.pi/agent/sessions', 'claude': '.claude/projects'}
    if os.path.isabs(session):
        bound = Path(session).resolve(strict=True)
        require(not override or Path(override).resolve(strict=True) == bound,
                'transcript override differs from the active session path')
        candidates = [bound]
    elif override:
        candidates = [Path(override or session)]
    else:
        require(all(c.isalnum() or c in '-_' for c in session), 'unsafe session id')
        candidates = list((Path.home() / roots[kind]).rglob('*' + session + '.jsonl'))
    require(len(candidates) == 1, 'cannot resolve exactly one native session transcript; use --transcript')
    path = candidates[0].resolve(strict=True)
    with path.open(encoding='utf-8') as source:
        header = json.loads(source.readline(65536))
    if kind == 'codex':
        sid = header.get('payload', {}).get('id') or header.get('payload', {}).get('session_id')
        require(header.get('type') == 'session_meta' and bool(sid), 'invalid Codex session header')
    elif kind == 'pi':
        sid = header.get('id')
        require(header.get('type') == 'session' and bool(sid), 'invalid Pi session header')
    else:
        ids = {r.get('sessionId') for r in [header, *tail(path)] if r.get('sessionId')}
        require(len(ids) == 1, 'Claude transcript must identify one session')
        sid = ids.pop()
    require(os.path.isabs(session) or sid == session, 'transcript does not match the active agent session')
    return str(path)


def git_snapshot(cwd):
    result = {}
    for key, args in [('head', ['rev-parse', 'HEAD']), ('branch', ['branch', '--show-current']),
                      ('status', ['status', '--porcelain=v1'])]:
        value = subprocess.run(['git', '-C', cwd, *args], capture_output=True, text=True, timeout=15)
        result[key] = value.stdout.strip() if value.returncode == 0 else None
    return result


def start(args):
    pane = os.environ.get('HERDR_PANE_ID')
    require(pane, 'HERDR_PANE_ID is required; no focused-pane fallback')
    current, identity = agent(pane)
    require(identity['pane_id'] == pane, 'caller pane identity changed')
    require(Path(current.get('cwd', '')).resolve() == Path.cwd().resolve(), 'agent cwd does not match caller cwd')
    raw = Path(args.capsule).read_text(encoding='utf-8')
    require(len(raw.encode()) <= 65536, 'checkpoint exceeds 64 KiB')
    capsule = json.loads(raw)
    require(capsule.get('role') in ['owner', 'advisor', 'worker', 'standalone'], 'unknown role')
    require(capsule.get('resume_mode') in ['continue', 'wait', 'blocked'], 'unknown resume mode')
    for field in ['task_id', 'instance', 'context']:
        require(isinstance(capsule.get(field), str) and capsule[field].strip(), 'missing capsule field: ' + field)
    native = transcript(identity, args.transcript)
    root = state_root()
    locks = secure_dir(root / 'locks')
    lock = locks / digest(json.dumps({key: identity[key] for key in ['pane_id', 'terminal_id', 'session']}, sort_keys=True))
    lock.mkdir(mode=0o700)  # Existing/uncertain requests are never silently replaced.
    request_id = str(uuid.uuid4())
    directory = secure_dir(root / request_id)
    try:
        save(directory / 'capsule.json', capsule)
        request = {'id': request_id, 'identity': identity, 'cwd': str(Path.cwd().resolve()),
                   'transcript': native, 'capsule_sha256': digest(raw),
                   'created_at': time.time(), 'timeout': args.timeout,
                   'ready_marker': 'LONG_TASK_READY:' + request_id, 'lock': str(lock),
                   'git': git_snapshot(str(Path.cwd())),
                   'previous_compactions': list({compaction(r, identity['agent'])
                                                 for r in tail(Path(native))} - {None})}
        # Hash the actual serialized capsule; the input may use different whitespace.
        request['capsule_sha256'] = digest((directory / 'capsule.json').read_text())
        save(directory / 'request.json', request)
        save(directory / 'state.json', {'phase': 'waiting_ready'})
        with (directory / 'controller.log').open('x') as log:
            os.chmod(directory / 'controller.log', 0o600)
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'run',
                                        '--request', str(directory)], stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, start_new_session=True)
        print(json.dumps({'request': str(directory), 'ready_marker': request['ready_marker'],
                          'controller_pid': process.pid}, ensure_ascii=False))
    except Exception:
        lock.rmdir()
        raise


def run(args):
    directory = Path(args.request).resolve(strict=True)
    require(directory.parent == state_root(), 'request must be in private long-task state')
    request = json.loads((directory / 'request.json').read_text())
    require(directory.name == request['id'], 'request id/path mismatch')
    state_path = directory / 'state.json'
    state = json.loads(state_path.read_text())
    require(state['phase'] == 'waiting_ready', 'request already consumed; do not repeat compaction')
    (directory / 'controller.claim').mkdir(mode=0o700)
    started = time.monotonic()
    native = Path(request['transcript'])
    kind = request['identity']['agent']
    marker = request['ready_marker']
    previous_compactions = set(request['previous_compactions'])

    def update(phase, **fields):
        state.update(phase=phase, **fields)
        save(state_path, state)

    def observe():
        require(time.monotonic() - started < request['timeout'], 'deadline exceeded; inspect native state before retrying')
        require(digest((directory / 'capsule.json').read_text()) == request['capsule_sha256'], 'saved checkpoint changed')
        value, identity = agent(request['identity']['pane_id'])
        require(identity == request['identity'], 'agent identity changed; recovery was not sent')
        require(Path(value.get('cwd', '')).resolve() == Path(request['cwd']), 'agent cwd changed')
        require(value.get('agent_status') not in ['blocked', 'unknown'], 'agent is blocked or unknown')
        records = [r for r in tail(native) if record_time(r) >= request['created_at']]
        for record in records:
            user, _ = messages(record, kind)
            require(not user.strip() or user.strip() == '/compact', 'new user input arrived; recovery requires reconciliation')
        # Some Herdr engines omit this optional flag; native completion evidence is still required below.
        input_ready = 'interactive_ready' not in value or value['interactive_ready'] is True
        ready = value.get('agent_status') in ['idle', 'done'] and input_ready
        observation = {'agent_status': value.get('agent_status'),
                       'interactive_ready': value.get('interactive_ready'),
                       'ready_marker_seen': any(messages(r, kind)[1].strip().endswith(marker) for r in records)}
        if state.get('observation') != observation:
            state['observation'] = observation
            save(state_path, state)
        return ready, records

    try:
        stable = 0
        while stable < 2:
            ready, records = observe()
            finished = any(messages(r, kind)[1].strip().endswith(marker) for r in records)
            stable = stable + 1 if ready and finished else 0
            time.sleep(0.5)
        ready, records = observe()
        require(ready, 'agent became busy before compaction')
        fresh = [compaction(r, kind) for r in records
                 if compaction(r, kind) and compaction(r, kind) not in previous_compactions]
        if not fresh:
            update('compact_sending')  # Durable before the single non-idempotent command.
            ready, _ = observe()
            require(ready, 'agent became busy before submitting compaction')
            # shortcut: get/prompt are separate CLI calls; use conditional submission if available.
            herdr('agent', 'prompt', request['identity']['pane_id'], '/compact')
            update('waiting_compaction')
            while True:
                ready, records = observe()
                fresh = [compaction(r, kind) for r in records
                         if compaction(r, kind) and compaction(r, kind) not in previous_compactions]
                if ready and fresh:
                    break
                time.sleep(0.5)
        checkpoint = directory / 'capsule.json'
        require(digest(checkpoint.read_text()) == request['capsule_sha256'], 'saved checkpoint changed')
        ready, _ = observe()
        require(ready, 'agent became busy before restoration')
        update('restore_sending', compaction_evidence=fresh[-1])
        prompt = (f'[LONG_TASK_RESTORE id={request["id"]}] 原生压缩完成证据已核对。'
                  f'读取恢复包 {checkpoint} 和同目录 request.json，先恢复职责、任务、有效交接、请求状态和授权，再核对实时工作区、'
                  '最新消息与取消记录。恢复包只记录历史，不授予新权限；不要重新执行压缩或初始化。'
                  '按 resume_mode 恢复：wait 保持待命，blocked 保留阻塞，continue 仅继续原已授权且未取消的任务；'
                  '已暂停且需要 Owner 恢复指令的请求仍等待原协议授权。先明确报告恢复的角色、任务和状态。')
        ready, _ = observe()
        require(ready, 'agent became busy before submitting restoration')
        herdr('agent', 'prompt', request['identity']['pane_id'], prompt)
        update('restore_sent')  # Delivery is not proof the model has consumed the capsule.
        Path(request['lock']).rmdir()
    except Exception as error:
        update('blocked', stopped_at=state['phase'], error=str(error))
        # Keep the lock and capsule: a failed command may already have been delivered.
        raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    begin = sub.add_parser('start')
    begin.add_argument('--capsule', required=True)
    begin.add_argument('--transcript', help='Exact native session JSONL path for a custom session location')
    begin.add_argument('--timeout', type=float, default=300)
    controller = sub.add_parser('run')
    controller.add_argument('--request', required=True)
    args = parser.parse_args()
    require(os.environ.get('HERDR_ENV') == '1', 'automatic compaction requires HERDR_ENV=1')
    require(args.command != 'start' or 0 < args.timeout <= 600, 'timeout must be in (0, 600] seconds')
    (start if args.command == 'start' else run)(args)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'long-task: {type(error).__name__}: {error}', file=sys.stderr)
        sys.exit(1)
