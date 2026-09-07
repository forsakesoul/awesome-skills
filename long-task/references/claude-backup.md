# Claude PreCompact 原始备份

仅在用户要求保存原始会话时配置此 hook；普通 checkpoint 不需要启用。原始 JSONL 可能含代码、凭据或个人数据，不能称为已脱敏，不进入仓库或云同步。

将下面的 command 加入用户选择作用域的 `PreCompact` hook：

```json
{"type":"command","command":"LONG_TASK_BACKUP=1 ~/.claude/skills/long-task/scripts/precompact_backup.sh"}
```

`LONG_TASK_BACKUP=1` 显式启用；仅安装脚本不启用。脚本从 hook stdin 读取 transcript_path，将每个项目的备份写入 `${XDG_STATE_HOME:-~/.local/state}/long-task/compact-backups/<project-hash>/`。目录 0700、文件 0600，唯一原子命名，每项目保留 20 份。失败输出不含原文的状态并返回 0，不阻塞 compact。依赖 python3；备份不替代脱敏 checkpoint，恢复后仍核对实时分支/SHA。

若用户主动要求清空 Claude 上下文，先保存 checkpoint，再提示 `/clear` 和恢复入口。不要把 `/clear` 当作每阶段必做步骤，也不将 Claude 命令用于其他宿主。
