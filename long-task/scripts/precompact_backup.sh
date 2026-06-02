#!/bin/sh
# PreCompact backup hook — part of the `long-task` skill.
#
# Before Claude Code compacts the conversation (either a manual `/compact` or an
# automatic auto-compact near the context limit), copy the current transcript to
# a timestamped backup so nothing important is lost when history gets summarised
# away.
#
# Wire it up in ~/.claude/settings.json (global) or a project .claude/settings.json:
#
#   "hooks": {
#     "PreCompact": [
#       { "matcher": "*", "hooks": [
#         { "type": "command",
#           "command": "~/.claude/skills/long-task/scripts/precompact_backup.sh" }
#       ]}
#     ]
#   }
#
# The hook receives a JSON payload on stdin that includes at least:
#   transcript_path  — path to the session's .jsonl transcript
#   trigger          — "manual" or "auto"
#
# It ALWAYS exits 0: a backup failure must never block compaction.

set -u

payload=$(cat)

# Extract fields from the JSON payload. python3 is available on macOS and most
# setups; if it is missing, the values come back empty and we exit quietly.
transcript=$(printf '%s' "$payload" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("transcript_path",""))' 2>/dev/null)
trigger=$(printf '%s' "$payload" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("trigger","unknown"))' 2>/dev/null)

# Nothing to back up — bail without blocking compaction.
[ -n "$transcript" ] && [ -f "$transcript" ] || exit 0

# Back up inside the project dir when Claude provides it, otherwise the cwd.
base="${CLAUDE_PROJECT_DIR:-$PWD}"
backup_dir="$base/.claude/compact-backups"
mkdir -p "$backup_dir" || exit 0

stamp=$(date +%Y%m%d-%H%M%S)
cp "$transcript" "$backup_dir/transcript-$stamp-${trigger:-unknown}.jsonl" 2>/dev/null || exit 0

# Keep only the 20 most recent backups; prune anything older.
ls -1t "$backup_dir"/transcript-*.jsonl 2>/dev/null | tail -n +21 | while IFS= read -r old; do
    rm -f "$old"
done

exit 0
