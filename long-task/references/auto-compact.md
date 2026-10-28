# 自动压缩与恢复

只处理当前会话。保存 checkpoint 后单次执行原生 `/compact`，完成后恢复原角色和原任务状态；模型选择由用户处理，恢复包中的旧模型名只作历史，不据此修改当前模型或推理等级。同一会话后续切换模型时仍可读该恢复包；新建/清空会话需要明确加载包，不能承诺自动继承。

## 运行条件

自动控制适用于 Herdr 中的 Codex CLI、Claude Code 和 Pi 交互会话，需要 `python3`、可用的 `herdr` CLI、`HERDR_ENV=1`、`HERDR_PANE_ID` 和可确认的原生 session。只控制调用者自己的 pane，沿用继承的本机/服务器环境；不查找焦点窗口，不选择其他 Agent，不重启或改启动模式。

桌面独立会话、未识别引擎或无可靠原生完成证据时，保存 checkpoint 并说明自动控制不可用，提供用户手动原生压缩的恢复入口；不把普通总结叫作压缩成功。

## 执行

1. 先收束本角色工具和写入，确认没有尚在运行的命令/子任务。读取当前有效职责、交接、最新消息和取消记录，按[checkpoint 模板](checkpoint.md)整理最小恢复内容。保留角色、任务编号、角色实例、有效交接版本、原执行请求、消息计数和待回报状态；没有的写不适用，不编造。Owner / Advisor 的只读职责、Worker 的唯一 writer、已获授权和未执行验收必须保留。不要复制初始化等待指令或整段历史日志。
2. 在私有临时目录写入一个 UTF-8 JSON capsule，目录 0700、文件 0600，内容不含凭据、Cookie、Token、可重放链接或原始会话全文。自动流程会将它复制到 `${XDG_STATE_HOME:-~/.local/state}/long-task/compactions/<id>/`，不写项目文件，也不启用原始备份 hook。

```json
{
  "task_id": "当前业务任务编号，单代理任务使用已有标识",
  "role": "owner",
  "instance": "当前角色实例，单代理写 standalone",
  "resume_mode": "wait",
  "context": "按 checkpoint 模板整理的 Markdown：职责、当前任务、有效交接和授权、进度/证据、待回报与控制状态、取消记录、下一步及继续/停止条件。"
}
```

`role` 取 `owner|advisor|worker|standalone`。`resume_mode` 取 `continue|wait|blocked`：原本待命或等回报的角色用 wait，阻塞/等待裁决的角色用 blocked；continue 仅用于原本可继续且已获授权的任务。已有 PAUSED/BLOCKED 请求仍须遵守原恢复授权，不以压缩包代替 Owner 裁决。

3. 从当前工作目录运行（脚本路径相对本 Skill 根目录）：

```bash
python3 <skill-dir>/scripts/compact.py start --capsule <私有 capsule.json>
```

脚本从调用者身份解析正确 session；自定义会话目录无法唯一解析时，核对该原生 session 的路径后加 `--transcript <绝对 JSONL 路径>`，不挑最新文件猜身份。该命令只安排后台控制器，成功返回 `request` 和唯一 `ready_marker`，尚未压缩。原始临时 capsule 可在复制成功后删除。

4. 本轮最终回复说明“已保存，正在安排原生压缩”，末行逐字输出返回的 `ready_marker` 并结束本轮，不继续工具调用、不在本轮等待自己压缩。压缩期间不要给同一会话发送新任务；控制器看到新用户消息、身份/CWD 漂移、未知/阻塞状态会停止。
5. 控制器等本次 final 标记和可交互空闲状态；只投递一次 `/compact`，等待正确 session 中本次新鲜的原生完成记录后，再投递一次恢复指令。准备期间已产生新鲜原生压缩证据时复用，不重复压缩。不调用新模型进程，不使用 `/clear`，不重建会话。

## 收到 LONG_TASK_RESTORE

读取消息中指定的 capsule 和 request 元数据，核对仍是原 pane/session/角色实例，恢复完整职责及当前有效任务，逐项核对实时分支、HEAD、已有修改、最新交接/消息/取消记录。checkpoint 是历史证据，变化先核验。任务已取消、请求过期或授权不足时保持停写，不复活请求或重派旧业务。

先向用户报告已恢复的角色、任务和状态。wait 保持待命，blocked 保留阻塞；continue 通过上述核对且原授权有效后继续。沿用原请求号、角色实例和待回报清单，不重新初始化、不归零、不再次调用压缩分支。

## 失败与证据边界

初次返回的 `request/state.json` 与 `controller.log` 是本次状态入口。`restore_sent` 只表示恢复消息已投递，实际恢复须由接收角色读包并核对；`blocked` 保留阶段和错误，不能报告成功。压缩/恢复投递前落盘，一旦投递结果不明，保留锁和完整包，不自动重试或删除锁；先核对原生会话实际结果再决定后续操作。

完成依据为当前原生 session 中的新增记录：Codex rollout 的 `compacted`、Claude 的 `system/compact_boundary`、Pi 的 `compaction`。仅投递成功、idle、文件变大或出现旧屏幕文案都不算完成。记录格式变化时停止并报告，不猜测兼容。

Herdr 的部分引擎不返回 `interactive_ready`；缺少该字段时仍须同时满足本次原生结束/压缩证据、同一身份和 `idle/done` 状态。字段存在但不是 `true` 时继续阻断。`state.json` 的 observation 记录实际状态、该可选字段和结束标记是否已识别，便于定位等待超时。

状态复核和 CLI 投递是分开的操作，发送前会再查一次，但无法原子排除恰在投递瞬间到达的输入；自动流程期间应让当前会话独占输入。恢复角色仍须核对最新消息和取消状态，不能因收到恢复包就忽略新指令。
