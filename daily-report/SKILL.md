# Daily Report Skill

基于 Git 提交记录生成工作日报。

## 安装

首次使用前，将模板配置复制为真实配置：

```bash
cp config.example.json config.json
```

然后编辑 `config.json`，填入你的实际仓库路径、作者名和输出目录。

> `config.json` 已加入 `.gitignore`，不会被提交到 git 仓库。`config.example.json` 是模板，随项目提交。

## 配置

所有配置统一在 `config.json`（与 SKILL.md 同级）中，**不在技能中硬编码**。

若 `config.json` 不存在，回退到 `config.example.json` 并提示用户创建真实配置。

```json
{
  "author": { "patterns": ["your-name", "your-email@example.com"] },
  "repos": ["/path/to/your/repo-1", "/path/to/your/repo-2"],
  "output_dir": "/path/to/your/daily-report/output",
  "file_naming": "MMDD.md"
}
```

- **author.patterns**：git log --author 匹配的作者名/邮箱，支持正则，多个之间是 OR 关系
- **repos**：Git 仓库路径列表
- **output_dir**：日报输出目录（自动检测周子目录结构）
- **file_naming**：日报文件命名格式（如 `MMDD.md` 生成 `0616.md`）

## 使用方式

用户说「生成日报」「总结日报」「今日日报」等触发词即可。

如需指定日期，可说「生成 6 月 15 日的日报」。

如需指定其他仓库，可补充仓库路径。

## 日报生成流程

1. **收集提交**: 对每个仓库执行 `git log --since="YYYY-MM-DD 00:00:00" --until="YYYY-MM-DD+1 00:00:00" --oneline --all --author="your-name\|your-github-username"`
2. **获取详情**: 对每个提交执行 `git log --format="%h %ad %s" --date=format:"%H:%M"` 获取时间和提交信息
3. **分支归属**: 对每个提交执行 `git branch -r --contains <hash>` 确定所属分支，取第一个非 HEAD 分支
4. **代码统计**: 执行 `git log --numstat --format=""` 统计增删行数
5. **按分支分组**: 同一分支的提交归类到一起展示
6. **生成日报**: 按模板生成 Markdown 日报
7. **写入文件**: 自动创建目录并写入 Obsidian 日报文件

## 日报模板

按**工作内容归类总结**，不要逐条罗列每个 commit。将同一类工作的多个提交合并为一条总结。

```markdown
# YYYY-MM-DD 工作日报

### <仓库名> / <分支名>（时间描述，如"全天主线"、"上午"、"下午"）

- **<工作类别1>**：<一句话总结该类工作做了什么，覆盖相关多个提交的核心内容>
- **<工作类别2>**：<同上>
- **<工作类别3>**：<同上>

### <仓库名2> / <分支名>（时间描述）

- **<工作类别>**：<总结>

## 数据概览

提交 **N** 个 ｜ 改动 **+N / −N** ｜ N 个仓库

## 小结与建议

<2-3 句话概括今天整体工作重心和成果>

> **建议**：<针对今天工作的后续跟进建议，1-2 条>
```

### 模板说明

- 每个仓库/分支下，按**工作类别**分组（如"Docker 构建优化""CI 修复""测试覆盖""文档补充"等），不是逐条列 commit
- 同一类工作的多个提交合并为一条，用一句话概括
- 每条以粗体标题开头，冒号后跟具体描述
- "数据概览"汇总所有仓库的提交数和代码增删
- "小结与建议"给出整体总结和可操作的后续建议

## 注意事项

- 日报总结应由 AI 根据提交内容自行总结，不要让用户自己写
- 分支名取 remote 分支的简称（去掉 `origin/`）
- 如果某个仓库无提交，仍然列出并标注「0 个提交」
- 代码统计只统计文件变更，不含 merge commit
- 自动检测周目录结构，第三周存到 `第三周/` 子目录
