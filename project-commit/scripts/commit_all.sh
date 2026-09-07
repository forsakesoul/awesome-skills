#!/usr/bin/env bash
# commit_all.sh - 项目批量提交脚本（读取 projects.json 配置）
#
# 用法:
#   bash commit_all.sh                 # 扫描全部项目，生成 commit message，确认后提交
#   bash commit_all.sh --dry-run      # 只扫描和生成，不提交
#   bash commit_all.sh --push         # 提交后自动 push
#   bash commit_all.sh --project project-a   # 只处理指定项目
#   bash commit_all.sh --message "fix: xxx"    # 统一使用指定 commit message

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 优先读取 projects.json（本地私有无 git 追踪），回退到 projects.example.json（模板）
if [ -f "$SCRIPT_DIR/../projects.json" ]; then
  CONFIG_FILE="$SCRIPT_DIR/../projects.json"
elif [ -f "$SCRIPT_DIR/../projects.example.json" ]; then
  CONFIG_FILE="$SCRIPT_DIR/../projects.example.json"
  echo "⚠️  未找到 projects.json，使用模板 projects.example.json。"
  echo "   请复制 projects.example.json → projects.json 并填入实际项目路径"
else
  echo "❌ 找不到配置文件 projects.json 或 projects.example.json"
  exit 1
fi

GENERATE_SCRIPT="$SCRIPT_DIR/generate_commit_msg.sh"

# --- 解析参数 ---
DRY_RUN=false
AUTO_PUSH=false
PROJECT_FILTER=""
UNIFIED_MESSAGE=""
SKIP_CONFIRM=false
EXTERNAL_MODEL=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run|-n) DRY_RUN=true; shift ;;
    --push|-p)    AUTO_PUSH=true; shift ;;
    --project)     PROJECT_FILTER="$2"; shift 2 ;;
    --message|-m) UNIFIED_MESSAGE="$2"; shift 2 ;;
    --external-model) EXTERNAL_MODEL=true; shift ;;
    --yes|-y)     SKIP_CONFIRM=true; shift ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# --- 读取配置 ---
if [ ! -f "$CONFIG_FILE" ]; then
  echo "❌ 配置文件不存在: $CONFIG_FILE"
  exit 1
fi

# 用 python3 读取配置并驱动主流程
python3 - "$CONFIG_FILE" "$PROJECT_FILTER" "$UNIFIED_MESSAGE" "$DRY_RUN" "$AUTO_PUSH" "$SKIP_CONFIRM" "$GENERATE_SCRIPT" "$EXTERNAL_MODEL" 3<&0 << 'PYEOF'
import json, sys, subprocess, os, tempfile, hashlib
from pathlib import Path
from urllib.parse import urlsplit

sys.stdin = os.fdopen(3)

config_file = sys.argv[1]
project_filter = sys.argv[2] if sys.argv[2] else None
unified_message = sys.argv[3] if sys.argv[3] else None
dry_run = sys.argv[4] == "true"
auto_push = sys.argv[5] == "true"
skip_confirm = sys.argv[6] == "true"
generate_script = sys.argv[7]
external_model = sys.argv[8] == "true" and not dry_run
failures = []
if external_model and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    external_model = False
    print("未配置外部模型凭据，使用本地规则；没有发送代码。")
