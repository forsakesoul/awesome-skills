---
name: daily-report
description: >-
  根据一个或多个 Git 仓库的提交记录生成工作日报与周功能总结，按作者过滤后汇总工作价值、变更范围与结果，并可按阶段标记关联 GitLab Work Item。当用户要求生成、总结或补充工作日报、周报、周功能总结、上周做了什么时使用。
---

# Daily Report Skill

基于 Git 提交记录生成工作日报。可选地把每个分支/提交关联的 GitLab Work Item 按阶段（需求梳理 / 技术设计 / 开发中 / 测试中 / 验收中 / 待上线 / 已上线 / 已合入主干）标记出来。

## 安装

首次使用前，从当前已加载的 `SKILL.md` 绝对路径取得其所在目录，并将下面的 `<skill-dir>` 替换为该目录，再将模板配置复制为真实配置：

```bash
cp "<skill-dir>/config.example.json" "<skill-dir>/config.json"
```

然后编辑 `<skill-dir>/config.json`，填入你的实际仓库路径、作者名和输出目录。

> `config.json` 已加入 `.gitignore`，不会被提交到 git 仓库。`config.example.json` 是模板，随项目提交。

## 配置

所有配置统一在 `<skill-dir>/config.json`（与 `SKILL.md` 同级）中，**不在技能中硬编码**。不要依赖调用时的当前工作目录，也不要假设 runner 的固定安装路径。

若 `<skill-dir>/config.json` 不存在，回退到 `<skill-dir>/config.example.json` 并提示用户创建真实配置。

```json
{
  "author": { "patterns": ["your-name", "your-email@example.com"] },
  "repos": ["/path/to/your/repo-1", "/path/to/your/repo-2"],
  "output_dir": "/path/to/your/daily-report/output",
  "file_naming": "MMDD.md",
  "workItems": {
    "enabled": true,
    "gitlab": {
      "base_url": "https://git.flam.dev",
      "project_paths": {
        "/path/to/your/repo-1": "intelligent-computing/repo-1",
        "/path/to/your/repo-2": "intelligent-computing/repo-2"
      },
      "url_template": "{base_url}/{project}/-/work_items/{id}"
    },
    "id_patterns": ["#\\d+", "&\\d+", "[A-Z][A-Z0-9]+-\\d+"],
    "stages": ["需求梳理", "技术设计", "开发中", "测试中", "验收中", "待上线", "已上线"],
    "branch_stage_hints": {
      "requirement": "需求梳理", "req": "需求梳理", "spec": "需求梳理",
      "design": "技术设计", "rfc": "技术设计",
      "feature/": "开发中", "fix/": "开发中", "dev/": "开发中", "refactor/": "开发中",
      "test": "测试中", "qa": "测试中", "verify": "测试中",
      "release/": "待上线", "hotfix/": "待上线", "staging": "待上线"
    },
    "merged_to_main_stage": "已合入主干",
    "released_branch_hints": ["release/", "hotfix/"],
    "blocked_hints": ["blocked", "WIP"],
    "branch_work_items": {}
  }
}
```

- **author.patterns**：git log --author 匹配的作者名/邮箱，支持正则，多个之间是 OR 关系
- **repos**：Git 仓库路径列表
- **output_dir**：日报输出目录（自动检测周子目录结构）
- **file_naming**：日报文件命名格式（如 `MMDD.md` 生成 `0616.md`）
- **workItems.enabled**：是否生成「Work Item 关联」章节（默认 `false`，老板侧为 `true`）
- **workItems.gitlab.base_url / project_paths / url_template**：拼出 Work Item 链接。`url_template` 中 `{base_url}`、`{project}`（取 project_paths 映射）、`{id}`（提取到的纯 ID）会被替换；GitLab 若用 issue 而非 work item，可改为 `{base_url}/{project}/-/issues/{id}`
- **workItems.id_patterns**：从分支名与 commit message 提取 Work Item ID 的正则列表（默认匹配 `#123` / `&123` / `PROJ-123`）
- **workItems.stages**：阶段有序列表，可增删改（默认 7 个：需求梳理→技术设计→开发中→测试中→验收中→待上线→已上线；另「已合入主干」由 `merged_to_main_stage` 控制）
- **workItems.branch_stage_hints**：分支名子串 → 阶段 的启发式映射
- **workItems.merged_to_main_stage**：分支已合入 main 但未发布时的归类阶段（默认「已合入主干」）
- **workItems.released_branch_hints**：命中即视为「已上线」的分支名前缀
- **workItems.blocked_hints**：命中即标记「⚠ 阻塞」的分支/commit 关键字
- **workItems.branch_work_items**：手动兜底映射，格式 `"分支名(去 origin/)": {"id": "123", "title": "...", "stage": "开发中"}`，用于分支名/commit 未带 Work Item 引用时补全

## 使用方式

用户说「生成日报」「总结日报」「今日日报」「更新下今天的日报」等触发词即生成日报。

用户说「生成周报」「周功能总结」「上周做了什么」「把上周做的总结下」等触发词即生成周功能总结（见末尾「周报（周功能总结）」章节）。

如需指定日期，可说「生成 6 月 15 日的日报」。

如需指定其他仓库，可补充仓库路径。

生成前先冻结目标日期和时区。指定日期时优先运行随 Skill 提供的采集脚本：

```bash
python3 "<skill-dir>/scripts/collect_commits.py" <repo...> \
  --date YYYY-MM-DD --timezone Asia/Shanghai -a '<author-pattern>'
```

