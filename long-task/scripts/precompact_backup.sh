#!/bin/sh
# Explicit raw-transcript backup; failure must not block compaction.
[ "${LONG_TASK_BACKUP:-0}" = 1 ] || exit 0
umask 077
python3 - 3<&0 <<'PY'
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

pending = None
try:
    payload = json.load(os.fdopen(3))
    source = Path(payload.get('transcript_path', ''))
    if not source.is_file():
        raise ValueError('transcript unavailable')
    project = str(Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd())).resolve())
    project_id = hashlib.sha256(project.encode()).hexdigest()[:20]
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
    directory = state / 'long-task' / 'compact-backups' / project_id
    for folder in [state / 'long-task', state / 'long-task/compact-backups', directory]:
        if folder.is_symlink():
            raise ValueError('backup directory must not be a symlink')
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.chmod(0o700)
    with tempfile.NamedTemporaryFile(dir=directory, prefix='transcript-', suffix='.tmp', delete=False) as output:
        pending = Path(output.name)
        with source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output)
    target = pending.with_suffix('.jsonl')
    os.link(pending, target)
    pending.unlink()
    pending = None
    backups = sorted(directory.glob('transcript-*.jsonl'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for old in backups[20:]:
        old.unlink()
    print('long-task: raw transcript backup saved (private local state)', file=sys.stderr)
except Exception as error:
    print(f'long-task: backup failed ({type(error).__name__}); compaction continues', file=sys.stderr)
finally:
    if pending is not None:
        pending.unlink(missing_ok=True)
PY
if [ "$?" != 0 ]; then
  echo 'long-task: backup process failed; compaction continues' >&2
fi
exit 0
