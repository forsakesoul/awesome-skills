# awesome-skills

A curated collection of [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills) — both originals and useful ones found in the wild.

精选的 Claude Code skills 合集，包含自制的与从社区收录的实用 skill。

## What's a skill?

A Claude Code "skill" is a packaged capability that Claude can invoke during a session. Each skill is a directory containing a `SKILL.md` (with YAML frontmatter declaring its name + description) plus any supporting scripts/examples. Claude reads the description to decide when to invoke the skill.

每个 skill 是一个目录，里面有 `SKILL.md`（含 YAML 前置元数据描述触发条件）和可选的脚本/示例。Claude 会根据 description 自动判断何时调用。

## Skills in this repo

### Media

| Skill | Description |
|---|---|
| [`copy-media-files`](./copy-media-files) | Concurrently copy photos/videos (ARW/HIF/JPG/...) from a source directory (e.g. an SD card's DCIM folder) to a target subdirectory, recursively, preserving the relative folder structure. Filters by file extension. |

### Workflow

| Skill | Description |
|---|---|
| [`long-task`](./long-task) | Run a long, multi-stage task without losing state to context limits: decompose into phases, persist progress to a file under `.claude/progress/`, delegate heavy searches to subagents, and resume cleanly after `/clear` or auto-compact. Ships an optional `PreCompact` backup hook. |
| [`project-commit`](./project-commit) | Batch-commit code across multiple Git repos with one command. Scans all configured projects, generates Conventional Commits messages from diffs (via built-in AI or Anthropic API), shows a summary table for confirmation, then commits. Supports `--dry-run`, `--push`, `--project <name>`, and `--message "<msg>"`. Config via local `projects.json` (never committed). |

### Productivity

| Skill | Description |
|---|---|
| [`daily-report`](./daily-report) | Generate a work daily report ("工作日报") from today's Git commits across one or more repos, filtered by operator/author. A helper script collects the day's commits (subject, body, files, +/− stats); Claude then summarizes them into a clean, value-focused report. Supports today / yesterday / last-N-days and multiple repos & authors. |

<!-- Add new skills here, grouped by category. Keep entries one-line. -->

## Install a skill

Claude Code loads user-level skills from `~/.claude/skills/<skill-name>/`. It only looks one level deep, so you need each skill to be a direct child of that directory.

The recommended workflow is to clone this repo once and symlink the skills you want:

```bash
# 1. Clone anywhere you like
git clone https://github.com/forsakesoul/awesome-skills.git ~/Code/awesome-skills

# 2. Make sure the skills directory exists
mkdir -p ~/.claude/skills

# 3. Symlink the skill(s) you want
ln -s ~/Code/awesome-skills/copy-media-files ~/.claude/skills/copy-media-files
```

Restart Claude Code (or start a new session) so it picks up the new skill list. Verify with `/skills` (if available) or by asking Claude what skills it has access to.

Prefer not to use symlinks? Just copy the directory in:

```bash
cp -R ~/Code/awesome-skills/copy-media-files ~/.claude/skills/
```

Either way, the skill is invoked automatically by Claude when the conversation matches its description — you typically don't need to type its name.

## Repo layout

```
awesome-skills/
├── README.md            ← this file
├── LICENSE              ← MIT
├── .gitignore
└── <skill-name>/        ← one directory per skill (kept flat so symlinks work)
    ├── SKILL.md
    └── scripts/         ← optional, scripts the skill references
```

Skills stay flat at the top level so a one-shot `ln -s` is enough. Categorisation happens in this README's table, not in nested folders.

## Contributing

Found a great skill or built one yourself? PRs welcome. Guidelines:

1. **One skill per directory** at the top level
2. **`SKILL.md` is required**, with a `name` and a `description` in YAML frontmatter
3. **Cross-platform paths**: use `~/.claude/skills/...` style — never hard-code absolute paths containing usernames
4. **Attribution for collected skills**: if the skill comes from someone else, credit them in the `SKILL.md` body and link to the source
5. **Add a row to the README table** under the appropriate category
6. **Smoke-test before submitting** — at minimum, run the scripts from a clean checkout

## License

MIT — see [LICENSE](./LICENSE). Skills authored by others are licensed under their original terms; their `SKILL.md` files include attribution and links.