脚本输出的精确半开区间 `[当天 00:00, 次日 00:00)` 是提交归属的事实边界；不得把区间外提交写进当天。周末归并只改变日报展示归属，原始提交仍按各自自然日分别采集并保留边界。

## 日报生成流程

1. **收集提交**: 使用 `scripts/collect_commits.py --date YYYY-MM-DD --timezone <zone>` 对全部配置仓库按精确自然日、`--all` 和作者条件采集；保留脚本回显的时区与半开区间
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

## 注意事项

- 日报总结应由 AI 根据提交内容自行总结，不要让用户自己写。
- 只纳入 config.author.patterns 匹配到的作者提交（个人日报视角）；若需团队视角，临时放宽 author 或说明。
- 分支名取 remote 分支的简称（去掉 `origin/`）；worktree 分支也按实际分支名标注。
- 如果某个仓库无提交，仍然列出并标注「0 个提交」。
- “0 个提交”只表示该日期、时区、作者和仓库集合下没有匹配的 Git commit。输出前必须确认已覆盖全部配置仓库且未使用 `--no-all`；未提交改动、设计、QA、验收和沟通另列为“非提交活动”，不得据此写成“当天没有工作”。
- 代码统计只统计文件变更，不含 merge commit。
- 采集务必用 `git log --all`，否则会漏掉 worktree / 未合入 feature 分支的提交。
- 自动检测周目录结构（第一周 / 第二周 / 第三周 …），日报写入对应周子目录。
- **Work Item 关联**：阶段判定是本地启发式（分支名关键字 + 合入状态 + `branch_work_items` 映射），不是 GitLab 真实状态；未检测到 ID 引用的分支归入「未分类」或靠映射补全。连 GitLab 后（配置 token）可升级为查真实阶段。
- **周末提交归类（周与日报边界）**：周六、周日的提交**不生成独立的当日日报**，统一归入**下一个周一**的日报（即「周末提交 → 下周一日报」）。周报统计区间按**周一至周五工作日**——周末（上周六、日）的提交不计入上周周报，而归入本周一所在的周（及该周一日报）。例：8/22（周六）、8/23（周日）的提交记入 0824（周一）日报，不计入 0817–0823 周报。生成周报时若用 `git log --since=周一首日 --until=周日+1` 整周采集，需手动剔除周末两天的提交，或将周末单独归入下周一。

---

## 周报（周功能总结）

当用户说「周功能总结」「上周做了什么」「把上周做的总结下」「生成周报」时，对 config.repos 采集整周提交（上周一~上周日，或指定区间），按**功能维度**而非日期归并。参考 `周报/2026/8/第二周/周功能总结-0810-0816.md` 的写法。

### 周报生成流程

1. **采集**：对每个仓库 `git log --all --since="周一首日 00:00" --until="周日+1 00:00" --author="patterns" --numstat`。
2. **归并**：跨仓库的同一功能合并为一节；按功能域排序（主线在前）。
3. **人员贡献**（若多人协作）：用 `git shortlog -sne --all` 统计作者分布，区分「总体」与「主要作者个人」。
4. **生成 Markdown 周报**，文件名如 `周功能总结-0810-0816.md`，写入对应周目录。

### 周报模板

```markdown
# 周功能总结 YYYY-MM-DD~YYYY-MM-DD（第 N 周）

> 上周跨 N 个仓库共约 **M 笔**提交（无提交仓库标注）。实际活跃区间；主线概述（2-3 条，如「三大主线：告警中心通知域收口 / gateway 模块架构重构 / central Skill 体系打磨」）。

## 1. <功能域1>
> 一句话定位（如「本周绝对主线。前端把通知配置从 Mock 切到真实后端，后端同步落地」）。

- **子能力**：描述（`hash`）。
- **子能力2**：描述（`hash`）。

## 2. <功能域2>
……（跨仓库同一功能合并为一节，标注各仓哈希）

---

## 数据概览

| 仓库 | 本周提交 | 主功能 |
|---|---|---|
| project-a | ~N | … |
| project-b | ~N | … |
| project-c | ~N | … |
| project-d | ~N | … |
| project-e | 0 | — |

**一句话**：<整体概括上周三条主线与成果>

---

## 人员贡献（可选，仅多人协作时需要）

### 总体
<作者分布表：作者 / 仓库 / 提交数 / 主要负责>

**要点**：<主要作者占比、最重单点工作量、他人分工>

### <主要作者> 个人
按仓库拆开：<各仓库负责的功能域与大致笔数，呼应上面的功能域编号>
```

### 周报说明

- 周报**按功能域归并**，不按日期；跨仓库同一功能合并为一节，并在节内分别标注各仓 commit 哈希。
- 每节开头用 `>` 引用一句话定位该域的重要性（如"本周绝对主线"）。
- «数据概览»用表格列各仓库提交数与主功能；«人员贡献»仅在多人协作时追加，区分「总体」与「个人」。
- 文件名 `周功能总结-MMDD-MMDD.md`，与每日 `MMDD.md` 同目录（对应周子目录）。
- 若 `workItems.enabled`，可在周报末尾附「**Work Item 阶段分布**」小节，按 `stages` 汇总本周各 Work Item 当前阶段。
- **周报区间以工作日为界**：周报覆盖周一~周五，周末（上周六、日）提交按「周末提交归类」规则归入下周一日报，不在本周围报体现（见上方「注意事项」）。生成周报的采集区间若用整周 `since=周一首日 --until=周日+1`，须手动剔除周末两天提交。
