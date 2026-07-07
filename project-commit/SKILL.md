---
name: project-commit
description: 批量代码提交工作流。当用户说"提交代码"、"提交"、"commit代码"、"commit code"、"推代码"等提交相关指令时触发。扫描 projects.json 中配置的 Git 项目，AI 根据 diff 和项目提交规范生成 Conventional Commits 格式的 commit message，用户确认后批量提交。支持指定单个项目提交、查看改动、提交并推送等变体。项目列表和提交规范通过 projects.json 配置，不在技能中硬编码。
agent_created: true
---

# 批量代码提交

## 安装

```bash
# 1. 复制技能到 WorkBuddy skills 目录
cp -r project-commit ~/.workbuddy/skills/

# 2. 创建本地配置（不会被 git 追踪）
cp projects.example.json projects.json

# 3. 编辑 projects.json，填入你的实际项目路径
#    项目名保持 project-a / project-b / project-c 即可（脱敏）
```

## 配置文件

项目路径和提交规范统一在 `projects.json`（与 SKILL.md 同级）中配置，**不在技能中硬编码**。

```json
{
  "projects": [
    {
      "name": "project-a",
      "path": "/path/to/your/project-a",
      "branch": "main",
      "commit_convention": "feat/fix/chore/docs/style/refactor..."
    },
    {
      "name": "project-b",
      "path": "/path/to/your/project-b",
      "branch": "main",
      "commit_convention": "提交保持聚焦..."
    }
  ],
  "commit_rules": { ... },
  "commit_message_subject_min_length": 50,
  "commit_message_subject_max_length": 300,
  "commit_types": ["feat", "fix", "chore", "docs", "style", "refactor", "test", "perf", "ci", "build"]
}
```

**修改配置**：直接编辑 `projects.json`，增删项目或修改路径，无需改动脚本。

> ⚠️ `projects.json` 包含真实路径，**不会被提交到 git 仓库**（已加入 .gitignore）。git 仓库中只保留 `projects.example.json` 模板。

## 提交规范

从各项目 `CLAUDE.md` 中摘录，配置在 `projects.json` 的 `commit_convention` 字段中：

- **格式**：`type(scope): subject`（Conventional Commits）
- **type**：`feat` / `fix` / `chore` / `docs` / `style` / `refactor` / `test` / `perf`
- **scope**：优先从分支名自动推导（如 `feature/removeReload` → scope=`removeReload`）；跨项目同一主题**必须复用同一个 scope**
- **header 长度**：整行 `type(scope): subject` 不得超过 100 字符；描述过长时使用短 header + body 格式
- **message 长度**：与改动规模成正比，可在 `projects.json` 中配置 `commit_message_subject_min_length` / `commit_message_subject_max_length`（默认 50~300）
  - 小改动（≤3 文件，≤50 行）→ 50-80 字
  - 中等改动（4-8 文件，50-200 行）→ 80-180 字
  - 大改动（≥9 文件或 >200 行）→ 180-300 字，详细说明模块、原因、影响范围
- **project-a 额外规则**：提交前自动执行 ESLint + Prettier；commitlint 强制校验 header 长度

## 使用方式

### 方式一：WorkBuddy 对话触发（推荐）

| 说什么 | 会发生什么 |
|--------|-----------|
| **提交代码** / **提交** / **commit** | 扫描配置的所有项目 → AI 生成 commit message → 你确认 → 批量提交 |
| **只提交 project-b** | 只扫描并提交指定项目 |
| **提交并推送** / **commit and push** | 提交后自动 push |
| **看看改动** / **有什么改动** | 只展示改动和生成的 message，不提交 |
| **推送** / **push** | 对已提交的项目执行 git push |

### 方式二：终端直接调用脚本

```bash
SKILL_DIR=~/.workbuddy/skills/project-commit

# 预览改动（不提交）
bash $SKILL_DIR/scripts/commit_all.sh --dry-run

# 完整提交流程
bash $SKILL_DIR/scripts/commit_all.sh

# 提交并推送
bash $SKILL_DIR/scripts/commit_all.sh --push

# 只提交某个项目
bash $SKILL_DIR/scripts/commit_all.sh --project project-a

# 用自定义 message 提交（所有项目共用）
bash $SKILL_DIR/scripts/commit_all.sh --message "fix: 修复登录bug"

# 仅扫描查看状态
bash $SKILL_DIR/scripts/scan_projects.sh

# 查看详细 diff
bash $SKILL_DIR/scripts/scan_projects.sh --diff
```

### 方式三：配置 Claude Code API（可选）

