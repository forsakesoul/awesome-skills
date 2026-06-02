---
name: long-task
description: Run a long, multi-stage, time-consuming task without losing state when the context window fills up, auto-compacts, or the session slows down. Decomposes the task into phases, persists progress to a file under `.claude/progress/`, delegates heavy searches to subagents to keep the main context lean, proactively suggests `/clear` at checkpoints, and resumes from the progress file in a fresh session. Use when a task is large or complex enough that context overflow, auto-compaction, or long-running slowdowns would otherwise derail it. Triggers: "这个任务很大/很复杂", "分阶段做", "长任务", "别让上下文爆了", "上下文老是超出", "接着上次的任务继续", "long running task", "break this into phases", "resume my task", "don't blow up the context".
---

# long-task

把一个**复杂、耗时、容易把上下文撑爆**的任务，拆成阶段、把进度落盘到文件，让会话只当“执行器”——这样无论自动压缩、`/clear` 还是会话卡断，任务都能从文件无损接续。

> 核心原则：**状态活在文件里，不要只活在对话上下文里。** 上下文随时可能被压缩或清空，文件不会。

## 何时调用

满足任一条件时调用：
- 任务跨多个步骤 / 多个文件 / 多个子系统，预计要连续工作很久
- 用户担心“上下文老是超出”“时间长了卡掉”“任务做着做着就跑偏了”
- 用户明确要“分阶段做”“长任务”“接着上次的继续”

不要用于：
- 一两步就能完成的简单任务（落盘进度反而是负担，直接做）
- 纯问答 / 一次性探索

## 工作流

### 1. 开工：先拆解，再落盘
1. 把任务拆成有序的若干**阶段**（每阶段是一个可验证的检查点）。
2. 在 `.claude/progress/<task-slug>.md` 写入进度文件（模板见下）。
3. 简要向用户复述阶段拆解；任务很大时等用户确认，否则直接开干。

### 2. 执行：每个检查点更新进度文件
- **每完成一个阶段、或做出关键决策**，立刻更新进度文件（勾选阶段、刷新“当前进度”、记下关键结论）。
- **重活外包给子代理**：大范围搜索、读一堆文件、探索陌生代码库时，用 Task 子代理去做，只把**结论**写回主对话和进度文件——别让翻找过程占满主上下文。
- 不要为了“确认改对了”反复重读刚编辑过的文件。

### 3. 管理上下文：主动建议 `/clear`，别等自动压缩
- 当对话已经很长，或刚完成一个大阶段时，**主动**告诉用户：
  > 进度已存到 `.claude/progress/<task-slug>.md`。建议你现在 `/clear`，然后说一句“继续 <task-slug>”，我会从进度文件接着干。
- 这样上下文始终精简，比被动等 auto-compact（会丢细节）更可控，也能缓解长上下文导致的卡顿。

### 4. 恢复：新会话 / 被重新触发时
1. 先读 `.claude/progress/<task-slug>.md`。
2. 用一两句话复述：现在在第几阶段、上一步做完了什么、下一步要干什么。
3. 从“下一步”继续，**不重复**已完成的工作。

## 进度文件模板

复制到 `.claude/progress/<task-slug>.md`：

```markdown
# 任务：<标题>

- 状态：进行中 | 已完成
- 创建：<YYYY-MM-DD>
- 更新：<YYYY-MM-DD>

## 目标与验收
<一句话目标 + 怎样算完成>

## 阶段
- [x] 1. <已完成的阶段>
- [ ] 2. <当前阶段>  ← 进行中
- [ ] 3. <后续阶段>

## 当前进度
- 正在做：<具体在干什么>
- 下一步：<紧接着要做的事>

## 关键决策 / 结论
- <决定了什么、为什么这么定>

## 相关文件
- `path/to/file` — <作用 / 改了什么>

## 待办 / 坑
- <还没解决的、要小心的>
```

进度文件要**简洁**——只记“恢复任务所需的最小信息”，别把它自己也写爆。不想提交它就加进 `.gitignore`：`echo '.claude/progress/' >> .gitignore`。

## 配套：PreCompact 自动备份 hook（可选，推荐）

auto-compact 在上下文接近满载时自动触发，会把历史总结掉、丢细节。挂上这个 hook，可在**每次压缩之前**自动把完整对话记录备份到 `.claude/compact-backups/`，万一压缩丢了重要信息还能翻回来。

把下面这段并进 `~/.claude/settings.json`（全局生效）或项目的 `.claude/settings.json`（仅本项目）的 `hooks` 字段：

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/skills/long-task/scripts/precompact_backup.sh"
          }
        ]
      }
    ]
  }
}
```

- `matcher`：`"*"` 手动和自动压缩都备份；想只备份其一，改成 `"manual"` 或 `"auto"`。
- 脚本依赖 `python3`（解析 hook 的 JSON 输入），macOS / 多数环境自带。
- 备份只保留最近 20 份，旧的自动清理，不会无限增长。
- 用 symlink 安装 skill 时，确保脚本有可执行权限：`chmod +x ~/.claude/skills/long-task/scripts/precompact_backup.sh`。

## 注意

- 进度文件是**唯一真相源**——更新它的优先级高于在对话里长篇汇报。
- 子代理用来“省上下文”，不是什么都丢给它；明确、可独立完成的搜索/读取才外包。
- 这个 skill 解决的是“状态不丢”，**不是“替你按下压缩键”**——Claude 无法自己执行 `/compact`，压缩要么你手动、要么系统在接近满载时自动触发。本 skill 的价值是让“被压缩/被清空”不再可怕。
