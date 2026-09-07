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

