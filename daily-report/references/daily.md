## 日报生成流程

1. **收集提交**: 使用 `scripts/collect_commits.py --date YYYY-MM-DD --timezone <zone>` 对用户指定仓库（未限定时使用配置仓库）按精确自然日、`--all` 和作者条件采集；保留脚本回显的时区与半开区间
2. **获取详情**: 复用采集脚本输出的 committer ISO 时间、提交信息及完整 subject/body，避免混用 author date，并据此提取 Work Item ID
3. **分支归属**: 对每个提交执行 `git branch -r --contains <hash>` 确定所属分支，取第一个非 HEAD 分支
4. **代码统计**: 执行 `git log --numstat --format=""` 统计增删行数
5. **Work Item 关联**（若 `workItems.enabled`）:
   - 对每个分支，从「分支名（去 `origin/`）」+ 该分支下所有 commit 的 subject/body 用 `id_patterns` 提取 Work Item ID；同时查 `branch_work_items` 手动映射
   - 按 Work Item ID 归并（同一需求跨仓/跨分支合并为一行）
   - 阶段判定：优先 `branch_stage_hints` 命中分支名 → 否则分支已合入 main 时按 `released_branch_hints`/`merged_to_main_stage` 归类 → 仍无则标「未分类」
   - 命中 `blocked_hints` 的加「⚠ 阻塞」标记；测试中阶段项下用 `[ing]`/`[done]` 标注子状态（依据 commit 类型/合入状态推断，无 API 时保守标 `[ing]`）
6. **按分支分组**: 同一分支的提交归类到一起展示
7. **生成日报**: 按模板生成 Markdown 日报（含「Work Item 关联」章节）
8. **写入文件**: 自动创建目录并写入 Obsidian 日报文件

## 日报模板

按**工作内容归类总结**，不要逐条罗列每个 commit。同一类工作的多个提交合并为一条，句末用反引号引用 commit 短哈希（多个用 `/` 分隔）。参考 `周报/2026/8/第一周/0803.md`、`第二周/0810.md` 的实际写法。

```markdown
# YYYY-MM-DD 工作日报

### <仓库名> / <分支名>（时间描述，如"全天主线"、"上午"、"下午"）

- **<工作类别1>**：<一句话总结该类工作做了什么>（`hash1` / `hash2` / `hash3`），可附带文件数与增删行如 `（3 files, +91/−18）`。
- **<工作类别2>**：<同上>。若一类较复杂，可在类别下再用 `-` 展开多条子项，每条带哈希。
- **<工作类别3>**：<同上>。

### <跨仓库同步工作标题>（如协作文档三仓统一重构 / project-a + project-b + project-c / feature/rule）

- **<子项>**：<总结>（`h1` / `h2` / `h3`，N 仓同步）。
- **MR 创建**：project-a [!49](https://gitlab.example/-/merge_requests/49) → master，……。

### 已合入 master / main（可选，按天汇总交叉仓库合入）

- project-a：`feature/rule` → `master`（`4c789d4`，08:43）。
- project-b：`codex/xxx` → `main`（`b5a0b9e` merge），MR !9 合入。

### 分支状态（强烈建议保留）

- <仓库> <分支>：本地领先 origin **N 笔** / behind M / 已合入 master 或 未合入 / 未推送。
- <仓库>：当天无新提交（标注「0 个提交」）。
- 另有未提交收尾（尚未 commit 的改动）：可单列一行注明。

### Work Item 关联（GitLab）（若 workItems.enabled）

> 阶段按分支名 / 合入状态启发式推断（当前未对接 GitLab API，非真实状态）。`[ing]`=测试中(进行)、`[done]`=测试完成。

#### 需求梳理
- [PROJ-101 功能快捷入口](url) — project-a `feature/quick-entry`（`d8d9429c` / `99868edb`）

#### 技术设计
- [PROJ-102 服务模块重构设计](url) — project-b `feature/module-architecture`（24ee8b8 设计文档）

#### 开发中
- [#123 通知域重构](url) — project-a `release/notification-refactor`（`fd56d0fd` / `4d8ec0ff`）+ project-b `feature/service-...`（`...`）

#### 测试中
- [#88 登录回跳验证 [ing]](url) — project-c `verify/login-return`（`dc888b9` / `f78cecd`）

#### 验收中
- [#90 单测执行环境验收 [done]](url) — project-a `refactor/unit-test`（`cca4e559`）

#### 待上线
- [#77 功能数据接入](url) — project-a `release/data-integration`（已合 master，待发布）

#### 已上线
- [#70 仪表盘数据接入](url) — project-a `master`（`b65336ad`）

#### 已合入主干（未发布）
- [#65 角色权限分配](url) — project-a `release/permission-update`（合 master，未部署）

> ⚠ 阻塞：[#60 某需求](url) — 依赖后端接口未就绪（`WIP`）。

> 注：未检测到 Work Item 引用的分支（如 `qa_cicd`、纯文档分支）归「未分类」或按 `branch_work_items` 映射补全；如需准确阶段请配置 GitLab token 后对接 API。

## 数据概览

提交 **N** 个（实质 X + merge Y）｜ 改动 **+N / −N** ｜ N 个仓库

> 若当天跨多条主线，在数据概览后用 1-2 句点明主线，例如：
> 「两条主线：协作文档三仓统一重构；前端编码规则体系扩展。验证仓额外完成结论回填。」

## 小结与建议

<2-3 句话概括今天整体工作重心和成果>

> **建议**：<针对今天工作的后续跟进建议，1-2 条，如某 worktree 分支领先 origin 极多、建议安排合入评审；或某域已切真实后端、建议补端到端联调>
```

### 模板说明

- 每个仓库/分支下，按**工作类别**分组（如"双抽屉链路""CI 修复""测试覆盖""文档补充"等），不是逐条列 commit。
- 同一类工作的多个提交合并为一条，用一句话概括；**commit 短哈希用反引号括起并 `/` 分隔**，方便回溯源码。
- 每条以粗体标题开头，冒号后跟具体描述；复杂类别可在标题下再用 `-` 展开子项。
- 跨仓库同步的工作可合并为一个分组标题，并在组内分别标注各仓哈希。
- **「已合入 master」**小节按天汇总当天合入主分支的分支、merge 哈希与时间，附 GitLab MR 链接。
- **「分支状态」**小节记录每个分支领先/落后 origin、是否合入、是否推送，以及当天无提交的仓库标注「0 个提交」——这是日报价值的关键，不能省略。
- **「Work Item 关联」**小节（启用时）按 `stages` 顺序分组列出当天涉及的 GitLab Work Item，每条含可点击链接、关联分支与 commit 哈希；阶段为本地启发式，非 GitLab 真实状态。
- "数据概览"汇总所有仓库的提交数（实质 + merge 拆分）和代码增删；"小结与建议"给整体总结与可操作的后续建议。