if external_model:
    destination = urlsplit(os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"))
    print(f"外部模型已显式选择：{destination.scheme}://{destination.hostname}；后续生成消息时将尝试发送截断 diff 与提交上下文。")

def snapshot():
    def git(*args):
        return subprocess.check_output(["git", *args])
    paths = sorted(set(git("ls-files", "--modified", "--deleted", "--others", "--exclude-standard", "-z").split(b"\0")) | set(git("diff", "--cached", "--name-only", "-z").split(b"\0")))
    paths = [os.fsdecode(p) for p in paths if p]
    digest = hashlib.sha256()
    for args in [("rev-parse", "HEAD"), ("symbolic-ref", "HEAD"), ("status", "--porcelain=v1", "-z", "--untracked-files=all"), ("diff", "--cached", "--binary"), ("diff", "--binary")]:
        digest.update(git(*args))
    for name in paths:
        path = Path(name)
        digest.update(os.fsencode(name) + b"\0")
        if path.is_symlink():
            digest.update(os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(path.read_bytes())
        elif path.exists():
            raise ValueError("不支持批量暂存目录或子模块: " + name)
    return paths, digest.hexdigest()

with open(config_file) as f:
    config = json.load(f)

projects = config["projects"]
commit_types = config.get("commit_types", [])
scope_hint = config.get("default_scope_hint", "")
commit_rules = config.get("commit_rules", {})
header_max_length = config.get("header_max_length", 100)
msg_min_length = config.get("commit_message_subject_min_length", 50)
msg_max_length = config.get("commit_message_subject_max_length", 300)

# 过滤项目
targets = [p for p in projects if not project_filter or project_filter == p["name"]]
if not targets:
    print(f"❌ 没有匹配的项目: {project_filter}")
    sys.exit(1)

os.environ["HEADER_MAX_LENGTH"] = str(header_max_length)
os.environ["COMMIT_MSG_MIN_LENGTH"] = str(msg_min_length)
os.environ["COMMIT_MSG_MAX_LENGTH"] = str(msg_max_length)

# --- Step0: 读取各项目近期 commit 风格 + 分支名 ---
print("📖 读取各项目分支名和近期 commit 风格...\n")

plans = []  # {name, path, branch, convention, files, diff_text, recent_commits}

for p in targets:
    name = p["name"]
    path = p["path"]
    convention = p.get("commit_convention", "")
    h_max = p.get("header_max_length", header_max_length)

    if not os.path.isdir(path):
        failures.append(name + ": missing-directory")
        print(f"⚠️  跳过（目录不存在）: {path}")
        continue

    os.chdir(path)

    # 读取当前分支名
    branch_result = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True)
    branch = branch_result.stdout.strip() or "unknown"

    # 读取近期 commits
    log_result = subprocess.run(["git", "log", "--oneline", "-10"], capture_output=True, text=True)
    recent = log_result.stdout.strip()

    try:
        paths, frozen = snapshot()
    except (subprocess.CalledProcessError, ValueError) as error:
        failures.append(name + ": snapshot-failed")
        print(f"❌ {name}: {error}")
        continue
    if not paths:
        print(f"  {name} ({branch}): 无改动，跳过")
        continue
    files = [("review", fname) for fname in paths]

    # 获取 diff
    diff_staged = subprocess.run(["git", "diff", "--staged"], capture_output=True, text=True)
    diff_unstaged = subprocess.run(["git", "diff"], capture_output=True, text=True)
    diff_text = diff_staged.stdout + "\n" + diff_unstaged.stdout
    # git diff omits untracked contents; include their additions in the same preview.
    for raw_name in subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"]).split(b"\0"):
        if not raw_name:
            continue
        addition = subprocess.run(["git", "diff", "--no-index", "--", os.devnull, os.fsdecode(raw_name)], capture_output=True, text=True, errors="replace")
        if addition.returncode not in (0, 1):
            failures.append(name + ": untracked-diff-failed")
            break
        diff_text += "\n" + addition.stdout
    else:
        addition = None
    if addition is not None:
        print(f"❌ {name}: 未跟踪文件预览失败，跳过")
        continue
    if len(diff_text) > 8000:
        diff_text = diff_text[:8000] + "\n...(diff truncated)"

    plans.append({
        "name": name,
        "path": path,
        "branch": branch,
        "convention": convention,
        "header_max_length": h_max,
        "files": files,
        "paths": paths,
        "snapshot": frozen,
        "diff": diff_text,
        "recent_commits": recent,
    })
    print(f"  {name} ({branch}): {len(files)} 个文件有改动")
    if recent:
        print(f"    近期 commits: {len(recent.splitlines())} 条")

if not plans:
    print("\n❌ 存在未完成的仓库扫描。" if failures else "\n✅ 所有项目都是干净的，没有东西需要提交。")
    sys.exit(1 if failures else 0)

# --- Step1: 推导跨项目统一 scope ---
# 从各项目分支名提取建议 scope
branch_scope_map = {}  # branch -> suggested scope
for plan in plans:
    branch = plan["branch"]
    if branch not in branch_scope_map:
        # 取最后一个 / 后的部分作为 scope
        suffix = branch.split("/")[-1] if "/" in branch else branch
        branch_scope_map[branch] = suffix

# 若所有项目分支名一致，直接使用该 scope
branches = set(plan["branch"] for plan in plans)
if len(branches) == 1:
    unified_scope = branch_scope_map.get(list(branches)[0], "")
    print(f"\n💡 检测到统一分支 [{list(branches)[0]}]，建议统一 scope: {unified_scope}")
else:
    # 多个分支，展示各分支的建议 scope
    print(f"\n💡 多分支检测到，各分支建议 scope:")
    for b, s in branch_scope_map.items():
        print(f"  {b} → scope={s}")
    unified_scope = ""

# --- Step2: 生成 Commit Message ---
print(f"\n{'='*60}")
print("🤖 生成 Commit Message...")
print(f"{'='*60}\n")

# 组装 commit_rules 文本
rules_text = ""
if commit_rules:
    for k, v in commit_rules.items():
        rules_text += f"- {k}: {v}\n"

for plan in plans:
    name = plan["name"]
    diff_text = plan["diff"]
    convention = plan["convention"]
    recent = plan.get("recent_commits", "")
    branch = plan["branch"]

    # 计算改动规模（文件数 + 代码行数）
    num_files = len(plan["files"])
    num_lines = len([l for l in diff_text.splitlines() if (l.startswith("+") or l.startswith("-")) and not l.startswith("+++") and not l.startswith("---")])

    if unified_message:
        plan["commit_msg"] = unified_message
        print(f"  {name}: 使用统一 message「{unified_message}」")
        continue

    # 建议 scope（优先统一 scope，否则用分支推导）
    suggested_scope = unified_scope or branch.split("/")[-1] if "/" in branch else ""

    # 写入临时 diff 文件
    with tempfile.NamedTemporaryFile(mode="w", suffix=".diff", delete=False) as tmp:
        tmp.write(diff_text)
        tmp_path = tmp.name

    try:
        # 调用 generate_commit_msg.sh
        # 参数: diff_file, project_name, convention, rules, recent_commits, current_branch
        env = os.environ.copy()
        env["HEADER_MAX_LENGTH"] = str(plan.get("header_max_length", header_max_length))
        env["CHANGED_FILES_COUNT"] = str(num_files)
        env["CHANGED_LINES_COUNT"] = str(num_lines)

        command = ["bash", generate_script] + (["--external-model"] if external_model else [])
        result = subprocess.run(
            [*command, tmp_path, name, convention, rules_text, recent, branch],
            capture_output=True, text=True, timeout=30,
            env=env
        )
        msg = result.stdout.strip()
        if result.returncode != 0 or not msg:
            msg = f"fix: update {name}"
        plan["commit_msg"] = msg
        print(f"  {name} ({branch}):")
        print(f"    {msg}")
    except Exception as e:
        plan["commit_msg"] = f"fix: update {name}"
        print(f"  {name}: (生成失败，使用默认) fix: update {name}")
    finally:
        os.unlink(tmp_path)

# --- Step3: 展示计划 ---
print(f"\n{'='*60}")
print("📋 提交计划")
print(f"{'='*60}")

for plan in plans:
    name = plan["name"]
    branch = plan["branch"]
    msg = plan["commit_msg"]
    print(f"\n[{name}] ({branch})")
    print(f"  commit: {msg}")
    for status, fname in plan["files"]:
        print(f"    [{status}] {fname}")

if dry_run:
    print("\n🔍 dry-run 模式，不执行提交。")
    sys.exit(1 if failures else 0)

# --- Step4: 确认 ---
if not skip_confirm:
    if scope_hint:
        print(f"\n💡 提示: {scope_hint}")
    answer = input("\n❓ 确认提交以上项目？(y/N/a=全部中止): ").strip().lower()
    if answer not in ("y", "yes"):
        print("❌ 已取消。")
        sys.exit(0)

# --- Step5: 执行提交 ---
print(f"\n{'='*60}")
print("🚀 开始提交...")
print(f"{'='*60}\n")

for plan in plans:
    name = plan["name"]
    path = plan["path"]
    msg = plan["commit_msg"]
    branch = plan["branch"]

    os.chdir(path)
    print(f"📂 [{name}]")

    # Recheck the approved snapshot before touching the real index.
    try:
        if snapshot()[1] != plan["snapshot"]:
            raise ValueError("预览后仓库发生变化，请重新审阅")
        subprocess.run(["git", "--literal-pathspecs", "add", "--all", "--", *plan["paths"]], check=True)
    except (subprocess.CalledProcessError, ValueError) as error:
        failures.append(name + ": stage-failed")
        print(f"   ❌ {error}")
        continue
    print("   ✓ 已暂存审阅路径")

    # git commit
    commit_result = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
    if commit_result.returncode != 0:
        err = commit_result.stderr.strip() or commit_result.stdout.strip()
        failures.append(name + ": commit-failed (保留暂存供检查)")
        print(f"   ❌ commit 失败:")
        print(f"   {err}")
        continue
    # 提取 commit hash
    hash_result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    commit_hash = hash_result.stdout.strip()
    print(f"   ✓ commit {commit_hash}: {msg}")

    # push（可选）
    if auto_push:
        push_result = subprocess.run(["git", "push", "origin", branch], capture_output=True, text=True)
        if push_result.returncode == 0:
            print(f"   ✓ git push origin {branch}")
        else:
            failures.append(name + ": committed, push-failed")
            print(f"   ⚠️  push 失败: {push_result.stderr.strip()}")

    print()

if failures:
    print("❌ 未全部完成：" + "; ".join(failures))
    sys.exit(1)
print("✅ 全部完成！")
PYEOF
