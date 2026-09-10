# awesome-skills

A curated collection of AI agent skills — both originals and useful ones found in the wild.

精选的 AI agent skills 合集，包含自制的与从社区收录的实用 skill。

## What's a skill?

An agent skill is a packaged capability that a compatible AI coding agent can invoke during a session. Each skill is a directory containing a `SKILL.md` (with YAML frontmatter declaring its name + description) plus any supporting scripts/examples. The agent reads the description to decide when to invoke the skill.

每个 skill 是一个目录，里面有 `SKILL.md`（含 YAML 前置元数据描述触发条件）和可选的脚本/示例。兼容的 AI coding agent 会根据 description 自动判断何时调用。

## Skills in this repo

### Media

| Skill | Description |
|---|---|
| [`copy-media-files`](./copy-media-files) | Concurrently copy photos/videos (ARW/HIF/JPG/...) from a source directory (e.g. an SD card's DCIM folder) to a target subdirectory, recursively, preserving the relative folder structure. Filters by file extension. |
| [`batch-image-compress`](./batch-image-compress) | 批量把本地图片上传到 PixelForge 在线压缩站点（或同构服务）压缩，按档位/格式处理后下载到新目录并保留相对结构。默认走服务端接口，`--mode ui` 可用真实 Chrome 驱动网页。含 md5 秒传、5 分钟 TTL、merge 504 等服务端坑位的绕过方案。 |

### Workflow

| Skill | Description |
|---|---|
| [`long-task`](./long-task) | Run a long, multi-stage task without losing state to context limits: decompose into phases, persist progress to a file under `.claude/progress/`, delegate heavy searches to subagents, and resume cleanly after `/clear` or auto-compact. Ships an optional `PreCompact` backup hook. |
| [`project-commit`](./project-commit) | Batch-commit code across multiple Git repos with one command. Scans all configured projects, generates Conventional Commits messages from diffs (via built-in AI or Anthropic API), shows a summary table for confirmation, then commits. Supports `--dry-run`, `--push`, `--project <name>`, and `--message "<msg>"`. Config via local `projects.json` (never committed). |
| [`sync-as-built-docs`](./sync-as-built-docs) | 审计已经合并、测试或发布的实现，并同步过时或缺失的 README、架构、API 契约、部署、运维及验证文档。 |

### Productivity

| Skill | Description |
|---|---|
| [`daily-report`](./daily-report) | Generate a work daily report ("工作日报") from today's Git commits across one or more repos, filtered by operator/author. A helper script collects the day's commits (subject, body, files, +/− stats); Claude then summarizes them into a clean, value-focused report. Supports today / yesterday / last-N-days and multiple repos & authors. |

### Knowledge

| Skill | Description |
|---|---|
| [`extract-project-interview-knowledge`](./extract-project-interview-knowledge) | 从项目源码、测试、CI、发布与事故证据中提炼带源码锚点、回答框架和证据边界的面试知识。 |

<!-- Add new skills here, grouped by category. Keep entries one-line. -->

## Install a skill

Following the same approach as [`chrome-use`](https://github.com/leeguooooo/chrome-use), use [`skills`](https://skills.sh/) to discover the skills in this repository and install them for a compatible agent. Add `-g` for a user-level install that is available across projects:

```bash
npx skills add forsakesoul/awesome-skills -g
```

The repository is scanned at install time. Any future top-level directory with a valid `SKILL.md` is discovered automatically, so the installation command and installer logic do not need a hard-coded skill list.

The command lets you choose which skills and agents to install to. For a non-interactive install, specify them explicitly:

```bash
npx skills add forsakesoul/awesome-skills -g --skill sync-as-built-docs --agent codex -y
```

Useful follow-up commands:

```bash
npx skills list -g
npx skills update -g
npx skills remove copy-media-files -g
```

Start a new agent session after installation so it picks up the updated skill list.

If you prefer to manage the files manually, clone the repository and link a skill into your agent's user-level skills directory. For Claude Code, for example:

```bash
git clone https://github.com/forsakesoul/awesome-skills.git ~/Code/awesome-skills
mkdir -p ~/.claude/skills
ln -s ~/Code/awesome-skills/copy-media-files ~/.claude/skills/copy-media-files
```

Whichever installation method you use, a compatible agent can invoke the skill automatically when the conversation matches its description.

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
3. **Portable paths**: resolve bundled scripts and assets relative to the skill directory; never hard-code usernames or assume a runner-specific install directory unless the skill only supports that runner
4. **Attribution for collected skills**: if the skill comes from someone else, credit them in the `SKILL.md` body and link to the source
5. **Add a row to the README table** under the appropriate category
6. **Smoke-test before submitting** — at minimum, run the scripts from a clean checkout
7. **Verify discovery**: run `npx skills add . --list` and fix every skipped or invalid skill before submitting

## License

MIT — see [LICENSE](./LICENSE). Skills authored by others are licensed under their original terms; their `SKILL.md` files include attribution and links.