在 `~/.zshrc` 中配置，commit message 改为调用 Anthropic API 生成：

```bash
export ANTHROPIC_AUTH_TOKEN="<your-anthropic-api-key>"
export ANTHROPIC_BASE_URL="https://api.anthropic.com"
export ANTHROPIC_DEFAULT_SONNET_MODEL="claude-sonnet-4-20250514"
```

不设则使用 WorkBuddy 内置 AI 生成，两种模式自动切换。

## 工作流（AI 执行指南）

### Step 1: 读取配置并扫描改动

```bash
# 脚本自动读取 projects.json，无需手动指定项目路径
bash <skill_dir>/scripts/scan_projects.sh --diff
```

- 扫描 `projects.json` 中配置的所有项目
- 输出每个项目的：分支名、改动文件列表、staged/unstaged diff
- 可加 `--project <name>` 只扫描指定项目
- **若所有项目均无改动**，直接告知用户，结束流程

### Step 2: 生成 Commit Message

对每个有改动的项目，**必须先读取当前分支名和近期 commits**，再生成 message：

**1. 读取分支名推导 scope**
```bash
cd <project_path> && git branch --show-current
```
从分支名提取 scope：取最后一个 `/` 后的部分作为建议 scope。  
例：`feature/removeReload` → scope=`removeReload`；`bug/fix-login` → scope=`fix-login`。

**2. 读取近期 commits 参考风格**
```bash
cd <project_path> && git log --oneline -10
```
参考其 scope 使用习惯、术语和 message 风格。

**3. 跨项目 scope 统一**
若多个项目在同一主题下均有改动，**强制复用同一个 scope**（优先使用各项目分支名推导结果，若分支名一致则直接使用）。

**4. 生成 commit message**
调用 `generate_commit_msg.sh`，传入：diff、项目名、项目提交规范、通用规则（`commit_rules`）、近期 commits。

注意：
- header（`type(scope): subject` 整行）不得超过 100 字符
- 若描述过长，使用短 header + body 格式（header 与 body 之间空一行）
- **message 长度与改动规模成正比**：文件数和代码行数越多，描述应越详细
  - 小改动（≤3 文件，≤50 行）→ 50-80 字
  - 中等改动（4-8 文件，50-200 行）→ 80-180 字
  - 大改动（≥9 文件或 >200 行）→ 180-300 字
- body 内容应包含：改了哪些模块/文件、为什么改、有什么影响
- 可配置项：`commit_message_subject_min_length`（默认 50）、`commit_message_subject_max_length`（默认 300）

### Step 3: 展示确认

以表格形式展示所有有改动项目的 commit 计划：

```
| 项目 | 分支 | 改动文件数 | Commit Message |
|------|------|-----------|----------------|
| project-a | feature/xxx | 5 | fix(session-subdomain): 修复 iframe 刷新问题 |
| project-b | feature/xxx | 2 | feat(sites): 新增操作日志页面 |
```

询问用户：确认提交全部？或需要修改某个项目的 message？或跳过某个项目？

### Step 4: 执行提交

用户确认后，对每个项目执行：

```bash
cd <project_path> && git add -A && git commit -m "<commit_message>"
```

若用户要求推送，则在 commit 后追加 `git push origin <branch>`。

### Step 5: 汇报结果

```
✅ project-a — commit a1b2c3d — fix(session-subdomain): 修复 iframe 刷新问题
✅ project-b — commit e4f5g6h — feat(sites): 新增操作日志页面
⏭️ project-c — 无改动，跳过
```

## 脚本说明

| 脚本 | 用途 | 说明 |
|------|------|------|
| `scan_projects.sh` | 扫描项目 git 状态 | 自动读取 `projects.json`，支持 `--diff`、`--project` |
| `generate_commit_msg.sh` | 从 diff 生成 commit message | 接收 diff + 项目名 + 项目提交规范，输出 commit message |
| `commit_all.sh` | 全流程一键提交 | 读取配置 → 扫描 → 生成 → 确认 → 提交，支持 `--dry-run`、`--push`、`--project`、`--message` |

## 注意事项

- 提交前务必让用户确认 commit message，不要跳过确认步骤
- 如果 git commit 失败（如 pre-commit hook 失败），展示错误信息并询问用户如何处理
- 不要使用 `--no-verify` 跳过 hooks，除非用户明确要求
- 不要使用 `--amend` 修改已有提交，除非用户明确要求
- untracked 文件（新文件）也需要包含在提交中（`git add -A`）
- **新增/移除项目或修改路径，只需编辑 `projects.json`，无需改动脚本**
